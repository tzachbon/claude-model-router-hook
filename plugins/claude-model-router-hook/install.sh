#!/usr/bin/env bash
set -euo pipefail

# Manual (non-plugin) installer for claude-model-router-hook.
# When installed as a Claude Code plugin, hooks/hooks.json auto-registers the
# four Python entrypoints and no manual step is needed. This script mirrors
# that setup for a manual clone-and-install into ~/.claude.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
AGENTS_DIR="$CLAUDE_DIR/agents"
SCHEMA_DIR="$CLAUDE_DIR/schema"

echo "Installing claude-model-router-hook (v2) to $CLAUDE_DIR"

if [ -e "$AGENTS_DIR" ] || [ -L "$AGENTS_DIR" ]; then
    if [ ! -d "$AGENTS_DIR" ] || [ -L "$AGENTS_DIR" ]; then
        echo "Refusing to replace non-directory agents path: $AGENTS_DIR" >&2
        exit 1
    fi
fi

STAGE="$(mktemp -d)"
trap 'rm -rf -- "$STAGE"' EXIT
STAGED_AGENTS="$STAGE/agents"
mkdir -p "$STAGED_AGENTS"
if [ -d "$AGENTS_DIR" ]; then
    cp -R "$AGENTS_DIR/." "$STAGED_AGENTS/"
fi

# Routed agent variants, generated from the resolved config so only tiers the
# config actually targets get an agent file. A failure here aborts the install
# (set -e): the obvious fallback, copying the committed DEFAULTS set, would
# reinstall variants for tiers this config rejects, which is the bug the
# generator exists to prevent. A conflict with a hand-written agent file is
# reported by name and is the user's call to resolve.
python3 "$REPO_ROOT/scripts/generate_variants.py" \
    --agents-dir "$STAGED_AGENTS" --use-user-config

mkdir -p "$HOOKS_DIR" "$SCHEMA_DIR"

# Router package
rm -rf "$HOOKS_DIR/router"
cp -R "$SCRIPT_DIR/hooks/router" "$HOOKS_DIR/router"

# Python entrypoints
cp "$SCRIPT_DIR/hooks/session_init.py"       "$HOOKS_DIR/session_init.py"
cp "$SCRIPT_DIR/hooks/user_prompt_submit.py" "$HOOKS_DIR/user_prompt_submit.py"
cp "$SCRIPT_DIR/hooks/pre_tool_use.py"       "$HOOKS_DIR/pre_tool_use.py"
cp "$SCRIPT_DIR/hooks/post_tool_use.py"      "$HOOKS_DIR/post_tool_use.py"

# Config schema (v1 + v2 shapes)
cp "$REPO_ROOT/schema/model-router.schema.json" "$SCHEMA_DIR/model-router.schema.json"

if [ -e "$AGENTS_DIR" ] || [ -L "$AGENTS_DIR" ]; then
    if [ ! -d "$AGENTS_DIR" ] || [ -L "$AGENTS_DIR" ]; then
        echo "Refusing to replace non-directory agents path: $AGENTS_DIR" >&2
        exit 1
    fi
    rm -rf -- "$AGENTS_DIR"
fi
cp -R "$STAGED_AGENTS" "$AGENTS_DIR"

echo ""
echo "Installed:"
echo "  hooks/router/                     -> $HOOKS_DIR/router/"
echo "  hooks/session_init.py             -> $HOOKS_DIR/session_init.py"
echo "  hooks/user_prompt_submit.py       -> $HOOKS_DIR/user_prompt_submit.py"
echo "  hooks/pre_tool_use.py             -> $HOOKS_DIR/pre_tool_use.py"
echo "  hooks/post_tool_use.py            -> $HOOKS_DIR/post_tool_use.py"
echo "  agents/routed-*.md                -> $AGENTS_DIR/"
echo "  schema/model-router.schema.json   -> $SCHEMA_DIR/"
echo ""
echo "Register the following in ~/.claude/settings.json:"
echo ""
echo "Under 'SessionStart':"
echo "  { \"type\": \"command\", \"command\": \"python3 \\\"$HOOKS_DIR/session_init.py\\\"\", \"timeout\": 5 }"
echo ""
echo "Under 'UserPromptSubmit':"
echo "  { \"type\": \"command\", \"command\": \"python3 \\\"$HOOKS_DIR/user_prompt_submit.py\\\"\", \"timeout\": 10 }"
echo ""
echo "Under 'PreToolUse' (matcher \"Agent|Task\"):"
echo "  { \"matcher\": \"Agent|Task\", \"hooks\": [ { \"type\": \"command\", \"command\": \"python3 \\\"$HOOKS_DIR/pre_tool_use.py\\\"\", \"timeout\": 10 } ] }"
echo ""
echo "Under 'PostToolUse' (matcher \"Agent|Task\"):"
echo "  { \"matcher\": \"Agent|Task\", \"hooks\": [ { \"type\": \"command\", \"command\": \"python3 \\\"$HOOKS_DIR/post_tool_use.py\\\"\", \"timeout\": 5 } ] }"
echo ""
echo "Routed subagent variants installed to $AGENTS_DIR, one per configured class target (listed above)."
echo ""
echo "Then restart Claude Code."
