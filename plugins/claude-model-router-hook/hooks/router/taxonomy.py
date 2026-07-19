"""Scored taxonomy classifier: signals, per-class scoring, margin confidence."""

import collections

from .config import resolve_list, safe_regex_match

CLASSES = ("mechanical", "implementation", "debugging", "architecture", "extreme")

# Caps per signal type (FR-7): no single signal type can force a tier.
TEXT_CAP = 6
EXTREME_CAP = 3
EXTREME_ESCALATION_MIN = 2

# Default text signals per class (config-extendable via classes.<name>).
DEFAULT_KEYWORDS = {
    "mechanical": [],
    "implementation": [],
    "debugging": [],
    "architecture": [
        "architect", "architecture", "evaluate", "tradeoff", "trade-off",
        "strategy", "strategic", "compare approaches", "why does", "deep dive",
        "redesign", "across the codebase", "investor", "multi-system",
        "complex refactor", "analyze", "analysis", "plan mode", "rethink",
        "high-stakes", "critical decision",
    ],
    "extreme": [
        "multi-system", "migration plan", "across the entire codebase",
        "long-horizon", "epic", "rewrite the platform",
    ],
}

DEFAULT_PATTERNS = {
    "mechanical": [
        r"\bgit\s+(commit|push|pull|status|log|diff|add|stash|branch|merge|rebase|checkout)\b",
        r"\bcommit\b.*\b(change|changes|push|all)\b",
        r"\bpush\s+(to|the|remote|origin)\b",
        r"\brename\b", r"\bre-?order\b", r"\bmove\s+file\b", r"\bdelete\s+file\b",
        r"\badd\s+(import|route|link)\b", r"\bformat\b", r"\blint\b",
        r"\bprettier\b", r"\beslint\b", r"\bremove\s+(unused|dead)\b",
        r"\bupdate\s+(version|package)\b",
    ],
    "implementation": [
        r"\bbuild\b", r"\bimplement\b", r"\bcreate\b", r"\bfix\b",
        r"\badd\s+feature\b", r"\bwrite\b", r"\bcomponent\b", r"\bservice\b",
        r"\bpage\b", r"\bdeploy\b", r"\btest\b", r"\bupdate\b", r"\brefactor\b",
        r"\bstyle\b", r"\bcss\b", r"\broute\b", r"\bapi\b", r"\bfunction\b",
    ],
    "debugging": [
        r"\bdebug\b", r"\bwhy\s+is\b.{0,80}\bfailing\b", r"\bflaky\b",
        r"\brace\s+(condition|conditions)\b", r"\bregression\b",
        r"\bstack\s+trace\b", r"error:", r"\btraceback\b", r"\bexit\s+code\b",
        r"\bbisect\b", r"\breproduce\b",
    ],
    "architecture": [],
    "extreme": [r"\brfc\b", r"\bdesign\s+doc\b"],
}

ScoreResult = collections.namedtuple(
    "ScoreResult", ["scores", "top", "second", "margin", "word_count"]
)


def _resolve_lists(klass, cfg):
    """Merge default keyword/pattern lists with config (extend/replace/remove)."""
    class_cfg = cfg.get("classes", {}).get(klass, {})
    return (
        resolve_list(class_cfg, "keywords", DEFAULT_KEYWORDS[klass]),
        resolve_list(class_cfg, "patterns", DEFAULT_PATTERNS[klass]),
    )


def _text_score(prompt_lower, keywords, patterns, per_hit=2, cap=TEXT_CAP):
    """Count keyword/pattern hits (per_hit points each), capped per class."""
    hits = sum(1 for kw in keywords if kw and kw.lower() in prompt_lower)
    hits += sum(1 for p in patterns if safe_regex_match([p], prompt_lower))
    return min(hits * per_hit, cap)


def score(prompt, cfg):
    """Score prompt against all classes; returns ScoreResult (deterministic)."""
    thresholds = cfg.get("thresholds", {})
    mechanical_max_words = thresholds.get("mechanical_max_words", 60)
    long_prompt_words = thresholds.get("long_prompt_words", 200)
    question_words = thresholds.get("question_words", 100)

    prompt = prompt or ""
    prompt_lower = prompt.lower()
    word_count = len(prompt.split())

    scores = {klass: 0.0 for klass in CLASSES}

    # Text signals (keyword/pattern hit = +2, cap +6 per class).
    for klass in ("mechanical", "implementation", "debugging", "architecture"):
        keywords, patterns = _resolve_lists(klass, cfg)
        scores[klass] += _text_score(prompt_lower, keywords, patterns)

    # Structural/length signals (per-class caps).
    if 1 <= word_count <= 12:  # short imperative
        scores["mechanical"] += 1
    if word_count > mechanical_max_words:  # length requirement, else zeroed
        scores["mechanical"] = 0.0

    if "```" in prompt:  # code fence
        scores["implementation"] += 1

    if "\n" in prompt and safe_regex_match(
        [r"\btraceback\b", r"error:", r"\bexception\b"], prompt_lower
    ):  # error/traceback text block
        scores["debugging"] += 2

    length_bonus = 0
    if word_count >= 2 * long_prompt_words:
        length_bonus = 2
    elif word_count >= long_prompt_words:
        length_bonus = 1
    if "?" in prompt and word_count >= question_words:
        length_bonus += 1
    scores["architecture"] += min(length_bonus, 2)  # hard cap +2 (FR-7)

    def _top_of(candidates):
        best = candidates[0]
        for klass in candidates[1:]:
            if scores[klass] > scores[best]:
                best = klass
        return best

    # Extremity: evaluated only when architecture is the top base class.
    base = ("mechanical", "implementation", "debugging", "architecture")
    if _top_of(base) == "architecture" and scores["architecture"] > 0:
        ex_keywords, ex_patterns = _resolve_lists("extreme", cfg)
        extremity = _text_score(
            prompt_lower, ex_keywords, ex_patterns, per_hit=1, cap=EXTREME_CAP
        )
        if extremity >= EXTREME_ESCALATION_MIN:
            scores["extreme"] = scores["architecture"] + extremity

    top = _top_of(CLASSES)
    second = _top_of([klass for klass in CLASSES if klass != top])
    margin = scores[top] - scores[second]
    return ScoreResult(scores, top, second, margin, word_count)


def classify_heuristic(prompt, cfg):
    """Decide (class | None-abstain, evidence); always decides alone (FR-24)."""
    result = score(prompt, cfg)
    if result.word_count == 0:  # empty/whitespace prompt
        return None, result

    confident_margin = cfg.get("thresholds", {}).get("confident_margin", 3)
    top_score = result.scores[result.top]
    if result.margin >= confident_margin and top_score >= 3:
        return result.top, result
    if top_score >= 2:  # low-confidence
        return result.top, result
    return None, result


def classify(prompt, cfg, data_dir):
    """Tiered classify (FR-24, FR-26): confident heuristic final, else CLI tiebreak.

    Decision ladder: confident heuristic -> no CLI; below threshold with
    classifier.cli_fallback enabled -> cache -> CLI tiebreak; CLI failure or
    fallback disabled -> heuristic low-confidence decision (fail-open).
    """
    klass, result = classify_heuristic(prompt, cfg)
    if result.word_count == 0:  # empty/whitespace prompt: abstain, no CLI
        return None, result

    confident_margin = cfg.get("thresholds", {}).get("confident_margin", 3)
    if result.margin >= confident_margin and result.scores[result.top] >= 3:
        return klass, result  # confident: final, no CLI

    classifier_cfg = cfg.get("classifier") or {}
    if not classifier_cfg.get("cli_fallback", True):
        return klass, result  # pure heuristics (AC-7.6, NFR-7)

    # Lazy import: no subprocess machinery loaded when fallback disabled.
    from . import cli_fallback

    reply = cli_fallback.classify_cli(prompt, cfg, data_dir)
    if reply == "abstain":
        return None, result
    if reply in CLASSES:
        return reply, result
    return klass, result  # CLI failure: heuristic decision applies (AC-7.4)
