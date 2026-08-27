#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="tzachbon/claude-model-router-hook"
PLUGIN="claude-model-router-hook@claude-model-router-hook"

BANNER_LINES=(
    ' __ .        .     .  .     .   .  .__'
    $'/  `| _.. . _| _   |\\/| _  _| _ |  [__)'
    $'\\__.|(_](_|(_](/,  |  |(_)(_](/,|  |  \\'
    ''
    '       ,        .  .      .'
    ' _ . .-+-_ ._.  |__| _  _ ;_/'
    $'(_)(_| |(/,[    |  |(_)(_)| \\'
)

print_sunset_line() {
    local line="$1"
    local index
    local red
    local green
    local blue

    for ((index = 0; index < ${#line}; index++)); do
        red=$((251 - index * 6 / 38))
        green=$((113 + index * 45 / 38))
        blue=$((133 - index * 122 / 38))
        printf '\033[38;2;%d;%d;%dm%s' "$red" "$green" "$blue" "${line:$index:1}"
    done
    printf '\033[0m\n'
}

print_banner() {
    local line

    if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
        for line in "${BANNER_LINES[@]}"; do
            if [ -n "$line" ]; then
                print_sunset_line "$line"
            else
                printf '\n'
            fi
        done
    else
        printf '%s\n' "${BANNER_LINES[@]}"
    fi
    printf '\n'
}

ask_yes() {
    local prompt="$1"
    local answer

    while true; do
        printf '%s' "$prompt"
        IFS= read -r answer || answer=""
        [ -t 0 ] || printf '\n'
        case "$answer" in
            ""|[Yy]|[Yy][Ee][Ss])
                ASK_RESULT="yes"
                return
                ;;
            [Nn]|[Nn][Oo])
                ASK_RESULT="no"
                return
                ;;
            *)
                echo "Please answer y or n."
                ;;
        esac
    done
}

install_with_claude() {
    command -v claude >/dev/null 2>&1 || {
        echo "Claude Code is required. Install claude, then run this command again." >&2
        return 1
    }
    command -v python3 >/dev/null 2>&1 || {
        echo "Python 3 is required by the router hooks." >&2
        return 1
    }

    echo "Installing $PLUGIN through the Claude plugin manager."
    if claude plugin marketplace list --json | python3 -c 'import json, sys; repo = sys.argv[1]; raise SystemExit(not any(item.get("repo") == repo for item in json.load(sys.stdin)))' "$REPOSITORY"; then
        echo "Marketplace already configured."
    else
        claude plugin marketplace add --scope user "$REPOSITORY" || return 1
    fi

    if claude plugin list --json | python3 -c 'import json, sys; plugin = sys.argv[1]; raise SystemExit(not any(item.get("id") == plugin and item.get("scope") == "user" for item in json.load(sys.stdin)))' "$PLUGIN"; then
        echo "Plugin already installed."
    else
        claude plugin install --scope user --yes "$PLUGIN" || return 1
    fi

    echo "Installed $PLUGIN. Claude registered the bundled hooks."
}

star_repository() {
    echo ""
    echo "Attempting to star $REPOSITORY with GitHub CLI credentials."

    if ! command -v gh >/dev/null 2>&1; then
        echo "The GitHub star was not added because gh is not installed."
        return
    fi

    if gh api --hostname github.com --method PUT "/user/starred/$REPOSITORY" >/dev/null 2>&1; then
        echo "Starred $REPOSITORY on GitHub."
    else
        echo "The GitHub star was not added. Check gh auth status and star $REPOSITORY later."
    fi
}

print_banner

ask_yes "Install in Claude globally? [Y/n] "
INSTALL_CHOICE="$ASK_RESULT"
ask_yes "Star on GitHub? [Y/n] "
STAR_CHOICE="$ASK_RESULT"

EXIT_STATUS=0
if [ "$INSTALL_CHOICE" = "yes" ]; then
    if ! install_with_claude; then
        echo "Claude global install failed." >&2
        EXIT_STATUS=1
    fi
else
    echo "Skipped Claude global install."
fi

if [ "$STAR_CHOICE" = "yes" ]; then
    star_repository
else
    echo "Skipped GitHub star."
fi

exit "$EXIT_STATUS"
