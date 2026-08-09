#!/usr/bin/env bash

# Code version: v1.0.0-codex.1

resolve_python_bin() {
	local candidate="${CACHELIKES_PYTHON:-/usr/local/bin/python3.13}"

	if [[ -x "$candidate" ]] && "$candidate" -c \
		'import sys; raise SystemExit(sys.version_info[:2] != (3, 13))' \
		>/dev/null 2>&1; then
		printf '%s\n' "$candidate"
		return 0
	fi

	return 1
}
