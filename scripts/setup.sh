#!/usr/bin/env bash
# Install ai-session-vault for development.
# Creates a virtualenv and installs the package in editable mode.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m venv "$REPO_ROOT/.venv"
"$REPO_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$REPO_ROOT/.venv/bin/python" -m pip install -e "$REPO_ROOT"

echo
echo "Venv ready. Activate with:"
echo "  source $REPO_ROOT/.venv/bin/activate"
echo "Then run: asv --help"