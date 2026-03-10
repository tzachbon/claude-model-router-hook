#!/usr/bin/env bash
set -euo pipefail

HOOKS_DIR="$HOME/.claude/hooks"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing claude-model-router-hook hooks to $HOOKS_DIR"

mkdir -p "$HOOKS_DIR"

cp "$SCRIPT_DIR/hooks/model-router-hook.sh" "$HOOKS_DIR/model-router-hook.sh"
cp "$SCRIPT_DIR/hooks/session-init.sh"  "$HOOKS_DIR/session-init.sh"
cp "$SCRIPT_DIR/hooks/model_router.py"  "$HOOKS_DIR/model_router.py"
chmod +x "$HOOKS_DIR/model-router-hook.sh" "$HOOKS_DIR/session-init.sh"

echo ""
echo "Hooks installed. Add the following to ~/.claude/settings.json:"
echo ""
echo "Under 'SessionStart':"
echo "  { \"type\": \"command\", \"command\": \"$HOOKS_DIR/session-init.sh\", \"timeout\": 2 }"
echo ""
echo "Under 'UserPromptSubmit':"
echo "  { \"type\": \"command\", \"command\": \"$HOOKS_DIR/model-router-hook.sh\", \"timeout\": 2 }"
echo ""
echo "Then restart Claude Code."
