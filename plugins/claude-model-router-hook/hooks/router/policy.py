"""Effort-first policy: class targets, decision matrix, gates and floors (FR-4, FR-5, FR-20, FR-21, FR-22)."""

import dataclasses

from .config import resolve_list, safe_regex_match
from .ladder import EFFORTS, TIERS, Decision, detect_tier, effort_distance

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
    """
    target = cfg["classes"][klass]["target"]
    model = target.get("model")
    if model not in TIERS:
        return None
    effort = None if model == "haiku" else target.get("effort")
    return Decision(model=model, effort=effort, klass=klass, source=source)


def main_prompt_decision(klass, current_model, current_effort, cfg, score):
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


def apply_gates(prompt, decision, cfg):
    """Capability gates and effort floors on a classified decision (FR-21, FR-22).

    - capability_gates patterns (handoff/multi-agent work) -> min tier sonnet;
      a haiku decision is bumped to (sonnet, medium) (AC-6.3).
    - debugging class -> effort >= high (AC-6.5).
    - effort_floors patterns (data-handling risk) -> effort >= effort_floors.floor;
      any floor implies min tier sonnet (haiku carries no effort).
    """
    prompt_lower = prompt.lower()
    floors_cfg = cfg.get("effort_floors") or {}

    floor = "high" if decision.klass == "debugging" else None
    # Resolve gate/floor patterns through config.resolve_list so extend/replace/
    # remove_patterns behave identically to per-class list resolution (F9).
    floor_patterns = resolve_list(floors_cfg, "patterns", DEFAULT_FLOOR_PATTERNS)
    if safe_regex_match(floor_patterns, prompt_lower):
        cfg_floor = floors_cfg.get("floor", "high")
        if cfg_floor not in EFFORTS:
            cfg_floor = "high"
        floor = _max_effort(floor, cfg_floor)

    gate_patterns = resolve_list(cfg.get("capability_gates"), "patterns", DEFAULT_GATE_PATTERNS)
    min_sonnet = floor is not None or safe_regex_match(gate_patterns, prompt_lower)

    model, effort = decision.model, decision.effort
    if min_sonnet and TIERS.index(model) < TIERS.index("sonnet"):
        model, effort = "sonnet", "medium"
    if floor is not None and (effort is None or EFFORTS.index(effort) < EFFORTS.index(floor)):
        effort = floor
    if model == decision.model and effort == decision.effort:
        return decision
    return dataclasses.replace(decision, model=model, effort=effort)
