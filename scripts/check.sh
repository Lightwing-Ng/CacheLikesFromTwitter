#!/usr/bin/env bash

# Code version: v1.2.1-codex.1

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/resolve_python.sh"
COVERAGE_MINIMUM="${AGENTIC_CONTEXT_COVERAGE_MINIMUM:-${CACHELIKES_COVERAGE_MINIMUM:-55}}"

if ! PYTHON_BIN="$(resolve_python_bin)"; then
	echo "Supported Python 3.13 or 3.14 interpreter not found: ${AGENTIC_CONTEXT_PYTHON:-${CACHELIKES_PYTHON:-host python3}}" >&2
	exit 1
fi

if ! command -v node >/dev/null 2>&1; then
	echo "Node.js is required for JavaScript syntax checks." >&2
	exit 1
fi

if [[ ! "$COVERAGE_MINIMUM" =~ ^[0-9]+$ ]] || (( COVERAGE_MINIMUM < 0 || COVERAGE_MINIMUM > 100 )); then
	echo "AGENTIC_CONTEXT_COVERAGE_MINIMUM must be an integer from 0 to 100." >&2
	exit 1
fi

cd "$ROOT_DIR"
mkdir -p test-results
export COVERAGE_FILE="$ROOT_DIR/test-results/.coverage"

echo "Quality gate configuration: Python=$PYTHON_BIN, branch coverage minimum=${COVERAGE_MINIMUM}%"

echo "[1/4] Python static checks"
"$PYTHON_BIN" -m ruff check main.py app tests

echo "[2/4] JavaScript syntax checks"
JS_FILE_COUNT=0
while IFS= read -r script_file; do
	JS_FILE_COUNT=$((JS_FILE_COUNT + 1))
	node --check "$script_file"
done < <(find app/web/static -type f -name '*.js' | sort)

if (( JS_FILE_COUNT == 0 )); then
	echo "No first-party JavaScript files were found for syntax checks." >&2
	exit 1
fi

echo "[3/4] JavaScript unit tests"
node --test tests/test_agent_optimization.mjs

echo "[4/4] Python tests with branch coverage"
"$ROOT_DIR/scripts/test.sh" \
	--cov=app \
	--cov-branch \
	--cov-report=term-missing \
	--cov-report=json:test-results/coverage.json \
	--cov-fail-under="$COVERAGE_MINIMUM"

echo "Quality gate passed."
