#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/install.sh"
TEST_BASE="${TMPDIR:-/tmp}"
TEST_BASE="${TEST_BASE%/}"
TEST_ROOT="$(mktemp -d "$TEST_BASE/claude-model-router-hook-test.XXXXXX")"
REMOTE_INSTALLER="$TEST_ROOT/install.sh"
cp "$INSTALLER" "$REMOTE_INSTALLER"

cleanup() {
    case "$TEST_ROOT" in
        "$TEST_BASE"/claude-model-router-hook-test.*)
            rm -rf -- "$TEST_ROOT"
            ;;
        *)
            echo "Refusing to remove unexpected test path: $TEST_ROOT" >&2
            exit 1
            ;;
    esac
}
trap cleanup EXIT

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

assert_contains() {
    local file="$1"
    local text="$2"
    grep -Fq -- "$text" "$file" || fail "$file does not contain: $text"
}

assert_empty() {
    local file="$1"
    [ ! -s "$file" ] || fail "$file should be empty"
}

assert_status() {
    local expected="$1"
    [ "$CASE_STATUS" -eq "$expected" ] || fail "expected status $expected, got $CASE_STATUS"
}

assert_count() {
    local file="$1"
    local text="$2"
    local expected="$3"
    local actual
    actual="$(grep -Fo -- "$text" "$file" | wc -l | tr -d '[:space:]')"
    [ "$actual" -eq "$expected" ] || fail "expected $expected occurrences of '$text' in $file, got $actual"
}

make_gh_stub() {
    local bin_dir="$1"
    mkdir -p "$bin_dir"
    # The literal variables belong to the generated stub.
    # shellcheck disable=SC2016
    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'printf "%s\\n" "$*" >> "$GH_LOG"' \
        'if [ "${GH_MODE:-success}" = "failure" ]; then' \
        '    exit 1' \
        'fi' > "$bin_dir/gh"
    chmod +x "$bin_dir/gh"
}

make_claude_stub() {
    local bin_dir="$1"
    mkdir -p "$bin_dir"
    # The literal variables belong to the generated stub.
    # shellcheck disable=SC2016
    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'printf "%s\\n" "$*" >> "$CLAUDE_LOG"' \
        'case "$*" in' \
        '    "plugin marketplace list --json")' \
        '        if [ -f "$MARKETPLACE_STATE" ]; then' \
        '            printf '\''[{"name":"claude-model-router-hook","repo":"tzachbon/claude-model-router-hook"}]\n'\''' \
        '        else' \
        '            printf '\''[]\n'\''' \
        '        fi' \
        '        ;;' \
        '    "plugin marketplace add --scope user tzachbon/claude-model-router-hook")' \
        '        : > "$MARKETPLACE_STATE"' \
        '        ;;' \
        '    "plugin list --json")' \
        '        if [ -f "$PLUGIN_STATE" ]; then' \
        '            printf '\''[{"id":"claude-model-router-hook@claude-model-router-hook","scope":"user"}]\n'\''' \
        '        else' \
        '            printf '\''[]\n'\''' \
        '        fi' \
        '        ;;' \
        '    "plugin install --scope user --yes claude-model-router-hook@claude-model-router-hook")' \
        '        if [ "${CLAUDE_MODE:-success}" = "install_failure" ]; then' \
        '            exit 1' \
        '        fi' \
        '        : > "$PLUGIN_STATE"' \
        '        ;;' \
        '    *)' \
        '        exit 1' \
        '        ;;' \
        'esac' > "$bin_dir/claude"
    chmod +x "$bin_dir/claude"
}

new_case() {
    local name="$1"
    CASE_ROOT="$TEST_ROOT/$name"
    CASE_BIN="$CASE_ROOT/bin"
    CASE_HOME="$CASE_ROOT/home"
    CASE_OUTPUT="$CASE_ROOT/output.log"
    CLAUDE_LOG="$CASE_ROOT/claude.log"
    GH_LOG="$CASE_ROOT/gh.log"
    MARKETPLACE_STATE="$CASE_ROOT/marketplace-state"
    PLUGIN_STATE="$CASE_ROOT/plugin-state"
    CLAUDE_MODE="success"
    GH_MODE="success"
    CASE_STATUS=0
    export CLAUDE_LOG GH_LOG MARKETPLACE_STATE PLUGIN_STATE CLAUDE_MODE GH_MODE
    mkdir -p "$CASE_BIN" "$CASE_HOME"
    : > "$CLAUDE_LOG"
    : > "$GH_LOG"
}

run_case() {
    local input="$1"
    local case_path="$2"
    set +e
    printf '%s' "$input" | HOME="$CASE_HOME" PATH="$case_path" /bin/bash "$REMOTE_INSTALLER" > "$CASE_OUTPUT" 2>&1
    CASE_STATUS=$?
    set -e
}

NORMAL_PATH_SUFFIX="/usr/bin:/bin"

new_case "default-yes"
make_claude_stub "$CASE_BIN"
make_gh_stub "$CASE_BIN"
run_case $'\n\n' "$CASE_BIN:$NORMAL_PATH_SUFFIX"
assert_status 0
assert_contains "$CASE_OUTPUT" ' __ .        .     .  .     .   .  .__'
assert_contains "$CASE_OUTPUT" $'(_)(_| |(/,[    |  |(_)(_)| \\'
assert_contains "$CASE_OUTPUT" "Install in Claude globally? [Y/n] "
assert_contains "$CASE_OUTPUT" "Star on GitHub? [Y/n] "
assert_contains "$CLAUDE_LOG" "plugin marketplace add --scope user tzachbon/claude-model-router-hook"
assert_contains "$CLAUDE_LOG" "plugin install --scope user --yes claude-model-router-hook@claude-model-router-hook"
assert_contains "$GH_LOG" "api --hostname github.com --method PUT /user/starred/tzachbon/claude-model-router-hook"
assert_contains "$CASE_OUTPUT" "Claude registered the bundled hooks."
assert_contains "$CASE_OUTPUT" "Starred tzachbon/claude-model-router-hook on GitHub."
echo "PASS: Enter accepts both defaults"

CLAUDE_LOG_BEFORE="$(wc -l < "$CLAUDE_LOG")"
run_case $'\n\n' "$CASE_BIN:$NORMAL_PATH_SUFFIX"
CLAUDE_LOG_AFTER="$(wc -l < "$CLAUDE_LOG")"
assert_status 0
[ "$((CLAUDE_LOG_AFTER - CLAUDE_LOG_BEFORE))" -eq 2 ] || fail "repeat install ran a mutation command"
assert_contains "$CASE_OUTPUT" "Marketplace already configured."
assert_contains "$CASE_OUTPUT" "Plugin already installed."
echo "PASS: repeat install is idempotent"

new_case "skip-install"
make_claude_stub "$CASE_BIN"
make_gh_stub "$CASE_BIN"
run_case $'N\nYES\n' "$CASE_BIN:$NORMAL_PATH_SUFFIX"
assert_status 0
assert_empty "$CLAUDE_LOG"
assert_contains "$GH_LOG" "api --hostname github.com --method PUT /user/starred/tzachbon/claude-model-router-hook"
assert_contains "$CASE_OUTPUT" "Skipped Claude global install."
echo "PASS: n/y skips Claude and stars GitHub"

new_case "skip-star"
make_claude_stub "$CASE_BIN"
make_gh_stub "$CASE_BIN"
run_case $'yes\nNo\n' "$CASE_BIN:$NORMAL_PATH_SUFFIX"
assert_status 0
assert_contains "$CLAUDE_LOG" "plugin install --scope user --yes claude-model-router-hook@claude-model-router-hook"
assert_empty "$GH_LOG"
assert_contains "$CASE_OUTPUT" "Skipped GitHub star."
echo "PASS: y/n installs Claude and skips GitHub"

new_case "skip-both"
run_case $'n\nno\n' "$CASE_BIN"
assert_status 0
assert_empty "$CLAUDE_LOG"
assert_empty "$GH_LOG"
assert_contains "$CASE_OUTPUT" "Skipped Claude global install."
assert_contains "$CASE_OUTPUT" "Skipped GitHub star."
echo "PASS: n/n needs neither CLI"

new_case "invalid-input"
run_case $'maybe\nn\nn\n' "$CASE_BIN"
assert_status 0
assert_contains "$CASE_OUTPUT" "Please answer y or n."
assert_count "$CASE_OUTPUT" "Install in Claude globally? [Y/n] " 2
assert_empty "$CLAUDE_LOG"
assert_empty "$GH_LOG"
echo "PASS: invalid input repeats the same question"

new_case "missing-claude"
run_case $'\nn\n' "$CASE_BIN"
assert_status 1
assert_contains "$CASE_OUTPUT" "Claude Code is required."
assert_contains "$CASE_OUTPUT" "Claude global install failed."
assert_empty "$GH_LOG"
echo "PASS: selected install requires Claude"

new_case "github-failure"
make_claude_stub "$CASE_BIN"
make_gh_stub "$CASE_BIN"
GH_MODE="failure"
export GH_MODE
run_case $'\n\n' "$CASE_BIN:$NORMAL_PATH_SUFFIX"
assert_status 0
assert_contains "$CLAUDE_LOG" "plugin install --scope user --yes claude-model-router-hook@claude-model-router-hook"
assert_contains "$GH_LOG" "api --hostname github.com --method PUT /user/starred/tzachbon/claude-model-router-hook"
assert_contains "$CASE_OUTPUT" "The GitHub star was not added."
echo "PASS: GitHub failure keeps a successful install"

new_case "missing-github"
make_claude_stub "$CASE_BIN"
ln -s /bin/bash "$CASE_BIN/bash"
ln -s "$(command -v python3)" "$CASE_BIN/python3"
run_case $'\n\n' "$CASE_BIN"
assert_status 0
assert_contains "$CLAUDE_LOG" "plugin install --scope user --yes claude-model-router-hook@claude-model-router-hook"
assert_contains "$CASE_OUTPUT" "The GitHub star was not added because gh is not installed."
echo "PASS: missing GitHub CLI keeps a successful install"

new_case "install-failure"
make_claude_stub "$CASE_BIN"
make_gh_stub "$CASE_BIN"
CLAUDE_MODE="install_failure"
export CLAUDE_MODE
run_case $'\n\n' "$CASE_BIN:$NORMAL_PATH_SUFFIX"
assert_status 1
assert_contains "$CASE_OUTPUT" "Claude global install failed."
assert_contains "$GH_LOG" "api --hostname github.com --method PUT /user/starred/tzachbon/claude-model-router-hook"
echo "PASS: GitHub star still runs after install failure"

README_COMMAND="bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/tzachbon/claude-model-router-hook/main/install.sh)\""
assert_contains "$REPO_ROOT/README.md" "$README_COMMAND"
echo "PASS: README command preserves wizard input"
