#!/usr/bin/env bash

# Code version: v1.1.0-codex.1

resolve_python_bin() {
	local candidate
	local explicit_candidate="${CACHELIKES_PYTHON:-}"
	local candidates=(
		"/opt/homebrew/bin/python3"
		"/opt/homebrew/opt/python@3.14/bin/python3.14"
		"/usr/local/bin/python3.13"
		"/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
		"$(command -v python3 2>/dev/null || true)"
		"$(command -v python 2>/dev/null || true)"
	)

	if [[ -n "$explicit_candidate" ]]; then
		candidates=("$explicit_candidate")
	fi

	for candidate in "${candidates[@]}"; do
		if [[ -x "$candidate" ]] && "$candidate" -c \
			'import sys; raise SystemExit(sys.version_info[:2] not in ((3, 13), (3, 14)))' \
			>/dev/null 2>&1; then
			printf '%s\n' "$candidate"
			return 0
		fi
	done

	return 1
}
