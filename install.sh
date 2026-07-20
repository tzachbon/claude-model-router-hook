#!/usr/bin/env bash
set -euo pipefail

# Thin delegation to the single real installer inside the plugin (FR-43).
# Keeps one script to maintain; zero drift between root and plugin copies.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/plugins/claude-model-router-hook/install.sh" "$@"
