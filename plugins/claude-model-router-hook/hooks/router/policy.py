"""Effort-first policy: class targets, decision matrix, gates and floors (FR-4, FR-5, FR-20, FR-21, FR-22)."""

import dataclasses

from .config import DEFAULTS, resolve_list, safe_regex_match
from .ladder import EFFORTS, TIERS, Decision, detect_tier, effort_distance
from .taxonomy import CLASSES

# Same-tier cells where effort escalates past the class target (effort-first):
# the session already sits on the target tier, so only effort can go higher.
_STAY_XHIGH_CLASSES = ("architecture", "extreme")

# Shipped defaults (config-extendable via capability_gates / effort_floors).
DEFAULT_GATE_PATTERNS = [
    r"\bsendmessage\b",
    r"\bhand[-\s]?offs?\b",
    r"\bcoordinat\w*\s+agents?\b",
    r"\bspawn\w*\s+sub[-\s]?agents?\b",
    r"\bmulti[-\s]?agent\b",
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
    classes = cfg.get("classes") if isinstance(cfg, dict) else None
    if not isinstance(classes, dict):
        return None
    entry = classes.get(klass)
    if not isinstance(entry, dict):
        return None
    target = entry.get("target")
    if not isinstance(target, dict):
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
    - same tier -> stay; architecture/extreme escalate effort to xhigh; match when
      effort_distance < effort_warn_distance (returns None, anti-nagging).
    - current tier above target: haiku targets down-route (guard: margin >=
      downroute_margin, else None); other classes stay at the current tier with
      the target effort, same effort-distance match rule.
    """
    target = target_for_class(klass, cfg)
    if target is None:
        return None  # invalid class target: fail-safe skip (pass-through)
    target = apply_gates(prompt, target, cfg)
    thresholds = cfg.get("thresholds", {})
    warn_distance = thresholds.get("effort_warn_distance", 2)
    downroute_margin = thresholds.get("downroute_margin", 4)
    current_tier = detect_tier(current_model)
    if current_tier is None:
        return target  # unknown model: treat as tier mismatch, suggest target
    current_effort = current_effort or "high"
    current_rank = TIERS.index(current_tier)
    target_rank = TIERS.index(target.model)

    if current_rank < target_rank:
        # Up-route (incl. haiku -> sonnet for implementation/debugging).
        return target

    if current_rank == target_rank:
        if target.model == "haiku":
            return None  # mechanical@haiku: match, no effort to compare
        effort = "xhigh" if klass in _STAY_XHIGH_CLASSES else target.effort
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
    """(model, effort) tier floor for gated work.

    Gated work (handoff/multi-agent, or anything carrying an effort floor) must
    not run on the bottom tier; that guarantee is the point of AC-6.3. The tier
    it escalates to is the configured implementation target rather than a
    hard-coded model, so a config that targets a tier nowhere can never be
    routed onto it.

    An implementation target of haiku is the awkward case. Taking it literally
    would leave gated work on the bottom tier and, because haiku decisions
    carry no effort, silently drop every effort floor with it: the escalation
    guarantee would disappear exactly where it matters most. Such a config is
    saying "implementation work is cheap", not "risky work should stay at the
    bottom". So walk instead to the cheapest non-haiku target any other class
    declares. Only a config with nothing above haiku anywhere yields a haiku
    floor, and there no escalation exists to offer.

    Falls back to the shipped implementation target when the configured value
    is absent or unusable. Never raises.
    """
    pair = _class_target_pair("implementation", cfg)
    if pair is None:
        default = DEFAULTS["classes"]["implementation"]["target"]
        pair = (default["model"], default.get("effort"))
    if pair[0] != "haiku":
        return pair

    best = None
    for klass in CLASSES:
        if klass == "implementation":
            continue
        other = _class_target_pair(klass, cfg)
        if other is None or other[0] == "haiku":
            continue
        if best is None or TIERS.index(other[0]) < TIERS.index(best[0]):
            best = other
    return best if best is not None else ("haiku", None)


def configured_floor(cfg):
    """The effort_floors.floor value a matching floor pattern applies."""
    floors_cfg = (cfg.get("effort_floors") if isinstance(cfg, dict) else None) or {}
    cfg_floor = floors_cfg.get("floor", "high")
    return cfg_floor if cfg_floor in EFFORTS else "high"


def _gated_pair(model, effort, floor, gated, cfg):
    """(model, effort) after the tier bump and the effort floor.

    The whole of the gate arithmetic, shared by apply_gates and gate_outcomes
    so the variant set cannot describe an outcome the router does not produce.
    """
    if gated:
        min_model, min_effort = min_gated_target(cfg)
        if TIERS.index(model) < TIERS.index(min_model):
            model, effort = min_model, min_effort
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


def apply_gates(prompt, decision, cfg):
    """Capability gates and effort floors on a classified decision (FR-21, FR-22).

    - capability_gates patterns (handoff/multi-agent work) -> min tier is
      min_gated_target; a decision below it is bumped (AC-6.3).
    - debugging class -> effort >= high (AC-6.5).
    - effort_floors patterns (data-handling risk) -> effort >= effort_floors.floor;
      any floor also implies that min tier (haiku carries no effort).
    """
    prompt_lower = prompt.lower()
    # cfg is normally the resolved dict from load_config, but every other entry
    # point in this module tolerates a malformed one and this must too: raising
    # here exits through fail-open and disables routing without a word.
    if not isinstance(cfg, dict):
        cfg = {}
    floors_cfg = cfg.get("effort_floors") or {}

    floor = "high" if decision.klass == "debugging" else None
    # Resolve gate/floor patterns through config.resolve_list so extend/replace/
    # remove_patterns behave identically to per-class list resolution (F9).
    floor_patterns = resolve_list(floors_cfg, "patterns", DEFAULT_FLOOR_PATTERNS)
    if safe_regex_match(floor_patterns, prompt_lower):
        floor = _max_effort(floor, configured_floor(cfg))

    gate_patterns = resolve_list(cfg.get("capability_gates"), "patterns", DEFAULT_GATE_PATTERNS)
    gated = floor is not None or safe_regex_match(gate_patterns, prompt_lower)

    model, effort = _gated_pair(decision.model, decision.effort, floor, gated, cfg)
    if model == decision.model and effort == decision.effort:
        return decision
    return dataclasses.replace(decision, model=model, effort=effort)
