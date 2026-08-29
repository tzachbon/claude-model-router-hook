"""Scored taxonomy classifier: signals, per-class scoring, margin confidence."""

import collections
import re

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
    "debugging": ["deadlock", "intermittent", "segfault", "corrupt"],
    # High-frequency English words (design, decision, approach, propose, should
    # we, platform, ...) are NOT bare keywords: each would score +2 and reach the
    # low-confidence floor, over-routing routine prompts to opus. Architecture
    # signals are phrases (design decision, propose an approach, tradeoff
    # analysis, how should we design, ...) plus lower-frequency technical terms.
    "architecture": [
        "architect", "architecture", "evaluate", "tradeoff", "trade-off",
        "strategy", "strategic", "compare approaches", "why does", "deep dive",
        "redesign", "across the codebase", "investor", "multi-system",
        "complex refactor", "tradeoff analysis", "plan mode", "rethink",
        "high-stakes", "critical decision", "design decision",
        "architecture decision", "design doc", "propose an approach",
        "the right approach", "which approach", "how should we design",
        "how should we structure", "walk me through", "data model", "migrat",
        "rewrit", "replatform", "monolith", "microservice", "multi-region",
        "multi-year", "long-horizon", "epic", "bounded-context",
    ],
    # Extreme markers are deliberately PHRASES (not bare tokens like "migrate"
    # or "rewrite"): each hit is +1 and >= 2 escalates architecture -> extreme,
    # so phrase-level markers resist keyword-stuffed prompts that pile up single
    # scale words without describing genuine program-scale work.
    "extreme": [
        "multi-system", "multi-region", "multi-year", "long-horizon", "epic",
        "company-wide", "across the entire codebase", "across the whole codebase",
        "entire codebase", "whole codebase", "entire system", "entire platform",
        "all services", "every service", "every data store", "all forty",
        "bounded-context", "several teams", "cross-team", "distributed database",
        "end-to-end", "microservices", "replatform", "regional stacks",
        "phased rollout", "rollback strategy", "program-level", "multi-tenant",
        "rewrite the", "monolithic database",
    ],
}

DEFAULT_PATTERNS = {
    "mechanical": [
        r"\bgit\s+(commit|push|pull|status|log|diff|add|stash|branch|merge|rebase|checkout)\b",
        r"\bcommit\b.*\b(change|changes|push|all)\b",
        r"\bpush\s+(to|the|remote|origin)\b",
        r"\brename\b", r"\bre-?order\b", r"\bmove\s+file\b",
        r"\bdelete\s+(the\s+)?file\b", r"\bmove\b.{0,40}\b(folder|directory|dir)\b",
        r"\bgitignore\b", r"\bbump\b.{0,20}\bversion\b",
        r"\badd\s+(import|route|link)\b", r"\bformat\b", r"\blint\b",
        r"\bprettier\b", r"\beslint\b", r"\bremove\s+(unused|dead)\b",
        r"\bupdate\s+(version|package)\b",
    ],
    "implementation": [
        r"\bbuild\b", r"\bimplement\b", r"\bcreate\b", r"\bfix\b",
        r"\badd\s+feature\b", r"\bwrite\b", r"\bcomponent\b",
        r"\bpage\b", r"\bdeploy\b", r"\btest\b", r"\bupdate\b", r"\brefactor\b",
        r"\bstyle\b", r"\bcss\b", r"\broute\b", r"\bfunction\b",
        r"\bendpoint\b", r"\bparam(eter)?s?\b",
        r"\bvalidat\w*\b", r"\bpars\w*\b",
    ],
    "debugging": [
        r"\bdebug\b",
        r"\bwhy\s+.{0,40}\b(fail|fails|failing|failed|crash|crashes|break|broke|hang|loop)\w*\b",
        r"\bflaky\b", r"\brace\s+(condition|conditions)\b", r"\bregression\b",
        r"\bstack\s+trace\b", r"error:", r"\btraceback\b", r"\bexit\s+code\b",
        r"\bbisect\b", r"\breproduce\b", r"\bcrash\w*\b", r"\bmemory\s+leak\b",
        r"\bstack\s+overflow\b", r"\bhang\w*\b", r"\bloops?\s+infinitely\b",
        r"\binfinite\s+loop\b",
    ],
    "architecture": [],
    "extreme": [r"\brfc\b", r"\bdesign\s+doc\b", r"\bmigration\s+plan\b", r"\bprogram\b"],
}

# Routing should react to a request to do coding work, not merely to the
# vocabulary inside a quoted document, error corpus, or a bag of taxonomy
# words.  These intentionally stay small and structural; detailed task-class
# selection remains the scored classifier below.
_TASK_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:"
    r"(?:can|could|would|will)\s+you\s+|"
    r"help(?:\s+me)?\s+(?:to\s+)?|"
    r")?"
    r"(?:add|analy[sz]e|architect|author|build|bump|change|check|clean|"
    r"configure|convert|create|debug|delete|deploy|design|diagnos\w*|"
    r"document|edit|evaluate|explain|fix|format|generat\w*|implement|"
    r"improv\w*|inspect|integrat\w*|investigate|lint|make|migrat\w*|"
    r"modify|move|optimiz\w*|plan|propose|redesign|refactor|remove|rename|"
    r"reorganize|review|run|search|split|test|update|upgrade|write|"
    r"git\s+(?:commit|push|pull|status|log|diff|add|stash|branch|merge|"
    r"rebase|checkout)|"
    r"do\s+(?:a\s+)?(?:bulk\s+|deep\s+dive\s+|mechanical\s+)*"
    r"(?:rename|pass|deep\s+dive)|"
    r"(?:long-horizon\s+strategy|epic[-\s]level\s+plan|"
    r"program[-\s]level\s+(?:migration\s+)?plan))\b",
    re.IGNORECASE,
)
_TASK_QUESTION_RE = re.compile(
    r"\b(?:why|how)\s+(?:is|are|does|do|did|should|can|would)\b|"
    r"\b(?:what|which)\s+(?:are|is)\s+(?:the\s+)?"
    r"(?:trade-?offs?|best|right|recommended|approach|strategy|design)\b|"
    r"\bshould\s+we\b",
    re.IGNORECASE,
)
_PROBLEM_REPORT_RE = re.compile(
    r"\b(?:error|exception|traceback|stack trace|crash\w*|hang\w*|"
    r"flaky|deadlock|race condition|regression|memory leak)\b",
    re.IGNORECASE,
)
_HELP_RE = re.compile(
    r"\b(?:help\s+(?:me\s+)?(?:figure|diagnose|debug|fix|with)|"
    r"(?:i|we)\s+(?:need|want|would\s+like)\s+(?:you\s+)?(?:a\s+|to\s+)?)\b",
    re.IGNORECASE,
)
_KEYWORD_BAG_WORDS = frozenset(
    "architecture condition deadlock debug deploy epic extreme implementation "
    "mechanical migration platform prod race refactor regression rewrite "
    "traceback tradeoff".split()
)

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
    """Count keyword/pattern hits (per_hit points each), capped per class.

    Non-string keywords (e.g. a numeric or boolean entry in user config) are
    skipped rather than raised, mirroring safe_regex_match for patterns.
    """
    hits = sum(
        1 for kw in keywords if isinstance(kw, str) and kw and kw.lower() in prompt_lower
    )
    hits += sum(1 for p in patterns if safe_regex_match([p], prompt_lower))
    return min(hits * per_hit, cap)


def _looks_like_keyword_bag(prompt_lower):
    """True for a taxonomy-word list with no task-shaped language."""
    words = re.findall(r"[a-z]+", prompt_lower)
    return len(words) >= 5 and all(word in _KEYWORD_BAG_WORDS for word in words)


def has_task_intent(prompt):
    """Whether text is plausibly a coding-assistant request.

    This is deliberately a narrow abstention guard.  It prevents a high score
    from incidental vocabulary, while error reports and normal imperative or
    design questions continue to reach the scored taxonomy.
    """
    if not isinstance(prompt, str):
        return False
    prompt = prompt or ""
    lower = prompt.lower()
    if _looks_like_keyword_bag(lower):
        return False
    return bool(
        _TASK_PREFIX_RE.search(prompt)
        or _TASK_QUESTION_RE.search(prompt)
        or _PROBLEM_REPORT_RE.search(prompt)
        or _HELP_RE.search(prompt)
        or "```" in prompt
    )


def score(prompt, cfg):
    """Score prompt against all classes; returns ScoreResult (deterministic)."""
    thresholds = cfg.get("thresholds", {})
    mechanical_max_words = thresholds.get("mechanical_max_words", 60)
    long_prompt_words = thresholds.get("long_prompt_words", 200)
    question_words = thresholds.get("question_words", 100)

    prompt = prompt if isinstance(prompt, str) else ""
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
    # Long prompts can still describe a pure mechanical batch operation.  Only
    # discard the weak short-imperative prior; retain an explicit mechanical
    # pattern such as a bulk rename or git command.
    if word_count > mechanical_max_words and scores["mechanical"] < 2:
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

    # Extremity: evaluated whenever architecture is AMONG the top-scoring base
    # classes, not only when it is the (tie-break-earlier) nominal pick. On an
    # architecture==debugging tie the strict-> pick is debugging, but the
    # architecture-gated escalation must still get a chance to fire (F5). The
    # primary class pick below is left unchanged; escalation only promotes to
    # extreme when the extreme markers actually clear the threshold.
    base = ("mechanical", "implementation", "debugging", "architecture")
    base_top_score = scores[_top_of(base)]
    if scores["architecture"] >= base_top_score and scores["architecture"] > 0:
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
    if not has_task_intent(prompt):
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
    if not has_task_intent(prompt):
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
