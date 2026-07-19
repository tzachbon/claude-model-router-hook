"""Headless CLI fallback classifier (FR-25..FR-28).

Shells out to `claude -p ... --model haiku` for low-confidence prompts.
Every failure mode (missing binary, non-zero exit, timeout, garbage reply)
returns None so the heuristic decision applies (fail-open ladder, AC-7.4).
"""

import hashlib
import json
import os
import subprocess
import tempfile
import time

from . import taxonomy

SNIPPET_MAX_CHARS = 1500
CACHE_FILENAME = "classifier-cache.json"
EVICT_FRACTION = 0.2

# Bump when the taxonomy/classification prompt changes so stale cached
# classes are invalidated (cache keys include this revision).
TAXONOMY_REV = "1"

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


def _cache_key(prompt):
    """32-hex-char sha256 of taxonomy revision + full prompt (NFR-5)."""
    return hashlib.sha256((TAXONOMY_REV + prompt).encode("utf-8")).hexdigest()[:32]


def _cache_path(data_dir):
    return os.path.join(data_dir, CACHE_FILENAME)


def _load_cache(data_dir):
    """Read the cache; corrupt/unreadable/malformed -> empty dict (NFR-9)."""
    try:
        with open(_cache_path(data_dir), "r", encoding="utf-8") as fh:
            cache = json.load(fh)
        if not isinstance(cache, dict):
            return {}
        return cache
    except (OSError, ValueError):
        return {}


def _save_cache(data_dir, cache, max_entries):
    """Atomically write the cache (tempfile + os.replace); errors ignored."""
    if len(cache) > max_entries:
        evict = max(1, int(max_entries * EVICT_FRACTION))
        oldest = sorted(cache, key=lambda k: cache[k].get("t", 0))[:evict]
        for key in oldest:
            del cache[key]
    try:
        fd, tmp_path = tempfile.mkstemp(dir=data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cache, fh)
            os.replace(tmp_path, _cache_path(data_dir))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except (OSError, ValueError, TypeError):
        pass


def _cache_lookup(data_dir, key):
    try:
        entry = _load_cache(data_dir).get(key)
        if isinstance(entry, dict) and entry.get("c") in _VALID_REPLIES:
            return entry["c"]
    except Exception:
        pass
    return None


def _cache_store(data_dir, key, klass, max_entries):
    try:
        cache = _load_cache(data_dir)
        cache[key] = {"c": klass, "t": int(time.time())}
        _save_cache(data_dir, cache, max_entries)
    except Exception:
        pass


def classify_cli(prompt, config, data_dir):
    """Classify prompt via headless claude CLI.

    Returns a class name from taxonomy.CLASSES, "abstain" (explicit model
    abstain), or None on any failure (fail-open). Results are cached in
    data_dir keyed by prompt hash; data_dir None/unset skips caching.
    """
    classifier_cfg = config.get("classifier") or {}
    if not classifier_cfg.get("cli_fallback", True):
        return None
    timeout = classifier_cfg.get("cli_timeout_seconds", 8)
    max_entries = classifier_cfg.get("cache_max_entries", 1000)

    key = None
    if data_dir:
        key = _cache_key(prompt)
        cached = _cache_lookup(data_dir, key)
        if cached is not None:
            return cached

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
    reply = _parse_reply(result.stdout)
    if reply is not None and key is not None:
        _cache_store(data_dir, key, reply, max_entries)
    return reply
