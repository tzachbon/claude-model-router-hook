"""Tier constants, decision type, and model-string utilities."""

from dataclasses import dataclass
import re

TIERS = ("haiku", "sonnet", "opus", "fable")  # index = rank; mythos nowhere
MODEL_IDS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
    "fable": "claude-fable-5",
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True)
class Decision:
    model: str  # alias from TIERS
    effort: str | None  # None iff model == "haiku"
    klass: str
    source: str  # "heuristic" | "cli" | "cache"

    def __post_init__(self):
        if "mythos" in self.model:
            raise ValueError(f"mythos model is never a valid target: {self.model!r}")
        if self.model not in TIERS:
            raise ValueError(f"model must be a ladder alias {TIERS}: {self.model!r}")
        if self.effort is not None and self.model == "haiku":
            raise ValueError("haiku decisions carry no effort; effort must be None")
        if self.effort is not None and self.effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS} or None: {self.effort!r}")


def detect_tier(model_str):
    """Map a model alias, ID, or ``[context]``-suffixed value to a tier.

    Match model-family tokens rather than arbitrary substrings.  A setting such
    as ``notsonnet`` is not a Sonnet request, while the host's normal aliases
    and IDs (``opus``, ``claude-opus-5``, ``opus[1m]``) remain supported.
    """
    if not isinstance(model_str, str):
        return None
    lower = model_str.lower()
    if "mythos" in lower:
        return None
    for tier in TIERS:
        if re.search(r"(?:^|[-_])" + re.escape(tier) + r"(?:$|[-_\[])", lower):
            return tier
    return None


def split_suffix(model_str):
    """Split a model string into (base, suffix), e.g. 'opus[1m]' -> ('opus', '[1m]')."""
    idx = model_str.find("[")
    if idx == -1:
        return (model_str, "")
    return (model_str[:idx], model_str[idx:])


def effort_distance(a, b):
    """Absolute distance between two effort levels on the EFFORTS scale."""
    return abs(EFFORTS.index(a) - EFFORTS.index(b))
