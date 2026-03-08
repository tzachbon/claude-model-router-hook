#!/bin/bash
# Test suite for model-router-hook
# Usage: bash tests/test-model-router.sh

PASS=0
FAIL=0
HOOK="$(cd "$(dirname "$0")/.." && pwd)/plugins/claude-model-router-hook/hooks/model-router-hook.sh"
ORIG_HOME="$HOME"

assert_exit() {
    local desc="$1" input="$2" expected_exit="$3"
    local actual_exit=0
    echo "$input" | bash "$HOOK" >/dev/null 2>/dev/null || actual_exit=$?
    if [ "$actual_exit" -eq "$expected_exit" ]; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
        echo "FAIL: $desc (expected exit $expected_exit, got $actual_exit)"
    fi
}

assert_stderr_contains() {
    local desc="$1" input="$2" expected_str="$3"
    local tmpfile=$(mktemp)
    echo "$input" | bash "$HOOK" >/dev/null 2>"$tmpfile" || true
    if grep -q "$expected_str" "$tmpfile"; then
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
        echo "FAIL: $desc (stderr missing '$expected_str')"
    fi
    rm -f "$tmpfile"
}

setup_config() {
    local config_content="$1"
    local tmpdir=$(mktemp -d)
    mkdir -p "$tmpdir/.claude/hooks"
    if [ -n "$config_content" ]; then
        echo "$config_content" > "$tmpdir/.claude/model-router-config.json"
    fi
    echo '{"model":"sonnet"}' > "$tmpdir/.claude/settings.json"
    export HOME="$tmpdir"
    echo "$tmpdir"
}

setup_config_with_model() {
    local config_content="$1"
    local model="$2"
    local tmpdir=$(mktemp -d)
    mkdir -p "$tmpdir/.claude/hooks"
    if [ -n "$config_content" ]; then
        echo "$config_content" > "$tmpdir/.claude/model-router-config.json"
    fi
    echo "{\"model\":\"$model\"}" > "$tmpdir/.claude/settings.json"
    export HOME="$tmpdir"
    echo "$tmpdir"
}

cleanup() {
    export HOME="$ORIG_HOME"
    if [ -n "$1" ] && [ -d "$1" ]; then
        rm -rf "$1"
    fi
}

# Summary
print_summary() {
    echo ""
    echo "========================"
    echo "Tests: $((PASS+FAIL)) | Pass: $PASS | Fail: $FAIL"
    echo "========================"
    if [ "$FAIL" -gt 0 ]; then
        exit 1
    fi
    exit 0
}

print_summary
