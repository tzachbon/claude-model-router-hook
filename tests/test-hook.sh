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

# Like make_home but also pins effortLevel in settings.json (effort-distance suites).
make_home_effort() {
    local model="$1"
    local effort="$2"
    local tmpdir
    tmpdir=$(mktemp -d)
    mkdir -p "$tmpdir/.claude/hooks"
    printf '{"model":"%s","effortLevel":"%s"}' "$model" "$effort" > "$tmpdir/.claude/settings.json"
    printf '{"version":2,"classifier":{"cli_fallback":false}}' > "$tmpdir/.claude/model-router.json"
    echo "$tmpdir"
}

# Like make_home but with apply_mode autoswitch and a settings.json carrying a
# foreign key ("theme") so writes can be checked for key preservation.
# $1 model, $2 effortLevel (default high), $3 allow_fable_autoswitch (default false).
make_home_autoswitch() {
    local model="$1"
    local effort="${2:-high}"
    local allow_fable="${3:-false}"
    local tmpdir
    tmpdir=$(mktemp -d)
    mkdir -p "$tmpdir/.claude/hooks"
    printf '{"model":"%s","effortLevel":"%s","theme":"dark"}' "$model" "$effort" > "$tmpdir/.claude/settings.json"
    printf '{"version":2,"apply_mode":"autoswitch","allow_fable_autoswitch":%s,"classifier":{"cli_fallback":false}}' "$allow_fable" > "$tmpdir/.claude/model-router.json"
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

run_hook "evaluate the tradeoff" "$HOME_DIR"
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

# ── Assert HOOK_STDERR contains a fixed substring ────────────────────────────
assert_stderr_contains() {
    local test_name="$1"
    local needle="$2"

    if echo "$HOOK_STDERR" | grep -qF -- "$needle"; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name - stderr missing '$needle' | stderr: $HOOK_STDERR"
        FAIL=$((FAIL + 1))
        ERRORS+=("$test_name")
    fi
}

# ── Suite 9: Extreme class, effort emission, suffix (FR-41, AC-1.1/1.4/10.5) ──
echo ""
echo "--- Suite 9: Extreme -> fable, effort message, [1m] suffix ---"

EXTREME_PROMPT="write an rfc design doc for the distributed architecture and evaluate the tradeoffs"

HOME_DIR=$(make_home "sonnet")

run_hook "$EXTREME_PROMPT" "$HOME_DIR"
assert_routes_to "extreme prompt on sonnet suggests fable" "fable"
assert_stderr_contains "extreme warn emits /effort suggestion" "/effort"

rm -rf "$HOME_DIR"

# AC-1.4: [1m] suffix on the session model carries into the /model suggestion,
# alongside the /effort part.
HOME_1M=$(make_home "sonnet[1m]")

run_hook "$EXTREME_PROMPT" "$HOME_1M"
assert_stderr_contains "[1m] suffix preserved in /model fable suggestion" "/model fable[1m]"
assert_stderr_contains "[1m] suffix suggestion still carries /effort" "/effort"

rm -rf "$HOME_1M"

# AC-10.5 anti-nagging: architecture on opus targets opus/xhigh; effort_distance
# from high is 1 (< default warn distance 2) so it stays silent, while distance 2
# (from medium) warns with the /effort xhigh suggestion.
ARCH_PROMPT="analyze the architecture and evaluate the tradeoffs deeply"

HOME_D1=$(make_home_effort "opus" "high")
run_hook "$ARCH_PROMPT" "$HOME_D1"
assert_routes_to "effort distance 1 mismatch stays silent" "allow"
rm -rf "$HOME_D1"

HOME_D2=$(make_home_effort "opus" "medium")
run_hook "$ARCH_PROMPT" "$HOME_D2"
assert_routes_to "effort distance 2 mismatch warns" "opus"
assert_stderr_contains "effort distance 2 warn suggests /effort xhigh" "/effort xhigh"
rm -rf "$HOME_D2"

# ── PreToolUse runner + assertions (FR-41, AC-4.x, AC-5.1, AC-10.5) ──────────
PRE_HOOK="$(cd "$(dirname "$0")/.." && pwd)/plugins/claude-model-router-hook/hooks/pre_tool_use.py"

# Run pre_tool_use.py with a tool-event JSON payload and HOME.
# Sets PRE_STDOUT (raw stdout JSON) and PRE_EXIT. Optional $3 = extra env
# assignment (e.g. "CLAUDE_MODEL_ROUTER_CHILD=1").
run_pre_hook() {
    local payload="$1"
    local home_dir="$2"
    local extra_env="${3:-}"
    local out_file
    out_file=$(mktemp)
    (printf '%s' "$payload" | HOME="$home_dir" env $extra_env python3 "$PRE_HOOK" >"$out_file" 2>/dev/null) && PRE_EXIT=0 || PRE_EXIT=$?
    PRE_STDOUT=$(cat "$out_file")
    rm -f "$out_file"
}

# Assert PRE_STDOUT satisfies a python assertion snippet (stdin = PRE_STDOUT).
assert_pre_json() {
    local test_name="$1"
    local py="$2"
    if printf '%s' "$PRE_STDOUT" | python3 -c "$py" >/dev/null 2>&1; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name - stdout: $PRE_STDOUT"
        FAIL=$((FAIL + 1))
        ERRORS+=("$test_name")
    fi
}

# Assert a clean pass-through: exit 0 and no stdout at all.
assert_pre_passthrough() {
    local test_name="$1"
    if [ "$PRE_EXIT" -eq 0 ] && [ -z "$PRE_STDOUT" ]; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name - exit=$PRE_EXIT stdout: $PRE_STDOUT"
        FAIL=$((FAIL + 1))
        ERRORS+=("$test_name")
    fi
}

# ── Suite 10: PreToolUse rewrite + respect contract (FR-41) ──────────────────
echo ""
echo "--- Suite 10: PreToolUse subagent rewrite + respect ---"

HOME_DIR=$(make_home "sonnet")
MECH_PROMPT="rename the file src/a.py to src/b.py and fix imports"

# Generic mechanical spawn: full rewrite -> routed-haiku variant + bare model alias.
run_pre_hook "{\"tool_name\":\"Agent\",\"tool_input\":{\"subagent_type\":\"general-purpose\",\"prompt\":\"$MECH_PROMPT\"}}" "$HOME_DIR"
assert_pre_json "generic mechanical spawn rewrites to routed-haiku + model haiku" \
    'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; u=d["updatedInput"]; assert d["permissionDecision"]=="allow"; assert u["subagent_type"]=="claude-model-router-hook:routed-haiku"; assert u["model"]=="haiku"'

# Custom subagent_type: model-only injection, subagent_type left untouched (FR-15).
run_pre_hook "{\"tool_name\":\"Agent\",\"tool_input\":{\"subagent_type\":\"my-custom-agent\",\"prompt\":\"$MECH_PROMPT\"}}" "$HOME_DIR"
assert_pre_json "custom subagent_type gets model-only injection, type untouched" \
    'import json,sys; u=json.load(sys.stdin)["hookSpecificOutput"]["updatedInput"]; assert u["model"]=="haiku"; assert u["subagent_type"]=="my-custom-agent"'

# Explicit caller model: respected, no updatedInput (locked decision 4).
run_pre_hook '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose","model":"opus","prompt":"rename file a to b"}}' "$HOME_DIR"
assert_pre_json "explicit caller model yields no updatedInput" \
    'import json,sys; raw=sys.stdin.read(); d=json.loads(raw) if raw.strip() else {}; assert "updatedInput" not in d.get("hookSpecificOutput",{})'

# Abstain (unclassifiable prompt): pass-through, no updatedInput (AC-4.3).
run_pre_hook '{"tool_name":"Agent","tool_input":{"subagent_type":"general-purpose","prompt":"hello there friend"}}' "$HOME_DIR"
assert_pre_passthrough "abstain prompt passes through with no output"

# Child recursion guard: exit 0, no output (AC-10.5).
run_pre_hook "{\"tool_name\":\"Agent\",\"tool_input\":{\"subagent_type\":\"general-purpose\",\"prompt\":\"$MECH_PROMPT\"}}" "$HOME_DIR" "CLAUDE_MODEL_ROUTER_CHILD=1"
assert_pre_passthrough "CLAUDE_MODEL_ROUTER_CHILD guard exits 0 with no output"

# Malformed stdin: fail open, exit 0, no output (FR-18).
run_pre_hook '{not json' "$HOME_DIR"
assert_pre_passthrough "malformed stdin exits 0 with no output"

rm -rf "$HOME_DIR"

# ── Autoswitch assertions (FR-9, FR-10, FR-11, AC-3.2, AC-3.3) ───────────────

# Assert the fake HOME's settings.json satisfies a python assertion snippet
# (the file path is passed as sys.argv[1]).
assert_settings() {
    local test_name="$1"
    local home_dir="$2"
    local py="$3"
    if python3 -c "$py" "$home_dir/.claude/settings.json" >/dev/null 2>&1; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name - settings: $(cat "$home_dir/.claude/settings.json")"
        FAIL=$((FAIL + 1))
        ERRORS+=("$test_name")
    fi
}

# Assert the fake HOME's settings.json is byte-identical to a captured baseline.
assert_settings_unchanged() {
    local test_name="$1"
    local home_dir="$2"
    local before="$3"
    local after
    after=$(cat "$home_dir/.claude/settings.json")
    if [ "$before" = "$after" ]; then
        echo "  PASS: $test_name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $test_name - settings changed to: $after"
        FAIL=$((FAIL + 1))
        ERRORS+=("$test_name")
    fi
}

# ── Suite 11: Autoswitch settings write (FR-9, FR-10, AC-3.2) ─────────────────
echo ""
echo "--- Suite 11: Autoswitch writes settings for new sessions ---"

AS_ARCH_PROMPT="analyze the architecture and evaluate the tradeoffs deeply"

# Clean project cwd (no .claude) so the write path is the fake home settings.json
# and no project-level setting masks it.
HOME_AS=$(make_home_autoswitch "sonnet" "high" "false")
PROJ_CLEAN=$(mktemp -d)

run_hook "$AS_ARCH_PROMPT" "$HOME_AS" "$PROJ_CLEAN"
assert_routes_to "autoswitch tier mismatch exits 2 with opus notice" "opus"
assert_stderr_contains "autoswitch stderr claims new sessions, not live switch" "new sessions"
assert_settings "autoswitch writes model+effortLevel, preserves foreign key" "$HOME_AS" \
    'import json,sys; s=json.load(open(sys.argv[1])); assert "opus" in s["model"]; assert s.get("effortLevel"); assert s["theme"]=="dark"'

rm -rf "$HOME_AS" "$PROJ_CLEAN"

# ── Suite 12: Fable autoswitch gate off -> warn, no write (FR-11, AC-3.3) ─────
echo ""
echo "--- Suite 12: Fable autoswitch gated off warns without writing ---"

AS_EXTREME_PROMPT="write an rfc design doc for the distributed architecture and evaluate the tradeoffs"

HOME_FG=$(make_home_autoswitch "sonnet" "high" "false")
PROJ_CLEAN=$(mktemp -d)
FG_BEFORE=$(cat "$HOME_FG/.claude/settings.json")

run_hook "$AS_EXTREME_PROMPT" "$HOME_FG" "$PROJ_CLEAN"
assert_routes_to "fable decision with gate off warns instead of writing" "fable"
assert_settings_unchanged "fable gate off leaves settings.json unwritten" "$HOME_FG" "$FG_BEFORE"

rm -rf "$HOME_FG" "$PROJ_CLEAN"

# ── Suite 13: Corrupt settings.json degrades to warn (FR-10, AC-3.2) ──────────
echo ""
echo "--- Suite 13: Corrupt settings.json degrades autoswitch to warn ---"

# Session model resolves from the project settings.local.json; the fake home
# settings.json (the write target) is corrupt, so the write fails and the hook
# degrades to a plain warn while leaving the file byte-identical.
HOME_CO=$(make_home_autoswitch "sonnet" "high" "false")
printf '{corrupt json!!' > "$HOME_CO/.claude/settings.json"
CO_BEFORE=$(cat "$HOME_CO/.claude/settings.json")

PROJ_MODEL=$(mktemp -d)
mkdir -p "$PROJ_MODEL/.claude"
printf '{"model":"sonnet","effortLevel":"high"}' > "$PROJ_MODEL/.claude/settings.local.json"

run_hook "$AS_ARCH_PROMPT" "$HOME_CO" "$PROJ_MODEL"
assert_routes_to "corrupt settings.json degrades autoswitch to warn" "opus"
assert_settings_unchanged "corrupt settings.json left byte-identical" "$HOME_CO" "$CO_BEFORE"

rm -rf "$HOME_CO" "$PROJ_MODEL"

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
