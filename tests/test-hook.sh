#!/bin/bash
# Integration tests for the v2 UserPromptSubmit entrypoint (user_prompt_submit.py).
# Tests full hook execution with real config files and stdin payloads.
# CLI fallback is forced off via config in every scripted test so no test can
# ever spawn a real claude subprocess.
#
# Usage: bash tests/test-hook.sh [from repo root]

set -euo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/plugins/claude-model-router-hook/hooks/user_prompt_submit.py"
PASS=0
FAIL=0
ERRORS=()

# ── Helpers ─────────────────────────────────────────────────────────────────

# Create a temporary HOME dir with a fake settings.json for the given model and a
# global v2 model-router.json with classifier.cli_fallback disabled (no subprocess).
make_home() {
    local model="$1"
    local tmpdir
    tmpdir=$(mktemp -d)
    mkdir -p "$tmpdir/.claude/hooks"
    printf '{"model":"%s"}' "$model" > "$tmpdir/.claude/settings.json"
    printf '{"version":2,"classifier":{"cli_fallback":false}}' > "$tmpdir/.claude/model-router.json"
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
    # HOME must be set on the python command (not printf) so the entrypoint sees it
    (cd "$cwd" && printf '%s' "$payload" | HOME="$home_dir" python3 "$HOOK" >"$stderr_file.stdout" 2>"$stderr_file") && HOOK_EXIT=0 || HOOK_EXIT=$?
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
            echo "  FAIL: $test_name - expected exit 0 (allow), got $HOOK_EXIT | stderr: $HOOK_STDERR"
            FAIL=$((FAIL + 1))
            ERRORS+=("$test_name")
        fi
    else
        if [ "$HOOK_EXIT" -eq 2 ] && echo "$HOOK_STDERR" | grep -qi "$expected_model"; then
            echo "  PASS: $test_name"
            PASS=$((PASS + 1))
        else
            echo "  FAIL: $test_name - expected exit 2 with '$expected_model', got exit=$HOOK_EXIT stderr='$HOOK_STDERR'"
            FAIL=$((FAIL + 1))
            ERRORS+=("$test_name")
        fi
    fi
}

# ── Test suites ──────────────────────────────────────────────────────────────

echo "=== Model Router Hook - Integration Tests ==="
echo ""

# ── Suite 1: Default behavior (no config file) ───────────────────────────────
echo "--- Suite 1: Default behavior ---"

HOME_DIR=$(make_home "sonnet")

run_hook "analyze the architecture" "$HOME_DIR"
assert_routes_to "architecture prompt routes to opus from sonnet" "opus"

run_hook "format and lint the code" "$HOME_DIR"
assert_routes_to "confident mechanical prompt downroutes to haiku from sonnet" "haiku"

HOME_OPUS=$(make_home "opus")

run_hook "format and lint the code" "$HOME_OPUS"
assert_routes_to "confident mechanical prompt downroutes to haiku from opus" "haiku"

run_hook "build a new feature" "$HOME_DIR"
assert_routes_to "implementation prompt allowed when already on sonnet" "allow"

HOME_HAIKU=$(make_home "haiku")

run_hook "build a new feature" "$HOME_HAIKU"
# v2 intentional change: implementation work up-routes a haiku session to sonnet
# warn (v1 stayed silent on haiku->sonnet). Design "haiku->sonnet" decision.
assert_routes_to "implementation prompt up-routes haiku session to sonnet warn" "sonnet"

run_hook "~ bypass the router" "$HOME_DIR"
assert_routes_to "tilde prefix bypasses all routing" "allow"

rm -rf "$HOME_DIR" "$HOME_OPUS" "$HOME_HAIKU"

# ── Suite 2: Custom config (extend mode) ────────────────────────────────────
echo ""
echo "--- Suite 2: Custom config (extend mode) ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "version": 2,
  "classifier": { "cli_fallback": false },
  "classes": {
    "architecture": {
      "mode": "extend",
      "keywords": ["my-custom-keyword"]
    }
  }
}
EOF

run_hook "my-custom-keyword should trigger opus" "$HOME_DIR"
assert_routes_to "user-defined keyword triggers opus" "opus"

run_hook "analyze this" "$HOME_DIR"
assert_routes_to "built-in keyword still works in extend mode" "opus"

rm -rf "$HOME_DIR"

# ── Suite 3: Custom config (replace mode) ───────────────────────────────────
echo ""
echo "--- Suite 3: Custom config (replace mode) ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "version": 2,
  "classifier": { "cli_fallback": false },
  "classes": {
    "architecture": {
      "mode": "replace",
      "keywords": ["only-my-keyword"]
    }
  }
}
EOF

run_hook "analyze this" "$HOME_DIR"
assert_routes_to "default architecture keywords removed in replace mode, allow" "allow"

run_hook "only-my-keyword here" "$HOME_DIR"
assert_routes_to "user-defined replace keyword triggers opus" "opus"

rm -rf "$HOME_DIR"

# ── Suite 4: remove_keywords ────────────────────────────────────────────────
echo ""
echo "--- Suite 4: remove_keywords ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "version": 2,
  "classifier": { "cli_fallback": false },
  "classes": {
    "architecture": {
      "mode": "extend",
      "remove_keywords": ["analyze"]
    }
  }
}
EOF

run_hook "analyze this problem" "$HOME_DIR"
assert_routes_to "'analyze' removed from defaults, allow" "allow"

run_hook "deep dive into this" "$HOME_DIR"
assert_routes_to "other default architecture keywords still work" "opus"

rm -rf "$HOME_DIR"

# ── Suite 5: Threshold overrides ─────────────────────────────────────────────
echo ""
echo "--- Suite 5: Threshold overrides ---"

HOME_DIR=$(make_home "sonnet")
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "version": 2,
  "classifier": { "cli_fallback": false },
  "thresholds": {
    "mechanical_max_words": 5
  }
}
EOF

# "lint" with 10 words: mechanical is zeroed once word count passes the threshold (5)
PROMPT="word word word word word word word word word lint"
run_hook "$PROMPT" "$HOME_DIR"
assert_routes_to "10 words exceeds mechanical_max_words=5, mechanical zeroed, allow" "allow"

rm -rf "$HOME_DIR"

# ── Suite 6: Project config overrides global ─────────────────────────────────
echo ""
echo "--- Suite 6: Project overrides global ---"

HOME_DIR=$(make_home "sonnet")
# Global config: lax long-prompt threshold (cli_fallback off carries to project merge)
cat > "$HOME_DIR/.claude/model-router.json" <<'EOF'
{
  "version": 2,
  "classifier": { "cli_fallback": false },
  "thresholds": { "long_prompt_words": 500 }
}
EOF

# Project config: stricter threshold
PROJECT_DIR=$(mktemp -d)
mkdir -p "$PROJECT_DIR/.claude"
cat > "$PROJECT_DIR/.claude/model-router.json" <<'EOF'
{
  "version": 2,
  "thresholds": { "long_prompt_words": 10 }
}
EOF

# 25-word prompt: over 2x the project threshold (10) so the architecture length
# signal fires (+2), but well under the global threshold (500) where it stays silent.
PROMPT="word word word word word word word word word word word word word word word word word word word word word word word word word"
run_hook "$PROMPT" "$HOME_DIR" "$PROJECT_DIR"
assert_routes_to "project long_prompt_words=10 wins over global=500" "opus"

rm -rf "$HOME_DIR" "$PROJECT_DIR"

# ── Suite 7: Invalid JSON config ─────────────────────────────────────────────
echo ""
echo "--- Suite 7: Invalid JSON graceful fallback ---"

HOME_DIR=$(make_home "sonnet")
printf '{invalid json!!' > "$HOME_DIR/.claude/model-router.json"

# Confident architecture prompt: routes on defaults with no CLI tiebreak, so a
# garbage config (which loses the cli_fallback override) still never spawns a subprocess.
run_hook "analyze the architecture and evaluate the tradeoffs" "$HOME_DIR"
assert_routes_to "invalid JSON config falls back to defaults, opus still routes" "opus"

rm -rf "$HOME_DIR"

# ── Suite 8: System prompts always allowed ──────────────────────────────────
echo ""
echo "--- Suite 8: System prompts (XML-tagged) always pass through ---"

HOME_DIR=$(make_home "sonnet")

run_hook '<task-notification><task-id>abc123</task-id><status>completed</status><summary>Agent completed build and deploy</summary></task-notification>' "$HOME_DIR"
assert_routes_to "task-notification with sonnet keywords passes through" "allow"

HOME_OPUS=$(make_home "opus")

run_hook '<task-notification><summary>lint the code</summary></task-notification>' "$HOME_OPUS"
assert_routes_to "task-notification with haiku keywords passes through on opus" "allow"

run_hook '<system-reminder>build a new feature and analyze architecture</system-reminder>' "$HOME_DIR"
assert_routes_to "system-reminder tag passes through" "allow"

rm -rf "$HOME_DIR" "$HOME_OPUS"

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
