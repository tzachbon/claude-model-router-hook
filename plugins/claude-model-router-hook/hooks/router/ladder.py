"""Tier constants, decision type, and model-string utilities (FR-1, FR-2, FR-3, FR-6)."""

from dataclasses import dataclass

TIERS = ("haiku", "sonnet", "opus", "fable")  # index = rank; mythos nowhere
MODEL_IDS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-4-8",
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
    """Map a model string (alias, full ID, or suffixed) to a ladder tier by substring."""
    for tier in TIERS:
        if tier in model_str:
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
