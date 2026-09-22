#!/usr/bin/env bash
# Run the ai-session-vault test suite.
# Usage: ./scripts/test.sh [--verbose]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="python3"
fi

ARGS=("--buffer")
if [[ "${1:-}" == "--verbose" ]]; then
    ARGS+=("-v")
fi

cd "$REPO_ROOT"
PYTHONPATH="$REPO_ROOT/src" "$PYTHON" -m unittest discover -s tests "${ARGS[@]}"