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
    TMPD=$(mktemp -d)
    mkdir -p "$TMPD/.claude/hooks"
    if [ -n "$config_content" ]; then
        echo "$config_content" > "$TMPD/.claude/model-router-config.json"
    fi
    echo '{"model":"sonnet"}' > "$TMPD/.claude/settings.json"
    export HOME="$TMPD"
}

setup_config_with_model() {
    local config_content="$1"
    local model="$2"
    TMPD=$(mktemp -d)
    mkdir -p "$TMPD/.claude/hooks"
    if [ -n "$config_content" ]; then
        echo "$config_content" > "$TMPD/.claude/model-router-config.json"
    fi
    echo "{\"model\":\"$model\"}" > "$TMPD/.claude/settings.json"
    export HOME="$TMPD"
}

cleanup() {
    export HOME="$ORIG_HOME"
    if [ -n "$TMPD" ] && [ -d "$TMPD" ]; then
        rm -rf "$TMPD"
        TMPD=""
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

# ============================
# Classification Tests
# ============================
echo "--- Classification Tests ---"

# Opus keyword triggers opus (on sonnet model -> mismatch -> block)
setup_config ""
assert_exit "opus keyword triggers block on sonnet" '{"prompt":"architect the system"}' 2
assert_stderr_contains "opus keyword stderr mentions opus" '{"prompt":"architect the system"}' "opus"
cleanup

# Sonnet pattern triggers sonnet (on opus model -> mismatch -> block)
setup_config_with_model "" "opus"
assert_exit "sonnet pattern triggers block on opus" '{"prompt":"build the feature"}' 2
assert_stderr_contains "sonnet pattern stderr mentions sonnet" '{"prompt":"build the feature"}' "sonnet"
cleanup

# Haiku pattern triggers haiku (on opus model -> mismatch -> block)
setup_config_with_model "" "opus"
assert_exit "haiku pattern triggers block on opus" '{"prompt":"git commit all changes"}' 2
assert_stderr_contains "haiku pattern stderr mentions haiku" '{"prompt":"git commit all changes"}' "haiku"
cleanup

# No match allows through
setup_config ""
assert_exit "no match allows through" '{"prompt":"hello"}' 0
cleanup

# Tilde prefix bypasses
setup_config ""
assert_exit "tilde bypasses classification" '{"prompt":"~ architect it"}' 0
cleanup

# Long prompt (>200 words) triggers opus
setup_config ""
LONG_PROMPT=$(python3 -c "print(' '.join(['word'] * 210))")
assert_exit "long prompt triggers opus" "{\"prompt\":\"$LONG_PROMPT\"}" 2
cleanup

# ============================
# Config Loading Tests
# ============================
echo "--- Config Loading Tests ---"

# Valid JSON parsed - custom opus keyword triggers opus
setup_config '{"keywords":{"opus":["xyzmagicword"]}}'
assert_exit "valid config custom keyword triggers opus" '{"prompt":"xyzmagicword please"}' 2
assert_stderr_contains "valid config stderr mentions opus" '{"prompt":"xyzmagicword please"}' "opus"
cleanup

# Malformed JSON warns but defaults apply
TMPD=$(mktemp -d)
mkdir -p "$TMPD/.claude/hooks"
python3 -c "open('$TMPD/.claude/model-router-config.json','w').write('{bad json')"
echo '{"model":"sonnet"}' > "$TMPD/.claude/settings.json"
export HOME="$TMPD"
assert_stderr_contains "malformed JSON warns on stderr" '{"prompt":"hello"}' "warning"
assert_exit "malformed JSON still allows through" '{"prompt":"hello"}' 0
export HOME="$ORIG_HOME"
rm -rf "$TMPD"

# Missing file is silent - no warnings
setup_config ""
rm -f "$HOME/.claude/model-router-config.json"
assert_exit "missing config silent exit 0" '{"prompt":"hello"}' 0
cleanup

# Non-dict JSON returns empty
TMPD=$(mktemp -d)
mkdir -p "$TMPD/.claude/hooks"
echo '[1,2,3]' > "$TMPD/.claude/model-router-config.json"
echo '{"model":"sonnet"}' > "$TMPD/.claude/settings.json"
export HOME="$TMPD"
assert_exit "non-dict JSON falls back to defaults" '{"prompt":"hello"}' 0
export HOME="$ORIG_HOME"
rm -rf "$TMPD"

# ============================
# Config Merging Tests
# ============================
echo "--- Config Merging Tests ---"

# Global config only - custom keyword from global triggers tier
setup_config '{"keywords":{"opus":["globalword"]}}'
assert_exit "global config keyword triggers opus" '{"prompt":"globalword please"}' 2
cleanup

# Project config only - custom keyword from project config triggers tier
# Create a temp git repo with project config
TMPD=$(mktemp -d)
mkdir -p "$TMPD/.claude/hooks"
echo '{"model":"sonnet"}' > "$TMPD/.claude/settings.json"
PROJ=$(mktemp -d)
(cd "$PROJ" && git init -q && mkdir -p .claude && echo '{"keywords":{"opus":["projword"]}}' > .claude/model-router-config.json)
export HOME="$TMPD"
# Run from the project dir so git rev-parse finds it
(cd "$PROJ" && echo '{"prompt":"projword please"}' | bash "$HOOK" >/dev/null 2>/dev/null); PROJ_EXIT=$?
if [ "$PROJ_EXIT" -eq 2 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: project config keyword triggers opus (expected 2, got $PROJ_EXIT)"; fi
export HOME="$ORIG_HOME"
rm -rf "$TMPD" "$PROJ"

# Arrays merged additively - global has "foo", project has "bar", both trigger
TMPD=$(mktemp -d)
mkdir -p "$TMPD/.claude/hooks"
echo '{"keywords":{"opus":["mergefoo"]}}' > "$TMPD/.claude/model-router-config.json"
echo '{"model":"sonnet"}' > "$TMPD/.claude/settings.json"
PROJ=$(mktemp -d)
(cd "$PROJ" && git init -q && mkdir -p .claude && echo '{"keywords":{"opus":["mergebar"]}}' > .claude/model-router-config.json)
export HOME="$TMPD"
(cd "$PROJ" && echo '{"prompt":"mergefoo please"}' | bash "$HOOK" >/dev/null 2>/dev/null); FOO_EXIT=$?
(cd "$PROJ" && echo '{"prompt":"mergebar please"}' | bash "$HOOK" >/dev/null 2>/dev/null); BAR_EXIT=$?
if [ "$FOO_EXIT" -eq 2 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: merged array foo triggers opus (expected 2, got $FOO_EXIT)"; fi
if [ "$BAR_EXIT" -eq 2 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: merged array bar triggers opus (expected 2, got $BAR_EXIT)"; fi
export HOME="$ORIG_HOME"
rm -rf "$TMPD" "$PROJ"

print_summary
