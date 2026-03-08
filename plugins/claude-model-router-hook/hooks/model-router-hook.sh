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

def _log_debug(msg):
    try:
        log_path = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

def load_config(path):
    try:
        with open(os.path.expanduser(path), "r") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            _log_debug(f"config path={path} status=non_dict_ignored")
            return {}
        _log_debug(f"config path={path} status=loaded")
        return cfg
    except FileNotFoundError:
        _log_debug(f"config path={path} status=not_found")
        return {}
    except Exception as e:
        _log_debug(f"config path={path} status=error error=\"{e}\"")
        print(f"model-router: warning: bad config {path}: {e}", file=sys.stderr)
        return {}

def merge_config(base, override):
    result = dict(base)
    for key in ("classifier", "default_model"):
        if key in override:
            result[key] = override[key]
    for section in ("keywords", "patterns"):
        base_sec = result.get(section, {})
        over_sec = override.get(section, {})
        if not isinstance(base_sec, dict):
            base_sec = {}
        if not isinstance(over_sec, dict):
            over_sec = {}
        merged_sec = dict(base_sec)
        for tier in ("opus", "sonnet", "haiku"):
            base_list = base_sec.get(tier, [])
            over_list = over_sec.get(tier, [])
            if not isinstance(base_list, list):
                base_list = []
            if not isinstance(over_list, list):
                over_list = []
            merged_sec[tier] = list(dict.fromkeys(base_list + over_list))
        result[section] = merged_sec
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

# --- Config Assembly ---
try:
    builtin = {
        "classifier": "keywords",
        "default_model": "sonnet",
        "keywords": {
            "opus": [
                "architect", "architecture", "evaluate", "tradeoff", "trade-off",
                "strategy", "strategic", "compare approaches", "why does", "deep dive",
                "redesign", "across the codebase", "investor", "multi-system",
                "complex refactor", "analyze", "analysis", "plan mode", "rethink",
                "high-stakes", "critical decision"
            ],
            "sonnet": [],
            "haiku": []
        },
        "patterns": {
            "opus": [],
            "sonnet": [
                r"\bbuild\b", r"\bimplement\b", r"\bcreate\b", r"\bfix\b", r"\bdebug\b",
                r"\badd\s+feature\b", r"\bwrite\b", r"\bcomponent\b", r"\bservice\b",
                r"\bpage\b", r"\bdeploy\b", r"\btest\b", r"\bupdate\b", r"\brefactor\b",
                r"\bstyle\b", r"\bcss\b", r"\broute\b", r"\bapi\b", r"\bfunction\b"
            ],
            "haiku": [
                r"\bgit\s+(commit|push|pull|status|log|diff|add|stash|branch|merge|rebase|checkout)\b",
                r"\bcommit\b.*\b(change|push|all)\b", r"\bpush\s+(to|the|remote|origin)\b",
                r"\brename\b", r"\bre-?order\b", r"\bmove\s+file\b", r"\bdelete\s+file\b",
                r"\badd\s+(import|route|link)\b", r"\bformat\b", r"\blint\b",
                r"\bprettier\b", r"\beslint\b", r"\bremove\s+(unused|dead)\b",
                r"\bupdate\s+(version|package)\b"
            ]
        }
    }
    cfg = dict(builtin)
    cfg = merge_config(cfg, load_config("~/.claude/model-router-config.json"))

    project_root = None
    try:
        project_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        pass

    if project_root:
        cfg = merge_config(cfg, load_config(
            os.path.join(project_root, ".claude", "model-router-config.json")
        ))

    env_classifier = os.environ.get("CLAUDE_ROUTER_CLASSIFIER", "")
    if env_classifier in ("keywords", "ai", "hybrid"):
        cfg["classifier"] = env_classifier

    env_extra = os.environ.get("CLAUDE_ROUTER_EXTRA_OPUS_KEYWORDS", "")
    if env_extra:
        extras = [k.strip() for k in env_extra.split(",") if k.strip()]
        cfg["keywords"]["opus"] = list(dict.fromkeys(
            cfg["keywords"].get("opus", []) + extras
        ))
except Exception:
    cfg = builtin

def classify_keywords(prompt_lower, word_count, cfg):
    opus_kw = cfg["keywords"].get("opus", [])
    opus_pat = cfg["patterns"].get("opus", [])
    has_opus_signal = any(kw in prompt_lower for kw in opus_kw)
    if not has_opus_signal:
        for p in opus_pat:
            try:
                if re.search(p, prompt_lower):
                    has_opus_signal = True
                    break
            except re.error:
                pass
    if has_opus_signal or (word_count > 100 and "?" in prompt_lower) or word_count > 200:
        return "opus"

    haiku_kw = cfg["keywords"].get("haiku", [])
    haiku_pat = cfg["patterns"].get("haiku", [])
    if word_count < 60:
        haiku_match = any(kw in prompt_lower for kw in haiku_kw)
        if not haiku_match:
            for p in haiku_pat:
                try:
                    if re.search(p, prompt_lower):
                        haiku_match = True
                        break
                except re.error:
                    pass
        if haiku_match:
            return "haiku"

    sonnet_kw = cfg["keywords"].get("sonnet", [])
    sonnet_pat = cfg["patterns"].get("sonnet", [])
    sonnet_match = any(kw in prompt_lower for kw in sonnet_kw)
    if not sonnet_match:
        for p in sonnet_pat:
            try:
                if re.search(p, prompt_lower):
                    sonnet_match = True
                    break
            except re.error:
                pass
    if sonnet_match:
        return "sonnet"

    return None

def classify_ai(prompt):
    try:
        log_path = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        snippet = prompt[:30].replace("\n", " ")
        with open(log_path, "a") as f:
            f.write(f"[{ts}] AI_CLASSIFY_START prompt=\"{snippet}...\"\n")
    except Exception:
        pass
    classification_prompt = (
        "Based on the following user prompt, classify which AI model tier should handle it. "
        "Reply with exactly one word: opus, sonnet, or haiku.\n\n"
        "- opus: complex reasoning, architecture, debugging hard problems, multi-file refactoring\n"
        "- sonnet: moderate tasks, code generation, explanations, standard development\n"
        "- haiku: simple questions, typo fixes, formatting, one-line changes, quick lookups\n\n"
        f"User prompt: {prompt[:500]}"
    )
    try:
        result = subprocess.run(
            ["timeout", "8s", "claude", "-p", "--model", "haiku", "--max-turns", "1",
             classification_prompt],
            capture_output=True, text=True, timeout=10
        )
        answer = result.stdout.strip().lower()
        if answer in ("opus", "sonnet", "haiku"):
            try:
                with open(log_path, "a") as f:
                    f.write(f"[{ts}] AI_CLASSIFY_RESULT answer={answer}\n")
            except Exception:
                pass
            return answer
        try:
            with open(log_path, "a") as f:
                f.write(f"[{ts}] AI_CLASSIFY_INVALID answer=\"{answer[:50]}\"\n")
        except Exception:
            pass
    except Exception as e:
        try:
            with open(log_path, "a") as f:
                f.write(f"[{ts}] AI_CLASSIFY_ERROR error=\"{str(e)[:100]}\"\n")
        except Exception:
            pass
    return "sonnet"

# --- Classify ---
if force_model in ("opus", "sonnet", "haiku"):
    recommendation = force_model
else:
    classifier_mode = cfg.get("classifier", "keywords")
    if classifier_mode == "ai":
        recommendation = classify_ai(prompt)
    elif classifier_mode == "hybrid":
        recommendation = classify_keywords(prompt_lower, word_count, cfg)
        if recommendation is None:
            recommendation = classify_ai(prompt)
    else:
        recommendation = classify_keywords(prompt_lower, word_count, cfg)

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

if [ -n "$STDERR_CONTENT" ]; then
    echo "$STDERR_CONTENT" >&2
fi

if [ $EXIT_CODE -eq 2 ]; then
    exit 2
fi

if [ -n "$STDOUT_RESULT" ]; then
    echo "$STDOUT_RESULT"
fi

exit 0
