#!/bin/bash
# Model Router Hook (UserPromptSubmit)
# Recommends a model tier based on prompt complexity and blocks with
# a "/model X" instruction. The user runs the slash command, then resends.
#
# Override: prefix prompt with "~" to bypass entirely.
# Adapted from model-matchmaker (https://github.com/coyvalyss1/model-matchmaker)

INPUT=$(cat)

LOG_DIR="$HOME/.claude/hooks"
mkdir -p "$LOG_DIR" 2>/dev/null

STDERR_FILE=$(mktemp)
STDOUT_RESULT=$(echo "$INPUT" | python3 -c '
import json, sys, os, re, pathlib
from datetime import datetime

def load_config():
    """Load and merge global + project configs."""
    config = {}

    # Global config
    global_path = pathlib.Path.home() / ".claude" / "model-router.json"
    if global_path.exists():
        try:
            with open(global_path) as f:
                config = json.load(f)
        except Exception:
            pass

    # Project config (walk up from CWD to find .claude/model-router.json)
    cwd = pathlib.Path.cwd()
    for parent in [cwd, *cwd.parents]:
        project_path = parent / ".claude" / "model-router.json"
        if project_path.exists():
            try:
                with open(project_path) as f:
                    project_config = json.load(f)
                # Deep merge: project overrides global per-key
                for key in project_config:
                    if key == "$schema":
                        continue
                    if key == "thresholds" and key in config:
                        config[key] = {**config.get(key, {}), **project_config[key]}
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
        return tier_config.get(field, defaults)

    # Extend mode
    result = list(defaults)
    result.extend(tier_config.get(field, []))

    # Remove specific entries
    remove_key = f"remove_{field}"
    for item in tier_config.get(remove_key, []):
        if item in result:
            result.remove(item)

    return result

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

prompt = data.get("prompt", "")

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
word_count = len(prompt.split())

# --- Load config ---
config = load_config()
thresholds = config.get("thresholds", {})
opus_word_count_threshold = thresholds.get("opus_word_count", 200)
opus_question_word_count_threshold = thresholds.get("opus_question_word_count", 100)
haiku_max_word_count_threshold = thresholds.get("haiku_max_word_count", 60)

# --- Classify ---
default_opus_keywords = [
    "architect", "architecture", "evaluate", "tradeoff", "trade-off",
    "strategy", "strategic", "compare approaches", "why does", "deep dive",
    "redesign", "across the codebase", "investor", "multi-system",
    "complex refactor", "analyze", "analysis", "plan mode", "rethink",
    "high-stakes", "critical decision"
]
default_haiku_patterns = [
    r"\bgit\s+(commit|push|pull|status|log|diff|add|stash|branch|merge|rebase|checkout)\b",
    r"\bcommit\b.*\b(change|push|all)\b", r"\bpush\s+(to|the|remote|origin)\b",
    r"\brename\b", r"\bre-?order\b", r"\bmove\s+file\b", r"\bdelete\s+file\b",
    r"\badd\s+(import|route|link)\b", r"\bformat\b", r"\blint\b",
    r"\bprettier\b", r"\beslint\b", r"\bremove\s+(unused|dead)\b",
    r"\bupdate\s+(version|package)\b"
]
default_sonnet_patterns = [
    r"\bbuild\b", r"\bimplement\b", r"\bcreate\b", r"\bfix\b", r"\bdebug\b",
    r"\badd\s+feature\b", r"\bwrite\b", r"\bcomponent\b", r"\bservice\b",
    r"\bpage\b", r"\bdeploy\b", r"\btest\b", r"\bupdate\b", r"\brefactor\b",
    r"\bstyle\b", r"\bcss\b", r"\broute\b", r"\bapi\b", r"\bfunction\b"
]

opus_keywords = resolve_list(config, "opus", "keywords", default_opus_keywords)
haiku_patterns = resolve_list(config, "haiku", "patterns", default_haiku_patterns)
sonnet_patterns = resolve_list(config, "sonnet", "patterns", default_sonnet_patterns)

has_opus_signal = any(kw in prompt_lower for kw in opus_keywords)
if has_opus_signal or (word_count > opus_question_word_count_threshold and "?" in prompt) or word_count > opus_word_count_threshold:
    recommendation = "opus"
else:
    is_haiku_task = word_count < haiku_max_word_count_threshold and any(re.search(p, prompt_lower) for p in haiku_patterns)
    if is_haiku_task:
        recommendation = "haiku"
    elif any(re.search(p, prompt_lower) for p in sonnet_patterns):
        recommendation = "sonnet"
    else:
        recommendation = None

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
    rec = recommendation or "match"
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
' 2>"$STDERR_FILE")

EXIT_CODE=$?
STDERR_CONTENT=$(cat "$STDERR_FILE")
rm -f "$STDERR_FILE"

if [ $EXIT_CODE -eq 2 ]; then
    echo "$STDERR_CONTENT" >&2
    exit 2
fi

if [ -n "$STDOUT_RESULT" ]; then
    echo "$STDOUT_RESULT"
fi

exit 0
