"""Headless CLI fallback classifier (FR-25..FR-28).

Shells out to `claude -p ... --model haiku` for low-confidence prompts.
Every failure mode (missing binary, non-zero exit, timeout, garbage reply)
returns None so the heuristic decision applies (fail-open ladder, AC-7.4).
"""

import os
import subprocess

from . import taxonomy

SNIPPET_MAX_CHARS = 1500

PROMPT_TEMPLATE = """Classify this coding-assistant request into exactly one class.
mechanical: git ops, renames, formatting, trivial single-step edits
implementation: writing or modifying code/features/tests, routine work
debugging: diagnosing failures, flaky tests, errors, regressions
architecture: design decisions, tradeoffs, deep multi-file analysis
extreme: architecture-scale, multi-system, long-horizon work
abstain: cannot tell / needs more info
Reply with ONLY the class word.
Request:
\"\"\"
{snippet}
\"\"\"
"""

_VALID_REPLIES = set(taxonomy.CLASSES) | {"abstain"}


def build_prompt(prompt):
    """Render the classification prompt from the first 1500 chars of prompt."""
    return PROMPT_TEMPLATE.format(snippet=prompt[:SNIPPET_MAX_CHARS])


def _parse_reply(stdout):
    """Strip/lower first token; must be a known class or abstain, else None."""
    tokens = (stdout or "").strip().lower().split()
    if not tokens:
        return None
    reply = tokens[0]
    if reply in _VALID_REPLIES:
        return reply
    return None


def classify_cli(prompt, config, data_dir):
    """Classify prompt via headless claude CLI.

    Returns a class name from taxonomy.CLASSES, "abstain" (explicit model
    abstain), or None on any failure (fail-open). data_dir is reserved for
    the classifier cache (task 2.9); caching is not implemented here yet.
    """
    classifier_cfg = config.get("classifier") or {}
    if not classifier_cfg.get("cli_fallback", True):
        return None
    timeout = classifier_cfg.get("cli_timeout_seconds", 8)

    try:
        result = subprocess.run(
            ["claude", "-p", build_prompt(prompt), "--model", "haiku"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "CLAUDE_MODEL_ROUTER_CHILD": "1"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return _parse_reply(result.stdout)
