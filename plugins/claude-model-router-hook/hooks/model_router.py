"""
Model Router — classifies prompt complexity and recommends a model tier.

Reads JSON from stdin ({"prompt": "..."}), checks ~/.claude/settings.json for
the current model, and exits 0 (allow) or 2 (suggest switch, message on stderr).
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime


def load_config(global_path=None, cwd=None):
    """Load and merge global + project configs.

    Args:
        global_path: Override path for the global config file (for testing).
        cwd: Override working directory to search for project config (for testing).
    """
    config = {}

    # Global config
    if global_path is None:
        global_path = pathlib.Path.home() / ".claude" / "model-router.json"
    else:
        global_path = pathlib.Path(global_path)
    if global_path.exists():
        try:
            with open(global_path) as f:
                config = json.load(f)
        except Exception:
            pass

    # Project config (walk up from CWD to find .claude/model-router.json)
    search_root = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    for parent in [search_root, *search_root.parents]:
        project_path = parent / ".claude" / "model-router.json"
        if project_path.exists():
            try:
                with open(project_path) as f:
                    project_config = json.load(f)
                # Deep merge: project overrides global per-key
                for key in project_config:
                    if key == "$schema":
                        continue
                    if isinstance(project_config[key], dict) and isinstance(config.get(key), dict):
                        config[key] = {**config[key], **project_config[key]}
                    else:
                        config[key] = project_config[key]
            except Exception:
                pass
            break

    return config


def resolve_list(config, tier, field, defaults):
    """Resolve final keyword/pattern list for a tier based on mode."""
    tier_config = config.get(tier, {})
    mode = tier_config.get("mode", "extend")

    if mode == "replace":
        return tier_config.get(field, [])

    # Extend mode
    result = list(defaults)
    result.extend(tier_config.get(field, []))

    # Remove specific entries
    remove_key = f"remove_{field}"
    for item in tier_config.get(remove_key, []):
        if item in result:
            result.remove(item)

    return result


def safe_regex_match(patterns, text):
    """Test if any pattern matches text, silently skipping invalid regexes."""
    for p in patterns:
        try:
            if re.search(p, text):
                return True
        except re.error:
            pass
    return False


def classify_with_haiku_fallback(prompt, timeout=4):
    """Use Haiku via the claude CLI to classify a prompt when regex is not confident.

    Returns "opus", "sonnet", or "haiku", or None on failure.
    """
    if not shutil.which("claude"):
        return None

    classification_prompt = (
        "You are a prompt complexity classifier for Claude Code. "
        "Given the following user prompt, classify it as exactly one of: opus, sonnet, haiku.\n\n"
        "- opus: complex architectural decisions, multi-system analysis, strategic planning, "
        "deep trade-off evaluation, large-scale refactoring\n"
        "- sonnet: building features, implementing components, fixing bugs, debugging, "
        "writing functions/services, deployment tasks\n"
        "- haiku: simple git commands, renaming, formatting, linting, deleting files, "
        "adding imports, trivial edits\n\n"
        f"User prompt: {prompt[:500]}\n\n"
        "Respond with exactly one word: opus, sonnet, or haiku."
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku"],
            input=classification_prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        answer = result.stdout.strip().lower()
        if answer in ("opus", "sonnet", "haiku"):
            return answer
        for tier in ("opus", "sonnet", "haiku"):
            if tier in answer:
                return tier
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    prompt = data.get("prompt", "")

    # System prompts (task notifications, etc.) are not real user input — always allow
    if prompt.lstrip().startswith("<"):
        sys.exit(0)

    # Override: prefix with "~" bypasses all checks
    if prompt.lstrip().startswith("~"):
        try:
            log_path = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
            snippet = prompt[:30].replace("\n", " ") + ("..." if len(prompt) > 30 else "")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a") as f:
                f.write(f"[{ts}] OVERRIDE prompt=\"{snippet}\"\n")
        except Exception:
            pass
        sys.exit(0)

    # Detect model from settings.json
    model = ""
    settings = {}
    settings_path = os.path.expanduser("~/.claude/settings.json")
    try:
        with open(settings_path, "r") as f:
            settings = json.load(f)
        model = settings.get("model", "").lower()
    except Exception:
        sys.exit(0)

    is_opus = "opus" in model
    is_sonnet = "sonnet" in model
    is_haiku = "haiku" in model

    if not (is_opus or is_sonnet or is_haiku):
        sys.exit(0)

    prompt_lower = prompt.lower()

    # --- Load config ---
    config = load_config()

    # --- Classify ---
    default_opus_keywords = [
        "architecture", "trade-off", "deep dive",
        "redesign", "across the codebase", "multi-system",
        "complex refactor", "plan mode",
    ]
    default_haiku_patterns = [
        r"\bgit\s+(commit|push|pull|status|log|diff|add|stash|branch|merge|rebase|checkout)\b",
        r"\bcommit\b.*\b(change|push|all)\b", r"\bpush\s+(to|the|remote|origin)\b",
        r"\brename\b", r"\bmove\s+file\b", r"\bdelete\s+file\b",
        r"\bformat\b", r"\blint\b",
        r"\bprettier\b", r"\beslint\b",
        r"\bupdate\s+(version|package)\b"
    ]
    default_sonnet_patterns = [
        r"\bimplement\b", r"\bfix\b", r"\bdebug\b",
        r"\badd\s+feature\b", r"\bdeploy\b", r"\brefactor\b",
        r"\bwrite\s+(a\s+)?(function|component|service|test|module|script|class|hook|middleware)\b",
        r"\bcreate\s+(a\s+)?(function|component|service|endpoint|module|database|schema|migration)\b",
        r"\b(add|write)\s+(unit\s+|integration\s+|e2e\s+)?tests?\s+(for|to|covering)\b",
    ]

    opus_keywords = resolve_list(config, "opus", "keywords", default_opus_keywords)
    opus_patterns = resolve_list(config, "opus", "patterns", [])
    haiku_patterns = resolve_list(config, "haiku", "patterns", default_haiku_patterns)
    sonnet_patterns = resolve_list(config, "sonnet", "patterns", default_sonnet_patterns)

    has_opus_keyword = any(kw in prompt_lower for kw in opus_keywords)
    has_opus_pattern = safe_regex_match(opus_patterns, prompt_lower)
    has_opus_signal = has_opus_keyword or has_opus_pattern

    if has_opus_signal:
        recommendation = "opus"
    elif safe_regex_match(haiku_patterns, prompt_lower):
        recommendation = "haiku"
    elif safe_regex_match(sonnet_patterns, prompt_lower):
        recommendation = "sonnet"
    else:
        recommendation = None

    # --- Haiku fallback classification ---
    used_fallback = False
    if recommendation is None:
        fallback_config = config.get("fallback", {})
        if fallback_config.get("enabled", False):
            recommendation = classify_with_haiku_fallback(prompt)
            if recommendation is not None:
                used_fallback = True

    # --- Determine if mismatch ---
    block = False
    new_model = None

    if recommendation == "haiku" and (is_opus or is_sonnet):
        block = True
        new_model = "haiku"
    elif recommendation == "sonnet" and is_opus:
        block = True
        suffix = re.search(r"(\[.+?\])$", settings.get("model", ""))
        new_model = "sonnet" + (suffix.group(1) if suffix else "")
    elif recommendation == "opus" and (is_sonnet or is_haiku):
        block = True
        suffix = re.search(r"(\[.+?\])$", settings.get("model", ""))
        new_model = "opus" + (suffix.group(1) if suffix else "")

    # --- Log ---
    try:
        log_path = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
        snippet = prompt[:30].replace("\n", " ") + ("..." if len(prompt) > 30 else "")
        rec = recommendation or "pass-through"
        if used_fallback:
            rec = f"{rec}(fallback)"
        action = f"SUGGEST->{new_model}" if block else "ALLOW"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a") as f:
            f.write(f"[{ts}] model={model} rec={rec} action={action} prompt=\"{snippet}\"\n")
    except Exception:
        pass

    # --- Act ---
    if block and new_model:
        base = new_model.split("[")[0]
        print(f"Run /model {base} then resend  (~ prefix to skip)", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
