<div align="center">

# Claude Model Router Hook

**Automatic model switching for Claude Code. No API calls, no config.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)
![Shell](https://img.shields.io/badge/shell-bash-blue)

<video src="docs/slides/public/model-router.mov" width="887" controls></video>

</div>

A Claude Code hook system that classifies every prompt by task complexity and switches your active model automatically. Sub-agent model rules are injected into every session so spawned agents also use the right tier.

## Features

- Classifies prompts by complexity using keyword and pattern matching (zero API calls)
- Warns on tier mismatch by default; optionally auto-switches `settings.json` (`action: "autoswitch"`)
- Injects sub-agent model-selection rules into every session via `SessionStart`
- Prefix any prompt with `~` to bypass classification and keep the current model
- Logs every classification and switch to `~/.claude/hooks/model-router-hook.log`

## How It Works

Two hook scripts run inside Claude Code:

**`session-init.sh`** (`SessionStart`) injects a `systemMessage` into every session that enforces these sub-agent rules:

| Tier | Use for |
|------|---------|
| `haiku` | Git ops, renames, formatting, file lookups, quick reads |
| `sonnet` | Feature work, debugging, writing/editing code, planning |
| `opus` | Architecture, deep multi-file analysis, complex refactors |

![Sub-agent spawned with Sonnet 4.6 model](assets/sub-agent-routing.png)

**`model-router-hook.sh`** (`UserPromptSubmit`) classifies the incoming prompt and compares the recommended tier against the current model in `settings.json`. By default it warns with a recommendation; set `"action": "autoswitch"` in your config to switch automatically.

## Installation

### Plugin install (recommended)

```bash
claude plugin marketplace add tzachbon/claude-model-router-hook
claude plugin install claude-model-router-hook@claude-model-router-hook
```

Hooks are registered automatically. Restart Claude Code to activate.

### One-liner (manual)

```bash
curl -fsSL https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/main/install.sh | bash
```

### Manual

```bash
git clone https://github.com/tzachbon/claude-model-router-hook.git
cd claude-model-router-hook
./install.sh
```

Or copy manually:

```bash
mkdir -p ~/.claude/hooks
cp hooks/session-init.sh hooks/model-router-hook.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/session-init.sh ~/.claude/hooks/model-router-hook.sh
```

Then add hooks to `~/.claude/settings.json` (use the full absolute path from `echo $HOME`):

Under `SessionStart`:

```json
{
  "type": "command",
  "command": "/home/yourname/.claude/hooks/session-init.sh",
  "timeout": 2
}
```

Under `UserPromptSubmit`:

```json
"UserPromptSubmit": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "/home/yourname/.claude/hooks/model-router-hook.sh",
        "timeout": 2
      }
    ]
  }
]
```

Then restart Claude Code.

## Override

Prefix any prompt with `~` to skip classification entirely and keep the current model active.

## Configuration

Routing behavior is controlled by `~/.claude/model-router.json` (global) or `.claude/model-router.json` (project-level, takes priority).

| Key | Values | Default | Description |
|-----|--------|---------|-------------|
| `action` | `"warn"`, `"autoswitch"` | `"warn"` | `warn` shows a recommendation; `autoswitch` changes `settings.json` automatically |

See the [schema](schema/model-router.schema.json) for all options (thresholds, per-tier keywords/patterns, etc.).

## Log

Activity is written to `~/.claude/hooks/model-router-hook.log`:

```
[2026-03-07 12:00:00] model=sonnet rec=opus action=WARN->opus prompt="analyze the entire..."
[2026-03-07 12:01:00] model=opus rec=match action=ALLOW prompt="git commit changes"
[2026-03-07 12:02:00] OVERRIDE prompt="~ keep opus for this..."
```

## Setup Prompt

Copy and paste this into any Claude Code session to install the hooks automatically.

<details>
<summary>View prompt</summary>

```
Set up the model-matchmaker hook system in my global Claude Code config. Do exactly the following steps:

────────────────────────────────────────────────────────────
STEP 1 — Create the hooks directory
────────────────────────────────────────────────────────────

Run: mkdir -p ~/.claude/hooks


────────────────────────────────────────────────────────────
STEP 2 — Create ~/.claude/hooks/session-init.sh
────────────────────────────────────────────────────────────

Write this exact content to the file, then run: chmod +x ~/.claude/hooks/session-init.sh

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
    "additionalContext": "## Model Tier Rules\n\nThese rules apply to YOU and to every sub-agent you spawn.\n\n### Sub-agent model selection (MANDATORY)\nWhen calling the Agent tool, you MUST set the model parameter based on task complexity:\n- **haiku** — simple mechanical tasks: file searches, grep, glob, reading a handful of files, git status/log, listing directories, quick lookups. Default for Explore agents unless deep reasoning is required.\n- **sonnet** — standard implementation: writing/editing code, debugging, creating components, running tests, most general-purpose agents.\n- **opus** — architecture decisions, deep multi-file analysis, complex refactors, plan-mode agents, anything requiring sustained reasoning across large context.\n\nNever default all sub-agents to Opus. Match the model to the work.\n\n### Your own tier${TIER_HINT}\n- Haiku: git ops, renames, formatting, simple edits.\n- Sonnet: feature work, debugging, planning.\n- Opus: architecture, deep analysis, multi-system reasoning.\n\n### Configuration\nIf the user wants to customize routing (keywords, patterns, thresholds), offer to create a config file at \`~/.claude/model-router.json\` (global) or \`.claude/model-router.json\` (project-level). Project config overrides global.\n- **thresholds**: \`opus_word_count\` (default 200), \`opus_question_word_count\` (default 100), \`haiku_max_word_count\` (default 60)\n- **Per tier** (opus/sonnet/haiku): \`mode\` (extend|replace), \`keywords\`, \`patterns\`, \`remove_keywords\`, \`remove_patterns\`\n- Mode \`extend\` (default) merges with built-ins; \`replace\` discards them.\n- **action**: \`warn\` (default) shows a recommendation without switching; \`autoswitch\` changes settings.json automatically.\n- Add \`\"\$schema\": \"https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/main/schema/model-router.schema.json\"\` for IDE validation."
  }
}
EOF

exit 0


────────────────────────────────────────────────────────────
STEP 3 — Create ~/.claude/hooks/model-router-hook.sh
────────────────────────────────────────────────────────────

Write this exact content to the file, then run: chmod +x ~/.claude/hooks/model-router-hook.sh

#!/bin/bash
# Model Router Hook (UserPromptSubmit)
# Classifies prompts and either warns or auto-switches model tier.
# Default: warn only. Set "action": "autoswitch" in config to switch automatically.
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

# --- Load config ---
action_mode = "warn"  # default: warn only, do not auto-switch
for cfg_path in [".claude/model-router.json", os.path.expanduser("~/.claude/model-router.json")]:
    try:
        with open(cfg_path, "r") as f:
            cfg = json.load(f)
        action_mode = cfg.get("action", "warn")
        break
    except Exception:
        pass

# --- Log ---
try:
    log_path = os.path.expanduser("~/.claude/hooks/model-router-hook.log")
    snippet = prompt[:30].replace("\n", " ") + ("..." if len(prompt) > 30 else "")
    rec = recommendation or "match"
    action = f"{action_mode.upper()}->{new_model}" if new_model else "ALLOW"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a") as f:
        f.write(f"[{ts}] model={model} rec={rec} action={action} prompt=\"{snippet}\"\n")
except Exception:
    pass

# --- Act ---
if new_model:
    if action_mode == "autoswitch":
        try:
            settings["model"] = new_model
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            msg = f"[model-router-hook] Switched {model} -> {new_model}  (prefix ~ to bypass)"
        except Exception:
            msg = f"[model-router-hook] Recommended {new_model} for this task but could not auto-switch. Run /model {new_model.split(\"[\")[0]}"
    else:
        msg = f"[model-router-hook] Recommended {new_model} for this task (current: {model}). Run /model {new_model.split(\"[\")[0]} to switch, or prefix ~ to bypass."
    print(json.dumps({"systemMessage": msg}))
'

exit 0


────────────────────────────────────────────────────────────
STEP 4 — Update ~/.claude/settings.json
────────────────────────────────────────────────────────────

Add these two hook entries to the "hooks" object in ~/.claude/settings.json.
Preserve any existing hooks already in the file.

Under "SessionStart", add a second hook entry alongside any existing ones:
  {
    "type": "command",
    "command": "~/.claude/hooks/session-init.sh",
    "timeout": 2
  }

Add a new top-level "UserPromptSubmit" section:
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

Use the full absolute path for "command" (e.g. /Users/yourname/.claude/hooks/...).
You can find your home path by running: echo $HOME


────────────────────────────────────────────────────────────
STEP 5 — Restart Claude Code
────────────────────────────────────────────────────────────

Restart to activate the hooks.
```

</details>

## Credits

Based on [model-matchmaker](https://github.com/coyvalyss1/model-matchmaker) by [@coyvalyss1](https://github.com/coyvalyss1).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
