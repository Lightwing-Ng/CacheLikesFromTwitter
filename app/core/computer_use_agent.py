"""Browser-mediated Computer Use agent for signed-in ChatGPT Web.

Code version: v3.4.0-codex.2
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from .browser_sessions import (
    browser_descriptors,
    goto_with_retry,
    launch_chromium_context,
    sync_playwright_or_error,
)
from .chatgpt_agent_sources import (
    normalize_chatgpt_conversation_url,
    normalize_chatgpt_project_url,
)
from .config import CrawlConfig, PROJECT_ROOT, resolve_runtime_root
from .safari_automation import SafariContext
from .state import utc_now


LOGGER = logging.getLogger(__name__)
CHATGPT_HOME_URL = "https://chatgpt.com/"
CHATGPT_HOSTS = {"chatgpt.com", "www.chatgpt.com"}
DEFAULT_AGENT_SETTINGS_PATH = (
    Path.home()
    / "Library/Application Support/CacheLikesFromTwitter/computer-use-agent.json"
)
DEFAULT_AGENT_RUNTIME_ROOT = (
    resolve_runtime_root() / ".computer-use-agent"
    if os.environ.get("CACHELIKES_RUNTIME_ROOT", "").strip()
    else Path.home()
    / "Library/Application Support/CacheLikesFromTwitter/computer-use-agent"
)
DEFAULT_CONTEXT_LIMIT_MIB = 8
MIN_CONTEXT_LIMIT_MIB = 1
MAX_CONTEXT_LIMIT_MIB = 512
DEFAULT_MAX_TURNS = 40
MIN_MAX_TURNS = 2
MAX_MAX_TURNS = 120
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
MIN_COMMAND_TIMEOUT_SECONDS = 5
MAX_COMMAND_TIMEOUT_SECONDS = 1_800
MAX_ACTION_OUTPUT_CHARS = 48_000
MAX_FILE_READ_CHARS = 120_000
MAX_ACTION_JSON_CHARS = 800_000
WEB_RESPONSE_MINIMUM_SECONDS = 1.5
WEB_RESPONSE_STABLE_SECONDS = 1.0
WEB_TURN_TIMEOUT_SECONDS = 1_800
CHATGPT_COMPOSER_TIMEOUT_SECONDS = 60
CHATGPT_COMPOSER_RELOAD_ATTEMPTS = 2
SAFARI_SEND_BUTTON_TIMEOUT_SECONDS = 15
CHROMIUM_SEND_BUTTON_TIMEOUT_SECONDS = 180
CHROMIUM_SUBMISSION_ACCEPT_TIMEOUT_SECONDS = 15
WEB_SEND_BUTTON_POLL_MILLISECONDS = 250
WEB_PROGRESS_TEXT = {"thinking", "working", "searching", "analyzing", "generating"}
SUPPORTED_BROWSERS = frozenset({"chrome", "edge", "safari"})
SUPPORTED_OPERATING_SYSTEMS = frozenset({"macos", "windows"})
SUPPORTED_AGENT_SESSION_MODES = frozenset({"new", "recent", "project_new", "project_session"})
DEFAULT_CHATGPT_MODEL = "gpt-5.6-sol"
CHATGPT_MODEL_OPTIONS = (
    {
        "key": DEFAULT_CHATGPT_MODEL,
        "label": "GPT-5.6 Sol",
        "remote_label": "GPT-5.6 Sol",
    },
)
SUPPORTED_CHATGPT_MODELS = frozenset(option["key"] for option in CHATGPT_MODEL_OPTIONS)
OPERATING_SYSTEM_OPTIONS = (
    {
        "key": "macos",
        "label": "macOS",
        "icon_filename": "images/finder.svg",
        "available": True,
    },
    {
        "key": "windows",
        "label": "Windows",
        "icon_filename": "images/MSFT.svg",
        "available": False,
    },
)
BROWSER_OPTIONS = (
    {"key": "safari", "label": "Safari", "icon_filename": "images/browser.safari.png"},
    {"key": "edge", "label": "Edge", "icon_filename": "images/browser.edge.png"},
    {"key": "chrome", "label": "Chrome", "icon_filename": "images/browser.chrome.png"},
)

DEFAULT_MACOS_SYSTEM_PROMPT = """You are the reasoning component of a local Computer Use coding agent.
The controller runs on macOS and owns one selected project. It can read and change only that project and can run bounded local checks. Treat controller results as authoritative. Never claim a file changed or a check passed until the controller reports it.

Work autonomously from the user's request. Read the repository instruction files before editing. Make the smallest correct change, preserve unrelated work, use existing project patterns, and verify material changes. Keep context economical: request only the files or ranges needed, keep command output bounded, and do not repeat controller results.

Every response during execution must be exactly one JSON object, with no Markdown fence and no prose outside JSON. Use one of these actions:
{"action":"list","path":".","depth":2}
{"action":"read","path":"relative/file","start_line":1,"end_line":240}
{"action":"search","query":"text or regex","path":".","glob":"*.py","max_results":80}
{"action":"replace","path":"relative/file","old":"exact text appearing once","new":"replacement text"}
{"action":"write","path":"relative/new-file","content":"complete content"}
{"action":"run","command":"focused inspection, build, lint, or test command"}
{"action":"bodycheck"}
{"action":"final","summary":"concise Markdown outcome","verification":["check and result"],"limitations":["remaining limitation"]}

Use read/search/list before editing. Use replace for existing files and write mainly for new files. Do not use shell commands to write, delete, move, install, download, change Git history, publish, or access secrets. Ask the controller to run bodycheck after all edits and checks. A final action is invalid until bodycheck succeeds after the latest edit. The final summary must be concise and must not restate the full transcript."""

DEFAULT_WINDOWS_SYSTEM_PROMPT = """You are the reasoning component of a local Computer Use coding agent targeting Windows.
The future controller will use PowerShell 7, Windows paths, and the selected project as its only writable root. Follow repository instruction files, preserve unrelated work, make focused changes, and verify them. Keep context economical.

Every execution response must be exactly one JSON object using the controller actions list, read, search, replace, write, run, bodycheck, or final. Never claim an operation succeeded before the controller reports it. Run bodycheck after the latest edit and before final. Do not use commands to write, delete, move, install, download, change Git history, publish, or access secrets."""

_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "local_store",
        "logs",
        "node_modules",
        "test-results",
        "vendor",
        "venv",
    }
)
_CONTEXT_PRIORITY_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    "README.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
)
_COMMAND_WRITE_PATTERN = re.compile(
    r"(?:^|[;&|]\s*)(?:rm|rmdir|mv|cp|install|curl|wget|scp|rsync|sudo|chmod|chown|"
    r"git\s+(?:add|commit|push|pull|reset|clean|checkout|switch|restore|merge|rebase|tag)|"
    r"npm\s+(?:install|uninstall|publish)|pip(?:3)?\s+install|brew\s+(?:install|uninstall)|"
    r"python(?:3(?:\.\d+)?)?\s+-m\s+pip\s+install)\b",
    re.IGNORECASE,
)
_COMMAND_REDIRECTION_PATTERN = re.compile(r"(?:^|\s)(?:>>?|2>|&>)\s*\S|\btee\b", re.IGNORECASE)
_COMMAND_SHELL_OPERATOR_PATTERN = re.compile(r"(?:&&|\|\||[;|`]|\$\(|\n|\r)")
_SAFE_GIT_SUBCOMMANDS = frozenset({"diff", "grep", "log", "ls-files", "show", "status"})
_SAFE_PYTHON_MODULES = frozenset({"compileall", "mypy", "py_compile", "pytest", "ruff"})
_SAFE_PACKAGE_SCRIPTS = re.compile(
    r"^(?:build|check|ci|lint|test|test:[\w:-]+|typecheck|verify)$",
    re.IGNORECASE,
)
_SAFE_SCRIPT_NAME = re.compile(
    r"^(?:check|lint|test|verify)(?:[._-][\w.-]+)?\.(?:sh|zsh|bash|py)$",
    re.IGNORECASE,
)
_UNSAFE_WRAPPER_EXECUTABLES = frozenset(
    {"bash", "cmd", "dash", "fish", "powershell", "pwsh", "sh", "zsh"}
)


@dataclass(frozen=True, slots=True)
class ComputerUseSettings:
    """Persist local Computer Use preferences and prompt policy."""

    workspace_path: str = str(PROJECT_ROOT)
    operating_system: str = "macos"
    browser: str = "edge"
    model: str = DEFAULT_CHATGPT_MODEL
    target_url: str = CHATGPT_HOME_URL
    context_limit_mib: int = DEFAULT_CONTEXT_LIMIT_MIB
    max_turns: int = DEFAULT_MAX_TURNS
    command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    macos_system_prompt: str = DEFAULT_MACOS_SYSTEM_PROMPT
    windows_system_prompt: str = DEFAULT_WINDOWS_SYSTEM_PROMPT

    @property
    def system_prompt(self) -> str:
        """Return the prompt configured for the selected operating system."""
        return (
            self.windows_system_prompt
            if self.operating_system == "windows"
            else self.macos_system_prompt
        )


@dataclass(slots=True)
class AgentRunSnapshot:
    """Describe one browser-mediated coding run without exposing project content."""

    running: bool = False
    phase: str = "idle"
    message: str = "Ready to use the signed-in ChatGPT Web session."
    engine: str = "computer_use"
    prompt: str = ""
    workspace_path: str = ""
    response: str = ""
    conversation_url: str = ""
    activity: list[dict[str, str]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    last_error: str = ""
    context_file: str = ""
    context_bytes: int = 0
    turn_count: int = 0
    bodycheck_passed: bool = False
    session_mode: str = "new"


@dataclass(slots=True)
class ActionState:
    """Track edit and bodycheck ordering for one workspace loop."""

    edit_generation: int = 0
    bodycheck_generation: int = -1

    @property
    def bodycheck_current(self) -> bool:
        return self.bodycheck_generation == self.edit_generation


def is_loopback_address(value: str | None) -> bool:
    """Return whether one request address is local to this machine."""
    candidate = (value or "").strip().split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return candidate.lower() == "localhost"


def detect_host_operating_system() -> str:
    """Return the Agent operating-system key detected from this host."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win") or os.name == "nt":
        return "windows"
    return "macos"


def launch_terminal_authorization(operating_system: str) -> dict[str, Any]:
    """Open the native authorization surface for the selected host terminal."""
    selected = str(operating_system or "").strip().lower()
    if selected not in SUPPORTED_OPERATING_SYSTEMS:
        raise ValueError("Choose macOS or Windows before opening terminal authorization.")

    host = detect_host_operating_system()
    if selected != host:
        target_label = "PowerShell" if selected == "windows" else "Terminal"
        host_label = "Windows" if host == "windows" else "macOS"
        raise RuntimeError(
            f"{target_label} authorization can only open while this app is running on "
            f"{selected.title() if selected == 'windows' else 'macOS'}, not {host_label}."
        )

    process_options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if selected == "macos":
        command = [
            "/usr/bin/open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
        ]
        process_options["start_new_session"] = True
        destination = "System Settings > Privacy & Security > Full Disk Access"
        application = "Terminal"
        message = (
            "System Settings opened to Full Disk Access. Enable the Terminal app that "
            "starts CacheLikesFromTwitter."
        )
    else:
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile' -Verb RunAs",
        ]
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess,
            "DETACHED_PROCESS",
            0,
        )
        if creation_flags:
            process_options["creationflags"] = creation_flags
        destination = "Windows User Account Control"
        application = "PowerShell"
        message = (
            "Windows requested administrator authorization for PowerShell. "
            "Approve the UAC prompt to continue."
        )

    try:
        subprocess.Popen(command, **process_options)
    except OSError as exc:
        raise RuntimeError(f"Could not open {application} authorization: {exc}") from exc

    return {
        "opened": True,
        "operating_system": selected,
        "application": application,
        "destination": destination,
        "message": message,
    }


def open_chatgpt_in_default_browser(target_url: str = "") -> dict[str, Any]:
    """Open a trusted ChatGPT target through the host system's default browser."""
    destination = (
        normalize_chatgpt_conversation_url(target_url)
        or normalize_chatgpt_project_url(target_url)
        or CHATGPT_HOME_URL
    )
    process_options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "darwin":
        command = ["/usr/bin/open", destination]
        process_options["start_new_session"] = True
    elif os.name == "nt":
        command = ["cmd.exe", "/c", "start", "", destination]
    else:
        command = ["xdg-open", destination]
        process_options["start_new_session"] = True

    try:
        subprocess.Popen(command, **process_options)
    except OSError as exc:
        raise RuntimeError(
            f"Could not open ChatGPT in the system default browser: {exc}"
        ) from exc

    return {
        "opened": True,
        "url": destination,
        "targeted_conversation": bool(normalize_chatgpt_conversation_url(target_url)),
    }


def validate_computer_use_settings(payload: dict[str, Any]) -> ComputerUseSettings:
    """Normalize and validate settings received from the local control page."""
    workspace = Path(str(payload.get("workspace_path", PROJECT_ROOT))).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Agent workspace directory was not found: {workspace}")

    operating_system = str(payload.get("operating_system", "macos")).strip().lower()
    if operating_system not in SUPPORTED_OPERATING_SYSTEMS:
        raise ValueError("The Agent operating system must be macOS or Windows.")

    browser = str(payload.get("browser", "edge")).strip().lower()
    if browser not in SUPPORTED_BROWSERS:
        raise ValueError("The Agent browser must be Safari, Edge, or Chrome.")

    model = str(payload.get("model", DEFAULT_CHATGPT_MODEL)).strip().lower()
    if model not in SUPPORTED_CHATGPT_MODELS:
        raise ValueError("Choose a supported ChatGPT model.")

    target_url = str(payload.get("target_url", CHATGPT_HOME_URL)).strip()
    target_parts = urlsplit(target_url)
    if target_parts.scheme != "https" or (target_parts.hostname or "").lower() not in CHATGPT_HOSTS:
        raise ValueError("The Agent target must use the official ChatGPT HTTPS host.")

    context_limit_mib = _bounded_int(
        payload.get("context_limit_mib", DEFAULT_CONTEXT_LIMIT_MIB),
        "Context Markdown limit",
        MIN_CONTEXT_LIMIT_MIB,
        MAX_CONTEXT_LIMIT_MIB,
    )
    max_turns = _bounded_int(
        payload.get("max_turns", DEFAULT_MAX_TURNS),
        "Maximum Agent turns",
        MIN_MAX_TURNS,
        MAX_MAX_TURNS,
    )
    command_timeout_seconds = _bounded_int(
        payload.get("command_timeout_seconds", DEFAULT_COMMAND_TIMEOUT_SECONDS),
        "Command timeout",
        MIN_COMMAND_TIMEOUT_SECONDS,
        MAX_COMMAND_TIMEOUT_SECONDS,
    )

    macos_system_prompt = str(
        payload.get("macos_system_prompt", DEFAULT_MACOS_SYSTEM_PROMPT)
    ).replace("\x00", "").strip()
    windows_system_prompt = str(
        payload.get("windows_system_prompt", DEFAULT_WINDOWS_SYSTEM_PROMPT)
    ).replace("\x00", "").strip()
    if not macos_system_prompt:
        raise ValueError("The macOS system prompt cannot be empty.")
    if not windows_system_prompt:
        raise ValueError("The Windows system prompt cannot be empty.")

    return ComputerUseSettings(
        workspace_path=str(workspace),
        operating_system=operating_system,
        browser=browser,
        model=model,
        target_url=target_url,
        context_limit_mib=context_limit_mib,
        max_turns=max_turns,
        command_timeout_seconds=command_timeout_seconds,
        macos_system_prompt=macos_system_prompt,
        windows_system_prompt=windows_system_prompt,
    )


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{label} must be from {minimum:,} through {maximum:,}.")
    return parsed


def load_computer_use_settings(
    settings_path: Path = DEFAULT_AGENT_SETTINGS_PATH,
) -> ComputerUseSettings:
    """Load local Agent settings or return safe defaults."""
    if not settings_path.exists():
        return ComputerUseSettings()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Agent settings must be a JSON object.")
        return validate_computer_use_settings(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        LOGGER.warning("Ignoring invalid Computer Use Agent settings at %s.", settings_path)
        return ComputerUseSettings()


def save_computer_use_settings(
    settings: ComputerUseSettings,
    settings_path: Path = DEFAULT_AGENT_SETTINGS_PATH,
) -> None:
    """Persist non-secret Agent settings with owner-only permissions."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(asdict(settings), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    settings_path.chmod(0o600)


class ComputerUseSettingsStore:
    """Own thread-safe Agent settings without a separate runtime process."""

    def __init__(self, settings_path: Path = DEFAULT_AGENT_SETTINGS_PATH) -> None:
        self._lock = RLock()
        self._settings_path = settings_path
        self._settings = load_computer_use_settings(settings_path)

    @property
    def settings(self) -> ComputerUseSettings:
        with self._lock:
            return self._settings

    def update(self, settings: ComputerUseSettings) -> ComputerUseSettings:
        with self._lock:
            save_computer_use_settings(settings, self._settings_path)
            self._settings = settings
            return settings

    def update_preferences(
        self,
        *,
        workspace_path: str,
        operating_system: str,
        browser: str,
        model: str | None = None,
    ) -> ComputerUseSettings:
        candidate = asdict(self.settings)
        candidate.update(
            {
                "workspace_path": workspace_path,
                "operating_system": operating_system,
                "browser": browser,
                "model": model or self.settings.model,
            }
        )
        return self.update(validate_computer_use_settings(candidate))

    def snapshot(self) -> dict[str, Any]:
        settings = self.settings
        host_operating_system = detect_host_operating_system()
        host_ready = settings.operating_system == "macos" and host_operating_system == "macos"
        return {
            "ready": host_ready,
            "host_operating_system": host_operating_system,
            "selected_operating_system": settings.operating_system,
            "message": (
                "Computer Use is ready on this Mac."
                if host_ready
                else (
                    "Windows execution is planned but is not available on this macOS host."
                    if host_operating_system == "macos"
                    else "Windows execution is planned but is not available on this host yet."
                )
            ),
            "settings": asdict(settings),
        }


def resolve_workspace_path(workspace_path: str) -> Path:
    """Resolve the exact project selected by the user."""
    workspace = Path(str(workspace_path or "")).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Agent workspace directory was not found: {workspace}")
    return workspace


def resolve_agent_session_target(
    session_mode: str,
    conversation_url: str = "",
    project_url: str = "",
) -> str:
    """Resolve one UI session choice to a verified ChatGPT Web target URL."""
    mode = str(session_mode or "new").strip().lower()
    if mode not in SUPPORTED_AGENT_SESSION_MODES:
        raise ValueError("Choose a supported ChatGPT session source.")
    if mode == "new":
        return CHATGPT_HOME_URL

    normalized_project_url = normalize_chatgpt_project_url(project_url)
    if mode == "project_new":
        if not normalized_project_url:
            raise ValueError("Choose a ChatGPT project before starting a new project session.")
        return normalized_project_url

    normalized_conversation_url = normalize_chatgpt_conversation_url(conversation_url)
    if not normalized_conversation_url:
        raise ValueError("Choose a recent ChatGPT session before joining it.")
    if mode == "project_session":
        if not normalized_project_url:
            raise ValueError("Choose the ChatGPT project that owns this session.")
        project_path = urlsplit(normalized_project_url).path.rstrip("/")
        project_path = project_path[: -len("/project")] if project_path.endswith("/project") else project_path
        conversation_path = urlsplit(normalized_conversation_url).path.rstrip("/")
        if not conversation_path.startswith(f"{project_path}/c/"):
            raise ValueError("The selected session does not belong to the selected ChatGPT project.")
    return normalized_conversation_url


def agent_session_opening_message(session_mode: str, browser_label: str) -> str:
    """Describe the selected ChatGPT session source in the live Agent status."""
    messages = {
        "new": "Opening a new signed-in ChatGPT Web session",
        "recent": "Joining the selected recent ChatGPT Web session",
        "project_new": "Opening a new session in the selected ChatGPT project",
        "project_session": "Joining the selected session in the ChatGPT project",
    }
    return f"{messages.get(session_mode, messages['new'])} in {browser_label}."


def build_context_markdown(
    workspace: Path,
    user_request: str,
    settings: ComputerUseSettings,
    destination: Path,
) -> tuple[Path, int]:
    """Build a bounded initial context bundle for a fresh ChatGPT conversation."""
    byte_limit = settings.context_limit_mib * 1_024 * 1_024
    sections = [
        "# Local Computer Use task\n",
        "## Request\n\n" + user_request.strip() + "\n",
        "## Execution environment\n\n"
        f"- Host controller: macOS\n"
        f"- Requested environment: {settings.operating_system}\n"
        f"- Project name: {workspace.name}\n"
        f"- Project root: `{workspace}`\n"
        "- The local controller, not ChatGPT Web, performs every file and command action.\n"
        "- Treat each controller result as the only evidence that an action succeeded.\n",
        "## Controller contract\n\n" + settings.system_prompt + "\n",
    ]
    instructions = _collect_instruction_files(workspace)
    if instructions:
        sections.append("## Repository instructions\n")
        for path in instructions:
            sections.append(_markdown_file_section(workspace, path, MAX_FILE_READ_CHARS))

    if (workspace / ".git").exists():
        status = _run_capture(["git", "status", "--short"], workspace, timeout=10)
        if status.strip():
            sections.append("## Existing working tree\n\n```text\n" + status.strip() + "\n```\n")

    file_index = _project_file_index(workspace)
    sections.append("## Project file index\n\n```text\n" + "\n".join(file_index) + "\n```\n")

    priority_files = _priority_context_files(workspace, instructions)
    if priority_files:
        sections.append("## Project entry files\n")
        for path in priority_files:
            sections.append(_markdown_file_section(workspace, path, 80_000))

    encoded_parts: list[bytes] = []
    used = 0
    truncation_note = b"\n## Context limit\n\nThe local bundle reached its configured byte limit. Request additional files with controller actions.\n"
    for section in sections:
        encoded = section.encode("utf-8", errors="replace")
        if used + len(encoded) <= byte_limit:
            encoded_parts.append(encoded)
            used += len(encoded)
            continue
        remaining = byte_limit - used - len(truncation_note)
        if remaining > 0:
            encoded_parts.append(_utf8_prefix(encoded, remaining))
        encoded_parts.append(truncation_note)
        break

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"".join(encoded_parts))
    destination.chmod(0o600)
    return destination, destination.stat().st_size


def _utf8_prefix(value: bytes, maximum: int) -> bytes:
    return value[: max(0, maximum)].decode("utf-8", errors="ignore").encode("utf-8")


def _collect_instruction_files(workspace: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        root_file = workspace / name
        if root_file.is_file():
            candidates.append(root_file)
    try:
        nested = sorted(
            (
                path
                for path in workspace.rglob("AGENTS.md")
                if not _path_has_ignored_part(path.relative_to(workspace))
            ),
            key=lambda path: (len(path.relative_to(workspace).parts), path.as_posix()),
        )
    except OSError:
        nested = []
    for path in nested:
        if path not in candidates:
            candidates.append(path)
    return candidates[:24]


def _project_file_index(workspace: Path) -> list[str]:
    command = [
        "rg",
        "--files",
        "--hidden",
        "-g",
        "!.git",
        "-g",
        "!node_modules",
        "-g",
        "!.venv",
        "-g",
        "!venv",
        "-g",
        "!local_store",
        "-g",
        "!logs",
    ]
    try:
        output = _run_capture(command, workspace, timeout=15)
        return output.splitlines()[:12_000]
    except (OSError, RuntimeError):
        paths: list[str] = []
        for path in workspace.rglob("*"):
            relative = path.relative_to(workspace)
            if path.is_file() and not _path_has_ignored_part(relative):
                paths.append(relative.as_posix())
            if len(paths) >= 12_000:
                break
        return sorted(paths)


def _priority_context_files(workspace: Path, instructions: list[Path]) -> list[Path]:
    instruction_set = set(instructions)
    files: list[Path] = []
    for name in _CONTEXT_PRIORITY_NAMES:
        candidate = workspace / name
        if candidate.is_file() and candidate not in instruction_set:
            files.append(candidate)
    return files[:12]


def _markdown_file_section(workspace: Path, path: Path, maximum_chars: int) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")[:maximum_chars]
    except OSError as exc:
        content = f"[Could not read file: {exc}]"
    suffix = path.suffix.lstrip(".") or "text"
    relative = path.relative_to(workspace).as_posix()
    return f"\n### `{relative}`\n\n```{suffix}\n{content}\n```\n"


def _path_has_ignored_part(relative: Path) -> bool:
    return any(part in _IGNORED_DIRECTORY_NAMES for part in relative.parts)


def parse_agent_action(response: str) -> dict[str, Any]:
    """Parse one strict JSON controller action from a ChatGPT response."""
    text = str(response or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    if len(text) > MAX_ACTION_JSON_CHARS:
        raise ValueError("ChatGPT returned an action that exceeds the controller limit.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("ChatGPT must return exactly one JSON controller action.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
        raise ValueError("ChatGPT returned an invalid controller action.")
    return payload


class WorkspaceController:
    """Execute a narrow action protocol inside one selected project."""

    def __init__(
        self,
        workspace: Path,
        settings: ComputerUseSettings,
        should_stop: Callable[[], bool],
        process_changed: Callable[[subprocess.Popen[str] | None], None] | None = None,
        read_only: bool = False,
    ) -> None:
        self.workspace = workspace.resolve()
        self.settings = settings
        self.state = ActionState()
        self.should_stop = should_stop
        self.process_changed = process_changed or (lambda _process: None)
        self.read_only = read_only

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one validated action and return a compact observation."""
        if self.should_stop():
            return {"ok": False, "stopped": True, "error": "Stop requested."}
        action = str(payload.get("action") or "").strip().lower()
        if self.read_only and action not in {"list", "read", "search", "bodycheck"}:
            return {
                "ok": False,
                "action": action,
                "error": "This Agent task is read-only; only list, read, search, and bodycheck are allowed.",
            }
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "list": self._list,
            "read": self._read,
            "search": self._search,
            "replace": self._replace,
            "write": self._write,
            "run": self._run,
            "bodycheck": self._bodycheck,
        }
        handler = handlers.get(action)
        if handler is None:
            return {"ok": False, "error": f"Unsupported controller action: {action or '[missing]'}"}
        try:
            return handler(payload)
        except (OSError, RuntimeError, ValueError) as exc:
            return {"ok": False, "action": action, "error": str(exc)[:2_000]}

    def _resolve_path(self, raw_path: Any, *, allow_missing: bool = False) -> Path:
        candidate = Path(str(raw_path or "."))
        if candidate.is_absolute():
            resolved = candidate.expanduser().resolve(strict=not allow_missing)
        else:
            resolved = (self.workspace / candidate).resolve(strict=not allow_missing)
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Controller paths must stay inside the selected project.") from exc
        if any(part in {".git", ".computer-use-agent"} for part in resolved.relative_to(self.workspace).parts):
            raise ValueError("Controller access to internal metadata is not allowed.")
        return resolved

    def _list(self, payload: dict[str, Any]) -> dict[str, Any]:
        root = self._resolve_path(payload.get("path", "."))
        if not root.is_dir():
            raise ValueError("The list action requires a directory.")
        depth = max(1, min(6, int(payload.get("depth", 2))))
        rows: list[str] = []
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            relative_to_root = path.relative_to(root)
            if len(relative_to_root.parts) > depth or _path_has_ignored_part(relative_to_root):
                continue
            suffix = "/" if path.is_dir() else ""
            rows.append(path.relative_to(self.workspace).as_posix() + suffix)
            if len(rows) >= 2_000:
                break
        return {"ok": True, "action": "list", "entries": rows, "truncated": len(rows) >= 2_000}

    def _read(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(payload.get("path"))
        if not path.is_file():
            raise ValueError("The read action requires a regular file.")
        if path.stat().st_size > 20 * 1_024 * 1_024:
            raise ValueError("The requested file is too large for a text read.")
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(payload.get("start_line", 1)))
        end = min(len(text), max(start, int(payload.get("end_line", start + 239))))
        lines = [f"{index}: {text[index - 1]}" for index in range(start, end + 1)]
        content = _truncate_text("\n".join(lines), MAX_FILE_READ_CHARS)
        return {
            "ok": True,
            "action": "read",
            "path": path.relative_to(self.workspace).as_posix(),
            "start_line": start,
            "end_line": end,
            "total_lines": len(text),
            "content": content,
        }

    def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("The search action requires a query.")
        root = self._resolve_path(payload.get("path", "."))
        max_results = max(1, min(300, int(payload.get("max_results", 80))))
        command = ["rg", "--line-number", "--color", "never", "--max-count", str(max_results)]
        glob = str(payload.get("glob") or "").strip()
        if glob:
            command.extend(["--glob", glob])
        command.extend([query, str(root.relative_to(self.workspace) or ".")])
        process = subprocess.run(
            command,
            cwd=self.workspace,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if process.returncode not in {0, 1}:
            raise RuntimeError((process.stderr or process.stdout or "Search failed.").strip())
        matches = (process.stdout or "").splitlines()[:max_results]
        return {"ok": True, "action": "search", "matches": matches, "truncated": len(matches) >= max_results}

    def _replace(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(payload.get("path"))
        if not path.is_file():
            raise ValueError("The replace action requires an existing file.")
        old = str(payload.get("old") or "")
        new = str(payload.get("new") or "")
        if not old:
            raise ValueError("The replace action requires non-empty old text.")
        source = path.read_text(encoding="utf-8")
        occurrences = source.count(old)
        if occurrences != 1:
            raise ValueError(f"Replace text must appear exactly once; found {occurrences:,} occurrences.")
        path.write_text(source.replace(old, new, 1), encoding="utf-8")
        self.state.edit_generation += 1
        return {
            "ok": True,
            "action": "replace",
            "path": path.relative_to(self.workspace).as_posix(),
            "changed_characters": len(new) - len(old),
        }

    def _write(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_path(payload.get("path"), allow_missing=True)
        if path.exists():
            raise ValueError("The write action creates new files only; use replace for an existing file.")
        content = str(payload.get("content") or "")
        if not content:
            raise ValueError("The write action requires file content.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.state.edit_generation += 1
        return {
            "ok": True,
            "action": "write",
            "path": path.relative_to(self.workspace).as_posix(),
            "bytes": path.stat().st_size,
        }

    def _run(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()
        validate_inspection_command(command)
        started = time.monotonic()
        command_parts = inspection_command_parts(command)
        process = subprocess.Popen(
            command_parts,
            cwd=self.workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.process_changed(process)
        try:
            output, _ = process.communicate(timeout=self.settings.command_timeout_seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                output, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate(timeout=3)
            raise RuntimeError(
                f"Command timed out after {self.settings.command_timeout_seconds:,} seconds.\n"
                + _truncate_text(output or "", MAX_ACTION_OUTPUT_CHARS)
            )
        finally:
            self.process_changed(None)
        return {
            "ok": process.returncode == 0,
            "action": "run",
            "exit_code": process.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "output": _truncate_text(output or "", MAX_ACTION_OUTPUT_CHARS),
        }

    def _bodycheck(self, _payload: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        if (self.workspace / ".git").exists():
            status = _run_capture(["git", "status", "--short"], self.workspace, timeout=20)
            diff_check = subprocess.run(
                ["git", "diff", "--check"],
                cwd=self.workspace,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            checks.append({"name": "git status --short", "ok": True, "output": _truncate_text(status, 16_000)})
            checks.append(
                {
                    "name": "git diff --check",
                    "ok": diff_check.returncode == 0,
                    "output": _truncate_text(diff_check.stdout + diff_check.stderr, 16_000),
                }
            )
        instructions = [path.relative_to(self.workspace).as_posix() for path in _collect_instruction_files(self.workspace)]
        passed = all(check["ok"] for check in checks) if checks else True
        if passed:
            self.state.bodycheck_generation = self.state.edit_generation
        return {
            "ok": passed,
            "action": "bodycheck",
            "bodycheck_current": self.state.bodycheck_current,
            "instruction_files": instructions,
            "checks": checks,
        }


def validate_inspection_command(command: str) -> None:
    """Reject shell commands that mutate outside the explicit file actions."""
    if not command or len(command) > 4_000 or "\x00" in command or "\n" in command:
        raise ValueError("Run requires one bounded shell command line.")
    if re.match(
        r"^\s*(?:bash|cmd|dash|fish|powershell|pwsh|sh|zsh)(?:\s|$)",
        command,
        flags=re.IGNORECASE,
    ):
        raise ValueError("Run cannot invoke a nested shell or command interpreter.")
    if _COMMAND_WRITE_PATTERN.search(command) or _COMMAND_REDIRECTION_PATTERN.search(command):
        raise ValueError("Run is limited to inspection, build, lint, and test commands.")
    if _COMMAND_SHELL_OPERATOR_PATTERN.search(command):
        raise ValueError("Run accepts one direct command without shell operators.")
    if re.search(r"\b(?:env|printenv|set)\b", command, flags=re.IGNORECASE):
        raise ValueError("Commands that enumerate the environment are not allowed.")


def inspection_command_parts(command: str) -> list[str]:
    """Parse one direct command and enforce the controller executable allowlist."""
    validate_inspection_command(command)
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ValueError("Run contains invalid shell quoting.") from exc
    if not parts:
        raise ValueError("Run requires a command.")

    executable = Path(parts[0]).name.casefold()
    arguments = parts[1:]
    if executable in _UNSAFE_WRAPPER_EXECUTABLES:
        raise ValueError("Run cannot invoke a nested shell or command interpreter.")
    if executable == "git":
        if not arguments or arguments[0].casefold() not in _SAFE_GIT_SUBCOMMANDS:
            raise ValueError("Git run actions are limited to read-only inspection subcommands.")
        return parts
    if executable == "rg":
        return parts
    if executable in {"pytest", "ruff", "mypy", "pyright", "eslint", "tsc"}:
        return parts
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
        if len(arguments) < 2 or arguments[0] != "-m" or arguments[1] not in _SAFE_PYTHON_MODULES:
            raise ValueError("Python run actions must use an approved verification module.")
        return parts
    if executable == "node":
        if not arguments or arguments[0] != "--check":
            raise ValueError("Node run actions are limited to syntax checks.")
        return parts
    if executable in {"npm", "pnpm", "yarn", "bun"}:
        normalized = [argument.casefold() for argument in arguments]
        if normalized == ["test"] or (
            len(arguments) >= 2
            and normalized[0] == "run"
            and _SAFE_PACKAGE_SCRIPTS.fullmatch(arguments[1])
        ):
            return parts
        raise ValueError("Package-manager run actions are limited to existing check scripts.")
    if executable == "go" and arguments and arguments[0] in {"test", "vet"}:
        return parts
    if executable == "cargo" and arguments and arguments[0] in {"check", "clippy", "test"}:
        return parts
    if executable == "make" and arguments and all(
        _SAFE_PACKAGE_SCRIPTS.fullmatch(argument) for argument in arguments if not argument.startswith("-")
    ):
        return parts
    if parts[0].startswith("./scripts/") and _SAFE_SCRIPT_NAME.fullmatch(Path(parts[0]).name):
        return parts
    raise ValueError("Run executable is outside the inspection and verification allowlist.")


def _truncate_text(value: str, maximum: int) -> str:
    text = str(value or "")
    if len(text) <= maximum:
        return text
    omitted = len(text) - maximum
    return text[:maximum] + f"\n[truncated {omitted:,} characters]"


def _run_capture(command: list[str], cwd: Path, timeout: int) -> str:
    process = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout or "Command failed.").strip())
    return process.stdout or ""


def _start_macos_idle_sleep_assertion(
    *,
    platform_name: str | None = None,
    executable: Path = Path("/usr/bin/caffeinate"),
) -> subprocess.Popen[Any] | None:
    """Keep macOS awake for one Agent task without waking the display."""
    if (platform_name or sys.platform) != "darwin" or not executable.is_file():
        return None
    try:
        return subprocess.Popen(
            [str(executable), "-i"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        LOGGER.warning("Could not prevent idle sleep for the Agent task: %s", exc)
        return None


def _stop_macos_idle_sleep_assertion(process: subprocess.Popen[Any] | None) -> None:
    """Release one task-scoped macOS idle-sleep assertion."""
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    except OSError:
        return


class ComputerUseAgentService:
    """Run a fresh ChatGPT Web action loop for one selected local project."""

    def __init__(
        self,
        settings_store: ComputerUseSettingsStore,
        runner: Callable[..., tuple[str, str, int, bool]] | None = None,
        runtime_root: Path = DEFAULT_AGENT_RUNTIME_ROOT,
    ) -> None:
        self._settings_store = settings_store
        self._runner = runner or run_chatgpt_web_computer_use
        self._runtime_root = runtime_root
        self._lock = RLock()
        self._snapshot = AgentRunSnapshot()
        self._stop_requested = Event()
        self._worker: Thread | None = None
        self._active_process: subprocess.Popen[str] | None = None
        self._sleep_assertion: subprocess.Popen[Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)

    def start(
        self,
        prompt: str,
        workspace_path: str,
        config: CrawlConfig,
        *,
        operating_system: str | None = None,
        browser: str | None = None,
        model: str | None = None,
        session_mode: str = "new",
        conversation_url: str = "",
        project_url: str = "",
        read_only: bool = False,
    ) -> None:
        clean_prompt = str(prompt or "").replace("\x00", "").strip()
        if not clean_prompt:
            raise ValueError("Enter a question or task for the agent.")
        base = self._settings_store.settings
        candidate = asdict(base)
        candidate.update(
            {
                "workspace_path": workspace_path,
                "operating_system": operating_system or base.operating_system,
                "browser": browser or base.browser,
                "model": model or base.model,
            }
        )
        settings = validate_computer_use_settings(candidate)
        if settings.operating_system != "macos":
            raise RuntimeError(
                "Windows execution is not available on this macOS host yet. Choose macOS to run the task."
            )
        workspace = resolve_workspace_path(settings.workspace_path)
        target_url = resolve_agent_session_target(session_mode, conversation_url, project_url)
        normalized_session_mode = str(session_mode or "new").strip().lower()
        self._settings_store.update(settings)

        with self._lock:
            if self._snapshot.running:
                raise RuntimeError("An Agent request is already running.")
            self._stop_requested.clear()
            self._snapshot = AgentRunSnapshot(
                running=True,
                phase="starting",
                message=agent_session_opening_message(
                    normalized_session_mode,
                    settings.browser.title(),
                ),
                prompt=clean_prompt,
                workspace_path=str(workspace),
                conversation_url=target_url,
                started_at=utc_now(),
                session_mode=normalized_session_mode,
            )
            self._worker = Thread(
                target=self._run,
                args=(
                    clean_prompt,
                    workspace,
                    config,
                    settings,
                    target_url,
                    normalized_session_mode,
                    bool(read_only),
                ),
                daemon=True,
            )
            self._worker.start()

    def request_stop(self) -> bool:
        with self._lock:
            if not self._snapshot.running:
                return False
            self._stop_requested.set()
            self._snapshot.phase = "stopping"
            self._snapshot.message = "Stop requested. Ending the browser turn and active local command."
            process = self._active_process
            sleep_assertion = self._sleep_assertion
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                pass
        _stop_macos_idle_sleep_assertion(sleep_assertion)
        return True

    def stop_at_exit(self) -> None:
        self.request_stop()
        with self._lock:
            worker = self._worker
        if worker is not None and worker is not current_thread() and worker.is_alive():
            worker.join(timeout=8)

    def _set_active_process(self, process: subprocess.Popen[str] | None) -> None:
        with self._lock:
            self._active_process = process

    def _set_sleep_assertion(self, process: subprocess.Popen[Any] | None) -> None:
        with self._lock:
            self._sleep_assertion = process

    def _run(
        self,
        prompt: str,
        workspace: Path,
        config: CrawlConfig,
        settings: ComputerUseSettings,
        target_url: str,
        session_mode: str,
        read_only: bool,
    ) -> None:
        sleep_assertion = _start_macos_idle_sleep_assertion()
        self._set_sleep_assertion(sleep_assertion)
        try:
            run_directory = self._runtime_root / time.strftime("%Y%m%d-%H%M%S")
            context_path, context_bytes = build_context_markdown(
                workspace,
                prompt,
                settings,
                run_directory / "context.md",
            )
            self._update(
                phase="preparing",
                message=f"Prepared a {context_bytes:,}-byte Markdown context bundle.",
                context_file=str(context_path),
                context_bytes=context_bytes,
            )
            response, conversation_url, turn_count, bodycheck_passed = self._runner(
                prompt=prompt,
                workspace=workspace,
                context_path=context_path,
                config=config,
                settings=settings,
                target_url=target_url,
                session_mode=session_mode,
                read_only=read_only,
                should_stop=self._stop_requested.is_set,
                update=self._update,
                process_changed=self._set_active_process,
            )
            with self._lock:
                stopped = self._stop_requested.is_set()
                self._snapshot.running = False
                self._snapshot.phase = "stopped" if stopped else "finished"
                self._snapshot.message = (
                    "Agent request stopped."
                    if stopped
                    else "ChatGPT Web completed the project task after local bodycheck."
                )
                self._snapshot.response = response
                self._snapshot.conversation_url = conversation_url
                self._snapshot.turn_count = turn_count
                self._snapshot.bodycheck_passed = bodycheck_passed
                self._snapshot.finished_at = utc_now()
        except Exception as exc:
            LOGGER.exception("Computer Use web-agent request failed.")
            with self._lock:
                self._snapshot.running = False
                self._snapshot.phase = "failed"
                self._snapshot.message = str(exc).splitlines()[0][:500]
                self._snapshot.last_error = str(exc)
                self._snapshot.finished_at = utc_now()
        finally:
            self._set_active_process(None)
            _stop_macos_idle_sleep_assertion(sleep_assertion)
            self._set_sleep_assertion(None)

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                if hasattr(self._snapshot, key):
                    setattr(self._snapshot, key, value)


def run_chatgpt_web_computer_use(
    *,
    prompt: str,
    workspace: Path,
    context_path: Path,
    config: CrawlConfig,
    settings: ComputerUseSettings,
    should_stop: Callable[[], bool],
    update: Callable[..., None],
    process_changed: Callable[[subprocess.Popen[str] | None], None],
    target_url: str | None = None,
    session_mode: str = "new",
    read_only: bool = False,
) -> tuple[str, str, int, bool]:
    """Run one selected ChatGPT Web session as a local controller action loop."""
    descriptor = browser_descriptors(config)[settings.browser]
    controller = WorkspaceController(
        workspace,
        settings,
        should_stop,
        process_changed,
        read_only=read_only,
    )
    selected_target_url = target_url or settings.target_url
    initial_message = _initial_chatgpt_message(
        prompt,
        workspace,
        settings,
        context_path,
        session_mode,
    )

    if descriptor.engine == "safari":
        with SafariContext(selected_target_url) as context:
            page = context.primary_page
            page.goto(selected_target_url, wait_until="domcontentloaded", timeout=90_000)
            return _run_web_action_loop(
                page=page,
                browser_kind="safari",
                initial_message=initial_message,
                controller=controller,
                context_path=context_path,
                settings=settings,
                session_mode=session_mode,
                selected_target_url=selected_target_url,
                should_stop=should_stop,
                update=update,
            )

    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(
            playwright,
            descriptor,
            headless=False,
            clone_profile_first=True,
            background_window=True,
        ) as context:
            page = context.pages[0] if context.pages else context.new_page()
            goto_with_retry(page, selected_target_url, attempts=2, timeout_ms=90_000)
            return _run_web_action_loop(
                page=page,
                browser_kind="chromium",
                initial_message=initial_message,
                controller=controller,
                context_path=context_path,
                settings=settings,
                session_mode=session_mode,
                selected_target_url=selected_target_url,
                should_stop=should_stop,
                update=update,
            )


def _initial_chatgpt_message(
    prompt: str,
    workspace: Path,
    settings: ComputerUseSettings,
    context_path: Path,
    session_mode: str,
) -> str:
    session_instruction = {
        "new": "Start a new root-level ChatGPT conversation for this task.",
        "recent": "Continue the selected existing root-level ChatGPT conversation for this task.",
        "project_new": "Start a new conversation inside the selected ChatGPT project for this task.",
        "project_session": "Continue the selected existing conversation inside the selected ChatGPT project for this task.",
    }.get(session_mode, "Start a new root-level ChatGPT conversation for this task.")
    return (
        settings.system_prompt
        + "\n\nA local context Markdown file is attached when the browser supports direct attachment. "
        "Its filename is `"
        + context_path.name
        + "`. If no attachment appears, use the environment summary below and request files through controller actions.\n\n"
        f"Project: {workspace.name}\n"
        f"Project root: {workspace}\n"
        f"Session source: {session_instruction}\n"
        f"User request: {prompt}\n\n"
        "Begin with the smallest useful read, search, or list JSON action."
    )


def _run_web_action_loop(
    *,
    page: Any,
    browser_kind: str,
    initial_message: str,
    controller: WorkspaceController,
    context_path: Path,
    settings: ComputerUseSettings,
    session_mode: str,
    selected_target_url: str,
    should_stop: Callable[[], bool],
    update: Callable[..., None],
) -> tuple[str, str, int, bool]:
    """Exchange JSON actions and compact observations in one ChatGPT conversation."""
    _verify_chatgpt_page(page, browser_kind, selected_target_url)
    _select_chat_mode(page, browser_kind)
    _select_chatgpt_model(page, browser_kind, settings.model)
    attached = _attach_context_file(page, browser_kind, context_path)
    update(
        phase="submitting",
        message=(
            "Uploading the local Markdown context and opening the selected ChatGPT session."
            if attached
            else "Opening the selected ChatGPT session; the controller will stream context on demand."
        ),
    )
    response = _submit_and_wait(
        page,
        browser_kind,
        initial_message,
        should_stop,
        on_submitted=lambda: update(
            phase="running",
            message="Prompt sent to ChatGPT Web; waiting for the first controller action.",
        ),
    )
    conversation_url = str(page.url or "")
    activity: list[dict[str, str]] = []

    for turn_index in range(1, settings.max_turns + 1):
        if should_stop():
            _stop_web_generation(page, browser_kind)
            return "", str(page.url or conversation_url), turn_index - 1, controller.state.bodycheck_current

        try:
            action = parse_agent_action(response)
        except ValueError as exc:
            observation = {
                "ok": False,
                "error": str(exc),
                "instruction": "Return exactly one valid JSON controller action with no surrounding prose.",
            }
            response = _submit_and_wait(
                page,
                browser_kind,
                _observation_message(turn_index, observation),
                should_stop,
                on_submitted=lambda: update(
                    phase="running",
                    message="Correction sent to ChatGPT Web; waiting for a valid controller action.",
                ),
            )
            continue

        action_name = str(action.get("action") or "").strip().lower()
        if action_name == "final":
            if not controller.state.bodycheck_current:
                response = _submit_and_wait(
                    page,
                    browser_kind,
                    _observation_message(
                        turn_index,
                        {
                            "ok": False,
                            "error": "Final is blocked until bodycheck succeeds after the latest edit.",
                        },
                    ),
                    should_stop,
                    on_submitted=lambda: update(
                        phase="running",
                        message="Bodycheck requirement sent; waiting for the next ChatGPT action.",
                    ),
                )
                continue
            final_response = _render_final_action(action)
            update(
                phase="finalizing",
                message="ChatGPT returned a final result after the current bodycheck.",
                response=final_response,
                conversation_url=str(page.url or conversation_url),
                turn_count=turn_index,
                bodycheck_passed=True,
            )
            return final_response, str(page.url or conversation_url), turn_index, True

        detail = _activity_detail(action)
        activity.append(
            {
                "label": action_name.replace("_", " ").title() or "Controller action",
                "detail": detail,
                "meta": f"Turn {turn_index:,}",
                "status": "running",
            }
        )
        update(
            phase="running",
            message=f"ChatGPT requested local {action_name or 'controller'} action.",
            activity=activity,
            conversation_url=str(page.url or conversation_url),
            turn_count=turn_index,
        )
        observation = controller.execute(action)
        activity[-1]["status"] = "completed" if observation.get("ok") else "failed"
        update(
            activity=activity,
            message=(
                f"Completed local {action_name} action."
                if observation.get("ok")
                else f"Local {action_name} action returned a bounded error."
            ),
            bodycheck_passed=controller.state.bodycheck_current,
        )
        if observation.get("stopped"):
            return "", str(page.url or conversation_url), turn_index, controller.state.bodycheck_current
        response = _submit_and_wait(
            page,
            browser_kind,
            _observation_message(turn_index, observation),
            should_stop,
            on_submitted=lambda: update(
                phase="running",
                message="Controller observation sent; waiting for the next ChatGPT action.",
            ),
        )

    raise RuntimeError(
        f"ChatGPT reached the configured {settings.max_turns:,}-turn limit before returning final."
    )


def _render_final_action(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise ValueError("The final action requires a summary.")
    parts = [summary]
    verification = payload.get("verification")
    if isinstance(verification, list) and verification:
        parts.append("\nVerification\n" + "\n".join(f"- {str(item)}" for item in verification[:20]))
    limitations = payload.get("limitations")
    if isinstance(limitations, list) and limitations:
        parts.append("\nLimitations\n" + "\n".join(f"- {str(item)}" for item in limitations[:20]))
    return "\n".join(parts).strip()


def _observation_message(turn_index: int, observation: dict[str, Any]) -> str:
    return (
        f"Controller observation for turn {turn_index:,}:\n"
        + json.dumps(observation, ensure_ascii=False, separators=(",", ":"))
        + "\nReturn exactly one next JSON action."
    )


def _activity_detail(action: dict[str, Any]) -> str:
    for key in ("path", "query", "command"):
        value = str(action.get(key) or "").strip()
        if value:
            return _truncate_text(value, 180)
    return "Local controller"


def _verify_chatgpt_page(
    page: Any,
    browser_kind: str,
    selected_target_url: str | None = None,
) -> None:
    if browser_kind == "safari":
        page.locator("#prompt-textarea").inner_text(timeout=60_000)
    else:
        _wait_for_chromium_composer(page)
    current_url = str(page.url or "")
    if (urlsplit(current_url).hostname or "").lower() not in CHATGPT_HOSTS:
        raise RuntimeError("The selected browser did not reach ChatGPT Web.")
    if selected_target_url and not _chatgpt_target_is_open(selected_target_url, current_url):
        raise RuntimeError("The selected ChatGPT session did not finish opening in the browser.")
    signed_out = bool(
        page.evaluate(
            """() => Array.from(document.querySelectorAll('a,button')).some((element) => {
                const text = (element.innerText || element.textContent || '').trim().toLowerCase();
                return element.offsetParent !== null && /^(log in|sign up)$/.test(text);
            })"""
        )
    )
    if signed_out:
        raise RuntimeError(f"{settings_browser_label(browser_kind)} is not signed in to ChatGPT Web.")


def _wait_for_chromium_composer(page: Any) -> None:
    """Wait for ChatGPT's composer, reloading a stalled authenticated page once."""
    last_error: Exception | None = None
    for attempt in range(1, CHATGPT_COMPOSER_RELOAD_ATTEMPTS + 1):
        try:
            page.locator("#prompt-textarea").wait_for(
                state="visible",
                timeout=CHATGPT_COMPOSER_TIMEOUT_SECONDS * 1_000,
            )
            return
        except Exception as exc:
            last_error = exc
            if attempt >= CHATGPT_COMPOSER_RELOAD_ATTEMPTS:
                break
            page.reload(wait_until="domcontentloaded", timeout=90_000)
    raise RuntimeError(
        "The Chromium browser loaded ChatGPT, but the message composer did not become ready after one reload."
    ) from last_error


def _chatgpt_target_is_open(target_url: str, current_url: str) -> bool:
    """Require the selected ChatGPT path while permitting query-string changes."""
    target = urlsplit(str(target_url or ""))
    current = urlsplit(str(current_url or ""))
    return (
        (target.hostname or "").lower() in CHATGPT_HOSTS
        and (current.hostname or "").lower() in CHATGPT_HOSTS
        and (target.path.rstrip("/") or "/") == (current.path.rstrip("/") or "/")
    )


def settings_browser_label(browser_kind: str) -> str:
    return "Safari" if browser_kind == "safari" else "The selected Chromium browser"


def _select_chat_mode(page: Any, browser_kind: str) -> None:
    """Select ordinary Chat mode when ChatGPT exposes a Chat/Work switch."""
    if browser_kind == "safari":
        page.evaluate(
            r"""() => {
                const chat = Array.from(document.querySelectorAll('button[role="radio"]')).find((button) =>
                    (button.innerText || button.textContent || '').trim().toLowerCase() === 'chat'
                );
                if (chat && chat.getAttribute('aria-checked') !== 'true') chat.click();
                return Boolean(chat);
            }"""
        )
        return
    chat_mode = page.get_by_role("radio", name="Chat", exact=True)
    if chat_mode.count() and chat_mode.first.get_attribute("aria-checked") != "true":
        chat_mode.first.click()


def _select_chatgpt_model(page: Any, browser_kind: str, model: str) -> None:
    """Require the selected ChatGPT model to be active in the remote composer."""
    del browser_kind
    selected_model = str(model or DEFAULT_CHATGPT_MODEL).strip().lower()
    option = next(
        (candidate for candidate in CHATGPT_MODEL_OPTIONS if candidate["key"] == selected_model),
        None,
    )
    if option is None:
        raise ValueError("Choose a supported ChatGPT model.")

    result = page.evaluate(
        r"""({label}) => {
            const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const isVisible = (element) => {
                const style = window.getComputedStyle(element);
                return element.getClientRects().length > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const visibleMenus = () => Array.from(document.querySelectorAll('[role="menu"]')).filter(isVisible);
            const powerLabels = new Set(['auto', 'low', 'medium', 'high', 'max', 'advanced', 'faster', 'smarter']);
            const powerButton = Array.from(document.querySelectorAll('button')).find((button) =>
                isVisible(button)
                && powerLabels.has(normalize(button.innerText || button.textContent))
                && !button.closest('[role="menu"]')
            );
            if (!powerButton) return {ok: false, reason: 'power-control-not-found', available: []};
            powerButton.click();

            const menu = visibleMenus().at(-1);
            const modelItem = Array.from(menu?.querySelectorAll('[role="menuitem"][aria-haspopup="menu"]') || [])
                .find((item) => normalize(item.innerText || item.textContent).startsWith('model'));
            if (!modelItem) {
                powerButton.click();
                return {ok: false, reason: 'model-control-not-found', available: []};
            }

            const current = normalize(
                modelItem.querySelector('[data-trailing-style], .trailing')?.innerText
                || (modelItem.innerText || '').replace(/^model\s*/i, '')
            );
            if (current === normalize(label)) {
                powerButton.click();
                return {ok: true, selected: current, available: [current]};
            }

            modelItem.click();
            const submenu = visibleMenus().at(-1);
            const candidates = Array.from(submenu?.querySelectorAll('[role="menuitem"], [role="option"]') || [])
                .filter(isVisible);
            const choice = candidates.find((item) => normalize(item.innerText || item.textContent) === normalize(label));
            if (choice) {
                choice.click();
                return {ok: true, selected: normalize(label), available: candidates.map((item) => normalize(item.innerText || item.textContent))};
            }
            return {
                ok: false,
                reason: 'model-not-exposed',
                available: [current, ...candidates.map((item) => normalize(item.innerText || item.textContent))].filter(Boolean),
            };
        }""",
        {"label": option["remote_label"]},
    )
    if isinstance(result, dict) and result.get("ok"):
        return
    available = []
    if isinstance(result, dict):
        available = [str(value) for value in result.get("available", []) if str(value).strip()]
    available_text = ", ".join(dict.fromkeys(available)) or "none"
    raise RuntimeError(
        f"ChatGPT Web does not expose the selected model {option['remote_label']}. "
        f"Available models: {available_text}."
    )


def _attach_context_file(page: Any, browser_kind: str, context_path: Path) -> bool:
    """Attach Markdown directly where supported; Safari streams context on demand."""
    if browser_kind == "safari":
        return False
    file_input = page.locator('input[type="file"]')
    if file_input.count() == 0:
        attach_button = page.locator(
            'button[aria-label*="Attach" i], button[aria-label*="Upload" i], button[data-testid*="attach" i]'
        )
        if attach_button.count() and attach_button.first.is_visible():
            attach_button.first.click()
    if file_input.count() == 0:
        return False
    try:
        file_input.first.set_input_files(str(context_path))
        return True
    except Exception as exc:
        LOGGER.info("ChatGPT context attachment fell back to on-demand reads: %s", exc)
        return False


def _submit_and_wait(
    page: Any,
    browser_kind: str,
    message: str,
    should_stop: Callable[[], bool],
    on_submitted: Callable[[], None] | None = None,
) -> str:
    """Submit one message and wait for one stable assistant response."""
    selector = '[data-message-author-role="assistant"]'
    baseline = _web_count(page, browser_kind, selector)
    baseline_response = _web_last_text(page, browser_kind, selector)
    if browser_kind == "safari":
        _submit_safari_prompt(page, message)
    else:
        _submit_chromium_prompt(page, message, should_stop)
    if on_submitted is not None and not should_stop():
        on_submitted()

    submitted_at = time.monotonic()
    stable_since = submitted_at
    previous = ""
    response = ""
    deadline = submitted_at + WEB_TURN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if should_stop():
            _stop_web_generation(page, browser_kind)
            return response
        count = _web_count(page, browser_kind, selector)
        latest_response = _web_last_text(page, browser_kind, selector)
        if count > baseline or (latest_response and latest_response != baseline_response):
            response = latest_response
        now = time.monotonic()
        if response != previous:
            previous = response
            stable_since = now
        generating = _web_is_generating(page, browser_kind)
        if _is_web_response_complete(
            response,
            is_generating=generating,
            submitted_at=submitted_at,
            stable_since=stable_since,
            now=now,
        ):
            return response
        _web_wait(page, browser_kind, 500)
    raise RuntimeError("ChatGPT did not finish the controller turn within 30 minutes.")


def _submit_safari_prompt(page: Any, message: str) -> None:
    """Fill Safari's composer and wait for ChatGPT's visible send control."""
    fill_result = page.evaluate(
        """({value}) => {
            const composer = document.querySelector('#prompt-textarea');
            if (!composer) throw new Error('ChatGPT composer was not found.');
            composer.focus();
            if (composer.tagName === 'TEXTAREA') {
                const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
                if (setter) setter.call(composer, value); else composer.value = value;
                composer.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
            } else {
                const selection = window.getSelection();
                const range = document.createRange();
                range.selectNodeContents(composer);
                selection?.removeAllRanges();
                selection?.addRange(range);
                const inserted = Boolean(document.execCommand?.('insertText', false, value));
                if (!inserted || composer.textContent !== value) {
                    composer.textContent = value;
                    composer.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                }
            }
            return {filled: true, tagName: composer.tagName, contentEditable: composer.isContentEditable};
        }""",
        {"value": message},
    )
    if not isinstance(fill_result, dict) or not fill_result.get("filled"):
        raise RuntimeError("Safari did not fill the ChatGPT composer.")

    deadline = time.monotonic() + SAFARI_SEND_BUTTON_TIMEOUT_SECONDS
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = page.evaluate(
            r"""() => {
                const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    return element.getClientRects().length > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const labelFor = (button) => `${button.getAttribute('aria-label') || ''} ${button.innerText || button.textContent || ''}`.trim();
                const controls = Array.from(document.querySelectorAll('button')).filter(isVisible);
                const sendButtons = controls.filter((button) => {
                    const label = labelFor(button);
                    return button.getAttribute('data-testid') === 'send-button'
                        || /^(send|send prompt)$/i.test(label);
                });
                const sendButton = sendButtons.find((button) =>
                    !button.disabled && button.getAttribute('aria-disabled') !== 'true'
                );
                if (sendButton) {
                    sendButton.click();
                    return {
                        clicked: true,
                        ariaLabel: sendButton.getAttribute('aria-label') || '',
                        dataTestId: sendButton.getAttribute('data-testid') || '',
                    };
                }
                const generating = controls.some((button) => {
                    const label = labelFor(button);
                    const testId = button.getAttribute('data-testid') || '';
                    return /stop\s+(generating|response|answering)/i.test(label)
                        || /stop-(button|generating|response)/i.test(testId);
                });
                return {
                    clicked: false,
                    generating,
                    sendButtons: sendButtons.map((button) => ({
                        ariaLabel: button.getAttribute('aria-label') || '',
                        disabled: Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true'),
                    })),
                };
            }"""
        )
        if isinstance(result, dict):
            last_state = result
            if result.get("clicked"):
                return
        page.wait_for_timeout(WEB_SEND_BUTTON_POLL_MILLISECONDS)

    details = json.dumps(last_state, ensure_ascii=False, separators=(",", ":"))[:500]
    raise RuntimeError(f"Safari did not expose an enabled ChatGPT send button: {details}")


def _submit_chromium_prompt(
    page: Any,
    message: str,
    should_stop: Callable[[], bool],
) -> None:
    """Fill Chromium's composer and click Send after any attachment is ready."""
    user_selector = '[data-message-author-role="user"]'
    baseline_user_count = _web_count(page, "chromium", user_selector)
    composer = page.locator("#prompt-textarea")
    composer.fill(message)

    deadline = time.monotonic() + CHROMIUM_SEND_BUTTON_TIMEOUT_SECONDS
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if should_stop():
            return
        result = page.evaluate(
            r"""() => {
                const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    return element.getClientRects().length > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const labelFor = (button) => `${button.getAttribute('aria-label') || ''} ${button.innerText || button.textContent || ''}`.trim();
                const controls = Array.from(document.querySelectorAll('button')).filter(isVisible);
                const sendButtons = controls.filter((button) => {
                    const label = labelFor(button);
                    return button.getAttribute('data-testid') === 'send-button'
                        || /^(send|send prompt)$/i.test(label);
                });
                const sendButton = sendButtons.find((button) =>
                    !button.disabled && button.getAttribute('aria-disabled') !== 'true'
                );
                if (sendButton) {
                    sendButton.click();
                    return {
                        clicked: true,
                        ariaLabel: sendButton.getAttribute('aria-label') || '',
                        dataTestId: sendButton.getAttribute('data-testid') || '',
                    };
                }
                return {
                    clicked: false,
                    sendButtons: sendButtons.map((button) => ({
                        ariaLabel: button.getAttribute('aria-label') || '',
                        dataTestId: button.getAttribute('data-testid') || '',
                        disabled: Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true'),
                    })),
                };
            }"""
        )
        if isinstance(result, dict):
            last_state = result
            if result.get("clicked"):
                break
        page.wait_for_timeout(WEB_SEND_BUTTON_POLL_MILLISECONDS)
    else:
        details = json.dumps(last_state, ensure_ascii=False, separators=(",", ":"))[:500]
        raise RuntimeError(
            "The Chromium browser did not expose an enabled ChatGPT send button after "
            f"waiting for the context attachment: {details}"
        )

    accepted_deadline = time.monotonic() + CHROMIUM_SUBMISSION_ACCEPT_TIMEOUT_SECONDS
    while time.monotonic() < accepted_deadline:
        if should_stop():
            return
        composer_empty = bool(
            page.evaluate(
                """() => {
                    const composer = document.querySelector('#prompt-textarea');
                    if (!composer) return true;
                    return !(composer.innerText || composer.textContent || '').trim();
                }"""
            )
        )
        if (
            composer_empty
            or _web_count(page, "chromium", user_selector) > baseline_user_count
            or _web_is_generating(page, "chromium")
        ):
            return
        page.wait_for_timeout(WEB_SEND_BUTTON_POLL_MILLISECONDS)
    raise RuntimeError("The Chromium browser clicked Send, but ChatGPT did not accept the prompt.")


def _is_web_response_complete(
    response: str,
    *,
    is_generating: bool,
    submitted_at: float,
    stable_since: float,
    now: float,
) -> bool:
    normalized = str(response or "").strip()
    if not normalized or normalized.casefold().rstrip(". …") in WEB_PROGRESS_TEXT:
        return False
    if is_generating or now - submitted_at < WEB_RESPONSE_MINIMUM_SECONDS:
        return False
    return now - stable_since >= WEB_RESPONSE_STABLE_SECONDS


def _web_count(page: Any, browser_kind: str, selector: str) -> int:
    if browser_kind == "safari":
        return int(page.evaluate("(selector) => document.querySelectorAll(selector).length", selector) or 0)
    return int(page.locator(selector).count())


def _web_last_text(page: Any, browser_kind: str, selector: str) -> str:
    if browser_kind == "safari":
        return str(
            page.evaluate(
                """(selector) => {
                    const elements = document.querySelectorAll(selector);
                    const element = elements[elements.length - 1];
                    return element ? (element.innerText || element.textContent || '').trim() : '';
                }""",
                selector,
            )
            or ""
        )
    elements = page.locator(selector)
    if elements.count() == 0:
        return ""
    return elements.last.inner_text(timeout=5_000).strip()


def _web_is_generating(page: Any, browser_kind: str) -> bool:
    del browser_kind
    return bool(
        page.evaluate(
            r"""() => Array.from(document.querySelectorAll('button')).some((button) => {
                const text = `${button.getAttribute('aria-label') || ''} ${button.innerText || button.textContent || ''}`.toLowerCase();
                const testId = (button.getAttribute('data-testid') || '').toLowerCase();
                return button.offsetParent !== null
                    && !button.disabled
                    && button.getAttribute('aria-disabled') !== 'true'
                    && (
                        /stop\s+(generating|response|answering|streaming)/.test(text)
                        || /stop-(button|generating|response|streaming)/.test(testId)
                    );
            })"""
        )
    )


def _stop_web_generation(page: Any, browser_kind: str) -> None:
    del browser_kind
    page.evaluate(
        r"""() => {
            const button = Array.from(document.querySelectorAll('button')).find((candidate) => {
                const text = `${candidate.getAttribute('aria-label') || ''} ${candidate.innerText || candidate.textContent || ''}`.toLowerCase();
                const testId = (candidate.getAttribute('data-testid') || '').toLowerCase();
                return candidate.offsetParent !== null
                    && !candidate.disabled
                    && candidate.getAttribute('aria-disabled') !== 'true'
                    && (
                        /stop\s+(generating|response|answering|streaming)/.test(text)
                        || /stop-(button|generating|response|streaming)/.test(testId)
                    );
            });
            if (button) button.click();
            return Boolean(button);
        }"""
    )


def _web_wait(page: Any, browser_kind: str, milliseconds: int) -> None:
    page.wait_for_timeout(milliseconds)
