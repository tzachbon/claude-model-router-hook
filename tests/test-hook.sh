#!/bin/bash
# Integration tests for hooks/model-router-hook.sh
# Tests full hook execution with real config files and stdin payloads.
#
# Usage: bash tests/test-hook.sh [from repo root]

set -euo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/hooks/model-router-hook.sh"
PASS=0
FAIL=0
ERRORS=()

# ── Helpers ─────────────────────────────────────────────────────────────────

# Create a temporary HOME dir with a fake settings.json for the given model.
make_home() {
    local model="$1"
    local tmpdir
    tmpdir=$(mktemp -d)
    mkdir -p "$tmpdir/.claude/hooks"
    printf '{"model":"%s"}' "$model" > "$tmpdir/.claude/settings.json"
    echo "$tmpdir"
}

# Run the hook with a given prompt and HOME.
# Returns exit code via $HOOK_EXIT, stderr via $HOOK_STDERR.
run_hook() {
    local prompt="$1"
    local home_dir="$2"
    local cwd="${3:-$home_dir}"
    local payload stderr_file
    payload=$(printf '{"prompt":"%s"}' "$prompt")
    stderr_file=$(mktemp)

    # Capture stderr to file, discard stdout, capture exit code without || true
    (cd "$cwd" && HOME="$home_dir" printf '%s' "$payload" | bash "$HOOK" >"$stderr_file.stdout" 2>"$stderr_file") && HOOK_EXIT=0 || HOOK_EXIT=$?
    HOOK_STDERR=$(cat "$stderr_file")
    rm -f "$stderr_file" "$stderr_file.stdout"
}

assert_routes_to() {
    local test_name="$1"
    local expected_model="$2"  # e.g. "opus", "haiku", "sonnet", or "allow"

    if [ "$expected_model" = "allow" ]; then
        if [ "$HOOK_EXIT" -eq 0 ]; then
            echo "  PASS: $test_name"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: $test_name — expected exit 0 (allow), got $HOOK_EXIT | stderr: $HOOK_STDERR"
            FAIL=$((FAIL + 1))
            ERRORS+=("$test_name")
        fi
    else
        if [ "$HOOK_EXIT" -eq 2 ] && echo "$HOOK_STDERR" | grep -qi "$expected_model"; then
            echo "  PASS: $test_name"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: $test_name — expected exit 2 with '$expected_model', got exit=$HOOK_EXIT stderr='$HOOK_STDERR'"
            FAIL=$((FAIL + 1))
            ERRORS+=("$test_name")
        fi
    fi
}

# ── Test suites ──────────────────────────────────────────────────────────────

echo "=== Model Router Hook — Integration Tests ==="
echo ""

# ── Suite 1: Default behavior (no config file) ───────────────────────────────
echo "--- Suite 1: Default behavior ---"

HOME_DIR=$(make_home "sonnet")

run_hook "analyze the architecture" "$HOME_DIR"
assert_routes_to "opus keyword 'analyze' routes to opus from sonnet" "opus"

run_hook "lint the code" "$HOME_DIR"
assert_routes_to "haiku pattern 'lint' routes to haiku from sonnet" "haiku"

HOME_OPUS=$(make_home "opus")

run_hook "lint the code" "$HOME_OPUS"
assert_routes_to "haiku pattern 'lint' routes to haiku from opus" "haiku"

run_hook "build a new feature" "$HOME_DIR"
assert_routes_to "sonnet pattern 'build' is allowed when already on sonnet" "allow"

HOME_HAIKU=$(make_home "haiku")

run_hook "build a new feature" "$HOME_HAIKU"
# Hook only upgrades haiku→opus (not haiku→sonnet), so sonnet prompts on haiku are allowed
assert_routes_to "sonnet prompt allowed when already on haiku (no haiku→sonnet redirect)" "allow"

run_hook "~ bypass the router" "$HOME_DIR"
assert_routes_to "tilde prefix bypasses all routing" "allow"

rm -rf "$HOME_DIR" "$HOME_OPUS" "$HOME_HAIKU"

# ── Suite 2: Custom config — extend mode ────────────────────────────────────
echo ""
echo "--- Suite 2: Custom config (extend mode) ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "opus": {
    "mode": "extend",
    "keywords": ["my-custom-keyword"]
  }
}
EOF

run_hook "my-custom-keyword should trigger opus" "$HOME_DIR"
assert_routes_to "user-defined keyword triggers opus" "opus"

run_hook "analyze this" "$HOME_DIR"
assert_routes_to "built-in keyword still works in extend mode" "opus"

rm -rf "$HOME_DIR"

# ── Suite 3: Custom config — replace mode ───────────────────────────────────
echo ""
echo "--- Suite 3: Custom config (replace mode) ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "opus": {
    "mode": "replace",
    "keywords": ["only-my-keyword"]
  }
}
EOF

run_hook "analyze this" "$HOME_DIR"
assert_routes_to "default opus keyword removed in replace mode — allow" "allow"

run_hook "only-my-keyword here" "$HOME_DIR"
assert_routes_to "user-defined replace keyword triggers opus" "opus"

rm -rf "$HOME_DIR"

# ── Suite 4: remove_keywords ────────────────────────────────────────────────
echo ""
echo "--- Suite 4: remove_keywords ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "opus": {
    "mode": "extend",
    "remove_keywords": ["analyze"]
  }
}
EOF

run_hook "analyze this problem" "$HOME_DIR"
assert_routes_to "'analyze' removed from defaults — allow" "allow"

run_hook "deep dive into this" "$HOME_DIR"
assert_routes_to "other default opus keywords still work" "opus"

rm -rf "$HOME_DIR"

# ── Suite 5: Threshold overrides ─────────────────────────────────────────────
echo ""
echo "--- Suite 5: Threshold overrides ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "thresholds": {
    "haiku_max_word_count": 5
  }
}
EOF

# "lint" with 10 words — would normally be haiku (< 60), but threshold is now 5
PROMPT="word word word word word word word word word lint"
run_hook "$PROMPT" "$HOME_DIR"
assert_routes_to "haiku pattern with 10 words exceeds haiku_max_word_count=5 — not haiku" "allow"

rm -rf "$HOME_DIR"

# ── Suite 6: Project config overrides global ─────────────────────────────────
echo ""
echo "--- Suite 6: Project overrides global ---"

HOME_DIR=$(make_home "sonnet")
# Global config: custom haiku threshold
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "thresholds": { "opus_word_count": 500 }
}
EOF

# Project config: stricter threshold
PROJECT_DIR=$(mktemp -d)
mkdir -p "$PROJECT_DIR/.claude"
cat > "$PROJECT_DIR/.claude/model-router.json" <<'EOF'
{
  "thresholds": { "opus_word_count": 10 }
}
EOF

# 15-word prompt — over project threshold (10) but under global (500)
PROMPT="word word word word word word word word word word word word word word word"
run_hook "$PROMPT" "$HOME_DIR" "$PROJECT_DIR"
assert_routes_to "project opus_word_count=10 wins over global=500" "opus"

rm -rf "$HOME_DIR" "$PROJECT_DIR"

# ── Suite 7: Invalid JSON config ─────────────────────────────────────────────
echo ""
echo "--- Suite 7: Invalid JSON graceful fallback ---"

HOME_DIR=$(make_home "sonnet")
printf '{invalid json!!' > "$HOME_DIR/.claude/model-router.json"

run_hook "analyze this" "$HOME_DIR"
assert_routes_to "invalid JSON config falls back to defaults — opus still routes" "opus"

rm -rf "$HOME_DIR"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ ${#ERRORS[@]} -gt 0 ]; then
    echo "Failed tests:"
    for t in "${ERRORS[@]}"; do
        echo "  - $t"
    done
    exit 1
fi

exit 0
