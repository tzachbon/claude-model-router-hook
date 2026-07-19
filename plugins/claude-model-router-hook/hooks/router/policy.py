"""Effort-first policy: class targets and main-prompt decision matrix (FR-4, FR-5, FR-20)."""

from .ladder import TIERS, Decision, detect_tier, effort_distance

# Same-tier cells where effort escalates past the class target (effort-first):
# the session already sits on the target tier, so only effort can go higher.
_STAY_XHIGH_CLASSES = ("architecture", "extreme")


def target_for_class(klass, cfg, source="heuristic"):
    """Class target Decision (used verbatim for subagent spawns). Haiku carries no effort."""
    target = cfg["classes"][klass]["target"]
    return Decision(
        model=target["model"],
        effort=target.get("effort"),
        klass=klass,
        source=source,
    )


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
