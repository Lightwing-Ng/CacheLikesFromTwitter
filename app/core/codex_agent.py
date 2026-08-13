"""Native Codex subscription runtime for the local Agent workspace.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
from threading import RLock
import time
from typing import Any, Callable

from .state import utc_now


DEFAULT_CODEX_BINARY = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
CODEX_STATUS_CACHE_SECONDS = 30.0
CODEX_RUN_TIMEOUT_SECONDS = 1_800
CODEX_ACTIVITY_LIMIT = 80
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(token|password|secret|api[_-]?key)\s*=\s*([^\s]+)"
)


def resolve_codex_binary() -> Path | None:
    """Resolve the bundled ChatGPT Codex CLI before consulting PATH."""
    if DEFAULT_CODEX_BINARY.is_file() and os.access(DEFAULT_CODEX_BINARY, os.X_OK):
        return DEFAULT_CODEX_BINARY
    discovered = shutil.which("codex")
    return Path(discovered).resolve() if discovered else None


class CodexRuntimeInspector:
    """Cache the local Codex installation and ChatGPT authentication status."""

    def __init__(self, binary_path: Path | None = None) -> None:
        self._binary_path = binary_path
        self._lock = RLock()
        self._cached_at = 0.0
        self._cached_snapshot: dict[str, Any] | None = None

    @property
    def binary_path(self) -> Path | None:
        """Return the configured or discovered Codex executable."""
        return self._binary_path or resolve_codex_binary()

    def snapshot(self, *, refresh: bool = False) -> dict[str, Any]:
        """Return a bounded, non-secret readiness snapshot."""
        with self._lock:
            now = time.monotonic()
            if (
                not refresh
                and self._cached_snapshot is not None
                and now - self._cached_at < CODEX_STATUS_CACHE_SECONDS
            ):
                return dict(self._cached_snapshot)

            snapshot = self._inspect()
            self._cached_snapshot = snapshot
            self._cached_at = now
            return dict(snapshot)

    def _inspect(self) -> dict[str, Any]:
        binary_path = self.binary_path
        if binary_path is None:
            return {
                "ready": False,
                "authenticated": False,
                "binary_path": "",
                "version": "",
                "message": "Codex is not installed with the ChatGPT desktop app.",
            }

        try:
            version_result = subprocess.run(
                [str(binary_path), "--version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            login_result = subprocess.run(
                [str(binary_path), "login", "status"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "ready": False,
                "authenticated": False,
                "binary_path": str(binary_path),
                "version": "",
                "message": f"Codex readiness check failed: {exc}",
            }

        version = (version_result.stdout or version_result.stderr or "").strip().splitlines()
        login_output = (login_result.stdout or login_result.stderr or "").strip()
        authenticated = (
            login_result.returncode == 0
            and "logged in using chatgpt" in login_output.casefold()
        )
        ready = version_result.returncode == 0 and authenticated
        return {
            "ready": ready,
            "authenticated": authenticated,
            "binary_path": str(binary_path),
            "version": version[0][:120] if version else "",
            "message": (
                "Ready through the ChatGPT subscription."
                if ready
                else "Open the ChatGPT desktop app and sign in before using Agent."
            ),
        }


def resolve_agent_workspace(workspace_path: str) -> Path:
    """Resolve one exact local project directory for a native Agent run."""
    workspace = Path(str(workspace_path or "")).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace directory was not found: {workspace}")
    return workspace


def run_codex_agent(
    *,
    prompt: str,
    workspace_path: str,
    config: Any,
    settings: Any,
    should_stop: Callable[[], bool],
    update: Callable[..., None],
    binary_path: Path | None = None,
) -> tuple[str, str]:
    """Run one autonomous Codex turn and stream safe progress summaries."""
    del config, settings
    executable = binary_path or resolve_codex_binary()
    if executable is None:
        raise RuntimeError("Codex is not installed with the ChatGPT desktop app.")

    workspace = resolve_agent_workspace(workspace_path)
    agent_prompt = (
        "Work autonomously on the user request in the current project. Follow every applicable "
        "instruction file, inspect before editing, verify material changes, and report the outcome "
        "with any limitations.\n\nUser request:\n"
        f"{prompt.strip()}"
    )
    command = _build_codex_command(executable, workspace, agent_prompt)
    process = subprocess.Popen(
        command,
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    if process.stdout is None:
        _terminate_process_group(process)
        raise RuntimeError("Codex did not expose its progress stream.")

    activity: list[dict[str, str]] = []
    item_activity_indexes: dict[str, int] = {}
    diagnostics: list[str] = []
    response_text = ""
    thread_id = ""
    deadline = time.monotonic() + CODEX_RUN_TIMEOUT_SECONDS
    stream_selector = selectors.DefaultSelector()
    stream_selector.register(process.stdout, selectors.EVENT_READ)

    update(
        phase="starting",
        message="Starting Codex in the selected project.",
        engine="codex",
        activity=[],
    )
    try:
        while True:
            if should_stop():
                _terminate_process_group(process)
                return response_text, ""
            if time.monotonic() >= deadline:
                _terminate_process_group(process)
                raise RuntimeError("Codex did not finish the Agent request within 30 minutes.")

            for key, _mask in stream_selector.select(timeout=0.25):
                line = key.fileobj.readline()
                if not line:
                    continue
                parsed = _parse_codex_event(line)
                if parsed is None:
                    _append_diagnostic(diagnostics, line)
                    continue
                event_error = _codex_event_error(parsed)
                if event_error:
                    _append_diagnostic(diagnostics, event_error)
                response_text, thread_id = _apply_codex_event(
                    parsed,
                    activity,
                    item_activity_indexes,
                    response_text,
                    thread_id,
                )
                update(
                    phase="running",
                    message=_activity_message(activity),
                    response=response_text,
                    thread_id=thread_id,
                    activity=list(activity),
                )

            if process.poll() is not None:
                remaining = process.stdout.read()
                for line in remaining.splitlines():
                    parsed = _parse_codex_event(line)
                    if parsed is None:
                        _append_diagnostic(diagnostics, line)
                        continue
                    event_error = _codex_event_error(parsed)
                    if event_error:
                        _append_diagnostic(diagnostics, event_error)
                    response_text, thread_id = _apply_codex_event(
                        parsed,
                        activity,
                        item_activity_indexes,
                        response_text,
                        thread_id,
                    )
                break
    finally:
        stream_selector.close()
        process.stdout.close()

    if process.returncode != 0:
        detail = next(
            (line for line in diagnostics if line.casefold().startswith("error:")),
            diagnostics[-1] if diagnostics else f"exit code {process.returncode}",
        )
        raise RuntimeError(f"Codex Agent failed: {detail}")
    if not response_text.strip():
        raise RuntimeError("Codex completed without a final response.")

    update(
        phase="finalizing",
        message="Codex finished the task and returned its verified result.",
        response=response_text,
        thread_id=thread_id,
        activity=list(activity),
    )
    return response_text.strip(), ""


def _build_codex_command(executable: Path, workspace: Path, agent_prompt: str) -> list[str]:
    """Build the compatible autonomous command for the bundled Codex runtime."""
    return [
        str(executable),
        "exec",
        "--json",
        "--color",
        "never",
        "--approve-for-me",
        "--skip-git-repo-check",
        "--cd",
        str(workspace),
        agent_prompt,
    ]


def _parse_codex_event(line: str) -> dict[str, Any] | None:
    """Decode one JSONL event while ignoring CLI diagnostics."""
    try:
        payload = json.loads(line)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _codex_event_error(payload: dict[str, Any]) -> str:
    """Extract a bounded diagnostic from structured Codex failure events."""
    if str(payload.get("type") or "") not in {"error", "turn.failed"}:
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("detail") or error
    return _sanitize_activity_text(str(error or payload.get("message") or ""))[:300]


def _append_diagnostic(diagnostics: list[str], value: str) -> None:
    """Append one sanitized diagnostic while bounding retained process output."""
    clean_diagnostic = _sanitize_activity_text(str(value or "").strip())
    if clean_diagnostic:
        diagnostics.append(clean_diagnostic[:300])
        del diagnostics[:-12]


def _apply_codex_event(
    payload: dict[str, Any],
    activity: list[dict[str, str]],
    item_activity_indexes: dict[str, int],
    response_text: str,
    thread_id: str,
) -> tuple[str, str]:
    """Project one Codex event into the user-facing activity stream."""
    event_type = str(payload.get("type") or "")
    if event_type == "thread.started":
        thread_id = str(payload.get("thread_id") or "")
        return response_text, thread_id

    item = payload.get("item")
    if not isinstance(item, dict):
        return response_text, thread_id
    item_type = str(item.get("type") or "")
    item_id = str(item.get("id") or "")
    if item_type == "agent_message":
        candidate = str(item.get("text") or "").strip()
        return (candidate or response_text), thread_id

    if event_type == "item.started":
        entry = _activity_entry(item, status="running")
        if entry is not None:
            activity.append(entry)
            if item_id:
                item_activity_indexes[item_id] = len(activity) - 1
            _trim_activity(activity, item_activity_indexes)
        return response_text, thread_id

    if event_type == "item.completed":
        index = item_activity_indexes.get(item_id)
        if index is None:
            entry = _activity_entry(item, status="completed")
            if entry is not None:
                activity.append(entry)
                _trim_activity(activity, item_activity_indexes)
            return response_text, thread_id
        exit_code = item.get("exit_code")
        activity[index]["status"] = "failed" if isinstance(exit_code, int) and exit_code != 0 else "completed"
        if isinstance(exit_code, int):
            activity[index]["meta"] = f"Exit {exit_code}"
    return response_text, thread_id


def _activity_entry(item: dict[str, Any], *, status: str) -> dict[str, str] | None:
    """Build one concise activity row without exposing command output."""
    item_type = str(item.get("type") or "")
    if item_type == "command_execution":
        raw_command = str(item.get("command") or "").strip()
        return {
            "kind": "command",
            "label": "Run command",
            "detail": _sanitize_activity_text(raw_command)[:220],
            "status": status,
            "meta": "",
            "timestamp": utc_now(),
        }
    if item_type in {"mcp_tool_call", "tool_call"}:
        tool_name = str(item.get("tool") or item.get("name") or "Tool").strip()
        return {
            "kind": "tool",
            "label": "Use tool",
            "detail": _sanitize_activity_text(tool_name)[:160],
            "status": status,
            "meta": "",
            "timestamp": utc_now(),
        }
    if item_type in {"file_change", "file_operation"}:
        path = str(item.get("path") or item.get("file") or "Workspace files").strip()
        return {
            "kind": "file",
            "label": "Update files",
            "detail": _sanitize_activity_text(path)[:220],
            "status": status,
            "meta": "",
            "timestamp": utc_now(),
        }
    return None


def _trim_activity(
    activity: list[dict[str, str]],
    item_activity_indexes: dict[str, int],
) -> None:
    """Bound status payload size while preserving the newest work."""
    overflow = len(activity) - CODEX_ACTIVITY_LIMIT
    if overflow <= 0:
        return
    del activity[:overflow]
    for item_id, index in list(item_activity_indexes.items()):
        adjusted = index - overflow
        if adjusted < 0:
            item_activity_indexes.pop(item_id, None)
        else:
            item_activity_indexes[item_id] = adjusted


def _activity_message(activity: list[dict[str, str]]) -> str:
    """Describe the latest visible Agent operation."""
    if not activity:
        return "Codex is inspecting the selected project."
    latest = activity[-1]
    detail = latest.get("detail") or latest.get("label") or "Working"
    return f"Codex is working: {detail[:180]}"


def _sanitize_activity_text(value: str) -> str:
    """Remove obvious secret assignments and flatten activity copy."""
    flattened = " ".join(str(value or "").split())
    return _SECRET_ASSIGNMENT_PATTERN.sub(r"\1=[redacted]", flattened)


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Stop the exact native Agent process group with a bounded escalation."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            process.wait(timeout=3)
