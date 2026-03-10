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

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

STDERR_FILE=$(mktemp)
STDOUT_RESULT=$(echo "$INPUT" | python3 "$HOOK_DIR/model_router.py" 2>"$STDERR_FILE")

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
