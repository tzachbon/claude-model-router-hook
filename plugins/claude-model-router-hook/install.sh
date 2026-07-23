#!/usr/bin/env bash
set -euo pipefail

# Manual (non-plugin) installer for claude-model-router-hook.
# When installed as a Claude Code plugin, hooks/hooks.json auto-registers the
# three python entrypoints and no manual step is needed. This script mirrors
# that setup for a manual clone-and-install into ~/.claude.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CLAUDE_DIR="$HOME/.claude"
HOOKS_DIR="$CLAUDE_DIR/hooks"
AGENTS_DIR="$CLAUDE_DIR/agents"
SCHEMA_DIR="$CLAUDE_DIR/schema"

echo "Installing claude-model-router-hook (v2) to $CLAUDE_DIR"

mkdir -p "$HOOKS_DIR" "$AGENTS_DIR" "$SCHEMA_DIR"

# Router package
rm -rf "$HOOKS_DIR/router"
cp -R "$SCRIPT_DIR/hooks/router" "$HOOKS_DIR/router"

# Python entrypoints
cp "$SCRIPT_DIR/hooks/session_init.py"       "$HOOKS_DIR/session_init.py"
cp "$SCRIPT_DIR/hooks/user_prompt_submit.py" "$HOOKS_DIR/user_prompt_submit.py"
cp "$SCRIPT_DIR/hooks/pre_tool_use.py"       "$HOOKS_DIR/pre_tool_use.py"

# Routed agent variants
cp "$SCRIPT_DIR"/agents/routed-*.md "$AGENTS_DIR/"

# Config schema (v1 + v2 shapes)
cp "$REPO_ROOT/schema/model-router.schema.json" "$SCHEMA_DIR/model-router.schema.json"

echo ""
echo "Installed:"
echo "  hooks/router/                     -> $HOOKS_DIR/router/"
echo "  hooks/session_init.py             -> $HOOKS_DIR/session_init.py"
echo "  hooks/user_prompt_submit.py       -> $HOOKS_DIR/user_prompt_submit.py"
echo "  hooks/pre_tool_use.py             -> $HOOKS_DIR/pre_tool_use.py"
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
echo "Routed subagent variants installed to $AGENTS_DIR (routed-haiku, routed-sonnet-medium, routed-sonnet-high, routed-opus-high, routed-fable-high)."
echo ""
echo "Then restart Claude Code."
