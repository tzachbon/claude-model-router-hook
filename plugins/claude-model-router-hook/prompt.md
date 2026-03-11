# Model-Matchmaker Hook Setup

Set up the model-matchmaker hook system in your global Claude Code config.

---

## Step 1 — Create the hooks directory

```bash
mkdir -p ~/.claude/hooks
```

---

## Step 2 — Create `~/.claude/hooks/session-init.sh`

Write the content below, then run `chmod +x ~/.claude/hooks/session-init.sh`.

```bash
#!/bin/bash
# Session init hook: injects model-tier guidance into every conversation,
# including mandatory rules for sub-agent model selection.
# Adapted from model-matchmaker (https://github.com/coyvalyss1/model-matchmaker)

INPUT=$(cat)

MODEL=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('model', 'unknown'))
except:
    print('unknown')
" 2>/dev/null)

MODEL_LOWER=$(echo "$MODEL" | tr '[:upper:]' '[:lower:]')
TIER_HINT=""
if echo "$MODEL_LOWER" | grep -q "opus"; then
    TIER_HINT=" You are currently on Opus. For simple tasks (git ops, renames, formatting), mention that Haiku or Sonnet would be cheaper."
elif echo "$MODEL_LOWER" | grep -q "haiku"; then
    TIER_HINT=" You are currently on Haiku. For deep analysis or architecture work, mention that Opus would produce better results."
elif echo "$MODEL_LOWER" | grep -q "sonnet"; then
    TIER_HINT=" You are currently on Sonnet. For simple mechanical tasks Haiku is cheaper; for architecture or deep analysis Opus is better."
fi

cat << EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "## Model Tier Rules\n\nThese rules apply to YOU and to every sub-agent you spawn.\n\n### Sub-agent model selection (MANDATORY)\nWhen calling the Agent tool, you MUST set the model parameter based on task complexity:\n- **haiku** — simple mechanical tasks: file searches, grep, glob, reading a handful of files, git status/log, listing directories, quick lookups. Default for Explore agents unless deep reasoning is required.\n- **sonnet** — standard implementation: writing/editing code, debugging, creating components, running tests, most general-purpose agents.\n- **opus** — architecture decisions, deep multi-file analysis, complex refactors, plan-mode agents, anything requiring sustained reasoning across large context.\n\nNever default all sub-agents to Opus. Match the model to the work.\n\n### Your own tier${TIER_HINT}\n- Haiku: git ops, renames, formatting, simple edits.\n- Sonnet: feature work, debugging, planning.\n- Opus: architecture, deep analysis, multi-system reasoning.\n\n### Configuration\nIf the user wants to customize routing (keywords, patterns, thresholds), offer to create a config file at \`~/.claude/model-router.json\` (global) or \`.claude/model-router.json\` (project-level). Project config overrides global.\n- **thresholds**: \`opus_word_count\` (default 200), \`opus_question_word_count\` (default 100), \`haiku_max_word_count\` (default 60)\n- **Per tier** (opus/sonnet/haiku): \`mode\` (extend|replace), \`keywords\`, \`patterns\`, \`remove_keywords\`, \`remove_patterns\`\n- Mode \`extend\` (default) merges with built-ins; \`replace\` discards them.\n- Add \`\"\$schema\": \"https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/main/schema/model-router.schema.json\"\` for IDE validation."
  }
}
EOF

exit 0
```

---

## Step 3 — Create `~/.claude/hooks/model-router-hook.sh`

Write the content below, then run `chmod +x ~/.claude/hooks/model-router-hook.sh`.

```bash
#!/bin/bash
# Model Router Hook (UserPromptSubmit)
# Auto-switches settings.json to the recommended model tier and injects a
# systemMessage into the chat announcing the switch.
#
# Override: prefix prompt with "~" to bypass entirely.
# Adapted from model-matchmaker (https://github.com/coyvalyss1/model-matchmaker)

INPUT=$(cat)

LOG_DIR="$HOME/.claude/hooks"
mkdir -p "$LOG_DIR" 2>/dev/null

echo "$INPUT" | python3 -c '
import json, sys, os, re
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
new_model = None

if recommendation == "haiku" and (is_opus or is_sonnet):
    new_model = "haiku"
elif recommendation == "sonnet" and is_opus:
    suffix = re.search(r"(\[.+?\])$", settings.get("model", ""))
    new_model = "sonnet" + (suffix.group(1) if suffix else "")
elif recommendation == "opus" and (is_sonnet or is_haiku):
    suffix = re.search(r"(\[.+?\])$", settings.get("model", ""))
    new_model = "opus" + (suffix.group(1) if suffix else "")

# --- Log ---
try:
    log_path = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
    snippet = prompt[:30].replace("\n", " ") + ("..." if len(prompt) > 30 else "")
    rec = recommendation or "match"
    action = f"AUTOSWITCH->{new_model}" if new_model else "ALLOW"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a") as f:
        f.write(f"[{ts}] model={model} rec={rec} action={action} prompt=\"{snippet}\"\n")
except Exception:
    pass

# --- Act ---
if new_model:
    try:
        settings["model"] = new_model
        with open(settings_path, "w") as f:
            json.dump(settings, f, indent=2)
        msg = f"[model-router-hook] Switched {model} -> {new_model}  (prefix ~ to bypass)"
    except Exception:
        msg = f"[model-router-hook] Recommended {new_model} for this task but could not auto-switch. Run /model {new_model.split(\"[\")[0]}"
    print(json.dumps({"systemMessage": msg}))
'

exit 0
```

---

## Step 4 — Update `~/.claude/settings.json`

Add these two hook entries to the `hooks` object. Preserve any existing hooks.

Under `SessionStart`, add alongside any existing entries:

```json
{
  "type": "command",
  "command": "~/.claude/hooks/session-init.sh",
  "timeout": 2
}
```

Add a new `UserPromptSubmit` section:

```json
"UserPromptSubmit": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "~/.claude/hooks/model-router-hook.sh",
        "timeout": 2
      }
    ]
  }
]
```

Use the full absolute path for `command` (e.g. `/home/yourname/.claude/hooks/...`).
Find your home path with: `echo $HOME`

---

## Step 5 — Restart Claude Code

Restart to activate the hooks.

---

## How It Works

- Every prompt is classified by task complexity (keyword + pattern matching, no API calls).
- If your active model doesn't match the task tier, it auto-switches `settings.json` and injects a `systemMessage` into the chat: `[model-router-hook] Switched sonnet -> opus`.
- The switch is visible in the chat on every affected message. No need to re-send.
- Prefix any prompt with `~` to bypass the advisor entirely.
- Every session gets context injecting mandatory sub-agent model rules:
  - `haiku` - file lookups, `grep`, `glob`, `git status`, quick reads
  - `sonnet` - writing/editing code, debugging, general agents
  - `opus` - architecture, deep multi-file analysis, plan-mode agents
- Classifications are logged to `~/.claude/hooks/model-router-hook.log`.
