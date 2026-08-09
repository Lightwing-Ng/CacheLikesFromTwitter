#!/usr/bin/env bash

# Code version: v1.0.0-codex.1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/resolve_python.sh"

if ! PYTHON_BIN="$(resolve_python_bin)"; then
	echo "Configured Python 3.13 interpreter not found: ${CACHELIKES_PYTHON:-/usr/local/bin/python3.13}" >&2
	exit 1
fi

cd "$ROOT_DIR"
exec "$PYTHON_BIN" main.py "$@"
