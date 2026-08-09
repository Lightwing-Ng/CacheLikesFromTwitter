#!/usr/bin/env bash

# Code version: v1.0.0-codex.1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/resolve_python.sh"

if ! PYTHON_BIN="$(resolve_python_bin)"; then
	echo "Configured Python 3.13 interpreter not found: ${CACHELIKES_PYTHON:-/usr/local/bin/python3.13}" >&2
	echo "Set CACHELIKES_PYTHON only when an explicit Python 3.13 override is required." >&2
	exit 1
fi

echo "Using Python: $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$ROOT_DIR/requirements-dev.txt"

if [[ "${CACHELIKES_SKIP_PLAYWRIGHT_INSTALL:-0}" != "1" ]]; then
	"$PYTHON_BIN" -m playwright install chromium
fi

echo
echo "Environment is ready."
echo "Run tests with: $ROOT_DIR/scripts/test.sh"
echo "Run the quality gate with: $ROOT_DIR/scripts/check.sh"
echo "Run the app with: $ROOT_DIR/scripts/run_app.sh"
