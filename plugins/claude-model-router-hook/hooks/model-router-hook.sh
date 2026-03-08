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
import json, sys, os, re, subprocess
from datetime import datetime

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

# ENV early exits
if os.environ.get("CLAUDE_ROUTER_DISABLED", "") == "1":
    sys.exit(0)

force_model = os.environ.get("CLAUDE_ROUTER_FORCE_MODEL", "").lower()

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

# --- Classify ---
opus_keywords = [
    "architect", "architecture", "evaluate", "tradeoff", "trade-off",
    "strategy", "strategic", "compare approaches", "why does", "deep dive",
    "redesign", "across the codebase", "investor", "multi-system",
    "complex refactor", "analyze", "analysis", "plan mode", "rethink",
    "high-stakes", "critical decision"
]
haiku_patterns = [
    r"\bgit\s+(commit|push|pull|status|log|diff|add|stash|branch|merge|rebase|checkout)\b",
    r"\bcommit\b.*\b(change|push|all)\b", r"\bpush\s+(to|the|remote|origin)\b",
    r"\brename\b", r"\bre-?order\b", r"\bmove\s+file\b", r"\bdelete\s+file\b",
    r"\badd\s+(import|route|link)\b", r"\bformat\b", r"\blint\b",
    r"\bprettier\b", r"\beslint\b", r"\bremove\s+(unused|dead)\b",
    r"\bupdate\s+(version|package)\b"
]
sonnet_patterns = [
    r"\bbuild\b", r"\bimplement\b", r"\bcreate\b", r"\bfix\b", r"\bdebug\b",
    r"\badd\s+feature\b", r"\bwrite\b", r"\bcomponent\b", r"\bservice\b",
    r"\bpage\b", r"\bdeploy\b", r"\btest\b", r"\bupdate\b", r"\brefactor\b",
    r"\bstyle\b", r"\bcss\b", r"\broute\b", r"\bapi\b", r"\bfunction\b"
]

if force_model in ("opus", "sonnet", "haiku"):
    recommendation = force_model
else:
    has_opus_signal = any(kw in prompt_lower for kw in opus_keywords)
    if has_opus_signal or (word_count > 100 and "?" in prompt) or word_count > 200:
        recommendation = "opus"
    else:
        is_haiku_task = word_count < 60 and any(re.search(p, prompt_lower) for p in haiku_patterns)
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
