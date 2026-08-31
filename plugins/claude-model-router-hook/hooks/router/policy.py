"""Effort-first policy: class targets, decision matrix, gates and floors (FR-4, FR-5, FR-20, FR-21, FR-22)."""

import dataclasses

from .config import DEFAULTS, as_dict, resolve_list, safe_regex_match
from .ladder import EFFORTS, TIERS, Decision, detect_tier, effort_distance
from .taxonomy import CLASSES

# A user may lower a class target in their config, but work that is already on
# the target tier must not lose the depth expected for architecture-scale work.
# ``max`` remains intact for an extreme target; the floor only raises effort.
_SAME_TIER_EFFORT_FLOORS = {
    "architecture": "xhigh",
    "extreme": "xhigh",
}

# Shipped defaults (config-extendable via capability_gates / effort_floors).
DEFAULT_GATE_PATTERNS = [
    r"\bsendmessage\b",
    r"\bhand[-\s]?offs?\b",
    r"\bdelegat\w*\b",
    r"\bcoordinat\w*\s+agents?\b",
    r"\bspawn\w*\s+sub[-\s]?agents?\b",
    r"\bmulti[-\s]?agent\b",
    r"\bagent\s+teams?\b",
    r"\bparallel(?:iz\w*|\s+(?:work|tasks?))?\b",
    r"\bfan[-\s]?out\b",
]
DEFAULT_FLOOR_PATTERNS = [
    r"\bmigrat\w*\b",
    r"\bdatabases?\b",
    r"\bprod(?:uction)?\b",
    r"\bdelete\s+data\b",
    r"\bbackfills?\b",
]


def target_for_class(klass, cfg, source="heuristic"):
    """Class target Decision (used verbatim for subagent spawns), or None.

    Returns None (fail-safe skip) when the configured target model is not a
    valid ladder tier: a bad/missing model would otherwise raise inside Decision
    and, via fail-open, disable all routing silently. Haiku targets always carry
    effort None, since a deep-merged partial override can leave an inherited
    effort on a model that was switched to haiku.

    A malformed config shape (missing or non-dict "classes", class entry or
    target) returns None for the same reason, rather than raising: exiting
    through fail-open and exiting through the None check produce the same
    pass-through, but only the None check is visible to callers that want to
    report the class as unroutable.
    """
    target = as_dict(as_dict(as_dict(cfg).get("classes")).get(klass)).get("target")
    target = as_dict(target)
    if not target:
        return None
    model = target.get("model")
    if model not in TIERS:
        return None
    if model == "haiku":
        effort = None
    else:
        effort = target.get("effort")
        # An invalid effort string (e.g. "ultra") would raise inside Decision and,
        # via fail-open, silently disable routing. Fall back to the shipped default
        # effort for this class instead (None only for a haiku default).
        if effort is not None and effort not in EFFORTS:
            effort = DEFAULTS["classes"].get(klass, {}).get("target", {}).get("effort")
    return Decision(model=model, effort=effort, klass=klass, source=source)


def main_prompt_decision(klass, current_model, current_effort, cfg, score, prompt=""):
    """Full 5x4 matrix: (class, current tier) -> Decision or None (match / guarded).

    Rules (design "(model, effort) output matrix" + Requirements Amendments):
    - current tier below target -> up-route to the class target (always warns).
    - same tier -> stay; architecture/extreme retain at least xhigh effort; match
      when effort_distance < effort_warn_distance (returns None, anti-nagging).
    - current tier above target: haiku targets down-route (guard: margin >=
      downroute_margin, else None); other classes stay at the current tier with
      the target effort, same effort-distance match rule.
    """
    target = target_for_class(klass, cfg)
    if target is None:
        return None  # invalid class target: fail-safe skip (pass-through)
    target = apply_gates(prompt, target, cfg)
    thresholds = as_dict(as_dict(cfg).get("thresholds"))
    warn_distance = thresholds.get("effort_warn_distance", 2)
    downroute_margin = thresholds.get("downroute_margin", 4)
    current_tier = detect_tier(current_model)
    if current_tier is None:
        return target  # unknown model: treat as tier mismatch, suggest target
    current_effort = current_effort or "high"
    current_rank = TIERS.index(current_tier)
    target_rank = TIERS.index(target.model)

    if current_rank < target_rank:
        # Up-route (including a Haiku or Sonnet session to the class target).
        return target

    if current_rank == target_rank:
        if target.model == "haiku":
            return None  # mechanical@haiku: match, no effort to compare
        effort = _max_effort(
            target.effort, _SAME_TIER_EFFORT_FLOORS.get(klass)
        )
        if effort_distance(current_effort, effort) < warn_distance:
            return None  # match (same tier, effort close enough)
        return Decision(target.model, effort, klass, target.source)

    # current_rank > target_rank
    if target.model == "haiku":
        # Tier-lowering decision: asymmetric downroute guard (FR-5).
        margin = score.margin if score is not None else 0
        if margin >= downroute_margin:
            return Decision("haiku", None, klass, target.source)
        return None
    # Non-haiku target below current tier: stay on the current tier, target effort.
    if effort_distance(current_effort, target.effort) < warn_distance:
        return None
    return Decision(current_tier, target.effort, klass, target.source)


def _max_effort(a, b):
    """Higher of two effort levels; either may be None."""
    if a is None:
        return b
    if b is None:
        return a
    return a if EFFORTS.index(a) >= EFFORTS.index(b) else b


def _class_target_pair(klass, cfg):
    """(model, effort) for a class, or None when the target is unusable."""
    decision = target_for_class(klass, cfg)
    if decision is None:
        return None
    return decision.model, decision.effort


def min_gated_target(cfg):
    """(model, effort) tier floor for gated work, or None when none is legal.

    Gated work (handoff/multi-agent, or anything carrying an effort floor) must
    not run on the bottom tier; that guarantee is the point of AC-6.3. The tier
    it escalates to is the configured implementation target rather than a
    hard-coded model, so a config that targets a tier nowhere can never be
    routed onto it.

    Two cases put pressure on that. An implementation target of haiku, taken
    literally, would leave gated work on the bottom tier and, because haiku
    decisions carry no effort, drop every effort floor with it. An unusable
    implementation target has nothing to read at all. Neither may be answered
    with the shipped default: DEFAULTS targets Opus, so one typo in one class
    would resurrect a model the config declares nowhere, which is the exact
    failure this module exists to prevent.

    So the fallback stays inside the config: walk to the cheapest non-haiku
    target any other class declares. When the config declares nothing usable
    above haiku, return None and let the caller skip the bump. A router that
    cannot find a legal escalation target leaves the decision alone rather than
    inventing one. Never raises.
    """
    pair = _class_target_pair("implementation", cfg)
    if pair is not None and pair[0] != "haiku":
        return pair

    best = None
    for klass in CLASSES:
        if klass == "implementation":
            continue
        other = _class_target_pair(klass, cfg)
        if other is None or other[0] == "haiku":
            continue
        if best is None or (
            TIERS.index(other[0]),
            other[1] is None,
            EFFORTS.index(other[1] or EFFORTS[0]),
        ) < (
            TIERS.index(best[0]),
            best[1] is None,
            EFFORTS.index(best[1] or EFFORTS[0]),
        ):
            best = other
    return best


def configured_floor(cfg):
    """The effort_floors.floor value a matching floor pattern applies."""
    cfg_floor = as_dict(as_dict(cfg).get("effort_floors")).get("floor", "high")
    return cfg_floor if cfg_floor in EFFORTS else "high"


def _gated_pair(model, effort, floor, gated, cfg):
    """(model, effort) after the tier bump and the effort floor.

    The whole of the gate arithmetic, shared by apply_gates and gate_outcomes
    so the variant set cannot describe an outcome the router does not produce.
    """
    if gated:
        minimum = min_gated_target(cfg)
        # No legal escalation target: leave the decision where it is rather
        # than reach outside the configured targets for one.
        if minimum is not None and TIERS.index(model) < TIERS.index(minimum[0]):
            model, effort = minimum
    # A decision that stayed on haiku carries no effort; assigning the floor
    # there would break the Decision invariant and, via fail-open, silently
    # disable routing. min_gated_target only leaves haiku here when the config
    # declares nothing above it, so there is no floor to honour anyway.
    if (
        model != "haiku"
        and floor is not None
        and (effort is None or EFFORTS.index(effort) < EFFORTS.index(floor))
    ):
        effort = floor
    return model, effort


def _gate_states(klass, cfg):
    """Every (floor, gated) state apply_gates can reach for a class.

    Enumerates over prompts rather than sampling them: the floor is either the
    pattern-independent debugging floor, the configured effort_floors.floor, or
    absent, and "gated" is implied by any floor plus the capability patterns.
    """
    cfg_floor = configured_floor(cfg)
    if klass == "debugging":
        # The debugging floor is pattern-independent, so floor is never None.
        states = [("high", True), (_max_effort("high", cfg_floor), True)]
    else:
        states = [(None, False), (None, True), (cfg_floor, True)]
    unique = []
    for state in states:
        if state not in unique:
            unique.append(state)
    return unique


def gate_outcomes(klass, cfg):
    """Every (model, effort) apply_gates can produce for a class's target.

    A class target alone is not the full set: a gate bump or an effort floor
    synthesizes pairs no class declares, and those need routed variants too.
    Returns [] for an unroutable class.
    """
    target = None
    try:
        target = target_for_class(klass, cfg)
    except Exception:
        target = None
    if target is None:
        return []
    outcomes = []
    for floor, gated in _gate_states(klass, cfg):
        pair = _gated_pair(target.model, target.effort, floor, gated, cfg)
        if pair not in outcomes:
            outcomes.append(pair)
    return outcomes


def apply_gates(prompt, decision, cfg, delegated=False):
    """Capability gates and effort floors on a classified decision (FR-21, FR-22).

    - capability_gates patterns and nested delegation -> min tier is
      min_gated_target; a decision below it is bumped.
    - debugging class -> effort >= high (AC-6.5).
    - effort_floors patterns (data-handling risk) -> effort >= effort_floors.floor;
      any floor also implies that min tier (haiku carries no effort).
    """
    prompt_lower = prompt.lower()
    # cfg and every container inside it come from free-form user JSON. Reading
    # a non-dict with .get raises, and inside a hook that exits through
    # fail-open as a silent exit 0 with routing disabled, so every nested read
    # here goes through as_dict.
    cfg = as_dict(cfg)
    floors_cfg = as_dict(cfg.get("effort_floors"))

    floor = "high" if decision.klass == "debugging" else None
    # Resolve gate/floor patterns through config.resolve_list so extend/replace/
    # remove_patterns behave identically to per-class list resolution (F9).
    floor_patterns = resolve_list(floors_cfg, "patterns", DEFAULT_FLOOR_PATTERNS)
    if safe_regex_match(floor_patterns, prompt_lower):
        floor = _max_effort(floor, configured_floor(cfg))

    gate_patterns = resolve_list(cfg.get("capability_gates"), "patterns", DEFAULT_GATE_PATTERNS)
    # A child Agent call is coordination even when its concise task prompt does
    # not repeat words such as "delegate" or "handoff".  Treating it as gated
    # keeps a nested fan-out from silently dropping to the mechanical tier.
    gated = (
        bool(delegated)
        or floor is not None
        or safe_regex_match(gate_patterns, prompt_lower)
    )

    model, effort = _gated_pair(decision.model, decision.effort, floor, gated, cfg)
    if model == decision.model and effort == decision.effort:
        return decision
    return dataclasses.replace(decision, model=model, effort=effort)
