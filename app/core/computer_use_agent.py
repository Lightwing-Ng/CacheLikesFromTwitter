"""Browser-mediated Computer Use agent for signed-in Web AI sessions.

Code version: v3.28.0-codex.1
"""

from __future__ import annotations

import base64
import binascii
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from glob import translate as translate_glob
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import shutil
import shlex
import signal
import stat as stat_module
import subprocess
import sys
from threading import Event, RLock, Thread, current_thread
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from .agent_session_sources import (
    CLAUDE_HOME_URL,
    CLAUDE_HOSTS,
    normalize_agent_conversation_url,
    normalize_agent_project_url,
)
from .browser_sessions import (
    browser_descriptors,
    goto_with_retry,
    launch_chromium_context,
    sync_playwright_or_error,
)
from .config import (
    CrawlConfig,
    PROJECT_ROOT,
    default_settings_path,
    is_windows_host,
    resolve_runtime_root,
)
from .safari_automation import SafariContext
from .state import utc_now


LOGGER = logging.getLogger(__name__)
_SUBPROCESS_POPEN_TYPE = subprocess.Popen
CHATGPT_HOME_URL = "https://chatgpt.com/"
CHATGPT_HOSTS = {"chatgpt.com", "www.chatgpt.com"}
GEMINI_HOME_URL = "https://gemini.google.com/app"
GEMINI_HOSTS = {"gemini.google.com"}
GROK_HOME_URL = "https://grok.com/"
GROK_HOSTS = {"grok.com", "www.grok.com"}
DEFAULT_AGENT_SETTINGS_PATH = default_settings_path().with_name("computer-use-agent.json")
DEFAULT_AGENT_RUNTIME_ROOT = (
    resolve_runtime_root() / ".computer-use-agent"
    if os.environ.get("CACHELIKES_RUNTIME_ROOT", "").strip()
    else default_settings_path().parent / "computer-use-agent"
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
RUN_OUTPUT_QUEUE_SIZE = 4
MAX_FILE_READ_CHARS = 120_000
MAX_ACTION_JSON_CHARS = 800_000
MAX_INVALID_ACTION_RETRIES = 3
CHATGPT_MODEL_VERIFICATION_ATTEMPTS = 3
MAX_BASE64_DECODED_BYTES = MAX_FILE_READ_CHARS
BROWSER_INTERRUPTION_TIMEOUT_SECONDS = 300
BROWSER_INTERRUPTION_POLL_SECONDS = 1.0
MAX_AGENT_SESSION_HISTORY = 100
PERSISTED_AGENT_SNAPSHOT_FILENAME = "last-run.json"
WEB_RESPONSE_MINIMUM_SECONDS = 1.5
WEB_RESPONSE_STABLE_SECONDS = 1.0
WEB_TURN_TIMEOUT_SECONDS = 1_800
GROK_KEYBOARD_SUBMIT_FALLBACK_SECONDS = 2.0
CHATGPT_COMPOSER_TIMEOUT_SECONDS = 60
CHATGPT_MODEL_COMPOSER_WAIT_SECONDS = 15
CHATGPT_COMPOSER_RELOAD_ATTEMPTS = 2
CHATGPT_COMPOSER_RELOAD_TIMEOUT_SECONDS = 5
SAFARI_SEND_BUTTON_TIMEOUT_SECONDS = 15
CHROMIUM_SEND_BUTTON_TIMEOUT_SECONDS = 180
CHROMIUM_SUBMISSION_ACCEPT_TIMEOUT_SECONDS = 15
WEB_SEND_BUTTON_POLL_MILLISECONDS = 250
WEB_PROGRESS_TEXT = {"thinking", "working", "searching", "analyzing", "generating"}
SUPPORTED_BROWSERS = frozenset({"chrome", "edge", "safari"})
SUPPORTED_OPERATING_SYSTEMS = frozenset({"macos", "windows"})
SUPPORTED_AGENT_SESSION_MODES = frozenset({"new", "recent", "project_new", "project_session"})
SUPPORTED_AGENT_PLATFORMS = frozenset({"chatgpt", "gemini", "grok", "claude"})
DEFAULT_AGENT_PLATFORM = "chatgpt"
CHATGPT_MODEL_OPTIONS = (
    {
        "key": "gpt-5.6-sol",
        "label": "GPT-5.6 Sol",
        "ui_label": "5.6 Sol",
        "remote_label": "GPT-5.6 Sol",
        "remote_labels": ("GPT-5.6 Sol", "5.6 Sol"),
        "strength": 100,
    },
)
GEMINI_MODEL_OPTIONS = (
    {
        "key": "gemini-3.1-pro",
        "label": "Gemini 3.1 Pro",
        "ui_label": "3.1 Pro",
        "remote_labels": ("Gemini 3.1 Pro", "3.1 Pro"),
        "strength": 100,
    },
)
GROK_MODEL_OPTIONS = (
    {
        "key": "grok-auto",
        "label": "Auto",
        "ui_label": "Auto",
        "remote_labels": ("Auto", "自動", "自动"),
        "strength": 100,
    },
)
CLAUDE_MODEL_OPTIONS = (
    {
        "key": "claude-auto",
        "label": "Auto",
        "ui_label": "Auto",
        "remote_labels": ("Auto", "Default", "Claude"),
        "strength": 100,
    },
)
AGENT_MODEL_OPTIONS_BY_PLATFORM = {
    "chatgpt": CHATGPT_MODEL_OPTIONS,
    "gemini": GEMINI_MODEL_OPTIONS,
    "grok": GROK_MODEL_OPTIONS,
    "claude": CLAUDE_MODEL_OPTIONS,
}


def strongest_model_option(options: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Return the strongest model from one provider's current option catalog."""
    return max(
        options,
        key=lambda option: (
            int(option.get("strength", 0)),
            str(option.get("key", "")),
        ),
    )


def default_model_for_platform(platform: str) -> str:
    """Return the strongest supported model for one Web Agent platform."""
    options = tuple(AGENT_MODEL_OPTIONS_BY_PLATFORM.get(platform, ()))
    if not options:
        raise ValueError(f"No Web Agent models are configured for {platform}.")
    return str(strongest_model_option(options)["key"])


DEFAULT_CHATGPT_MODEL = default_model_for_platform("chatgpt")
SUPPORTED_CHATGPT_MODELS = frozenset(option["key"] for option in CHATGPT_MODEL_OPTIONS)
AGENT_PLATFORM_OPTIONS = (
    {
        "key": "chatgpt",
        "label": "ChatGPT",
        "icon_filename": "images/ChatGPT-Logo.svg",
        "home_url": CHATGPT_HOME_URL,
        "hosts": CHATGPT_HOSTS,
    },
    {
        "key": "gemini",
        "label": "Gemini",
        "icon_filename": "images/Google_Gemini_logo_2025_symbol.svg",
        "home_url": GEMINI_HOME_URL,
        "hosts": GEMINI_HOSTS,
    },
    {
        "key": "grok",
        "label": "Grok",
        "icon_filename": "images/grok.svg",
        "home_url": GROK_HOME_URL,
        "hosts": GROK_HOSTS,
    },
    {
        "key": "claude",
        "label": "Claude",
        "icon_filename": "images/claude.svg",
        "home_url": CLAUDE_HOME_URL,
        "hosts": CLAUDE_HOSTS,
    },
)
AGENT_PLATFORM_BY_KEY = {option["key"]: option for option in AGENT_PLATFORM_OPTIONS}
AGENT_MODEL_OPTIONS = CHATGPT_MODEL_OPTIONS
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
        "available": True,
    },
)
BROWSER_OPTIONS = (
    {"key": "safari", "label": "Safari", "icon_filename": "images/browser.safari.png"},
    {"key": "edge", "label": "Edge", "icon_filename": "images/browser.edge.png"},
    {"key": "chrome", "label": "Chrome", "icon_filename": "images/browser.chrome.png"},
)

JSON_ACTION_RESPONSE_INSTRUCTION = (
    "Return exactly one strict JSON controller action inside one Markdown fenced code block labelled json, "
    "with no prose outside the fence. The fence preserves quotes, backslashes, asterisks, and source code "
    "through the Web page's rendered text. JSON-escape embedded double quotes as \\\", backslashes as \\\\, "
    "and newlines as \\n. "
    "When old or new text contains HTML attributes, template syntax, or multiple layers of quotes, "
    "use replace_base64 or write_base64 with standard base64-encoded fields to avoid quote corruption."
)

_BASE64_CORRECTION_INSTRUCTION = (
    "The previous action contained unescapable quotes or backslashes. "
    "Resend it using replace_base64 or write_base64 with base64-encoded content fields. "
    "Do not attempt to manually escape the problematic characters."
)

DEFAULT_MACOS_SYSTEM_PROMPT = (
    """You are the reasoning component of a local Computer Use coding agent.
The controller runs on macOS and owns one selected project. It can read and change only that project and can run bounded local checks. Treat controller results as authoritative. Never claim a file changed or a check passed until the controller reports it.

Work autonomously from the user's request. Read the repository instruction files before editing. Make the smallest correct change, preserve unrelated work, use existing project patterns, and verify material changes. Keep context economical: request only the files or ranges needed, keep command output bounded, and do not repeat controller results.

"""
    + JSON_ACTION_RESPONSE_INSTRUCTION
    + """

Use one of these actions:
{"action":"list","path":".","depth":2}
{"action":"read","path":"relative/file","start_line":1,"end_line":240}
{"action":"search","query":"literal text","path":".","glob":"*.py","max_results":80}
{"action":"replace","path":"relative/file","old":"exact text appearing once","new":"replacement text"}
{"action":"replace_base64","path":"relative/file","old_base64":"base64-of-old","new_base64":"base64-of-new"}
{"action":"write","path":"relative/new-file","content":"complete content"}
{"action":"write_base64","path":"relative/new-file","content_base64":"base64-of-content"}
{"action":"run","command":"focused inspection, build, lint, or test command"}
{"action":"bodycheck"}
{"action":"final","summary":"concise Markdown outcome","verification":["check and result"],"limitations":["remaining limitation"]}

Use read/search/list before editing. Use replace for existing files and write mainly for new files. Do not use shell commands to write, delete, move, install, download, change Git history, publish, or access secrets. After edits, run at least one approved focused verification command, then ask the controller to run bodycheck. A final action is invalid until both verification and bodycheck succeed after the latest edit. The final summary must be concise and must not restate the full transcript."""
)

DEFAULT_WINDOWS_SYSTEM_PROMPT = (
    """You are the reasoning component of a local Computer Use coding agent targeting Windows.
The controller runs on Windows, uses PowerShell-compatible Windows paths, and owns the selected project as its only writable root. Follow repository instruction files, preserve unrelated work, make focused changes, and verify them. Keep context economical.

"""
    + JSON_ACTION_RESPONSE_INSTRUCTION
    + """

Use the controller actions list, read, search, replace, write, run, bodycheck, or final. Never claim an operation succeeded before the controller reports it. After edits, run one approved verification command and then bodycheck before final. Do not use commands to write, delete, move, install, download, change Git history, publish, or access secrets."""
)

_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".computer-use-agent",
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
SEARCH_MAX_FILE_BYTES = 2 * 1_024 * 1_024
SEARCH_MAX_RAW_EVENTS = 12_000
SEARCH_MAX_MATCH_TEXT_CHARS = 4_000
SEARCH_TIMEOUT_SECONDS = 30
SEARCH_STDOUT_QUEUE_SIZE = 4
MAX_SEARCH_QUERY_CHARS = 8_000
GIT_STATUS_MAX_RAW_CHARS = 2 * 1_024 * 1_024
GIT_STATUS_TIMEOUT_SECONDS = 10
WORKSPACE_FINGERPRINT_MAX_FILES = 12_000
WORKSPACE_FINGERPRINT_MAX_DIRECTORIES = 12_000
WORKSPACE_FINGERPRINT_MAX_BYTES = 512 * 1_024 * 1_024
WORKSPACE_FINGERPRINT_TIMEOUT_SECONDS = 15
_STREAM_READ_FAILED = object()
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
_SAFE_GIT_SUBCOMMANDS = frozenset({"status"})
_SAFE_GIT_STATUS_FLAGS = frozenset(
    {
        "--branch",
        "--porcelain",
        "--porcelain=v1",
        "--short",
        "--untracked-files=all",
        "--untracked-files=no",
        "--untracked-files=normal",
        "-b",
        "-s",
    }
)
_SAFE_PYTHON_MODULES = frozenset({"compileall", "mypy", "py_compile", "pytest", "ruff"})
_SAFE_PACKAGE_SCRIPTS = re.compile(
    r"^(?:build|check|ci|lint|test|test:[\w:-]+|typecheck|verify)$",
    re.IGNORECASE,
)
_SAFE_SCRIPT_NAME = re.compile(
    r"^(?:check|lint|test|verify)(?:[._-][\w.-]+)?\.(?:sh|zsh|bash|py|ps1)$",
    re.IGNORECASE,
)
_UNSAFE_WRAPPER_EXECUTABLES = frozenset(
    {"bash", "cmd", "dash", "fish", "powershell", "pwsh", "sh", "zsh"}
)
_MUTATING_OR_UNBOUNDED_RUN_FLAGS = frozenset(
    {
        "--apply",
        "--add-noqa",
        "--createstub",
        "--exec",
        "--fix",
        "--force",
        "--in-place",
        "--install-types",
        "--output",
        "--output-file",
        "--pastebin",
        "--pre",
        "--pre-glob",
        "--replace",
        "--update-snapshots",
        "--watch",
        "--write",
        "-exec",
        "-i",
        "-o",
        "-w",
    }
)
_SENSITIVE_PATH_NAMES = frozenset(
    {
        ".aws",
        ".env",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".ssh",
        "cookies",
        "cookies.json",
        "credential",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ed25519",
        "id_ecdsa",
        "id_rsa",
        "secret",
        "secrets",
        "secrets.json",
    }
)
_SENSITIVE_PATH_SUFFIXES = (".key", ".p12", ".pem", ".pfx")


DEFAULT_OPERATING_SYSTEM = "windows" if is_windows_host() else "macos"


@dataclass(frozen=True, slots=True)
class ComputerUseSettings:
    """Persist local Computer Use preferences and prompt policy."""

    workspace_path: str = str(PROJECT_ROOT)
    operating_system: str = DEFAULT_OPERATING_SYSTEM
    platform: str = DEFAULT_AGENT_PLATFORM
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


SAFE_PROTOCOL_PROMPT_MARKERS = (
    "fenced code block labelled json",
    "replace_base64",
    "write_base64",
)


def system_prompt_has_safe_protocol(prompt: str) -> bool:
    """Return whether one system prompt includes the current JSON controller contract."""
    text = str(prompt or "")
    return all(marker in text for marker in SAFE_PROTOCOL_PROMPT_MARKERS)


def migrate_legacy_system_prompts(settings: ComputerUseSettings) -> ComputerUseSettings:
    """Replace persisted prompts that lack the current safe-protocol markers."""
    macos_prompt = settings.macos_system_prompt
    windows_prompt = settings.windows_system_prompt
    if not system_prompt_has_safe_protocol(macos_prompt):
        macos_prompt = DEFAULT_MACOS_SYSTEM_PROMPT
    if not system_prompt_has_safe_protocol(windows_prompt):
        windows_prompt = DEFAULT_WINDOWS_SYSTEM_PROMPT
    if (
        macos_prompt == settings.macos_system_prompt
        and windows_prompt == settings.windows_system_prompt
    ):
        return settings
    return replace(
        settings,
        macos_system_prompt=macos_prompt,
        windows_system_prompt=windows_prompt,
    )


@dataclass(slots=True)
class AgentRunSnapshot:
    """Describe one browser-mediated coding run without exposing project content."""

    running: bool = False
    phase: str = "idle"
    message: str = "Ready to use a signed-in Web AI session."
    engine: str = "computer_use"
    prompt: str = ""
    workspace_path: str = ""
    response: str = ""
    conversation_url: str = ""
    project_url: str = ""
    session_title: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    activity: list[dict[str, str]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    last_error: str = ""
    context_file: str = ""
    context_bytes: int = 0
    context_attached: bool = False
    turn_count: int = 0
    bodycheck_passed: bool = False
    session_mode: str = "new"
    platform: str = DEFAULT_AGENT_PLATFORM
    browser: str = "edge"
    model: str = DEFAULT_CHATGPT_MODEL
    model_verified: bool = False
    actual_model: str = ""
    session_type: str = ""
    catalog_state: str = "idle"
    catalog_error: str = ""
    paused: bool = False
    pause_reason: str = ""
    traditional_handoff_available: bool = False
    traditional_handoff_opened: bool = False
    traditional_handoff_message: str = ""


@dataclass(slots=True)
class ActionState:
    """Track edit and bodycheck ordering for one workspace loop."""

    edit_generation: int = 0
    bodycheck_generation: int = -1
    verification_generation: int = -1
    successful_checks: list[str] = field(default_factory=list)

    @property
    def bodycheck_current(self) -> bool:
        return self.bodycheck_generation == self.edit_generation

    @property
    def verification_current(self) -> bool:
        return self.verification_generation == self.edit_generation


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


def browser_options_for_host() -> tuple[dict[str, str], ...]:
    """Return browser options that are available on the current host."""
    if detect_host_operating_system() == "windows":
        return tuple(option for option in BROWSER_OPTIONS if option["key"] != "safari")
    return BROWSER_OPTIONS


def _process_group_options() -> dict[str, Any]:
    """Return subprocess options that isolate a task on the current host."""
    if is_windows_host():
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creation_flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": creation_flags} if creation_flags else {}
    return {"start_new_session": True}


def _stop_process(process: subprocess.Popen[Any], *, timeout: float = 3) -> None:
    """Stop one isolated task process and every surviving descendant."""
    bounded_timeout = max(0.05, float(timeout))
    if is_windows_host():
        if process.poll() is None:
            try:
                process.send_signal(
                    getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM)
                )
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=bounded_timeout)
            except (OSError, subprocess.TimeoutExpired):
                pass
        taskkill = _trusted_windows_taskkill()
        if taskkill is not None:
            try:
                subprocess.run(
                    [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=bounded_timeout,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=bounded_timeout)
        except (OSError, subprocess.TimeoutExpired):
            return
        return

    deadline = time.monotonic() + bounded_timeout
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        try:
            process.wait(timeout=0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return
    except OSError:
        return
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired):
        pass
    while time.monotonic() < deadline:
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            break
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        return
    try:
        process.wait(timeout=bounded_timeout)
    except (OSError, subprocess.TimeoutExpired):
        pass


def terminal_execution_permission_snapshot(
    operating_system: str,
    workspace_path: str,
) -> dict[str, Any]:
    """Report whether the local controller can execute in the selected project."""
    selected = str(operating_system or "").strip().lower()
    host = detect_host_operating_system()
    application = "PowerShell" if selected == "windows" else "Terminal"
    workspace = Path(str(workspace_path or "")).expanduser().resolve()

    if selected not in SUPPORTED_OPERATING_SYSTEMS:
        return {
            "ready": False,
            "status_label": "Not granted",
            "application": application,
            "message": "Choose macOS or Windows before checking terminal execution permission.",
        }
    if selected != host:
        host_label = "Windows" if host == "windows" else "macOS"
        return {
            "ready": False,
            "status_label": "Not granted",
            "application": application,
            "message": f"{application} execution is unavailable while the app runs on {host_label}.",
        }

    executable = shutil.which("powershell.exe" if selected == "windows" else "zsh")
    workspace_access = (
        workspace.is_dir()
        and os.access(workspace, os.R_OK | os.W_OK | os.X_OK)
    )
    ready = bool(
        executable
        and os.access(executable, os.X_OK)
        and workspace_access
    )
    if ready:
        message = (
            f"{application} command execution and read/write access to the selected project "
            "are available."
        )
    elif not executable:
        message = f"{application} could not be found on this host."
    elif not workspace_access:
        message = (
            f"{application} does not have read/write access to the selected project. "
            "Review its system privacy permissions."
        )
    else:
        message = f"{application} command execution is unavailable."
    return {
        "ready": ready,
        "status_label": "Granted" if ready else "Not granted",
        "application": application,
        "message": message,
    }


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


def _platform_model_options(platform: str) -> tuple[dict[str, Any], ...]:
    """Return the supported remote model choices for one web platform."""
    return tuple(AGENT_MODEL_OPTIONS_BY_PLATFORM.get(platform, ()))


def _platform_home_url(platform: str) -> str:
    """Return the official home URL for one supported web platform."""
    option = AGENT_PLATFORM_BY_KEY.get(platform)
    if option is None:
        raise ValueError("Choose ChatGPT, Gemini, Grok, or Claude for the Web Agent.")
    return str(option["home_url"])


def _platform_hosts(platform: str) -> set[str]:
    """Return the official HTTPS hosts accepted for one web platform."""
    option = AGENT_PLATFORM_BY_KEY.get(platform)
    if option is None:
        raise ValueError("Choose ChatGPT, Gemini, Grok, or Claude for the Web Agent.")
    return set(option["hosts"])


def _normalize_web_agent_target(platform: str, target_url: str = "") -> str:
    """Normalize one safe target without allowing cross-site browser navigation."""
    normalized_target_url = (
        normalize_agent_conversation_url(platform, target_url)
        or normalize_agent_project_url(platform, target_url)
    )
    if normalized_target_url:
        return normalized_target_url
    return _platform_home_url(platform)


def open_agent_in_default_browser(platform: str = DEFAULT_AGENT_PLATFORM, target_url: str = "") -> dict[str, Any]:
    """Open one trusted Web Agent target through the host system's default browser."""
    selected_platform = str(platform or DEFAULT_AGENT_PLATFORM).strip().lower()
    destination = _normalize_web_agent_target(selected_platform, target_url)
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
            f"Could not open {selected_platform.title()} in the system default browser: {exc}"
        ) from exc

    return {
        "opened": True,
        "platform": selected_platform,
        "url": destination,
        "targeted_conversation": bool(normalize_agent_conversation_url(selected_platform, target_url)),
    }


def open_agent_in_browser(
    platform: str = DEFAULT_AGENT_PLATFORM,
    browser: str = "edge",
    target_url: str = "",
    *,
    background: bool = False,
) -> dict[str, Any]:
    """Open one trusted Web Agent target in the explicitly selected browser."""
    selected_platform = str(platform or DEFAULT_AGENT_PLATFORM).strip().lower()
    selected_browser = str(browser or "edge").strip().lower()
    if selected_browser not in SUPPORTED_BROWSERS:
        raise ValueError("The Agent browser must be Safari, Edge, or Chrome.")

    destination = _normalize_web_agent_target(selected_platform, target_url)
    process_options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    application = selected_browser.title()

    if sys.platform == "darwin":
        application = {
            "safari": "Safari",
            "edge": "Microsoft Edge",
            "chrome": "Google Chrome",
        }[selected_browser]
        if background and selected_browser in {"edge", "chrome"}:
            command = [
                "/usr/bin/osascript",
                "-e",
                "on run argv",
                "-e",
                "set destinationURL to item 1 of argv",
                "-e",
                f'tell application "{application}"',
                "-e",
                "set handoffWindow to make new window",
                "-e",
                "set URL of active tab of handoffWindow to destinationURL",
                "-e",
                "end tell",
                "-e",
                "end run",
                destination,
            ]
        else:
            command = ["/usr/bin/open"]
            if background:
                command.append("-g")
            command.extend(["-a", application, destination])
        process_options["start_new_session"] = True
    elif os.name == "nt":
        if selected_browser == "safari":
            raise RuntimeError("Safari is not available for a traditional Windows handoff.")
        application = "Microsoft Edge" if selected_browser == "edge" else "Google Chrome"
        executable = "msedge.exe" if selected_browser == "edge" else "chrome.exe"
        command = ["cmd.exe", "/c", "start", "", executable, destination]
    else:
        if selected_browser == "safari":
            raise RuntimeError("Safari is not available for a traditional Linux handoff.")
        application = "Microsoft Edge" if selected_browser == "edge" else "Google Chrome"
        executable = "microsoft-edge" if selected_browser == "edge" else "google-chrome"
        resolved_executable = shutil.which(executable)
        if not resolved_executable:
            raise RuntimeError(f"{application} could not be found on this host.")
        command = [resolved_executable, destination]
        process_options["start_new_session"] = True

    try:
        subprocess.Popen(command, **process_options)
    except OSError as exc:
        raise RuntimeError(
            f"Could not open {AGENT_PLATFORM_BY_KEY[selected_platform]['label']} in {application}: {exc}"
        ) from exc

    return {
        "opened": True,
        "platform": selected_platform,
        "browser": selected_browser,
        "application": application,
        "url": destination,
        "targeted_conversation": bool(normalize_agent_conversation_url(selected_platform, target_url)),
        "background": bool(background),
    }


def open_chatgpt_in_default_browser(target_url: str = "") -> dict[str, Any]:
    """Open a trusted ChatGPT target through the host system's default browser."""
    result = open_agent_in_default_browser("chatgpt", target_url)
    result.pop("platform", None)
    return result


def validate_computer_use_settings(payload: dict[str, Any]) -> ComputerUseSettings:
    """Normalize and validate settings received from the local control page."""
    workspace = Path(str(payload.get("workspace_path", PROJECT_ROOT))).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Agent workspace directory was not found: {workspace}")

    operating_system = str(payload.get("operating_system", DEFAULT_OPERATING_SYSTEM)).strip().lower()
    if operating_system not in SUPPORTED_OPERATING_SYSTEMS:
        raise ValueError("The Agent operating system must be macOS or Windows.")

    platform = str(payload.get("platform", DEFAULT_AGENT_PLATFORM)).strip().lower()
    if platform not in SUPPORTED_AGENT_PLATFORMS:
        raise ValueError("The Agent platform must be ChatGPT, Gemini, Grok, or Claude.")

    browser = str(payload.get("browser", "edge")).strip().lower()
    if browser not in SUPPORTED_BROWSERS:
        raise ValueError("The Agent browser must be Safari, Edge, or Chrome.")
    if operating_system == "windows" and browser == "safari":
        raise ValueError("Windows Agent sessions require Edge or Chrome; Safari is macOS-only.")
    if platform != "chatgpt" and browser == "safari":
        raise ValueError("Gemini, Grok, and Claude Agent sessions require Edge or Chrome.")

    default_model = default_model_for_platform(platform)
    model = str(payload.get("model", default_model)).strip().lower()
    supported_models = frozenset(option["key"] for option in _platform_model_options(platform))
    if model not in supported_models:
        platform_label = AGENT_PLATFORM_BY_KEY[platform]["label"]
        raise ValueError(f"Choose a supported {platform_label} model.")

    target_url = str(payload.get("target_url", _platform_home_url(platform))).strip()
    target_parts = urlsplit(target_url)
    if target_parts.scheme != "https" or (target_parts.hostname or "").lower() not in _platform_hosts(platform):
        platform_label = AGENT_PLATFORM_BY_KEY[platform]["label"]
        raise ValueError(f"The Agent target must use the official {platform_label} HTTPS host.")

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
        platform=platform,
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
    """Load local Agent settings or return safe defaults.

    Legacy persisted prompts that lack the current fenced-JSON and base64
    transport markers are replaced with the current defaults and written back
    immediately. Unrelated settings are preserved.
    """
    if not settings_path.exists():
        return ComputerUseSettings()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Agent settings must be a JSON object.")
        settings = validate_computer_use_settings(payload)
        migrated = migrate_legacy_system_prompts(settings)
        if migrated != settings:
            try:
                save_computer_use_settings(migrated, settings_path)
                LOGGER.info(
                    "Migrated legacy Computer Use Agent system prompts at %s.",
                    settings_path,
                )
            except OSError as exc:
                LOGGER.warning(
                    "Could not persist migrated Computer Use Agent settings at %s: %s",
                    settings_path,
                    exc,
                )
        return migrated
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

    def __init__(self, settings_path: Path | None = None) -> None:
        self._lock = RLock()
        self._settings_path = settings_path or DEFAULT_AGENT_SETTINGS_PATH
        self._settings = load_computer_use_settings(self._settings_path)

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
        platform: str = DEFAULT_AGENT_PLATFORM,
        model: str | None = None,
    ) -> ComputerUseSettings:
        candidate = asdict(self.settings)
        candidate.update(
            {
                "workspace_path": workspace_path,
                "operating_system": operating_system,
                "platform": platform,
                "browser": browser,
                "model": model or self.settings.model,
            }
        )
        if platform != self.settings.platform:
            candidate["target_url"] = _platform_home_url(platform)
        return self.update(validate_computer_use_settings(candidate))

    def snapshot(self) -> dict[str, Any]:
        settings = self.settings
        host_operating_system = detect_host_operating_system()
        host_ready = settings.operating_system == host_operating_system
        terminal_execution = terminal_execution_permission_snapshot(
            settings.operating_system,
            settings.workspace_path,
        )
        host_label = "Windows" if host_operating_system == "windows" else "macOS"
        return {
            "ready": host_ready,
            "host_operating_system": host_operating_system,
            "selected_operating_system": settings.operating_system,
            "message": (
                f"Computer Use is ready on this {host_label} host."
                if host_ready
                else f"{settings.operating_system.title()} execution is unavailable on this {host_label} host."
            ),
            "terminal_execution": terminal_execution,
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
    platform: str = DEFAULT_AGENT_PLATFORM,
) -> str:
    """Resolve one UI session choice to a verified Web Agent target URL."""
    mode = str(session_mode or "new").strip().lower()
    if mode not in SUPPORTED_AGENT_SESSION_MODES:
        raise ValueError("Choose a supported Web Agent session source.")
    selected_platform = str(platform or DEFAULT_AGENT_PLATFORM).strip().lower()
    if selected_platform not in SUPPORTED_AGENT_PLATFORMS:
        raise ValueError("Choose ChatGPT, Gemini, Grok, or Claude for the Web Agent.")
    if mode == "new":
        return _platform_home_url(selected_platform)

    platform_label = AGENT_PLATFORM_BY_KEY[selected_platform]["label"]
    normalized_project_url = normalize_agent_project_url(selected_platform, project_url)
    if mode == "project_new":
        if not normalized_project_url:
            raise ValueError(f"Choose a {platform_label} Project before starting a new Project session.")
        return normalized_project_url

    normalized_conversation_url = normalize_agent_conversation_url(selected_platform, conversation_url)
    if not normalized_conversation_url:
        raise ValueError(f"Choose a recent {platform_label} session before joining it.")
    if mode == "project_session":
        if not normalized_project_url:
            raise ValueError(f"Choose the {platform_label} Project that owns this session.")
        if selected_platform == "chatgpt":
            project_path = urlsplit(normalized_project_url).path.rstrip("/")
            project_path = project_path[: -len("/project")] if project_path.endswith("/project") else project_path
            conversation_path = urlsplit(normalized_conversation_url).path.rstrip("/")
            if not conversation_path.startswith(f"{project_path}/c/"):
                raise ValueError("The selected session does not belong to the selected Project.")
        elif selected_platform == "claude":
            project_path = urlsplit(normalized_project_url).path.rstrip("/")
            conversation_path = urlsplit(normalized_conversation_url).path.rstrip("/")
            if not conversation_path.startswith(f"{project_path}/"):
                raise ValueError("The selected session does not belong to the selected Project.")
    return normalized_conversation_url


def agent_session_opening_message(
    session_mode: str,
    browser_label: str,
    platform: str = DEFAULT_AGENT_PLATFORM,
) -> str:
    """Describe the selected Web Agent session source in the live Agent status."""
    platform_label = AGENT_PLATFORM_BY_KEY.get(platform, AGENT_PLATFORM_BY_KEY[DEFAULT_AGENT_PLATFORM])["label"]
    messages = {
        "new": f"Opening a new signed-in {platform_label} Web session",
        "recent": f"Joining the selected recent {platform_label} Web session",
        "project_new": "Opening a new session in the selected Project",
        "project_session": "Joining the selected session in the selected Project",
    }
    return f"{messages.get(session_mode, messages['new'])} in {browser_label}."


def session_type_for_mode(session_mode: str) -> str:
    """Map an explicit session_mode to fresh, reused, or project."""
    mode = str(session_mode or "new").strip().lower()
    if mode == "recent":
        return "reused"
    if mode in {"project_new", "project_session"}:
        return "project"
    return "fresh"


def build_context_markdown(
    workspace: Path,
    user_request: str,
    settings: ComputerUseSettings,
    destination: Path,
) -> tuple[Path, int]:
    """Build a bounded initial context bundle for a fresh Web Agent conversation."""
    byte_limit = settings.context_limit_mib * 1_024 * 1_024
    sections = [
        "# Local Computer Use task\n",
        "## Request\n\n" + user_request.strip() + "\n",
        "## Execution environment\n\n"
        f"- Host controller: {('Windows' if detect_host_operating_system() == 'windows' else 'macOS')}\n"
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
        status = _filtered_git_status(workspace)
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
    try:
        destination.write_bytes(b"".join(encoded_parts))
        destination.chmod(0o600)
        byte_count = destination.stat().st_size
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            LOGGER.exception(
                "Could not remove a partially prepared Agent context: %s",
                destination,
            )
        raise
    return destination, byte_count


def _utf8_prefix(value: bytes, maximum: int) -> bytes:
    return value[: max(0, maximum)].decode("utf-8", errors="ignore").encode("utf-8")


def _filtered_git_status(
    workspace: Path,
    *,
    should_stop: Callable[[], bool] | None = None,
    process_changed: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> str:
    """Return porcelain status rows after excluding every protected path."""
    output, truncated = _bounded_git_status_output(
        workspace,
        should_stop=should_stop,
        process_changed=process_changed,
    )
    if truncated and not output.endswith("\x00"):
        output = output.rsplit("\x00", 1)[0] + "\x00" if "\x00" in output else ""
    values = output.split("\x00")
    rows: list[str] = []
    index = 0
    while index < len(values):
        record = values[index]
        index += 1
        if len(record) < 4 or record[2] != " ":
            continue
        status = record[:2]
        paths = [record[3:]]
        if ("R" in status or "C" in status) and index < len(values):
            paths.append(values[index])
            index += 1
        normalized_paths: list[str] = []
        safe = True
        for value in paths:
            candidate = Path(value)
            if (
                not value
                or candidate.is_absolute()
                or ".." in candidate.parts
                or _path_has_ignored_part(candidate)
                or _path_has_sensitive_part(candidate)
            ):
                safe = False
                break
            normalized_paths.append(candidate.as_posix())
        if not safe:
            continue
        rendered_paths = [json.dumps(path, ensure_ascii=False) for path in normalized_paths]
        if len(rendered_paths) == 2:
            rows.append(f"{status} {rendered_paths[1]} -> {rendered_paths[0]}")
        else:
            rows.append(f"{status} {rendered_paths[0]}")
        if len(rows) >= 12_000:
            break
    if truncated:
        rows.append("!! [status truncated at the controller output limit]")
    return "\n".join(rows)


def _bounded_git_status_output(
    workspace: Path,
    *,
    should_stop: Callable[[], bool] | None = None,
    process_changed: Callable[[subprocess.Popen[str] | None], None] | None = None,
) -> tuple[str, bool]:
    """Stream a fixed Git porcelain command with a global memory and time limit."""
    stop_requested = should_stop or (lambda: False)
    publish_process = process_changed or (lambda _process: None)
    git = _trusted_system_executable("git", forbidden_root=workspace)
    if git is None:
        raise RuntimeError("Git is unavailable for bounded working-tree inspection.")
    command = [
        str(git),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_process_group_options(),
        )
    except OSError as exc:
        raise RuntimeError("Could not inspect the bounded Git working-tree status.") from exc
    if process.stdout is None:
        _stop_process(process, timeout=1)
        raise RuntimeError("Could not open the bounded Git status stream.")

    chunks: list[str] = []
    used = 0
    truncated = False
    timed_out = False
    stopped = False
    stream_failed = False
    loop_completed = False
    discard_output: Event | None = None
    reader: Thread | None = None
    deadline = time.monotonic() + GIT_STATUS_TIMEOUT_SECONDS
    try:
        output_queue: Queue[Any] = Queue(maxsize=SEARCH_STDOUT_QUEUE_SIZE)
        discard_output = Event()
        reader = Thread(
            target=_queue_text_chunks,
            args=(process.stdout, output_queue, discard_output),
            daemon=True,
        )
        publish_process(process)
        reader.start()
        while True:
            if stop_requested():
                stopped = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            try:
                remaining_time = max(0.001, deadline - time.monotonic())
                chunk = output_queue.get(timeout=min(0.05, remaining_time))
            except Empty:
                if not reader.is_alive() and output_queue.empty():
                    break
                continue
            if chunk is _STREAM_READ_FAILED:
                stream_failed = True
                break
            if chunk is None:
                break
            if not isinstance(chunk, str):
                stream_failed = True
                break
            remaining_chars = GIT_STATUS_MAX_RAW_CHARS - used
            if len(chunk) >= remaining_chars:
                if remaining_chars > 0:
                    chunks.append(chunk[:remaining_chars])
                used += max(0, remaining_chars)
                truncated = True
                break
            chunks.append(chunk)
            used += len(chunk)
        loop_completed = True
    finally:
        if (
            truncated
            or timed_out
            or stopped
            or stream_failed
            or not loop_completed
        ):
            if discard_output is not None:
                discard_output.set()
            _stop_process(process, timeout=1)
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            if discard_output is not None:
                discard_output.set()
            _stop_process(process, timeout=1)
        if isinstance(process, _SUBPROCESS_POPEN_TYPE):
            _stop_process(process, timeout=0.25)
        if discard_output is not None:
            discard_output.set()
        if reader is not None and reader.ident is not None:
            reader.join(timeout=1)
        if reader is None or not reader.is_alive():
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass
        publish_process(None)

    if stopped:
        raise RuntimeError("Stop requested.")
    if stream_failed:
        raise RuntimeError("Could not read the bounded Git status stream safely.")
    if timed_out:
        raise RuntimeError(
            f"Git status exceeded the {GIT_STATUS_TIMEOUT_SECONDS}-second controller limit."
        )
    if not truncated and process.returncode != 0:
        raise RuntimeError(
            f"Git status failed with exit code {process.returncode}."
        )
    return "".join(chunks), truncated


def _is_safe_context_file(workspace: Path, path: Path) -> bool:
    """Return whether one context source is a regular in-workspace non-secret file."""
    try:
        relative = path.relative_to(workspace)
        if (
            _path_is_link_like(path)
            or not path.is_file()
            or _path_has_ignored_part(relative)
            or _path_has_sensitive_part(relative)
        ):
            return False
        path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _path_is_link_like(path: Path) -> bool:
    """Reject symbolic, junction, and hard-linked files at trust boundaries."""
    try:
        is_junction = getattr(path, "is_junction", None)
        if path.is_symlink() or bool(callable(is_junction) and is_junction()):
            return True
        path_stat = path.stat()
        return stat_module.S_ISREG(path_stat.st_mode) and path_stat.st_nlink != 1
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _is_safe_context_directory(workspace: Path, path: Path) -> bool:
    """Return whether traversal may enter one real directory inside the workspace."""
    try:
        relative = path.relative_to(workspace)
        if (
            _path_is_link_like(path)
            or not path.is_dir()
            or _path_has_ignored_part(relative)
            or _path_has_sensitive_part(relative)
        ):
            return False
        path.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


def _collect_instruction_files(workspace: Path) -> list[Path]:
    candidates: list[Path] = []
    for name in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        root_file = workspace / name
        if _is_safe_context_file(workspace, root_file):
            candidates.append(root_file)
    nested: list[Path] = []
    pending = deque([workspace])
    inspected_directories = 0
    while pending and inspected_directories < 12_000 and len(nested) < 256:
        directory = pending.popleft()
        inspected_directories += 1
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        child_directories: list[Path] = []
        for path in entries:
            if path.name == "AGENTS.md" and _is_safe_context_file(workspace, path):
                nested.append(path)
                if len(nested) >= 256:
                    break
            elif _is_safe_context_directory(workspace, path):
                child_directories.append(path)
        pending.extend(child_directories)
    for path in nested:
        if path not in candidates:
            candidates.append(path)
    return candidates[:24]


def _project_file_index(workspace: Path) -> list[str]:
    """Build a deterministic, bounded file index without subprocess buffering."""
    paths: list[str] = []
    inspected_directories = 0
    try:
        for raw_directory, directory_names, file_names in os.walk(
            workspace,
            topdown=True,
            followlinks=False,
        ):
            inspected_directories += 1
            if inspected_directories > 12_000:
                break
            directory = Path(raw_directory)
            allowed_directories: list[str] = []
            for name in sorted(directory_names, key=str.casefold):
                candidate = directory / name
                if not _is_safe_context_directory(workspace, candidate):
                    continue
                allowed_directories.append(name)
            directory_names[:] = allowed_directories
            for name in sorted(file_names, key=str.casefold):
                path = directory / name
                relative = path.relative_to(workspace)
                if not _is_safe_context_file(workspace, path):
                    continue
                paths.append(relative.as_posix())
                if len(paths) >= 12_000:
                    return paths
    except OSError:
        return paths
    return paths


def _priority_context_files(workspace: Path, instructions: list[Path]) -> list[Path]:
    instruction_set = set(instructions)
    files: list[Path] = []
    for name in _CONTEXT_PRIORITY_NAMES:
        candidate = workspace / name
        if (
            _is_safe_context_file(workspace, candidate)
            and candidate not in instruction_set
        ):
            files.append(candidate)
    return files[:12]


def _markdown_file_section(workspace: Path, path: Path, maximum_chars: int) -> str:
    if not _is_safe_context_file(workspace, path):
        return ""
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            content = handle.read(maximum_chars)
    except OSError as exc:
        content = f"[Could not read file: {exc}]"
    suffix = path.suffix.lstrip(".") or "text"
    relative = path.relative_to(workspace).as_posix()
    return f"\n### `{relative}`\n\n```{suffix}\n{content}\n```\n"


def _path_has_ignored_part(relative: Path) -> bool:
    return any(part.casefold() in _IGNORED_DIRECTORY_NAMES for part in relative.parts)


def _path_has_sensitive_part(relative: Path) -> bool:
    """Keep credentials and private keys outside Web-visible controller context."""
    for part in relative.parts:
        normalized = part.casefold()
        if (
            normalized in _SENSITIVE_PATH_NAMES
            or normalized.startswith(".env.")
            or normalized.endswith(_SENSITIVE_PATH_SUFFIXES)
        ):
            return True
    return False


def _search_exclusion_globs() -> tuple[str, ...]:
    """Return case-insensitive command-layer exclusions for every forbidden path."""
    names = _IGNORED_DIRECTORY_NAMES | _SENSITIVE_PATH_NAMES
    patterns = {
        pattern
        for name in names
        for pattern in (
            f"!{name}",
            f"!{name}/**",
            f"!**/{name}",
            f"!**/{name}/**",
        )
    }
    patterns.update({"!.env.*", "!**/.env.*"})
    for suffix in _SENSITIVE_PATH_SUFFIXES:
        patterns.update({f"!*{suffix}", f"!**/*{suffix}"})
    return tuple(sorted(patterns, key=str.casefold))


def _search_include_globs(
    glob: str,
    root: Path,
    workspace: Path,
) -> tuple[str, ...]:
    """Translate controller glob candidates into conservative rg include globs."""
    if not glob:
        return ()
    normalized = (
        glob.replace("\\", "/")
        if is_windows_host()
        else glob.replace("\\", "\\\\")
    )
    patterns = {normalized}
    if root.is_dir():
        try:
            root_relative = root.relative_to(workspace).as_posix()
        except ValueError:
            root_relative = "."
        if root_relative not in {"", "."}:
            patterns.add(f"{root_relative}/{normalized}")
    return tuple(sorted(patterns, key=str.casefold))


def _queue_text_lines(
    stream: Any,
    output: Queue[Any],
    discard: Event,
) -> None:
    """Drain a text stream into a bounded queue without retaining excess output."""
    terminal_event: object | None = None
    try:
        for line in stream:
            while not discard.is_set():
                try:
                    output.put(line, timeout=0.05)
                    break
                except Full:
                    continue
            if discard.is_set():
                break
    except (OSError, UnicodeError, ValueError):
        terminal_event = _STREAM_READ_FAILED
    finally:
        while not discard.is_set():
            try:
                output.put(terminal_event, timeout=0.05)
                break
            except Full:
                continue


def _queue_text_chunks(
    stream: Any,
    output: Queue[Any],
    discard: Event,
) -> None:
    """Drain fixed-size text chunks into a bounded queue."""
    terminal_event: object | None = None
    try:
        while not discard.is_set():
            chunk = stream.read(4_096)
            if not chunk:
                break
            while not discard.is_set():
                try:
                    output.put(chunk, timeout=0.05)
                    break
                except Full:
                    continue
    except (OSError, UnicodeError, ValueError):
        terminal_event = _STREAM_READ_FAILED
    finally:
        while not discard.is_set():
            try:
                output.put(terminal_event, timeout=0.05)
                break
            except Full:
                continue


def _bounded_verification_process_output(
    process: subprocess.Popen[str],
    *,
    timeout_seconds: int,
    should_stop: Callable[[], bool],
) -> tuple[str, int, bool, bool, bool]:
    """Drain one verification process with fixed memory, time, and Stop bounds."""
    if process.stdout is None:
        _stop_process(process, timeout=1)
        raise RuntimeError("Verification could not open a bounded output stream.")

    chunks: list[str] = []
    retained_characters = 0
    truncated = False
    stopped = False
    timed_out = False
    stream_failed = False
    stream_done = False
    loop_completed = False
    discard_output: Event | None = None
    reader: Thread | None = None
    deadline = time.monotonic() + timeout_seconds
    try:
        output_queue: Queue[Any] = Queue(maxsize=RUN_OUTPUT_QUEUE_SIZE)
        discard_output = Event()
        reader = Thread(
            target=_queue_text_chunks,
            args=(process.stdout, output_queue, discard_output),
            daemon=True,
        )
        reader.start()
        while True:
            if should_stop():
                stopped = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            if stream_done:
                if process.poll() is not None:
                    break
                time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
                continue
            try:
                remaining_time = max(0.001, deadline - time.monotonic())
                value = output_queue.get(timeout=min(0.05, remaining_time))
            except Empty:
                if not reader.is_alive() and output_queue.empty():
                    stream_done = True
                continue
            if value is _STREAM_READ_FAILED:
                stream_failed = True
                break
            if value is None:
                stream_done = True
                continue
            if not isinstance(value, str):
                stream_failed = True
                break
            remaining_characters = MAX_ACTION_OUTPUT_CHARS - retained_characters
            if remaining_characters > 0:
                retained = value[:remaining_characters]
                chunks.append(retained)
                retained_characters += len(retained)
            if len(value) > remaining_characters:
                truncated = True
        loop_completed = True
    finally:
        if stopped or timed_out or stream_failed or not loop_completed:
            if discard_output is not None:
                discard_output.set()
            _stop_process(process, timeout=1)
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            if discard_output is not None:
                discard_output.set()
            _stop_process(process, timeout=1)
        if isinstance(process, _SUBPROCESS_POPEN_TYPE):
            _stop_process(process, timeout=0.25)
        if discard_output is not None:
            discard_output.set()
        if reader is not None and reader.ident is not None:
            reader.join(timeout=1)
        if reader is None or not reader.is_alive():
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass

    if stream_failed:
        raise RuntimeError("Verification output could not be read safely.")
    output = "".join(chunks)
    if truncated:
        marker = f"\n[output truncated at {MAX_ACTION_OUTPUT_CHARS:,} characters]"
        output = output[: max(0, MAX_ACTION_OUTPUT_CHARS - len(marker))] + marker
    returncode = process.returncode if isinstance(process.returncode, int) else -1
    return output, returncode, truncated, stopped, timed_out


def _bounded_devnull_process(
    command: list[str],
    *,
    workspace: Path,
    timeout_seconds: float,
    should_stop: Callable[[], bool],
    process_changed: Callable[[subprocess.Popen[str] | None], None],
) -> tuple[int, bool, bool]:
    """Run one no-output check with bounded time, Stop, and process cleanup."""
    try:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_process_group_options(),
        )
    except OSError as exc:
        raise RuntimeError("Verification process could not be started.") from exc

    stopped = False
    timed_out = False
    loop_completed = False
    deadline = time.monotonic() + timeout_seconds
    try:
        process_changed(process)
        while process.poll() is None:
            if should_stop():
                stopped = True
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
        loop_completed = True
    finally:
        if stopped or timed_out or not loop_completed:
            _stop_process(process, timeout=1)
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            _stop_process(process, timeout=1)
        if isinstance(process, _SUBPROCESS_POPEN_TYPE):
            _stop_process(process, timeout=0.25)
        process_changed(None)

    returncode = process.returncode if isinstance(process.returncode, int) else -1
    return returncode, stopped, timed_out


def _discard_text_stream(stream: Any) -> None:
    """Drain subprocess diagnostics without exposing or retaining path-bearing text."""
    try:
        for _chunk in iter(lambda: stream.read(4_096), ""):
            pass
    except (OSError, ValueError):
        return


def _path_matches_search_glob(
    path: Path,
    root: Path,
    glob: str,
    *,
    workspace: Path,
) -> bool:
    """Match glob against basename, workspace-relative path, and root-relative path."""
    if not glob:
        return True
    normalized_glob = glob.replace("\\", "/") if is_windows_host() else glob
    candidates = [path.name]
    try:
        workspace_relative = path.relative_to(workspace).as_posix()
        if workspace_relative not in candidates:
            candidates.append(workspace_relative)
    except ValueError:
        pass
    if not root.is_file():
        try:
            root_relative = path.relative_to(root).as_posix()
            if root_relative not in candidates:
                candidates.append(root_relative)
        except ValueError:
            pass
    translated_glob = translate_glob(
        normalized_glob,
        recursive=True,
        include_hidden=True,
        seps="/",
    )
    flags = re.IGNORECASE if is_windows_host() else 0
    return any(
        re.fullmatch(translated_glob, candidate, flags=flags) is not None
        for candidate in candidates
    )


def _is_confined_search_match(
    workspace: Path,
    root: Path,
    relative_path: Path,
) -> bool:
    """Confirm an rg-reported file resolves inside both workspace and search root."""
    candidate = workspace / relative_path
    try:
        current = workspace
        for part in relative_path.parts:
            current /= part
            if _path_is_link_like(current):
                return False
        if not candidate.is_file():
            return False
        resolved_candidate = candidate.resolve(strict=True)
        resolved_workspace = workspace.resolve(strict=True)
        resolved_relative = resolved_candidate.relative_to(resolved_workspace)
        if (
            _path_has_ignored_part(resolved_relative)
            or _path_has_sensitive_part(resolved_relative)
        ):
            return False
        resolved_root = root.resolve(strict=True)
        if root.is_file():
            return resolved_candidate == resolved_root
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return False
    return True


def _parse_rg_search_match(value: str) -> tuple[Path, str] | None:
    """Parse one structured ripgrep match in fallback-compatible form."""
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("type") != "match":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    path_data = data.get("path")
    lines_data = data.get("lines")
    line_number = data.get("line_number")
    if (
        not isinstance(path_data, dict)
        or not isinstance(lines_data, dict)
        or not isinstance(path_data.get("text"), str)
        or not isinstance(lines_data.get("text"), str)
        or not isinstance(line_number, int)
        or isinstance(line_number, bool)
        or line_number < 1
    ):
        return None
    raw_path = path_data["text"]
    if not raw_path.strip() or any(character in raw_path for character in "\x00\r\n"):
        return None
    native_path = raw_path.replace("\\", "/") if is_windows_host() else raw_path
    relative = Path(native_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    normalized_path = relative.as_posix()
    if normalized_path in {"", "."}:
        return None
    line_text = _truncate_search_match_text(lines_data["text"].rstrip("\r\n"))
    return relative, f"{normalized_path}:{line_number}:{line_text}"


def _truncate_search_match_text(value: str) -> str:
    """Bound one search line without introducing a second observation line."""
    if len(value) <= SEARCH_MAX_MATCH_TEXT_CHARS:
        return value
    omitted = len(value) - SEARCH_MAX_MATCH_TEXT_CHARS
    return (
        value[:SEARCH_MAX_MATCH_TEXT_CHARS]
        + f" [truncated {omitted:,} characters]"
    )


def _fallback_search_matches(
    *,
    workspace: Path,
    root: Path,
    query: str,
    glob: str,
    max_results: int,
    should_stop: Callable[[], bool] | None = None,
) -> list[str]:
    """Search text files in Python when ripgrep is unavailable to the service."""
    matches: list[str] = []
    inspected_files = 0
    deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
    try:
        root_is_file = root.is_file()
        candidates = (root,) if root_is_file else root.rglob("*")
        for path in candidates:
            if callable(should_stop) and should_stop():
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Search exceeded the {SEARCH_TIMEOUT_SECONDS}-second controller limit."
                )
            if inspected_files >= 12_000 or len(matches) >= max_results:
                break
            try:
                relative_to_workspace = path.relative_to(workspace)
                if (
                    _path_has_ignored_part(relative_to_workspace)
                    or _path_has_sensitive_part(relative_to_workspace)
                    or not _is_confined_search_match(
                        workspace,
                        root,
                        relative_to_workspace,
                    )
                    or path.stat().st_size > SEARCH_MAX_FILE_BYTES
                ):
                    continue
            except (OSError, ValueError):
                continue

            if not _path_matches_search_glob(path, root, glob, workspace=workspace):
                continue

            inspected_files += 1
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if callable(should_stop) and should_stop():
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        f"Search exceeded the {SEARCH_TIMEOUT_SECONDS}-second controller limit."
                    )
                if query not in line:
                    continue
                relative = path.relative_to(workspace).as_posix()
                matches.append(
                    f"{relative}:{line_number}:{_truncate_search_match_text(line)}"
                )
                if len(matches) >= max_results:
                    break
    except OSError:
        return matches
    return matches


_FENCED_JSON_RE = re.compile(
    r"```json\s*\n(.*?)\n\s*```", re.DOTALL
)
_PRE_CODE_RE = re.compile(
    r"<pre>\s*<code(?:\s[^>]*)?>(.*?)</code>\s*</pre>", re.DOTALL | re.IGNORECASE
)


def _mask_regions(text: str, regions: list[tuple[int, int]]) -> str:
    """Replace selected spans with spaces so raw_decode cannot repair them."""
    if not regions:
        return text
    chars = list(text)
    for start, end in regions:
        for index in range(max(0, start), min(len(chars), end)):
            chars[index] = " "
    return "".join(chars)


def parse_agent_action(response: str) -> dict[str, Any]:
    """Parse one JSON controller action across provider formatting variants.

    Collect valid candidates from the whole response in document order:
    1. Literal ```json fences (never repaired on JSONDecodeError).
    2. Literal <pre><code> blocks (never repaired on JSONDecodeError).
    3. Strict json.loads on the remaining response.
    4. raw_decode scanning of the remaining response.

    Same-action duplicates keep the final candidate. Different actions reject.
    """
    text = str(response or "").strip()
    if len(text) > MAX_ACTION_JSON_CHARS:
        raise ValueError("The Web provider returned an action that exceeds the controller limit.")

    ordered: list[tuple[int, dict[str, Any]]] = []
    candidate_signatures: set[str] = set()
    decoder = json.JSONDecoder()
    masked_regions: list[tuple[int, int]] = []
    malformed_fenced = False

    def register(payload: Any, position: int) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("action"), str):
            return
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if signature not in candidate_signatures:
            candidate_signatures.add(signature)
            ordered.append((position, payload))

    def resolve_candidates() -> dict[str, Any]:
        candidates = [payload for _position, payload in sorted(ordered, key=lambda item: item[0])]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            action_names = {
                str(candidate.get("action") or "").strip().lower() for candidate in candidates
            }
            if len(action_names) == 1:
                LOGGER.warning(
                    "The Web provider returned %s same-action controller candidates; using the final candidate.",
                    len(candidates),
                )
                return candidates[-1]
            raise ValueError("The Web provider returned more than one JSON controller action.")
        if malformed_fenced:
            raise ValueError(
                "The Web provider returned a fenced JSON block that is not valid strict JSON. "
                "Use replace_base64 or write_base64 for content containing HTML quotes or backslashes."
            )
        raise ValueError("The Web provider must return exactly one JSON controller action.")

    for match in _FENCED_JSON_RE.finditer(text):
        masked_regions.append((match.start(), match.end()))
        try:
            register(json.loads(match.group(1).strip()), match.start())
        except json.JSONDecodeError:
            malformed_fenced = True

    for match in _PRE_CODE_RE.finditer(text):
        masked_regions.append((match.start(), match.end()))
        try:
            register(json.loads(match.group(1).strip()), match.start())
        except json.JSONDecodeError:
            pass

    remainder = _mask_regions(text, masked_regions)
    try:
        register(json.loads(remainder.strip()), 0)
    except json.JSONDecodeError:
        cursor = 0
        while cursor < len(remainder):
            start = remainder.find("{", cursor)
            if start < 0:
                break
            try:
                payload, end = decoder.raw_decode(remainder, start)
            except json.JSONDecodeError:
                cursor = start + 1
                continue
            register(payload, start)
            cursor = end

    return resolve_candidates()


def _decode_base64_utf8(
    value: str,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> str:
    """Decode one controller base64 field with strict validation and a size cap."""
    raw = str(value or "")
    if not raw:
        if allow_empty:
            return ""
        raise ValueError(f"The {field_name} field requires non-empty base64.")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Invalid base64 encoding in {field_name}.") from exc
    if len(decoded) > MAX_BASE64_DECODED_BYTES:
        raise ValueError(f"Decoded {field_name} exceeds the controller size limit.")
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Decoded {field_name} is not valid UTF-8.") from exc



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
            "replace_base64": self._replace_base64,
            "write": self._write,
            "write_base64": self._write_base64,
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
        lexical = candidate.expanduser() if candidate.is_absolute() else self.workspace / candidate
        try:
            lexical_relative = lexical.relative_to(self.workspace)
        except ValueError:
            lexical_relative = Path()
        if ".." in lexical_relative.parts:
            raise ValueError("Controller paths must stay inside the selected project.")
        current = self.workspace
        for part in lexical_relative.parts:
            current /= part
            if _path_is_link_like(current):
                raise ValueError(
                    "Controller paths cannot traverse linked files or directories."
                )
            if not current.exists():
                break
        if candidate.is_absolute():
            resolved = candidate.expanduser().resolve(strict=not allow_missing)
        else:
            resolved = (self.workspace / candidate).resolve(strict=not allow_missing)
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Controller paths must stay inside the selected project.") from exc
        relative = resolved.relative_to(self.workspace)
        if any(
            part.casefold() in {".git", ".computer-use-agent"}
            for part in relative.parts
        ):
            raise ValueError("Controller access to internal metadata is not allowed.")
        if _path_has_sensitive_part(relative):
            raise ValueError(
                "Controller access to credentials and private-key files is not allowed."
            )
        return resolved

    def _list(self, payload: dict[str, Any]) -> dict[str, Any]:
        root = self._resolve_path(payload.get("path", "."))
        if not root.is_dir():
            raise ValueError("The list action requires a directory.")
        depth = max(1, min(6, int(payload.get("depth", 2))))
        rows: list[str] = []
        pending = deque([(root, 0)])
        inspected_directories = 0
        scan_truncated = False
        while pending and len(rows) < 2_000:
            directory, directory_depth = pending.popleft()
            inspected_directories += 1
            if inspected_directories > 12_000:
                scan_truncated = True
                break
            try:
                entries = sorted(
                    directory.iterdir(),
                    key=lambda item: item.name.casefold(),
                )
            except OSError:
                continue
            for path in entries:
                relative_to_workspace = path.relative_to(self.workspace)
                if (
                    _path_has_ignored_part(relative_to_workspace)
                    or _path_has_sensitive_part(relative_to_workspace)
                    or _path_is_link_like(path)
                ):
                    continue
                if _is_safe_context_directory(self.workspace, path):
                    rows.append(relative_to_workspace.as_posix() + "/")
                    if directory_depth + 1 < depth:
                        pending.append((path, directory_depth + 1))
                elif _is_safe_context_file(self.workspace, path):
                    rows.append(relative_to_workspace.as_posix())
                if len(rows) >= 2_000:
                    scan_truncated = True
                    break
        rows.sort(key=str.casefold)
        return {
            "ok": True,
            "action": "list",
            "entries": rows,
            "truncated": scan_truncated or bool(pending),
        }

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
        if (
            len(query) > MAX_SEARCH_QUERY_CHARS
            or "\x00" in query
            or "\n" in query
            or "\r" in query
        ):
            raise ValueError(
                "The search query is invalid or exceeds the controller limit."
            )
        root = self._resolve_path(payload.get("path", "."))
        max_results = max(1, min(300, int(payload.get("max_results", 80))))
        glob = str(payload.get("glob") or "").strip()
        if len(glob) > 1_000 or "\x00" in glob or "\n" in glob or "\r" in glob:
            raise ValueError("The search glob is invalid or exceeds the controller limit.")
        if glob.startswith("!"):
            raise ValueError("The search glob must be an inclusive pattern.")
        if any(character in glob for character in "{}[]"):
            raise ValueError(
                "The search glob supports literals, path separators, *, ?, and ** only."
            )
        ripgrep = _trusted_system_executable("rg", forbidden_root=self.workspace)
        if ripgrep is None:
            matches = _fallback_search_matches(
                workspace=self.workspace,
                root=root,
                query=query,
                glob=glob,
                max_results=max_results,
                should_stop=self.should_stop,
            )
            if self.should_stop():
                return {
                    "ok": False,
                    "action": "search",
                    "stopped": True,
                    "error": "Stop requested.",
                }
            return {
                "ok": True,
                "action": "search",
                "matches": matches,
                "truncated": len(matches) >= max_results,
                "engine": "python-fallback",
            }
        command = [
            str(ripgrep),
            "--no-config",
            "--json",
            "--line-number",
            "--with-filename",
            "--fixed-strings",
            "--color",
            "never",
            "--hidden",
            "--no-ignore",
            "--no-follow",
            "--no-messages",
            "--max-count",
            str(max_results),
            "--max-filesize",
            str(SEARCH_MAX_FILE_BYTES),
        ]
        include_glob_option = "--iglob" if is_windows_host() else "--glob"
        for included_glob in _search_include_globs(glob, root, self.workspace):
            command.extend([include_glob_option, included_glob])
        for excluded_glob in _search_exclusion_globs():
            command.extend(["--iglob", excluded_glob])
        command.extend(["--", query, str(root.relative_to(self.workspace) or ".")])
        if self.should_stop():
            return {
                "ok": False,
                "action": "search",
                "stopped": True,
                "error": "Stop requested.",
            }
        try:
            process = subprocess.Popen(
                command,
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_process_group_options(),
            )
        except FileNotFoundError:
            matches = _fallback_search_matches(
                workspace=self.workspace,
                root=root,
                query=query,
                glob=glob,
                max_results=max_results,
                should_stop=self.should_stop,
            )
            if self.should_stop():
                return {
                    "ok": False,
                    "action": "search",
                    "stopped": True,
                    "error": "Stop requested.",
                }
            return {
                "ok": True,
                "action": "search",
                "matches": matches,
                "truncated": len(matches) >= max_results,
                "engine": "python-fallback",
            }

        if process.stdout is None or process.stderr is None:
            _stop_process(process, timeout=1)
            raise RuntimeError("Search could not open bounded ripgrep output streams.")
        matches: list[str] = []
        raw_events = 0
        truncated = False
        stopped = False
        timed_out = False
        stream_failed = False
        terminated_early = False
        loop_completed = False
        discard_output: Event | None = None
        stdout_thread: Thread | None = None
        stderr_thread: Thread | None = None
        deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
        try:
            output_queue: Queue[Any] = Queue(maxsize=SEARCH_STDOUT_QUEUE_SIZE)
            discard_output = Event()
            stdout_thread = Thread(
                target=_queue_text_lines,
                args=(process.stdout, output_queue, discard_output),
                daemon=True,
            )
            stderr_thread = Thread(
                target=_discard_text_stream,
                args=(process.stderr,),
                daemon=True,
            )
            self.process_changed(process)
            stdout_thread.start()
            stderr_thread.start()
            while True:
                if self.should_stop():
                    stopped = True
                    terminated_early = True
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    terminated_early = True
                    break
                try:
                    remaining = max(0.001, deadline - time.monotonic())
                    value = output_queue.get(timeout=min(0.05, remaining))
                except Empty:
                    if not stdout_thread.is_alive() and output_queue.empty():
                        break
                    continue
                if value is _STREAM_READ_FAILED:
                    stream_failed = True
                    terminated_early = True
                    break
                if value is None:
                    break
                if not isinstance(value, str):
                    stream_failed = True
                    terminated_early = True
                    break
                raw_events += 1
                if raw_events > SEARCH_MAX_RAW_EVENTS:
                    truncated = True
                    terminated_early = True
                    break
                normalized = _parse_rg_search_match(value)
                if normalized is None:
                    continue
                relative_path, normalized_value = normalized
                candidate_path = self.workspace / relative_path
                if (
                    _path_has_ignored_part(relative_path)
                    or _path_has_sensitive_part(relative_path)
                ):
                    continue
                try:
                    if root.is_file():
                        if candidate_path != root:
                            continue
                    else:
                        candidate_path.relative_to(root)
                except ValueError:
                    continue
                if (
                    not _path_matches_search_glob(
                        candidate_path,
                        root,
                        glob,
                        workspace=self.workspace,
                    )
                    or not _is_confined_search_match(
                        self.workspace,
                        root,
                        relative_path,
                    )
                ):
                    continue
                matches.append(normalized_value)
                if len(matches) >= max_results:
                    truncated = True
                    terminated_early = True
                    break
            loop_completed = True
        finally:
            if terminated_early or stream_failed or not loop_completed:
                if discard_output is not None:
                    discard_output.set()
                _stop_process(process, timeout=1)
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                if discard_output is not None:
                    discard_output.set()
                _stop_process(process, timeout=1)
            if isinstance(process, _SUBPROCESS_POPEN_TYPE):
                _stop_process(process, timeout=0.25)
            if discard_output is not None:
                discard_output.set()
            if stdout_thread is not None and stdout_thread.ident is not None:
                stdout_thread.join(timeout=1)
            if stderr_thread is not None and stderr_thread.ident is not None:
                stderr_thread.join(timeout=1)
            streams_and_readers = (
                (process.stdout, stdout_thread),
                (process.stderr, stderr_thread),
            )
            for stream, reader_thread in streams_and_readers:
                if reader_thread is not None and reader_thread.is_alive():
                    continue
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            self.process_changed(None)

        if stopped:
            return {
                "ok": False,
                "action": "search",
                "stopped": True,
                "error": "Stop requested.",
            }
        if timed_out:
            raise RuntimeError(
                f"Search exceeded the {SEARCH_TIMEOUT_SECONDS}-second controller limit."
            )
        if stream_failed:
            raise RuntimeError("Search output could not be read safely.")
        if not terminated_early and process.returncode not in {0, 1}:
            raise RuntimeError(
                f"Search failed with ripgrep exit code {process.returncode}."
            )
        return {
            "ok": True,
            "action": "search",
            "matches": matches,
            "truncated": truncated,
            "engine": "rg",
        }

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

    def _replace_base64(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Replace with base64-encoded old/new to avoid HTML quote corruption."""
        path = self._resolve_path(payload.get("path"))
        if not path.is_file():
            raise ValueError("The replace_base64 action requires an existing file.")
        old = _decode_base64_utf8(
            str(payload.get("old_base64") or ""),
            field_name="old_base64",
            allow_empty=False,
        )
        if not old:
            raise ValueError("The replace_base64 action requires non-empty old text.")
        new = _decode_base64_utf8(
            str(payload.get("new_base64") or ""),
            field_name="new_base64",
            allow_empty=True,
        )
        source = path.read_text(encoding="utf-8")
        occurrences = source.count(old)
        if occurrences != 1:
            raise ValueError(f"Replace text must appear exactly once; found {occurrences:,} occurrences.")
        path.write_text(source.replace(old, new, 1), encoding="utf-8")
        self.state.edit_generation += 1
        return {
            "ok": True,
            "action": "replace_base64",
            "path": path.relative_to(self.workspace).as_posix(),
            "changed_characters": len(new) - len(old),
        }

    def _write_base64(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write a new file with base64-encoded content to avoid quote corruption."""
        path = self._resolve_path(payload.get("path"), allow_missing=True)
        if path.exists():
            raise ValueError("The write_base64 action creates new files only; use replace_base64 for an existing file.")
        content = _decode_base64_utf8(
            str(payload.get("content_base64") or ""),
            field_name="content_base64",
            allow_empty=False,
        )
        if not content:
            raise ValueError("The write_base64 action requires non-empty decoded content.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.state.edit_generation += 1
        return {
            "ok": True,
            "action": "write_base64",
            "path": path.relative_to(self.workspace).as_posix(),
            "bytes": path.stat().st_size,
        }

    def _run(self, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()
        command_parts = inspection_command_parts(command, workspace=self.workspace)
        if command_parts[:2] == ["git", "status"]:
            started = time.monotonic()
            try:
                output = _filtered_git_status(
                    self.workspace,
                    should_stop=self.should_stop,
                    process_changed=self.process_changed,
                )
            except RuntimeError:
                if self.should_stop():
                    return {
                        "ok": False,
                        "action": "run",
                        "stopped": True,
                        "error": "Stop requested.",
                    }
                raise
            return {
                "ok": True,
                "action": "run",
                "exit_code": 0,
                "duration_seconds": round(time.monotonic() - started, 2),
                "output": _truncate_text(output, MAX_ACTION_OUTPUT_CHARS),
                "mutated_workspace": False,
                "error": "",
            }
        before_fingerprint, before_scan_complete = (
            _workspace_mutation_fingerprint(
                self.workspace,
                should_stop=self.should_stop,
            )
        )
        if self.should_stop():
            return {
                "ok": False,
                "action": "run",
                "stopped": True,
                "error": "Stop requested.",
            }
        if not before_scan_complete:
            raise RuntimeError(
                "The verification command was not started because the controller could not "
                "create a complete bounded workspace fingerprint. Narrow the selected "
                "workspace before continuing."
            )
        started = time.monotonic()
        process = subprocess.Popen(
            command_parts,
            cwd=self.workspace,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            **_process_group_options(),
        )
        output = ""
        returncode = -1
        output_truncated = False
        stopped = False
        timed_out = False
        run_error: OSError | RuntimeError | ValueError | None = None
        try:
            self.process_changed(process)
            output, returncode, output_truncated, stopped, timed_out = (
                _bounded_verification_process_output(
                    process,
                    timeout_seconds=self.settings.command_timeout_seconds,
                    should_stop=self.should_stop,
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            run_error = exc
        finally:
            self.process_changed(None)
        after_fingerprint, after_scan_complete = (
            _workspace_mutation_fingerprint(
                self.workspace,
                should_stop=self.should_stop,
            )
        )
        workspace_scan_complete = before_scan_complete and after_scan_complete
        mutated_workspace = after_fingerprint != before_fingerprint
        if mutated_workspace or not workspace_scan_complete:
            self.state.edit_generation += 1
        elif run_error is None and not stopped and not timed_out and returncode == 0:
            self.state.verification_generation = self.state.edit_generation
            self.state.successful_checks.append(command)
        if run_error is not None:
            raise run_error
        if stopped:
            return {
                "ok": False,
                "action": "run",
                "stopped": True,
                "error": "Stop requested.",
                "output": output,
                "output_truncated": output_truncated,
                "mutated_workspace": mutated_workspace,
                "workspace_scan_complete": workspace_scan_complete,
            }
        if timed_out:
            raise RuntimeError(
                f"Command timed out after {self.settings.command_timeout_seconds:,} seconds.\n"
                + output
            )
        return {
            "ok": returncode == 0 and not mutated_workspace and workspace_scan_complete,
            "action": "run",
            "exit_code": returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "output": output,
            "output_truncated": output_truncated,
            "mutated_workspace": mutated_workspace,
            "workspace_scan_complete": workspace_scan_complete,
            "error": (
                "The verification command changed project files; the prior bodycheck is stale. "
                "Inspect those changes before continuing."
                if mutated_workspace
                else (
                    "The controller could not prove that the verification command left the "
                    "project unchanged within its bounded workspace scan; the prior bodycheck "
                    "is stale. Narrow the selected workspace before continuing."
                    if not workspace_scan_complete
                    else ""
                )
            ),
        }

    def _bodycheck(self, _payload: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        if (self.workspace / ".git").exists():
            try:
                status = _filtered_git_status(
                    self.workspace,
                    should_stop=self.should_stop,
                    process_changed=self.process_changed,
                )
            except RuntimeError:
                if self.should_stop():
                    return {
                        "ok": False,
                        "action": "bodycheck",
                        "stopped": True,
                        "error": "Stop requested.",
                    }
                raise
            git = _trusted_system_executable("git", forbidden_root=self.workspace)
            if git is None:
                raise RuntimeError("Git is unavailable for bounded diff inspection.")
            diff_returncode, diff_stopped, diff_check_timed_out = (
                _bounded_devnull_process(
                    [
                        str(git),
                        "-c",
                        "core.fsmonitor=false",
                        "-c",
                        "core.untrackedCache=false",
                        "diff",
                        "--check",
                    ],
                    workspace=self.workspace,
                    timeout_seconds=30,
                    should_stop=self.should_stop,
                    process_changed=self.process_changed,
                )
            )
            if diff_stopped:
                return {
                    "ok": False,
                    "action": "bodycheck",
                    "stopped": True,
                    "error": "Stop requested.",
                }
            diff_check_ok = diff_returncode == 0 and not diff_check_timed_out
            checks.append({"name": "git status --short", "ok": True, "output": _truncate_text(status, 16_000)})
            checks.append(
                {
                    "name": "git diff --check",
                    "ok": diff_check_ok,
                    "output": (
                        ""
                        if diff_check_ok
                        else (
                            "Git diff checking exceeded the 30-second controller limit."
                            if diff_check_timed_out
                            else "Git found whitespace errors in the current project diff."
                        )
                    ),
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
            "verification_current": self.state.verification_current,
            "successful_checks": self.state.successful_checks[-20:],
            "instruction_files": instructions,
            "checks": checks,
        }


def _workspace_mutation_fingerprint(
    workspace: Path,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[str, bool]:
    """Return a bounded content fingerprint and whether its scan was complete."""
    digest = hashlib.sha256()
    inspected_files = 0
    inspected_directories = 0
    inspected_bytes = 0
    pending = deque([workspace])
    deadline = time.monotonic() + WORKSPACE_FINGERPRINT_TIMEOUT_SECONDS
    stop_requested = should_stop or (lambda: False)
    try:
        resolved_workspace = workspace.resolve(strict=True)
    except (OSError, ValueError):
        return digest.hexdigest(), False

    while pending:
        if (
            inspected_directories >= WORKSPACE_FINGERPRINT_MAX_DIRECTORIES
            or time.monotonic() >= deadline
            or stop_requested()
        ):
            return digest.hexdigest(), False
        directory = pending.popleft()
        try:
            entries = sorted(
                os.scandir(directory),
                key=lambda entry: entry.name.casefold(),
            )
        except OSError:
            return digest.hexdigest(), False
        inspected_directories += 1
        for entry in entries:
            if time.monotonic() >= deadline or stop_requested():
                return digest.hexdigest(), False
            path = Path(entry.path)
            try:
                relative = path.relative_to(workspace)
            except ValueError:
                return digest.hexdigest(), False
            if _path_has_ignored_part(relative):
                continue
            try:
                initial_stat = entry.stat(follow_symlinks=False)
            except OSError:
                return digest.hexdigest(), False
            relative_bytes = relative.as_posix().encode(
                "utf-8",
                errors="replace",
            )
            digest.update(relative_bytes)
            digest.update(
                f"\0mode:{initial_stat.st_mode}\0size:{initial_stat.st_size}\0".encode()
            )
            if stat_module.S_ISLNK(initial_stat.st_mode) or (
                stat_module.S_ISREG(initial_stat.st_mode)
                and initial_stat.st_nlink != 1
            ):
                return digest.hexdigest(), False
            if stat_module.S_ISDIR(initial_stat.st_mode) and _path_is_link_like(path):
                return digest.hexdigest(), False
            try:
                path.resolve(strict=True).relative_to(resolved_workspace)
            except (OSError, ValueError):
                return digest.hexdigest(), False
            if stat_module.S_ISDIR(initial_stat.st_mode):
                digest.update(b"directory\0")
                pending.append(path)
                continue
            if not stat_module.S_ISREG(initial_stat.st_mode):
                return digest.hexdigest(), False
            if inspected_files >= WORKSPACE_FINGERPRINT_MAX_FILES:
                return digest.hexdigest(), False
            if (
                inspected_bytes + initial_stat.st_size
                > WORKSPACE_FINGERPRINT_MAX_BYTES
            ):
                return digest.hexdigest(), False
            digest.update(b"file\0")
            try:
                with path.open("rb") as handle:
                    while True:
                        if time.monotonic() >= deadline or stop_requested():
                            return digest.hexdigest(), False
                        chunk = handle.read(64 * 1_024)
                        if not chunk:
                            break
                        digest.update(chunk)
                final_stat = path.stat()
            except OSError:
                return digest.hexdigest(), False
            if (
                initial_stat.st_dev,
                initial_stat.st_ino,
                initial_stat.st_mode,
                initial_stat.st_size,
                initial_stat.st_mtime_ns,
            ) != (
                final_stat.st_dev,
                final_stat.st_ino,
                final_stat.st_mode,
                final_stat.st_size,
                final_stat.st_mtime_ns,
            ):
                return digest.hexdigest(), False
            inspected_files += 1
            inspected_bytes += initial_stat.st_size

    digest.update(
        (
            f"files:{inspected_files}\0directories:{inspected_directories}"
            f"\0bytes:{inspected_bytes}"
        ).encode()
    )
    return digest.hexdigest(), True


def _inspection_argument_path_value(argument: str) -> str:
    value = str(argument or "").strip()
    if value.startswith("-") and "=" in value:
        value = value.split("=", 1)[1].strip()
    return value.split("::", 1)[0]


def _ruff_subcommand(arguments: list[str]) -> str:
    """Return Ruff's subcommand after the small approved global-option subset."""
    index = 0
    value_options = {"--config", "--cache-dir"}
    standalone_options = {
        "--isolated",
        "--no-cache",
        "--quiet",
        "--silent",
        "--verbose",
    }
    while index < len(arguments):
        normalized = arguments[index].casefold()
        if normalized in standalone_options:
            index += 1
            continue
        if normalized in value_options:
            index += 2
            continue
        if any(normalized.startswith(f"{option}=") for option in value_options):
            index += 1
            continue
        return normalized
    return ""


def _portable_executable_names(value: str) -> tuple[str, str]:
    """Return the portable filename and normalized tool name for one argv token."""
    executable_name = value.replace("\\", "/").rsplit("/", 1)[-1]
    if not executable_name:
        raise ValueError("Run requires a named executable.")
    executable = (
        executable_name[:-4]
        if executable_name.casefold().endswith(".exe")
        else executable_name
    )
    return executable_name, executable.casefold()


def _trusted_system_executable(
    executable_name: str,
    *,
    forbidden_root: Path | None = None,
) -> Path | None:
    """Resolve one PATH tool once so workspace cwd cannot replace it at launch."""
    located = shutil.which(executable_name)
    if not located:
        return None
    try:
        resolved = Path(located).resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_file():
        return None
    if forbidden_root is not None:
        try:
            resolved.relative_to(forbidden_root.resolve(strict=True))
        except (OSError, ValueError):
            pass
        else:
            return None
    return resolved


def _trusted_windows_taskkill() -> Path | None:
    """Resolve taskkill only from the Windows system directory."""
    system_root = os.environ.get("SystemRoot", "").strip()
    if not system_root:
        return None
    try:
        candidate = (Path(system_root) / "System32" / "taskkill.exe").resolve(
            strict=True
        )
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _canonical_inspection_executable(
    token: str,
    executable_name: str,
    workspace: Path | None,
    *,
    trusted_override: Path | None = None,
) -> str:
    """Return a trusted absolute executable and reject basename path aliases."""
    trusted = trusted_override or _trusted_system_executable(
        executable_name, forbidden_root=workspace
    )
    if trusted is None:
        raise ValueError(
            f"The approved verification executable {executable_name} is unavailable."
        )
    portable_token = token.replace("\\", "/")
    if "/" not in portable_token:
        return str(trusted)
    candidate = Path(portable_token)
    if not candidate.is_absolute():
        candidate = (workspace or Path.cwd()) / candidate
    try:
        if not candidate.resolve(strict=True).samefile(trusted):
            raise ValueError(
                "Run executable paths must resolve to the trusted PATH executable."
            )
    except OSError as exc:
        raise ValueError(
            "Run executable paths must resolve to the trusted PATH executable."
        ) from exc
    return str(trusted)


def _safe_workspace_script(
    token: str,
    workspace: Path | None,
) -> tuple[Path, str] | None:
    """Resolve one real non-linked verification script under workspace/scripts."""
    if workspace is None:
        return None
    portable_token = token.replace("\\", "/")
    relative = Path(portable_token)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0].casefold() != "scripts"
        or not _SAFE_SCRIPT_NAME.fullmatch(relative.name)
    ):
        return None
    try:
        resolved_workspace = workspace.resolve(strict=True)
        scripts_root = (workspace / "scripts").resolve(strict=True)
        scripts_root.relative_to(resolved_workspace)
        candidate = workspace / relative
        current = workspace
        for part in relative.parts:
            current /= part
            if _path_is_link_like(current):
                return None
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(scripts_root)
        if not candidate.is_file():
            return None
    except (OSError, ValueError):
        return None
    suffix = resolved_candidate.suffix.casefold()
    if is_windows_host():
        return (
            (resolved_candidate, "powershell")
            if suffix == ".ps1"
            else None
        )
    if suffix not in {".bash", ".py", ".sh", ".zsh"}:
        return None
    if not os.access(resolved_candidate, os.X_OK):
        return None
    return resolved_candidate, "direct"


def _validate_inspection_arguments(
    parts: list[str],
    workspace: Path | None = None,
) -> None:
    """Reject mutating flags, network targets, and paths outside the workspace."""
    _executable_name, executable = _portable_executable_names(parts[0])
    effective_tool = executable
    effective_arguments = parts[1:]
    if (
        re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable)
        or executable == "py"
    ) and len(parts) >= 3 and parts[1] == "-m":
        effective_tool = parts[2].casefold()
        effective_arguments = parts[3:]
    if effective_tool in {"eslint", "pytest"} and any(
        argument.casefold() == "-c"
        or (
            argument.casefold().startswith("-c")
            and not argument.casefold().startswith("--")
        )
        for argument in parts[1:]
    ):
        raise ValueError(
            f"Run does not allow custom {effective_tool} configuration files."
        )
    if effective_tool == "pytest" and any(
        argument.casefold() == "-o"
        or (
            argument.casefold().startswith("-o")
            and not argument.casefold().startswith("--")
        )
        or argument.casefold() == "--override-ini"
        or argument.casefold().startswith("--override-ini=")
        for argument in effective_arguments
    ):
        raise ValueError("Run does not allow pytest configuration overrides.")
    if effective_tool == "pytest" and any(
        argument.casefold() == "--pyargs"
        or argument.casefold().startswith("--pyargs=")
        or argument.casefold() == "-p"
        or (
            argument.casefold().startswith("-p")
            and not argument.casefold().startswith("--")
        )
        for argument in effective_arguments
    ):
        raise ValueError("Run does not allow pytest package or plugin loading.")
    if effective_tool == "mypy" and any(
        argument.casefold() in {"-m", "-p", "--module", "--package"}
        or argument.casefold().startswith(("--module=", "--package="))
        or (
            argument.casefold().startswith(("-m", "-p"))
            and not argument.casefold().startswith("--")
        )
        for argument in effective_arguments
    ):
        raise ValueError("Run does not allow mypy targets outside project paths.")
    if effective_tool == "compileall" and any(
        (
            argument.casefold().startswith("-i")
            and not argument.casefold().startswith("--")
        )
        or argument.casefold() == "-b"
        for argument in effective_arguments
    ):
        raise ValueError("Run does not allow unsafe compileall output or file lists.")
    if effective_tool == "cargo" and any(
        argument.casefold() == "--config"
        or argument.casefold().startswith("--config=")
        for argument in effective_arguments
    ):
        raise ValueError("Run does not allow Cargo command-line configuration overrides.")
    if effective_tool == "ruff" and any(
        argument.casefold() in {"--cache-dir", "--config"}
        or argument.casefold().startswith(("--cache-dir=", "--config="))
        for argument in effective_arguments
    ):
        raise ValueError("Run does not allow Ruff path or inline configuration overrides.")
    if effective_tool == "ruff" and _ruff_subcommand(effective_arguments) != "check":
        raise ValueError("Run allows only the non-mutating ruff check command.")
    for argument in parts[1:]:
        normalized = argument.casefold()
        if argument.startswith("@"):
            raise ValueError("Run does not allow external response files.")
        flag = normalized.split("=", 1)[0]
        if flag in _MUTATING_OR_UNBOUNDED_RUN_FLAGS:
            raise ValueError(
                f"Run does not allow the mutating or unbounded flag {flag}."
            )

        path_value = _inspection_argument_path_value(argument)
        if not path_value or path_value.startswith("-"):
            continue
        portable_value = path_value.replace("\\", "/")
        if "://" in portable_value:
            raise ValueError("Run cannot access network targets.")
        portable_path = Path(portable_value)
        if (
            portable_value.startswith(("/", "//"))
            or re.match(r"^[a-zA-Z]:/", portable_value)
            or ".." in portable_path.parts
        ):
            raise ValueError("Run arguments must stay inside the selected project.")
        if (
            any(
                part.casefold() in {".git", ".computer-use-agent"}
                for part in portable_path.parts
            )
            or _path_has_sensitive_part(portable_path)
        ):
            raise ValueError(
                "Run arguments cannot target credentials or internal Agent metadata."
            )
        if workspace is None:
            continue
        candidate = workspace / portable_value
        try:
            current = workspace
            for part in portable_path.parts:
                current /= part
                if _path_is_link_like(current):
                    raise ValueError(
                        "Run arguments cannot traverse symlinks or junctions."
                    )
                if not current.exists():
                    break
            resolved_workspace = workspace.resolve(strict=True)
            resolved_candidate = candidate.resolve(strict=False)
            resolved_relative = resolved_candidate.relative_to(resolved_workspace)
            if (
                _path_has_ignored_part(resolved_relative)
                or _path_has_sensitive_part(resolved_relative)
            ):
                raise ValueError(
                    "Run arguments cannot target credentials or internal Agent metadata."
                )
        except (OSError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("Run arguments"):
                raise
            raise ValueError(
                "Run arguments must stay inside the selected project."
            ) from exc


def _split_inspection_command(command: str) -> list[str]:
    """Split one direct command and remove Windows-only outer token quotes."""
    windows_host = is_windows_host()
    try:
        parts = shlex.split(command, posix=not windows_host)
    except ValueError as exc:
        raise ValueError("Run contains invalid shell quoting.") from exc
    if not windows_host:
        return parts
    normalized: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
            part = part[1:-1]
        if '"' in part:
            raise ValueError("Run contains unsupported Windows command quoting.")
        normalized.append(part)
    return normalized


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
    parts = _split_inspection_command(command)
    _validate_inspection_arguments(parts)


def inspection_command_parts(
    command: str,
    *,
    workspace: Path | None = None,
) -> list[str]:
    """Parse one direct command and enforce the controller executable allowlist."""
    validate_inspection_command(command)
    parts = _split_inspection_command(command)
    if not parts:
        raise ValueError("Run requires a command.")
    _validate_inspection_arguments(parts, workspace)

    executable_name, executable = _portable_executable_names(parts[0])
    arguments = parts[1:]
    python_executable = bool(
        re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable)
        or executable == "py"
    )
    if executable in _UNSAFE_WRAPPER_EXECUTABLES:
        raise ValueError("Run cannot invoke a nested shell or command interpreter.")
    safe_script = _safe_workspace_script(parts[0], workspace)
    canonical_executable = ""
    if safe_script is None:
        trusted_override: Path | None = None
        if python_executable:
            allowed_python_names = {
                "py",
                "python",
                "python3",
                f"python{sys.version_info.major}.{sys.version_info.minor}",
            }
            if executable not in allowed_python_names:
                raise ValueError(
                    "Python run actions must use the controller runtime version."
                )
            try:
                trusted_override = Path(sys.executable).resolve(strict=True)
                if workspace is not None:
                    trusted_override.relative_to(workspace.resolve(strict=True))
            except ValueError:
                pass
            except OSError as exc:
                raise ValueError(
                    "The controller Python runtime is unavailable."
                ) from exc
            else:
                if workspace is not None:
                    raise ValueError(
                        "The controller Python runtime cannot be inside the selected project."
                    )
        canonical_executable = _canonical_inspection_executable(
            parts[0],
            executable_name,
            workspace,
            trusted_override=trusted_override,
        )
    if executable == "git":
        if not arguments or arguments[0].casefold() not in _SAFE_GIT_SUBCOMMANDS:
            raise ValueError("Git run actions are limited to filtered status inspection.")
        if any(
            argument.casefold() not in _SAFE_GIT_STATUS_FLAGS
            for argument in arguments[1:]
        ):
            raise ValueError("Git status run actions contain an unsupported argument.")
        return ["git", "status", "--short"]
    if executable == "rg":
        raise ValueError(
            "Use the project-confined search action instead of running ripgrep directly."
        )
    if executable == "tsc":
        normalized_arguments = [argument.casefold() for argument in arguments]
        no_emit_positions = [
            index
            for index, argument in enumerate(normalized_arguments)
            if argument == "--noemit"
        ]
        no_emit_has_boolean_value = bool(
            no_emit_positions
            and no_emit_positions[0] + 1 < len(normalized_arguments)
            and normalized_arguments[no_emit_positions[0] + 1] in {"false", "true"}
        )
        if len(no_emit_positions) != 1 or no_emit_has_boolean_value:
            raise ValueError("TypeScript verification must use one standalone --noEmit.")
    if executable in {"pytest", "ruff", "mypy", "pyright", "eslint", "tsc"}:
        return [canonical_executable, *arguments]
    if python_executable:
        if len(arguments) < 2 or arguments[0] != "-m" or arguments[1] not in _SAFE_PYTHON_MODULES:
            raise ValueError("Python run actions must use an approved verification module.")
        return [canonical_executable, *arguments]
    if executable == "node":
        if (
            len(arguments) != 2
            or arguments[0] != "--check"
            or arguments[1].startswith("-")
        ):
            raise ValueError("Node run actions are limited to syntax checks.")
        return [canonical_executable, *arguments]
    if executable in {"npm", "pnpm", "yarn", "bun"}:
        normalized = [argument.casefold() for argument in arguments]
        if normalized == ["test"] or (
            len(arguments) >= 2
            and normalized[0] == "run"
            and _SAFE_PACKAGE_SCRIPTS.fullmatch(arguments[1])
        ):
            return [canonical_executable, *arguments]
        raise ValueError("Package-manager run actions are limited to existing check scripts.")
    if executable == "go" and arguments and arguments[0] in {"test", "vet"}:
        return [canonical_executable, *arguments]
    if executable == "cargo" and arguments and arguments[0] in {"check", "clippy", "test"}:
        return [canonical_executable, *arguments]
    if executable == "make" and arguments and all(
        _SAFE_PACKAGE_SCRIPTS.fullmatch(argument) for argument in arguments
    ):
        return [canonical_executable, *arguments]
    if safe_script is not None:
        script_path, launch_kind = safe_script
        if launch_kind == "powershell":
            powershell = _trusted_system_executable(
                "pwsh",
                forbidden_root=workspace,
            ) or _trusted_system_executable(
                "powershell",
                forbidden_root=workspace,
            )
            if powershell is None:
                raise ValueError("Windows PowerShell is required to run a .ps1 verification script.")
            return [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script_path),
                *parts[1:],
            ]
        return [str(script_path), *parts[1:]]
    raise ValueError("Run executable is outside the inspection and verification allowlist.")


def _truncate_text(value: str, maximum: int) -> str:
    text = str(value or "")
    if len(text) <= maximum:
        return text
    omitted = len(text) - maximum
    return text[:maximum] + f"\n[truncated {omitted:,} characters]"


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
    """Release one task-scoped macOS idle-sleep assertion without blocking completion."""
    if process is None:
        return
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    except Exception as exc:
        LOGGER.warning("Could not fully release the Agent idle-sleep assertion: %s", exc)


def _agent_history_key(
    conversation_url: str,
    platform: str = DEFAULT_AGENT_PLATFORM,
) -> str:
    """Return a stable in-memory key for one Web AI conversation."""
    candidate = str(conversation_url or "").strip()
    return normalize_agent_conversation_url(platform, candidate) or candidate.rstrip(
        "/"
    )


def _clean_agent_session_title(value: str, fallback: str) -> str:
    """Return a concise session title without accepting selector placeholders."""
    candidate = " ".join(str(value or "").replace("\x00", "").split())
    if candidate.casefold() in {
        "new session",
        "new session in project",
        "recent sessions",
        "recent projects",
    }:
        candidate = ""
    clean_fallback = " ".join(str(fallback or "").replace("\x00", "").split())
    return (candidate or clean_fallback)[:240]


class ComputerUseAgentService:
    """Run a fresh Web Agent action loop for one selected local project."""

    def __init__(
        self,
        settings_store: ComputerUseSettingsStore,
        runner: Callable[..., tuple[str, str, int, bool]] | None = None,
        runtime_root: Path = DEFAULT_AGENT_RUNTIME_ROOT,
        browser_opener: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._settings_store = settings_store
        self._runner = runner or run_chatgpt_web_computer_use
        self._runtime_root = runtime_root
        self._browser_opener = browser_opener or open_agent_in_browser
        self._lock = RLock()
        self._snapshot = self._load_persisted_snapshot()
        self._stop_requested = Event()
        self._resume_requested = Event()
        self._worker: Thread | None = None
        self._active_process: subprocess.Popen[str] | None = None
        self._sleep_assertion: subprocess.Popen[Any] | None = None
        self._completion_started = False
        self._conversation_histories: dict[str, list[dict[str, str]]] = {}
        self._conversation_titles: dict[str, str] = {}
        if self._snapshot.phase == "interrupted":
            with self._lock:
                self._persist_snapshot_locked()

    def _load_persisted_snapshot(self) -> AgentRunSnapshot:
        """Restore non-content run metadata and mark abandoned work as interrupted."""
        path = self._runtime_root / PERSISTED_AGENT_SNAPSHOT_FILENAME
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return AgentRunSnapshot()
        if not isinstance(payload, dict):
            return AgentRunSnapshot()
        allowed = {
            key: payload[key]
            for key in AgentRunSnapshot.__dataclass_fields__
            if key in payload
        }
        snapshot = AgentRunSnapshot(**allowed)
        if snapshot.running:
            snapshot.running = False
            snapshot.phase = "interrupted"
            snapshot.message = (
                "The previous Agent process ended before recording a final result. "
                "Continue the same Web session or start a new task."
            )
            snapshot.finished_at = utc_now()
            snapshot.bodycheck_passed = False
        return snapshot

    def _persist_snapshot_locked(self) -> None:
        """Atomically persist bounded run metadata without prompts, responses, or source text."""
        fields = (
            "running",
            "phase",
            "message",
            "conversation_url",
            "project_url",
            "session_title",
            "started_at",
            "finished_at",
            "turn_count",
            "bodycheck_passed",
            "session_mode",
            "platform",
            "browser",
            "model",
            "model_verified",
            "actual_model",
            "context_attached",
            "context_file",
            "context_bytes",
        )
        payload = {
            field_name: getattr(self._snapshot, field_name) for field_name in fields
        }
        path = self._runtime_root / PERSISTED_AGENT_SNAPSHOT_FILENAME
        temporary = path.with_suffix(".tmp")
        try:
            self._runtime_root.mkdir(parents=True, exist_ok=True)
            self._runtime_root.chmod(0o700)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.chmod(0o600)
            os.replace(temporary, path)
            path.chmod(0o600)
        except OSError as exc:
            LOGGER.warning("Could not persist bounded Agent run metadata: %s", exc)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)

    def _require_resolved_context_cleanup_locked(self) -> None:
        """Retry one recorded cleanup and block a new run while context remains."""
        raw_path = str(self._snapshot.context_file or "").strip()
        if not raw_path:
            return
        runtime_root = self._runtime_root.expanduser().resolve()
        context_path = Path(raw_path).expanduser().resolve(strict=False)
        try:
            context_path.relative_to(runtime_root)
        except ValueError as exc:
            raise RuntimeError(
                "The previous Agent context cleanup record is outside the runtime root; "
                "resolve it before starting another production run."
            ) from exc
        if context_path.name != "context.md":
            raise RuntimeError(
                "The previous Agent context cleanup record is invalid; resolve it before "
                "starting another production run."
            )
        try:
            context_path.unlink(missing_ok=True)
            context_removed = not context_path.exists()
        except OSError as exc:
            raise RuntimeError(
                f"Temporary Agent context cleanup is still pending for {context_path}."
            ) from exc
        if not context_removed:
            raise RuntimeError(
                f"Temporary Agent context cleanup is still pending for {context_path}."
            )
        try:
            context_path.parent.rmdir()
        except OSError:
            pass
        self._snapshot.context_file = ""
        self._snapshot.context_bytes = 0
        self._persist_snapshot_locked()

    def start(
        self,
        prompt: str,
        workspace_path: str,
        config: CrawlConfig,
        *,
        operating_system: str | None = None,
        platform: str | None = None,
        browser: str | None = None,
        model: str | None = None,
        session_mode: str = "new",
        conversation_url: str = "",
        project_url: str = "",
        session_title: str = "",
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
                "platform": platform or base.platform,
                "browser": browser or base.browser,
                "model": model or base.model,
            }
        )
        if candidate["platform"] != base.platform:
            candidate["target_url"] = _platform_home_url(candidate["platform"])
        settings = validate_computer_use_settings(candidate)
        host_operating_system = detect_host_operating_system()
        if settings.operating_system != host_operating_system:
            host_label = "Windows" if host_operating_system == "windows" else "macOS"
            raise RuntimeError(
                f"{settings.operating_system.title()} execution is not available on this host. "
                f"Choose {host_label} to run the task."
            )
        workspace = resolve_workspace_path(settings.workspace_path)
        normalized_session_mode = str(session_mode or "new").strip().lower()
        target_url = resolve_agent_session_target(
            normalized_session_mode,
            conversation_url,
            project_url,
            settings.platform,
        )
        clean_session_title = _clean_agent_session_title(session_title, "")

        with self._lock:
            if self._snapshot.running:
                raise RuntimeError("An Agent request is already running.")
            self._require_resolved_context_cleanup_locked()
            self._settings_store.update(settings)
            self._stop_requested.clear()
            self._resume_requested.clear()
            self._completion_started = False
            history_key = _agent_history_key(target_url, settings.platform)
            existing_history = (
                []
                if normalized_session_mode in {"new", "project_new"}
                else [dict(item) for item in self._conversation_histories.get(history_key, [])]
            )
            resolved_session_title = (
                clean_session_title
                or self._conversation_titles.get(history_key, "")
                or clean_prompt
            )
            self._snapshot = AgentRunSnapshot(
                running=True,
                phase="starting",
                message=agent_session_opening_message(
                    normalized_session_mode,
                    settings.browser.title(),
                    settings.platform,
                ),
                prompt=clean_prompt,
                workspace_path=str(workspace),
                conversation_url=target_url,
                project_url=normalize_agent_project_url(settings.platform, project_url),
                session_title=resolved_session_title,
                history=existing_history,
                started_at=utc_now(),
                session_mode=normalized_session_mode,
                platform=settings.platform,
                browser=settings.browser,
                model=settings.model,
            )
            self._persist_snapshot_locked()
            self._worker = Thread(
                target=self._run,
                args=(
                    clean_prompt,
                    workspace,
                    config,
                    settings,
                    target_url,
                    normalized_session_mode,
                    resolved_session_title,
                    bool(read_only),
                ),
                daemon=True,
            )
            self._worker.start()

    def request_stop(self) -> bool:
        with self._lock:
            if not self._snapshot.running or self._completion_started:
                return False
            self._stop_requested.set()
            self._snapshot.phase = "stopping"
            self._snapshot.message = "Stop requested. Ending the browser turn and active local command."
            self._persist_snapshot_locked()
            process = self._active_process
        if process is not None and process.poll() is None:
            _stop_process(process)
        return True

    def request_resume(self) -> bool:
        """Resume a paused Web Agent run without duplicating the outstanding submit."""
        with self._lock:
            if not self._snapshot.running or not self._snapshot.paused:
                return False
            self._resume_requested.set()
            self._snapshot.message = (
                "Resume requested. Continuing the current Web Agent turn."
            )
            self._persist_snapshot_locked()
            return True

    def _consume_resume(self) -> bool:
        """Return True once for each Resume click without leaving a sticky event."""
        if not self._resume_requested.is_set():
            return False
        self._resume_requested.clear()
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

    def _publish_run_completion(
        self,
        *,
        sleep_assertion: subprocess.Popen[Any] | None,
        context_path: Path | None,
        completion: dict[str, Any],
    ) -> None:
        """Release runtime resources, then publish running=false as the completion barrier."""
        self._set_active_process(None)
        context_removed = True
        context_cleanup_error = ""
        if context_path is not None:
            try:
                context_path.unlink(missing_ok=True)
            except OSError as exc:
                context_cleanup_error = str(exc)
            try:
                context_removed = not context_path.exists()
            except OSError as exc:
                context_removed = False
                context_cleanup_error = context_cleanup_error or str(exc)
            if context_removed:
                try:
                    context_path.parent.rmdir()
                except OSError:
                    pass
            else:
                LOGGER.warning(
                    "Temporary Agent context cleanup failed for %s: %s",
                    context_path,
                    context_cleanup_error or "the file still exists",
                )
        try:
            _stop_macos_idle_sleep_assertion(sleep_assertion)
        except Exception:
            LOGGER.exception("Unexpected failure while releasing the Agent idle-sleep assertion.")
        finally:
            self._set_sleep_assertion(None)
        with self._lock:
            for key, value in completion.items():
                if hasattr(self._snapshot, key):
                    setattr(self._snapshot, key, value)
            if context_removed:
                self._snapshot.context_file = ""
                self._snapshot.context_bytes = 0
            else:
                self._snapshot.context_file = str(context_path or "")
                if self._snapshot.context_bytes <= 0 and context_path is not None:
                    try:
                        self._snapshot.context_bytes = context_path.stat().st_size
                    except OSError:
                        self._snapshot.context_bytes = 0
                cleanup_message = (
                    "Agent task ended, but temporary context cleanup failed; "
                    f"remove {context_path} before the next production run."
                )
                self._snapshot.phase = "failed"
                self._snapshot.message = cleanup_message
                self._snapshot.last_error = "\n".join(
                    part
                    for part in (
                        self._snapshot.last_error,
                        context_cleanup_error or cleanup_message,
                    )
                    if part
                )
            self._snapshot.running = False
            self._persist_snapshot_locked()

    def _run(
        self,
        prompt: str,
        workspace: Path,
        config: CrawlConfig,
        settings: ComputerUseSettings,
        target_url: str,
        session_mode: str,
        session_title: str,
        read_only: bool,
    ) -> None:
        sleep_assertion = _start_macos_idle_sleep_assertion()
        self._set_sleep_assertion(sleep_assertion)
        context_path: Path | None = None
        completion: dict[str, Any] = {}
        try:
            run_directory = self._runtime_root / time.strftime("%Y%m%d-%H%M%S")
            context_path = run_directory / "context.md"
            self._update(
                phase="preparing",
                message="Preparing the task-scoped Markdown context bundle.",
                context_file=str(context_path),
                context_bytes=0,
            )
            context_path, context_bytes = build_context_markdown(
                workspace,
                prompt,
                settings,
                context_path,
            )
            self._update(
                phase="preparing",
                message=f"Prepared a {context_bytes:,}-byte Markdown context bundle.",
                context_file=str(context_path),
                context_bytes=context_bytes,
            )
            if self._stop_requested.is_set():
                response, conversation_url, turn_count, bodycheck_passed = (
                    "",
                    target_url,
                    0,
                    False,
                )
            else:
                response, conversation_url, turn_count, bodycheck_passed = self._runner(
                    prompt=prompt,
                    workspace=workspace,
                    context_path=context_path,
                    config=config,
                    settings=settings,
                    target_url=target_url,
                    session_mode=session_mode,
                    session_title=session_title,
                    read_only=read_only,
                    should_stop=self._stop_requested.is_set,
                    should_resume=self._consume_resume,
                    update=self._update,
                    process_changed=self._set_active_process,
                )
            with self._lock:
                self._completion_started = True
                stopped = self._stop_requested.is_set()
                finished_at = utc_now()
                final_history_key = _agent_history_key(
                    conversation_url or target_url,
                    settings.platform,
                )
                history = [
                    dict(item)
                    for item in self._conversation_histories.get(
                        final_history_key,
                        self._snapshot.history,
                    )
                ]
                if response.strip():
                    history.append(
                        {
                            "prompt": prompt,
                            "response": response,
                            "started_at": self._snapshot.started_at,
                            "finished_at": finished_at,
                        }
                    )
                    history = history[-MAX_AGENT_SESSION_HISTORY:]
                    self._conversation_histories[final_history_key] = history
                    self._conversation_titles[final_history_key] = self._snapshot.session_title
                completion = {
                    "phase": "stopped" if stopped else "finished",
                    "message": (
                        "Agent request stopped."
                        if stopped
                        else (
                            f"{self._snapshot.actual_model or AGENT_PLATFORM_BY_KEY[settings.platform]['label']} "
                            "completed the project task after local bodycheck."
                        )
                    ),
                    "response": response,
                    "conversation_url": conversation_url,
                    "history": history,
                    "turn_count": turn_count,
                    "bodycheck_passed": bodycheck_passed,
                    "finished_at": finished_at,
                }
        except Exception as exc:
            LOGGER.exception("Computer Use web-agent request failed.")
            with self._lock:
                self._completion_started = True
                recorded_conversation_url = str(self._snapshot.conversation_url or "")
            handoff_url = normalize_agent_conversation_url(
                settings.platform,
                recorded_conversation_url,
            )
            handoff_available = bool(
                settings.platform == "chatgpt"
                and settings.browser == "edge"
                and handoff_url
                and not self._stop_requested.is_set()
            )
            handoff_opened = False
            handoff_message = ""
            if handoff_available:
                try:
                    self._browser_opener(
                        settings.platform,
                        settings.browser,
                        handoff_url,
                        background=True,
                    )
                    handoff_opened = True
                    handoff_message = (
                        "The same ChatGPT conversation was opened quietly in Edge for traditional "
                        "continuation. Local edits and bodycheck remain unfinished until the Agent "
                        "controller verifies them."
                    )
                except (OSError, RuntimeError, ValueError) as handoff_exc:
                    LOGGER.warning("Could not open the traditional Edge handoff: %s", handoff_exc)
                    handoff_message = (
                        "Continue the same ChatGPT conversation with the Edge button. Local edits "
                        "and bodycheck remain unfinished until the Agent controller verifies them."
                    )
            failure_message = str(exc).splitlines()[0][:500]
            completion = {
                "phase": "failed",
                "message": (
                    f"{failure_message} {handoff_message}".strip()
                    if handoff_message
                    else failure_message
                ),
                "last_error": str(exc),
                "traditional_handoff_available": handoff_available,
                "traditional_handoff_opened": handoff_opened,
                "traditional_handoff_message": handoff_message,
                "finished_at": utc_now(),
            }
        finally:
            self._publish_run_completion(
                sleep_assertion=sleep_assertion,
                context_path=context_path,
                completion=completion,
            )

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                if hasattr(self._snapshot, key):
                    setattr(self._snapshot, key, value)
            self._persist_snapshot_locked()


def run_web_computer_use(
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
    session_title: str = "",
    read_only: bool = False,
    should_resume: Callable[[], bool] | None = None,
) -> tuple[str, str, int, bool]:
    """Run one selected Web AI session as a local controller action loop."""
    descriptor = browser_descriptors(config)[settings.browser]
    controller = WorkspaceController(
        workspace,
        settings,
        should_stop,
        process_changed,
        read_only=read_only,
    )
    selected_target_url = target_url or (
        _platform_home_url(settings.platform)
        if settings.platform != DEFAULT_AGENT_PLATFORM
        else settings.target_url
    )
    initial_message = _initial_web_agent_message(
        prompt,
        workspace,
        settings,
        context_path,
        session_mode,
        platform=settings.platform,
        session_title=session_title,
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
                platform=settings.platform,
                session_mode=session_mode,
                selected_target_url=selected_target_url,
                should_stop=should_stop,
                should_resume=should_resume,
                update=update,
            )

    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(
            playwright,
            descriptor,
            headless=False,
            clone_profile_first=True,
            background_window=True,
            silent=settings.browser == "edge",
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
                platform=settings.platform,
                session_mode=session_mode,
                selected_target_url=selected_target_url,
                should_stop=should_stop,
                should_resume=should_resume,
                update=update,
            )


def _initial_web_agent_message(
    prompt: str,
    workspace: Path,
    settings: ComputerUseSettings,
    context_path: Path,
    session_mode: str,
    platform: str = DEFAULT_AGENT_PLATFORM,
    session_title: str = "",
) -> str:
    platform_label = AGENT_PLATFORM_BY_KEY.get(platform, AGENT_PLATFORM_BY_KEY[DEFAULT_AGENT_PLATFORM])["label"]
    session_instruction = {
        "new": f"Start a new root-level {platform_label} Web conversation for this task.",
        "recent": f"Continue the selected existing root-level {platform_label} Web conversation for this task.",
        "project_new": "Start a new conversation inside the selected Project for this task.",
        "project_session": "Continue the selected existing conversation inside the selected Project for this task.",
    }.get(session_mode, f"Start a new root-level {platform_label} Web conversation for this task.")
    clean_session_title = _clean_agent_session_title(session_title, "")
    title_instruction = (
        f"Session name: {clean_session_title}\n"
        "Keep this exact name as the local Agent session label. The provider may generate its own remote conversation title."
        if clean_session_title
        else "Session name: Use the local Agent session label associated with this task."
    )
    return (
        settings.system_prompt
        + "\n\nA local context Markdown file is attached when the browser supports direct attachment. "
        "Its filename is `"
        + context_path.name
        + "`. If no attachment appears, use the environment summary below and request files through controller actions.\n\n"
        f"Project: {workspace.name}\n"
        f"Project root: {workspace}\n"
        f"Session source: {session_instruction}\n"
        f"{title_instruction}\n"
        f"User request: {prompt}\n\n"
        "Begin with the smallest useful read, search, or list JSON action."
    )


def _initial_chatgpt_message(
    prompt: str,
    workspace: Path,
    settings: ComputerUseSettings,
    context_path: Path,
    session_mode: str,
    session_title: str = "",
) -> str:
    """Keep the previous ChatGPT-specific helper as a compatibility wrapper."""
    return _initial_web_agent_message(
        prompt,
        workspace,
        settings,
        context_path,
        session_mode,
        "chatgpt",
        session_title=session_title,
    )


def run_chatgpt_web_computer_use(
    **kwargs: Any,
) -> tuple[str, str, int, bool]:
    """Compatibility wrapper for callers that still use the old runner name."""
    return run_web_computer_use(**kwargs)


def _current_agent_conversation_url(
    page: Any, platform: str, fallback: str = ""
) -> str:
    """Return the provider-canonical conversation URL without query or fragment drift."""
    current = str(getattr(page, "url", "") or "").strip()
    normalized = normalize_agent_conversation_url(platform, current)
    if normalized:
        return normalized
    normalized_fallback = normalize_agent_conversation_url(platform, fallback)
    return normalized_fallback or current or str(fallback or "").strip()


def _provider_tab_identity(page: Any) -> tuple[Any, str, str]:
    """Return provider-tab id, exact URL, and title without activating the window."""
    tab_id = getattr(page, "_guid", None)
    if tab_id is None:
        tab_id = id(page)
    url = str(getattr(page, "url", "") or "").strip()
    title = ""
    title_fn = getattr(page, "title", None)
    if callable(title_fn):
        try:
            title = str(title_fn() or "").strip()
        except Exception:
            title = ""
    return tab_id, url, title


def _chatgpt_fresh_navigation_allowed(expected_url: str, current_url: str) -> bool:
    """Permit the normal ChatGPT home-to-conversation transition."""
    expected = urlsplit(str(expected_url or ""))
    current = urlsplit(str(current_url or ""))
    if (expected.hostname or "").lower() not in CHATGPT_HOSTS:
        return False
    if (current.hostname or "").lower() not in CHATGPT_HOSTS:
        return False
    expected_path = expected.path.rstrip("/") or "/"
    current_path = current.path.rstrip("/") or "/"
    if expected_path == "/" and re.fullmatch(r"/c/[^/]+/?", current_path, re.IGNORECASE):
        return True
    if expected_path.endswith("/project"):
        project_prefix = expected_path[: -len("/project")]
        if re.fullmatch(re.escape(project_prefix) + r"/c/[^/]+/?", current_path, re.IGNORECASE):
            return True
    return False


def _provider_url_still_on_selected_target(
    platform: str,
    expected_url: str,
    current_url: str,
    session_mode: str,
) -> bool:
    """Compare the remote provider tab against the selected target URL."""
    if _web_target_is_open(platform, expected_url, current_url):
        return True
    mode = str(session_mode or "new").strip().lower()
    if platform == "chatgpt" and mode in {"new", "project_new"}:
        return _chatgpt_fresh_navigation_allowed(expected_url, current_url)
    return False


def _macos_screen_is_locked() -> bool | None:
    """Return lock-screen state only when a reliable macOS signal is present."""
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["ioreg", "-n", "Root", "-d1", "-w0"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = result.stdout or ""
    match = re.search(r'"CGSSessionScreenIsLocked"\s*=\s*(\w+)', text)
    if match is None:
        return None
    value = match.group(1).strip().lower()
    if value in {"yes", "true", "1"}:
        return True
    if value in {"no", "false", "0"}:
        return False
    return None


def _detect_browser_interruption(
    page: Any,
    expected_url: str,
    browser_kind: str,
    *,
    platform: str = DEFAULT_AGENT_PLATFORM,
    session_mode: str = "new",
    expected_tab_id: Any = None,
    expected_title: str = "",
) -> tuple[bool, str]:
    """Detect provider-tab closure, crash, identity change, or user takeover.

    Compares the selected remote provider target, not the local Agent page.
    Edge being frontmost is not treated as user takeover. Unknown lock-screen
    state must not create a permanent false pause.
    """
    del browser_kind  # retained for callers; frontmost-app checks are not used
    is_closed = getattr(page, "is_closed", None)
    if callable(is_closed):
        try:
            if is_closed():
                return True, "The selected provider tab was closed."
        except Exception:
            return True, "The selected provider page crashed or is no longer accessible."

    tab_id, current_url, current_title = _provider_tab_identity(page)
    if expected_tab_id is not None and tab_id != expected_tab_id:
        return True, "The selected provider tab identity changed."
    if expected_url and current_url:
        hosts = {str(host).lower() for host in _platform_hosts(platform)}
        expected_host = (urlsplit(expected_url).hostname or "").lower()
        current_host = (urlsplit(current_url).hostname or "").lower()
        if current_host and hosts and current_host not in hosts:
            return True, f"The selected provider tab navigated away from {expected_host or platform} to {current_host}."
        if not _provider_url_still_on_selected_target(
            platform, expected_url, current_url, session_mode
        ):
            return True, "The selected provider tab navigated away from the chosen session."
    if expected_title and current_title and expected_title != current_title:
        if current_url and expected_url and current_url.rstrip("/") != str(expected_url).rstrip("/"):
            return True, "The selected provider tab title no longer matches the chosen session."

    if callable(is_closed):
        locked = _macos_screen_is_locked()
        if locked is True:
            return True, "The screen is locked."
    return False, ""


def _wait_for_browser_recovery(
    *,
    page: Any,
    expected_url: str,
    browser_kind: str,
    platform: str,
    session_mode: str,
    expected_tab_id: Any,
    expected_title: str,
    should_stop: Callable[[], bool],
    should_resume: Callable[[], bool] | None,
    update: Callable[..., None],
    reason: str,
) -> str:
    """Pause until the provider tab recovers, the user resumes, or the wait expires.

    Returns 'recovered', 'stopped', or 'timeout'. Does not submit a prompt.
    """
    update(
        paused=True,
        pause_reason=reason,
        phase="paused",
        message=reason,
    )
    deadline = time.monotonic() + BROWSER_INTERRUPTION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if should_stop():
            return "stopped"
        resume_requested = bool(should_resume and should_resume())
        interrupted, current_reason = _detect_browser_interruption(
            page,
            expected_url,
            browser_kind,
            platform=platform,
            session_mode=session_mode,
            expected_tab_id=expected_tab_id,
            expected_title=expected_title,
        )
        if not interrupted:
            update(paused=False, pause_reason="", phase="running", message="Resumed the Web Agent after a browser interruption.")
            return "recovered"
        if resume_requested:
            update(
                paused=True,
                pause_reason=current_reason or reason,
                phase="paused",
                message=(
                    "Resume was requested, but the selected provider tab is still interrupted. "
                    + (current_reason or reason)
                ),
            )
        time.sleep(BROWSER_INTERRUPTION_POLL_SECONDS)
    return "timeout"


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
    platform: str = DEFAULT_AGENT_PLATFORM,
    should_resume: Callable[[], bool] | None = None,
) -> tuple[str, str, int, bool]:
    """Exchange JSON actions and compact observations in one Web AI conversation."""
    verified = _verify_agent_page(
        page,
        browser_kind,
        platform,
        selected_target_url,
        should_stop,
    )
    if verified is False or should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, selected_target_url),
            0,
            False,
        )
    if platform == "chatgpt":
        _select_chat_mode(page, browser_kind)
    if should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, selected_target_url),
            0,
            False,
        )

    session_type = session_type_for_mode(session_mode)
    page_url = str(getattr(page, "url", "") or "").strip()
    expected_tab_id, _expected_url, expected_title = _provider_tab_identity(page)
    model_observation: dict[str, Any] = {}
    model_selected = _select_web_model(
        page,
        browser_kind,
        platform,
        settings.model,
        model_observation,
        should_stop=should_stop,
    )
    if should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, page_url or selected_target_url),
            0,
            False,
        )
    selected_option = next(
        (
            option
            for option in _platform_model_options(platform)
            if option["key"] == settings.model
        ),
        None,
    )
    expected_label = str((selected_option or {}).get("label") or settings.model)
    attempted_labels = tuple(
        (selected_option or {}).get("remote_labels") or (expected_label,)
    )
    if model_selected:
        actual_model = str(
            model_observation.get("observed") or expected_label
        )
        update(
            phase="preparing",
            message=f"Verified {actual_model} in {AGENT_PLATFORM_BY_KEY[platform]['label']} Web.",
            model_verified=True,
            actual_model=actual_model,
            session_type=session_type,
        )
    elif platform == "chatgpt":
        observed = str(model_observation.get("observed") or "").strip() or "none"
        menu_text = str(model_observation.get("menu_text") or "").strip() or "none"
        available = model_observation.get("available") or []
        available_text = ", ".join(str(item) for item in available if str(item).strip()) or menu_text
        recorded_attempted_labels = model_observation.get("attempted_labels")
        if not isinstance(recorded_attempted_labels, (list, tuple)):
            recorded_attempted_labels = attempted_labels
        verified_attempted_labels = [
            str(item).strip()
            for item in recorded_attempted_labels
            if str(item).strip()
        ] or list(attempted_labels)
        raise RuntimeError(
            f"ChatGPT Web could not verify {expected_label} after "
            f"{CHATGPT_MODEL_VERIFICATION_ATTEMPTS} attempt(s). "
            "No project context or prompt was sent. "
            f"URL={page_url}, session_mode={session_mode}, session_type={session_type}, "
            f"expected_model={expected_label}, observed_model={observed}, "
            f"menu_text={available_text}, "
            f"visible_buttons={model_observation.get('visible_buttons') or []}, "
            f"menu_roles={model_observation.get('menu_roles') or []}, "
            f"attempted_labels={verified_attempted_labels}."
        )
    else:
        update(
            phase="preparing",
            message=(
                f"{AGENT_PLATFORM_BY_KEY[platform]['label']} Web did not expose a model selector; "
                "keeping the selected session's current model."
            ),
            session_type=session_type,
        )
    if should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, page_url or selected_target_url),
            0,
            False,
        )
    attached = _attach_context_file(
        page,
        browser_kind,
        context_path,
        should_stop,
    )
    if should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, page_url or selected_target_url),
            0,
            False,
        )
    update(context_attached=attached)
    if should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, page_url or selected_target_url),
            0,
            False,
        )
    update(
        phase="submitting",
        message=(
            f"Uploading the local Markdown context and opening the selected {AGENT_PLATFORM_BY_KEY[platform]['label']} Web session."
            if attached
            else (
                f"Opening the selected {AGENT_PLATFORM_BY_KEY[platform]['label']} Web session; "
                "the controller will stream context on demand."
            )
        ),
    )
    if should_stop():
        return (
            "",
            _current_agent_conversation_url(page, platform, page_url or selected_target_url),
            0,
            False,
        )
    response = _submit_and_wait(
        page,
        browser_kind,
        initial_message,
        should_stop,
        platform=platform,
        on_submitted=lambda: update(
            phase="running",
            message=f"Prompt sent to {AGENT_PLATFORM_BY_KEY[platform]['label']} Web; waiting for the first controller action.",
        ),
    )
    conversation_url = _current_agent_conversation_url(
        page, platform, selected_target_url
    )
    if conversation_url:
        update(conversation_url=conversation_url)
    activity: list[dict[str, str]] = []

    turn_index = 0
    invalid_action_retries = 0
    _seen_failure_hashes: set[str] = set()
    while turn_index < settings.max_turns:
        if should_stop():
            _stop_web_generation(page, browser_kind)
            return (
                "",
                _current_agent_conversation_url(page, platform, conversation_url),
                turn_index,
                controller.state.bodycheck_current,
            )

        interrupted, interrupt_reason = _detect_browser_interruption(
            page,
            selected_target_url,
            browser_kind,
            platform=platform,
            session_mode=session_mode,
            expected_tab_id=expected_tab_id,
            expected_title=expected_title,
        )
        if interrupted:
            LOGGER.info("Browser interrupted: %s. Waiting for recovery.", interrupt_reason)
            wait_result = _wait_for_browser_recovery(
                page=page,
                expected_url=selected_target_url,
                browser_kind=browser_kind,
                platform=platform,
                session_mode=session_mode,
                expected_tab_id=expected_tab_id,
                expected_title=expected_title,
                should_stop=should_stop,
                should_resume=should_resume,
                update=update,
                reason=interrupt_reason,
            )
            if wait_result == "stopped":
                _stop_web_generation(page, browser_kind)
                return (
                    "",
                    _current_agent_conversation_url(page, platform, conversation_url),
                    turn_index,
                    controller.state.bodycheck_current,
                )
            if wait_result != "recovered":
                raise RuntimeError(
                    f"Browser did not recover after interruption: {interrupt_reason}"
                )
            LOGGER.info("Browser recovered from interruption without duplicating a submit.")

        try:
            action = parse_agent_action(response)
        except ValueError as exc:
            invalid_action_retries += 1
            response_hash = hashlib.sha256(
                str(response or "").encode("utf-8", errors="replace")
            ).hexdigest()[:16]
            LOGGER.warning(
                "%s returned an invalid controller response on retry %s "
                "(characters=%s, sha256=%s).",
                AGENT_PLATFORM_BY_KEY[platform]["label"],
                invalid_action_retries,
                len(str(response or "")),
                response_hash,
            )
            # Fail immediately if the same malformed response appears twice
            if response_hash in _seen_failure_hashes:
                raise RuntimeError(
                    f"{AGENT_PLATFORM_BY_KEY[platform]['label']} returned the same invalid "
                    f"controller action twice (sha256={response_hash}). "
                    f"Parser reason: {exc}"
                ) from exc
            _seen_failure_hashes.add(response_hash)
            if invalid_action_retries > MAX_INVALID_ACTION_RETRIES:
                raise RuntimeError(
                    f"{AGENT_PLATFORM_BY_KEY[platform]['label']} returned too many invalid "
                    f"controller actions in a row. Last parser reason: {exc}"
                ) from exc
            # Request base64 safe transport on correction
            correction_instruction = (
                _BASE64_CORRECTION_INSTRUCTION
                if "quote" in str(exc).lower() or "base64" in str(exc).lower()
                else JSON_ACTION_RESPONSE_INSTRUCTION
            )
            observation = {
                "ok": False,
                "error": str(exc),
                "instruction": correction_instruction,
            }
            response = _submit_and_wait(
                page,
                browser_kind,
                _observation_message(turn_index + 1, observation),
                should_stop,
                platform=platform,
                on_submitted=lambda: update(
                    phase="running",
                    message=f"Correction sent to {AGENT_PLATFORM_BY_KEY[platform]['label']} Web; waiting for a valid controller action.",
                ),
            )
            continue

        invalid_action_retries = 0
        turn_index += 1
        action_name = str(action.get("action") or "").strip().lower()
        if action_name == "final":
            final_blocker = ""
            if (
                controller.state.edit_generation > 0
                and not controller.state.verification_current
            ):
                final_blocker = (
                    "Final is blocked until one approved verification command succeeds "
                    "after the latest edit."
                )
            elif not controller.state.bodycheck_current:
                final_blocker = (
                    "Final is blocked until bodycheck succeeds after the latest edit."
                )
            if final_blocker:
                response = _submit_and_wait(
                    page,
                    browser_kind,
                    _observation_message(
                        turn_index,
                        {
                            "ok": False,
                            "error": final_blocker,
                        },
                    ),
                    should_stop,
                    platform=platform,
                    on_submitted=lambda: update(
                        phase="running",
                        message=f"Bodycheck requirement sent; waiting for the next {AGENT_PLATFORM_BY_KEY[platform]['label']} action.",
                    ),
                )
                continue
            final_response = _render_final_action(action)
            conversation_url = _current_agent_conversation_url(
                page, platform, conversation_url
            )
            update(
                phase="finalizing",
                message=f"{AGENT_PLATFORM_BY_KEY[platform]['label']} returned a final result after the current bodycheck.",
                response=final_response,
                conversation_url=conversation_url,
                turn_count=turn_index,
                bodycheck_passed=True,
            )
            return final_response, conversation_url, turn_index, True

        detail = _activity_detail(action)
        activity.append(
            {
                "label": action_name.replace("_", " ").title() or "Controller action",
                "detail": detail,
                "meta": f"Turn {turn_index:,}",
                "status": "running",
            }
        )
        conversation_url = _current_agent_conversation_url(
            page, platform, conversation_url
        )
        update(
            phase="running",
            message=f"{AGENT_PLATFORM_BY_KEY[platform]['label']} requested local {action_name or 'controller'} action.",
            activity=activity,
            conversation_url=conversation_url,
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
            return "", conversation_url, turn_index, controller.state.bodycheck_current
        response = _submit_and_wait(
            page,
            browser_kind,
            _observation_message(turn_index, observation),
            should_stop,
            platform=platform,
            on_submitted=lambda: update(
                phase="running",
                message=f"Controller observation sent; waiting for the next {AGENT_PLATFORM_BY_KEY[platform]['label']} action.",
            ),
        )

    raise RuntimeError(
        f"{AGENT_PLATFORM_BY_KEY[platform]['label']} reached the configured {settings.max_turns:,}-turn limit before returning final."
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
        + "\n"
        + JSON_ACTION_RESPONSE_INSTRUCTION
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
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    if callable(should_stop) and should_stop():
        return False
    if browser_kind == "safari":
        page.locator("#prompt-textarea").inner_text(timeout=60_000)
    else:
        if not _wait_for_chromium_composer(page, should_stop=should_stop):
            return False
    if callable(should_stop) and should_stop():
        return False
    current_url = str(page.url or "")
    if (urlsplit(current_url).hostname or "").lower() not in CHATGPT_HOSTS:
        raise RuntimeError("The selected browser did not reach ChatGPT Web.")
    if selected_target_url and not _chatgpt_target_is_open(selected_target_url, current_url):
        raise RuntimeError("The selected ChatGPT session did not finish opening in the browser.")
    if callable(should_stop) and should_stop():
        return False
    signed_out = bool(
        page.evaluate(
            """() => Array.from(document.querySelectorAll('a,button')).some((element) => {
                const text = (element.innerText || element.textContent || '').trim().toLowerCase();
                return element.offsetParent !== null && /^(log in|sign up)$/.test(text);
            })"""
        )
    )
    if callable(should_stop) and should_stop():
        return False
    if signed_out:
        raise RuntimeError(f"{settings_browser_label(browser_kind)} is not signed in to ChatGPT Web.")
    return True


def _web_composer_selector(platform: str) -> str:
    """Return the least-specific composer contract accepted for one provider."""
    return {
        "chatgpt": "#prompt-textarea",
        "gemini": 'textarea, [contenteditable="true"]',
        "grok": "textarea",
        "claude": (
            'textarea, [contenteditable="true"][role="textbox"], '
            'div.ProseMirror[contenteditable="true"], [contenteditable="true"]'
        ),
    }.get(platform, 'textarea, [contenteditable="true"]')


def _web_assistant_selector(platform: str) -> str:
    """Return ordered assistant message selectors for one provider."""
    return {
        "chatgpt": '[data-message-author-role="assistant"]',
        "gemini": 'model-response, [data-test-id="model-response"], .model-response-text, message-content',
        "grok": (
            '[data-testid="assistant-message"], [data-testid*="assistant" i], '
            '[data-testid*="response" i], [data-role="assistant"], '
            '[data-message-author-role="assistant"]'
        ),
        "claude": (
            '[data-testid="assistant-message"], [data-testid*="assistant" i], '
            '[data-message-author-role="assistant"], [data-role="assistant"], '
            '.font-claude-message'
        ),
    }.get(platform, '[data-message-author-role="assistant"]')


def _web_target_is_open(platform: str, target_url: str, current_url: str) -> bool:
    """Check that a provider page stayed on its official host and selected path."""
    target = urlsplit(str(target_url or ""))
    current = urlsplit(str(current_url or ""))
    hosts = _platform_hosts(platform)
    if (target.hostname or "").lower() not in hosts or (current.hostname or "").lower() not in hosts:
        return False
    if platform == "chatgpt":
        return _chatgpt_target_is_open(target_url, current_url)
    target_path = target.path.rstrip("/") or "/"
    current_path = current.path.rstrip("/") or "/"
    if platform == "claude" and target_path == "/new":
        return current_path == "/new" or current_path.startswith("/chat/") or current_path.startswith("/project/")
    return current_path == target_path or current_path.startswith(f"{target_path}/")


class _ComposerReadinessTimeout(TimeoutError):
    """Signal that retryable composer waits exhausted their bounded deadline."""


def _is_composer_wait_timeout(exc: Exception) -> bool:
    """Recognize built-in and Playwright timeout errors without importing Playwright eagerly."""
    return isinstance(exc, TimeoutError) or exc.__class__.__name__ == "TimeoutError"


def _wait_for_visible_composer(
    target: Any,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Poll one composer locator so Stop can interrupt the initial readiness gate."""
    deadline = time.monotonic() + CHATGPT_COMPOSER_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if callable(should_stop) and should_stop():
            return False
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1_000))
        try:
            target.wait_for(
                state="visible",
                timeout=min(WEB_SEND_BUTTON_POLL_MILLISECONDS, remaining_ms),
            )
            if callable(should_stop) and should_stop():
                return False
            return True
        except Exception as exc:
            if not _is_composer_wait_timeout(exc):
                raise
            last_error = exc
    raise _ComposerReadinessTimeout(
        "The provider composer readiness wait expired."
    ) from last_error


def _wait_for_web_composer(
    page: Any,
    platform: str,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Wait for a provider's composer without bringing its background window forward."""
    selector = _web_composer_selector(platform)
    last_error: Exception | None = None
    for attempt in range(1, CHATGPT_COMPOSER_RELOAD_ATTEMPTS + 1):
        try:
            if not _wait_for_visible_composer(
                page.locator(selector).first,
                should_stop=should_stop,
            ):
                return False
            return True
        except _ComposerReadinessTimeout as exc:
            last_error = exc
            if callable(should_stop) and should_stop():
                return False
            if attempt >= CHATGPT_COMPOSER_RELOAD_ATTEMPTS:
                break
            page.reload(
                wait_until="commit",
                timeout=CHATGPT_COMPOSER_RELOAD_TIMEOUT_SECONDS * 1_000,
            )
            if callable(should_stop) and should_stop():
                return False
    platform_label = AGENT_PLATFORM_BY_KEY.get(platform, AGENT_PLATFORM_BY_KEY[DEFAULT_AGENT_PLATFORM])["label"]
    raise RuntimeError(
        f"The Chromium browser loaded {platform_label}, but its message composer did not become ready after one reload."
    ) from last_error


def _verify_agent_page(
    page: Any,
    browser_kind: str,
    platform: str,
    selected_target_url: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Verify one provider's authenticated composer before any project content is sent."""
    if platform == "chatgpt":
        return _verify_chatgpt_page(
            page,
            browser_kind,
            selected_target_url,
            should_stop,
        )
    if browser_kind == "safari":
        raise RuntimeError(f"{AGENT_PLATFORM_BY_KEY[platform]['label']} Agent sessions require Edge or Chrome.")
    if not _wait_for_web_composer(page, platform, should_stop=should_stop):
        return False
    if callable(should_stop) and should_stop():
        return False
    current_url = str(page.url or "")
    if (urlsplit(current_url).hostname or "").lower() not in _platform_hosts(platform):
        raise RuntimeError(f"The selected browser did not reach {AGENT_PLATFORM_BY_KEY[platform]['label']} Web.")
    if selected_target_url and not _web_target_is_open(platform, selected_target_url, current_url):
        raise RuntimeError(
            f"The selected {AGENT_PLATFORM_BY_KEY[platform]['label']} session did not finish opening in the browser."
        )
    if callable(should_stop) and should_stop():
        return False
    signed_out = bool(
        page.evaluate(
            r"""() => {
                const visible = (element) => element && element.getClientRects().length > 0
                    && getComputedStyle(element).visibility !== 'hidden'
                    && getComputedStyle(element).display !== 'none';
                const bodyText = (document.body?.innerText || '').trim();
                const account = document.querySelector(
                    '[aria-label^="Google Account"], [aria-label*="Google Account:"], [data-testid*="account" i], [data-testid*="profile" i]'
                );
                const composer = document.querySelector('textarea, [contenteditable="true"]');
                const authAction = [...document.querySelectorAll('a,button')].some((element) =>
                    visible(element) && /^(sign in|log in|sign up)$/i.test(
                        (element.innerText || element.textContent || '').trim()
                    )
                );
                return Boolean(authAction && !account && !composer && bodyText);
            }"""
        )
    )
    if callable(should_stop) and should_stop():
        return False
    if signed_out:
        raise RuntimeError(
            f"{settings_browser_label(browser_kind)} is not signed in to {AGENT_PLATFORM_BY_KEY[platform]['label']} Web."
        )
    return True


def _wait_for_chromium_composer(
    page: Any,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Wait for ChatGPT's composer, reloading a stalled authenticated page once."""
    last_error: Exception | None = None
    for attempt in range(1, CHATGPT_COMPOSER_RELOAD_ATTEMPTS + 1):
        try:
            if not _wait_for_visible_composer(
                page.locator("#prompt-textarea"),
                should_stop=should_stop,
            ):
                return False
            return True
        except _ComposerReadinessTimeout as exc:
            last_error = exc
            if callable(should_stop) and should_stop():
                return False
            if attempt >= CHATGPT_COMPOSER_RELOAD_ATTEMPTS:
                break
            page.reload(
                wait_until="commit",
                timeout=CHATGPT_COMPOSER_RELOAD_TIMEOUT_SECONDS * 1_000,
            )
            if callable(should_stop) and should_stop():
                return False
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


def _chatgpt_model_text_matches(value: str, labels: tuple[str, ...]) -> bool:
    normalized = " ".join(str(value or "").split()).casefold()
    return any(
        normalized == " ".join(label.split()).casefold()
        or normalized.endswith(f" {' '.join(label.split()).casefold()}")
        for label in labels
    )


CHATGPT_MODEL_TRIGGER_LABELS = (
    "Instant",
    "GPT-5.6 Sol",
    "5.6 Sol",
    "Extra High",
)

CHATGPT_MODEL_DIAGNOSTIC_MAX_ITEMS = 20
CHATGPT_MODEL_DIAGNOSTIC_MAX_CHARS = 160
_CHATGPT_MODEL_DIAGNOSTIC_PATTERN = re.compile(
    r"(?:^|\s)(?:instant|gpt-?5\.6 sol|5\.6 sol|extra high|"
    r"model(?: picker)?|switch model|auto|high|medium|low|max|pro|"
    r"advanced|faster|smarter)(?:$|\s)",
    re.IGNORECASE,
)


def _first_visible_role_control(
    page: Any,
    role: str,
    names: tuple[str, ...],
    predicate: Callable[[Any], bool] | None = None,
) -> Any | None:
    """Return the first visible exact-name Playwright role control."""
    for name in names:
        locator = page.get_by_role(role, name=name, exact=True)
        for index in range(locator.count()):
            candidate = locator.nth(index)
            if candidate.is_visible() and (predicate is None or predicate(candidate)):
                return candidate
    return None


def _wait_for_chatgpt_composer_if_available(
    page: Any,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """Wait briefly for the ChatGPT composer, aborting when Stop is requested."""
    locator_fn = getattr(page, "locator", None)
    if not callable(locator_fn):
        return
    try:
        handle = locator_fn("#prompt-textarea")
        target = getattr(handle, "first", handle)
        wait_for = getattr(target, "wait_for", None)
        if not callable(wait_for):
            return
        deadline = time.monotonic() + CHATGPT_MODEL_COMPOSER_WAIT_SECONDS
        while time.monotonic() < deadline:
            if callable(should_stop) and should_stop():
                return
            remaining_ms = max(50.0, (deadline - time.monotonic()) * 1_000)
            try:
                wait_for(state="visible", timeout=min(250.0, remaining_ms))
                return
            except Exception as exc:
                if not _is_composer_wait_timeout(exc):
                    return
                if callable(should_stop) and should_stop():
                    return
    except Exception:
        return


def _chatgpt_visible_model_controls(page: Any) -> dict[str, Any]:
    """Read visible model-related button names and menu roles without clicking."""
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return {"buttons": [], "menus": []}
    try:
        result = evaluate(
            r"""() => {
                const visible = (element) => {
                    if (!element) return false;
                    const style = getComputedStyle(element);
                    return element.getClientRects().length > 0
                        && style.display !== 'none'
                        && style.visibility !== 'hidden';
                };
                const textOf = (element) => String(
                    element.getAttribute('aria-label')
                    || element.innerText
                    || element.textContent
                    || ''
                ).replace(/\s+/g, ' ').trim();
                const diagnosticPattern = /(?:^|\s)(?:instant|gpt-?5\.6 sol|5\.6 sol|extra high|model(?: picker)?|switch model|auto|high|medium|low|max|pro|advanced|faster|smarter)(?:$|\s)/i;
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'))
                    .filter(visible)
                    .map(textOf)
                    .map((label) => label.slice(0, 160))
                    .filter((label) => diagnosticPattern.test(label));
                const menus = Array.from(document.querySelectorAll('[role="menu"], [role="listbox"]'))
                    .filter(visible)
                    .map((element) => element.getAttribute('role') || '');
                return {
                    buttons: [...new Set(buttons)].slice(0, 20),
                    menus: [...new Set(menus.filter(Boolean))].slice(0, 20),
                };
            }"""
        )
    except Exception:
        return {"buttons": [], "menus": []}
    if not isinstance(result, dict):
        return {"buttons": [], "menus": []}
    raw_buttons = result.get("buttons", [])
    if not isinstance(raw_buttons, (list, tuple)):
        raw_buttons = []
    buttons: list[str] = []
    seen_buttons: set[str] = set()
    for item in raw_buttons:
        label = " ".join(str(item).split())[:CHATGPT_MODEL_DIAGNOSTIC_MAX_CHARS]
        identity = label.casefold()
        if (
            not label
            or identity in seen_buttons
            or not _CHATGPT_MODEL_DIAGNOSTIC_PATTERN.search(label)
        ):
            continue
        seen_buttons.add(identity)
        buttons.append(label)
        if len(buttons) >= CHATGPT_MODEL_DIAGNOSTIC_MAX_ITEMS:
            break

    raw_menus = result.get("menus", [])
    if not isinstance(raw_menus, (list, tuple)):
        raw_menus = []
    menus: list[str] = []
    for item in raw_menus:
        role = str(item).strip().casefold()
        if role in {"menu", "listbox"} and role not in menus:
            menus.append(role)
        if len(menus) >= CHATGPT_MODEL_DIAGNOSTIC_MAX_ITEMS:
            break
    return {"buttons": buttons, "menus": menus}


def _read_chatgpt_model_menu(page: Any) -> dict[str, Any]:
    """Read the visible ChatGPT power menu without generating synthetic click events."""
    result = page.evaluate(
        r"""() => {
            const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
            const visible = (element) => {
                if (!element) return false;
                const style = getComputedStyle(element);
                return element.getClientRects().length > 0
                    && style.display !== 'none'
                    && style.visibility !== 'hidden';
            };
            const menus = Array.from(document.querySelectorAll('[role="menu"]')).filter(visible);
            const menu = menus.find((candidate) =>
                Array.from(candidate.querySelectorAll('[role="menuitem"]')).some((item) =>
                    normalize(item.innerText || item.textContent).toLowerCase().startsWith('model')
                )
            );
            const modelItem = Array.from(menu?.querySelectorAll('[role="menuitem"]') || [])
                .find((item) => normalize(item.innerText || item.textContent).toLowerCase().startsWith('model'));
            if (!modelItem) {
                const menuText = normalize(menu?.innerText || menu?.textContent || '');
                return {
                    ok: false,
                    diagnostic: {
                        visibleMenuCount: menus.length,
                        menuItemCount: menu?.querySelectorAll('[role="menuitem"]').length || 0,
                        menuTextHasModel: /(^|\s)model(\s|$)/i.test(menuText),
                        menuTextHasSol: /5\.6 sol/i.test(menuText),
                    },
                };
            }
            const lines = String(modelItem.innerText || modelItem.textContent || '')
                .split(/\n+/)
                .map((value) => value.trim())
                .filter(Boolean);
            const descendants = Array.from(modelItem.querySelectorAll('span'))
                .map((element) => String(element.innerText || element.textContent || '').trim())
                .filter(Boolean);
            return {
                ok: true,
                current: lines.length > 1
                    ? lines.slice(1).join(' ')
                    : (descendants.at(-1) || lines.at(-1) || ''),
            };
        }"""
    )
    return result if isinstance(result, dict) else {"ok": False, "diagnostic": {}}


def _record_model_observation(
    observation: dict[str, Any] | None,
    *,
    observed: str = "",
    available: list[str] | tuple[str, ...] | None = None,
    reason: str = "",
    attempted_labels: tuple[str, ...] = (),
    menu_text: str = "",
    visible_buttons: list[str] | tuple[str, ...] | None = None,
    menu_roles: list[str] | tuple[str, ...] | None = None,
) -> None:
    if observation is None:
        return
    observation.update(
        {
            "observed": str(observed or "").strip(),
            "available": [str(item) for item in (available or []) if str(item).strip()],
            "reason": str(reason or "").strip(),
            "attempted_labels": list(attempted_labels),
            "menu_text": str(menu_text or observed or "").strip(),
            "visible_buttons": [str(item).strip() for item in (visible_buttons or []) if str(item).strip()],
            "menu_roles": [str(item).strip() for item in (menu_roles or []) if str(item).strip()],
        }
    )


def _chatgpt_control_has_model_menu_semantics(control: Any) -> bool:
    """Accept only model-menu triggers, never composer or open-menu internals."""
    evaluate = getattr(control, "evaluate", None)
    if callable(evaluate):
        try:
            return bool(
                evaluate(
                    r"""element => {
                        if (!(element instanceof Element)) return false;
                        if (element.closest('[role="menu"], [role="listbox"]')) return false;
                        if (element.closest('#prompt-textarea, [contenteditable="true"]')) return false;
                        const popup = String(element.getAttribute('aria-haspopup') || '').trim().toLowerCase();
                        const expanded = String(element.getAttribute('aria-expanded') || '').trim().toLowerCase();
                        return popup === 'menu' || popup === 'listbox' || popup === 'true'
                            || expanded === 'true' || expanded === 'false';
                    }"""
                )
            )
        except Exception:
            return False
    get_attribute = getattr(control, "get_attribute", None)
    if not callable(get_attribute):
        return False
    popup = str(get_attribute("aria-haspopup") or "").strip().casefold()
    expanded = str(get_attribute("aria-expanded") or "").strip().casefold()
    return popup in {"menu", "listbox", "true"} or expanded in {"true", "false"}


def _select_chatgpt_model_chromium(
    page: Any,
    option: dict[str, Any],
    remote_labels: tuple[str, ...],
    observation: dict[str, Any] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Use trusted Playwright clicks, then read back the remote Chromium model."""
    wait_for_timeout = getattr(page, "wait_for_timeout", lambda _milliseconds: None)

    def stop_requested() -> bool:
        if not callable(should_stop) or not should_stop():
            return False
        _record_model_observation(
            observation,
            reason="stop-requested",
            attempted_labels=remote_labels,
        )
        return True

    _wait_for_chatgpt_composer_if_available(page, should_stop=should_stop)
    if stop_requested():
        return False
    power_button = None
    for attempt in range(CHATGPT_MODEL_VERIFICATION_ATTEMPTS):
        if stop_requested():
            return False
        power_button = _first_visible_role_control(
            page,
            "button",
            CHATGPT_MODEL_TRIGGER_LABELS,
            predicate=_chatgpt_control_has_model_menu_semantics,
        )
        if power_button is not None:
            break
        if attempt + 1 < CHATGPT_MODEL_VERIFICATION_ATTEMPTS:
            wait_for_timeout(1_000)
            if stop_requested():
                return False
    if power_button is None:
        controls = _chatgpt_visible_model_controls(page)
        LOGGER.warning(
            "ChatGPT Web could not find the visible power control for %s (visible=%s).",
            option["label"],
            controls.get("buttons") or [],
        )
        _record_model_observation(
            observation,
            reason="power-control-not-found",
            attempted_labels=remote_labels + CHATGPT_MODEL_TRIGGER_LABELS,
            visible_buttons=controls.get("buttons") or [],
            menu_roles=controls.get("menus") or [],
        )
        return False

    if stop_requested():
        return False
    if power_button.get_attribute("aria-expanded") != "true":
        power_button.click()
    if stop_requested():
        return False
    result: dict[str, Any] = {"ok": False, "diagnostic": {}}
    for _attempt in range(10):
        if stop_requested():
            return False
        page.wait_for_timeout(200)
        if stop_requested():
            return False
        result = _read_chatgpt_model_menu(page)
        if result.get("ok"):
            break
    current = str(result.get("current") or "")
    if result.get("ok") and _chatgpt_model_text_matches(current, remote_labels):
        if stop_requested():
            return False
        if power_button.get_attribute("aria-expanded") == "true":
            power_button.click()
        _record_model_observation(
            observation,
            observed=current,
            available=[current],
            attempted_labels=remote_labels,
            menu_text=current,
        )
        return True

    model_item = None
    role_items = page.get_by_role("menuitem")
    for index in range(role_items.count()):
        if stop_requested():
            return False
        candidate = role_items.nth(index)
        if candidate.is_visible() and " ".join(
            candidate.inner_text().split()
        ).casefold().startswith("model"):
            model_item = candidate
            break
    if model_item is not None:
        if stop_requested():
            return False
        model_item.click()
        if stop_requested():
            return False
        page.wait_for_timeout(350)
        if stop_requested():
            return False
        for role in ("menuitem", "option"):
            choices = page.get_by_role(role)
            for index in range(choices.count()):
                if stop_requested():
                    return False
                choice = choices.nth(index)
                if not choice.is_visible():
                    continue
                if _chatgpt_model_text_matches(choice.inner_text(), remote_labels):
                    if stop_requested():
                        return False
                    choice.click()
                    if stop_requested():
                        return False
                    page.wait_for_timeout(500)
                    if stop_requested():
                        return False
                    if power_button.get_attribute("aria-expanded") != "true":
                        power_button.click()
                    if stop_requested():
                        return False
                    for _attempt in range(10):
                        if stop_requested():
                            return False
                        page.wait_for_timeout(200)
                        if stop_requested():
                            return False
                        result = _read_chatgpt_model_menu(page)
                        if result.get("ok"):
                            break
                    current = str(result.get("current") or "")
                    if stop_requested():
                        return False
                    if power_button.get_attribute("aria-expanded") == "true":
                        power_button.click()
                    matched = bool(
                        result.get("ok")
                        and _chatgpt_model_text_matches(current, remote_labels)
                    )
                    _record_model_observation(
                        observation,
                        observed=current,
                        available=[current] if current else [],
                        attempted_labels=remote_labels,
                        menu_text=current,
                        reason="" if matched else "model-mismatch",
                    )
                    return matched

    if stop_requested():
        return False
    if power_button.get_attribute("aria-expanded") == "true":
        power_button.click()
    controls = _chatgpt_visible_model_controls(page)
    LOGGER.warning(
        "ChatGPT Web could not verify model %s through the Chromium power menu (current=%s; diagnostic=%s).",
        option["label"],
        current or "none",
        result.get("diagnostic", {}),
    )
    _record_model_observation(
        observation,
        observed=current,
        available=[current] if current else [],
        attempted_labels=remote_labels + CHATGPT_MODEL_TRIGGER_LABELS,
        menu_text=current or str(result.get("diagnostic") or ""),
        reason="model-mismatch",
        visible_buttons=controls.get("buttons") or [],
        menu_roles=controls.get("menus") or [],
    )
    return False


def _select_chatgpt_model(
    page: Any,
    browser_kind: str,
    model: str,
    observation: dict[str, Any] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Select and read back the requested ChatGPT model before any project upload."""
    selected_model = str(model or DEFAULT_CHATGPT_MODEL).strip().lower()
    option = next(
        (candidate for candidate in CHATGPT_MODEL_OPTIONS if candidate["key"] == selected_model),
        None,
    )
    if option is None:
        raise ValueError("Choose a supported ChatGPT model.")

    remote_labels = tuple(option.get("remote_labels") or (option.get("label", ""),))
    if browser_kind != "safari" and hasattr(page, "get_by_role"):
        return _select_chatgpt_model_chromium(
            page,
            option,
            remote_labels,
            observation=observation,
            should_stop=should_stop,
        )
    wait_for_timeout = getattr(page, "wait_for_timeout", lambda _milliseconds: None)
    model_control_script = r"""({labels, phase}) => {
            const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const isVisible = (element) => {
                const style = window.getComputedStyle(element);
                return element.getClientRects().length > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const visibleMenus = () => Array.from(document.querySelectorAll('[role="menu"]')).filter(isVisible);
            const matches = (value) => {
                const current = normalize(value);
                return labels.some((label) => {
                    const target = normalize(label);
                    return current === target || current.endsWith(` ${target}`);
                });
            };
            const powerLabels = new Set([
                'instant', 'gpt-5.6 sol', '5.6 sol', 'extra high'
            ]);
            const labelFor = (button) => normalize(
                `${button.getAttribute('aria-label') || ''} ${button.innerText || button.textContent || ''}`
            );
            const hasMenuSemantics = (button) => {
                const popup = normalize(button.getAttribute('aria-haspopup') || '');
                const expanded = normalize(button.getAttribute('aria-expanded') || '');
                return popup === 'menu' || popup === 'listbox' || popup === 'true'
                    || expanded === 'true' || expanded === 'false';
            };
            const powerButton = Array.from(document.querySelectorAll('button, [role="button"]')).find((button) =>
                isVisible(button)
                && !button.closest('[role="menu"], [role="listbox"]')
                && !button.closest('#prompt-textarea, [contenteditable="true"]')
                && hasMenuSemantics(button)
                && (powerLabels.has(normalize(button.innerText || button.textContent))
                    || powerLabels.has(normalize(button.getAttribute('aria-label') || ''))
                    || [...powerLabels].some((label) => labelFor(button) === label || labelFor(button).endsWith(` ${label}`)))
            );
            if (!powerButton) return {ok: false, reason: 'power-control-not-found', available: []};
            if (phase === 'choose') {
                const submenu = visibleMenus().at(-1);
                const candidates = Array.from(
                    submenu?.querySelectorAll('[role="menuitem"], [role="option"]') || []
                ).filter(isVisible);
                const choice = candidates.find((item) => matches(item.innerText || item.textContent));
                if (choice) {
                    choice.click();
                    return {
                        ok: true,
                        clicked: true,
                        available: candidates.map((item) => normalize(item.innerText || item.textContent)),
                    };
                }
                return {
                    ok: false,
                    reason: 'model-not-exposed',
                    available: candidates.map((item) => normalize(item.innerText || item.textContent)),
                };
            }

            let menu = visibleMenus().find((candidate) =>
                Array.from(candidate.querySelectorAll('[role="menuitem"]'))
                    .some((item) => normalize(item.innerText || item.textContent).startsWith('model'))
            );
            if (!menu && powerButton.getAttribute('aria-expanded') !== 'true') {
                powerButton.click();
                menu = visibleMenus().at(-1);
            }
            const modelItem = Array.from(menu?.querySelectorAll('[role="menuitem"]') || [])
                .find((item) => normalize(item.innerText || item.textContent).startsWith('model'));
            if (!modelItem) {
                const menuText = normalize(menu?.innerText || menu?.textContent || '');
                return {
                    ok: false,
                    reason: 'model-control-not-found',
                    available: [],
                    diagnostic: {
                        powerExpanded: powerButton.getAttribute('aria-expanded') === 'true',
                        visibleMenuCount: visibleMenus().length,
                        menuItemCount: menu?.querySelectorAll('[role="menuitem"]').length || 0,
                        menuTextHasModel: /(^|\s)model(\s|$)/.test(menuText),
                        menuTextHasSol: menuText.includes('5.6 sol'),
                    },
                };
            }

            const lines = String(modelItem.innerText || modelItem.textContent || '')
                .split(/\n+/)
                .map((value) => value.trim())
                .filter(Boolean);
            const descendants = Array.from(modelItem.querySelectorAll('span'))
                .map((element) => String(element.innerText || element.textContent || '').trim())
                .filter(Boolean);
            const current = normalize(
                lines.length > 1
                    ? lines.slice(1).join(' ')
                    : (descendants.at(-1) || lines.at(-1) || '')
            );
            if (matches(current)) {
                powerButton.click();
                return {ok: true, selected: current, available: [current]};
            }

            modelItem.click();
            return {
                ok: false,
                reason: 'selection-required',
                current,
                available: [current].filter(Boolean),
            };
        }"""
    result: Any = None
    for _attempt in range(CHATGPT_MODEL_VERIFICATION_ATTEMPTS):
        result = page.evaluate(
            model_control_script,
            {"labels": list(remote_labels), "phase": "inspect"},
        )
        if isinstance(result, dict) and (
            result.get("ok") or result.get("reason") == "selection-required"
        ):
            break
        wait_for_timeout(500)
    if isinstance(result, dict) and result.get("ok"):
        _record_model_observation(
            observation,
            observed=str(result.get("selected") or ""),
            available=list(result.get("available") or []),
            attempted_labels=remote_labels,
            menu_text=str(result.get("selected") or ""),
        )
        return True
    if isinstance(result, dict) and result.get("reason") == "selection-required":
        wait_for_timeout(350)
        selection = page.evaluate(
            model_control_script,
            {"labels": list(remote_labels), "phase": "choose"},
        )
        if isinstance(selection, dict) and selection.get("clicked"):
            wait_for_timeout(500)
            result = page.evaluate(
                model_control_script,
                {"labels": list(remote_labels), "phase": "verify"},
            )
            if isinstance(result, dict) and result.get("ok"):
                _record_model_observation(
                    observation,
                    observed=str(result.get("selected") or ""),
                    available=list(result.get("available") or []),
                    attempted_labels=remote_labels,
                    menu_text=str(result.get("selected") or ""),
                )
                return True
        else:
            result = selection
    available = []
    reason = "model-control-unavailable"
    if isinstance(result, dict):
        available = [str(value) for value in result.get("available", []) if str(value).strip()]
        reason = str(result.get("reason") or reason)
    diagnostic = result.get("diagnostic", {}) if isinstance(result, dict) else {}
    available_text = ", ".join(dict.fromkeys(available)) or "none"
    LOGGER.warning(
        "ChatGPT Web could not verify model %s (%s; available: %s; diagnostic: %s).",
        option["label"],
        reason,
        available_text,
        diagnostic,
    )
    _record_model_observation(
        observation,
        observed=str(result.get("current") or "") if isinstance(result, dict) else "",
        available=available,
        attempted_labels=remote_labels,
        menu_text=available_text,
        reason=reason,
    )
    return False


def _select_web_model(
    page: Any,
    browser_kind: str,
    platform: str,
    model: str,
    observation: dict[str, Any] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Select a provider model when its page exposes a compatible model menu."""
    if platform == "chatgpt":
        return _select_chatgpt_model(
            page,
            browser_kind,
            model,
            observation,
            should_stop=should_stop,
        )
    options = _platform_model_options(platform)
    option = next((candidate for candidate in options if candidate["key"] == model), None)
    if option is None:
        raise ValueError(f"Choose a supported {AGENT_PLATFORM_BY_KEY[platform]['label']} model.")
    remote_labels = tuple(option.get("remote_labels") or (option.get("label", ""),))
    result = page.evaluate(
        r"""async ({remoteLabels, platform}) => {
            const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const isVisible = (element) => {
                const style = window.getComputedStyle(element);
                return element.getClientRects().length > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const matches = (value) => {
                const normalized = normalize(value);
                return remoteLabels.some((label) => {
                    const target = normalize(label);
                    return normalized === target || normalized.includes(target);
                });
            };
            const labelFor = (element) => `${element.getAttribute('aria-label') || ''} ${element.innerText || element.textContent || ''}`.trim();
            const triggers = [...document.querySelectorAll('button, [role="button"]')]
                .filter(isVisible)
                .filter((element) => !element.closest('[role="menu"], [role="listbox"]'));
            const trigger = triggers.find((element) => {
                const label = labelFor(element);
                const normalized = normalize(label);
                if (matches(label)) return true;
                if (platform === 'gemini' && /mode picker|model|模式|模型|选择|選擇/i.test(normalized)) return true;
                if (platform === 'grok' && /model|mode|auto|grok|模式|模型|选择|選擇|自動|自动/i.test(normalized)) return true;
                return platform === 'claude' && /model|mode|auto|default|claude|sonnet|opus/i.test(normalized);
            });
            if (!trigger) return {ok: false, reason: 'model-control-not-found', available: []};
            if (matches(labelFor(trigger))) return {ok: true, selected: normalize(labelFor(trigger)), available: []};
            trigger.click();
            let candidates = [];
            for (let attempt = 0; attempt < 10; attempt += 1) {
                await new Promise((resolve) => window.setTimeout(resolve, 100));
                candidates = [...document.querySelectorAll('[role="menuitem"], [role="option"], button')]
                    .filter(isVisible)
                    .filter((element) => element !== trigger)
                    .filter((element) => !/send|submit|attach|upload|dictate/i.test(labelFor(element)));
                const choice = candidates.find((element) => matches(labelFor(element)));
                if (choice) {
                    choice.click();
                    return {
                        ok: true,
                        selected: normalize(labelFor(choice)),
                        available: candidates.map(labelFor).filter(Boolean),
                    };
                }
            }
            return {
                ok: false,
                reason: 'model-not-exposed',
                available: candidates.map(labelFor).filter(Boolean),
            };
        }""",
        {"remoteLabels": list(remote_labels), "platform": platform},
    )
    if isinstance(result, dict) and result.get("ok"):
        return True
    available = []
    reason = "model-control-unavailable"
    if isinstance(result, dict):
        available = [str(value) for value in result.get("available", []) if str(value).strip()]
        reason = str(result.get("reason") or reason)
    LOGGER.info(
        "%s Web did not expose model %s (%s; available: %s); retaining the current remote model.",
        AGENT_PLATFORM_BY_KEY[platform]["label"],
        remote_labels[0],
        reason,
        ", ".join(dict.fromkeys(available)) or "none",
    )
    return False


def _attach_context_file(
    page: Any,
    browser_kind: str,
    context_path: Path,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    """Attach Markdown and require a visible composer readback before claiming success."""
    if browser_kind == "safari" or (callable(should_stop) and should_stop()):
        return False
    file_input = page.locator('input[type="file"]')
    if file_input.count() == 0:
        attach_button = page.locator(
            'button[aria-label*="Attach" i], button[aria-label*="Upload" i], button[data-testid*="attach" i]'
        )
        if (
            not (callable(should_stop) and should_stop())
            and attach_button.count()
            and attach_button.first.is_visible()
        ):
            attach_button.first.click()
    if file_input.count() == 0 or (callable(should_stop) and should_stop()):
        return False
    try:
        if callable(should_stop) and should_stop():
            return False
        file_input.first.set_input_files(str(context_path))
        expected_name = context_path.name
        for _attempt in range(40):
            if callable(should_stop) and should_stop():
                return False
            state = page.evaluate(
                r"""({expectedName}) => {
                    const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
                    const expected = normalize(expectedName);
                    const escapedExpected = expected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const exactFilename = new RegExp(
                        `(^|[^a-z0-9._-])${escapedExpected}($|[^a-z0-9._-])`,
                        'i'
                    );
                    const containsExactFilename = (value) => exactFilename.test(normalize(value));
                    const composer = document.querySelector('#prompt-textarea')
                        || document.querySelector('textarea')
                        || document.querySelector('[contenteditable="true"]');
                    const input = Array.from(document.querySelectorAll('input[type="file"]')).find((element) =>
                        Array.from(element.files || []).some((file) => normalize(file.name) === expected)
                    );
                    const scope = composer?.closest('form')
                        || composer?.parentElement?.parentElement?.parentElement
                        || input?.closest('form')
                        || input?.parentElement;
                    const visible = (element) => {
                        if (!element) return false;
                        const style = getComputedStyle(element);
                        return element.getClientRects().length > 0
                            && style.display !== 'none'
                            && style.visibility !== 'hidden';
                    };
                    const candidates = Array.from(scope?.querySelectorAll(
                        '[data-testid*="attach" i], [data-testid*="file" i], [aria-label], [title], button, span'
                    ) || []).filter(visible);
                    const labels = candidates.map((element) => normalize(
                        `${element.getAttribute('aria-label') || ''} ${element.getAttribute('title') || ''} ${element.innerText || element.textContent || ''}`
                    ));
                    const scopeText = normalize(scope?.innerText || scope?.textContent || '');
                    const failure = labels.find((label) =>
                        containsExactFilename(label)
                        && /failed|unsupported|too large|could not upload|upload error/.test(label)
                    );
                    return {
                        accepted: !failure && (
                            containsExactFilename(scopeText)
                            || labels.some(containsExactFilename)
                        ),
                        failed: Boolean(failure),
                    };
                }""",
                {"expectedName": expected_name},
            )
            if isinstance(state, dict) and state.get("accepted"):
                return True
            if isinstance(state, dict) and state.get("failed"):
                return False
            if callable(should_stop) and should_stop():
                return False
            _web_wait(page, browser_kind, 250)
        LOGGER.info(
            "Web context attachment did not expose a visible %s chip; using on-demand reads.",
            expected_name,
        )
        return False
    except Exception as exc:
        LOGGER.info("Web context attachment fell back to on-demand reads: %s", exc)
        return False


def _submit_and_wait(
    page: Any,
    browser_kind: str,
    message: str,
    should_stop: Callable[[], bool],
    on_submitted: Callable[[], None] | None = None,
    platform: str = DEFAULT_AGENT_PLATFORM,
) -> str:
    """Submit one message and wait for one stable provider response."""
    if should_stop():
        return ""
    selector = _web_assistant_selector(platform)
    baseline = _platform_web_count(page, browser_kind, platform, selector)
    baseline_response = _platform_web_last_text(page, browser_kind, platform, selector)
    if should_stop():
        return ""
    if browser_kind == "safari":
        if platform != "chatgpt":
            raise RuntimeError(f"{AGENT_PLATFORM_BY_KEY[platform]['label']} Agent sessions require Edge or Chrome.")
        _submit_safari_prompt(page, message)
    elif platform == "chatgpt":
        _submit_chromium_prompt(page, message, should_stop)
    else:
        _submit_chromium_web_prompt(page, platform, message, should_stop)
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
        count = _platform_web_count(page, browser_kind, platform, selector)
        latest_response = _platform_web_last_text(page, browser_kind, platform, selector)
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
    raise RuntimeError(f"{AGENT_PLATFORM_BY_KEY[platform]['label']} did not finish the controller turn within 30 minutes.")


def _web_user_selector(platform: str) -> str:
    """Return provider-specific user message selectors for submission acceptance."""
    return {
        "chatgpt": '[data-message-author-role="user"]',
        "gemini": 'user-query, [data-test-id="user-query-content"]',
        "grok": '[data-testid*="user" i], [data-role="user"], [data-message-author-role="user"]',
        "claude": '[data-testid*="human" i], [data-testid*="user" i], [data-role="user"], [data-message-author-role="user"]',
    }.get(platform, '[data-message-author-role="user"]')


def _submit_chromium_web_prompt(
    page: Any,
    platform: str,
    message: str,
    should_stop: Callable[[], bool],
) -> None:
    """Fill a non-ChatGPT Chromium composer and click its enabled semantic send control."""
    if should_stop():
        return
    user_selector = _web_user_selector(platform)
    baseline_user_count = _web_count(page, "chromium", user_selector, platform)
    if should_stop():
        return
    composer = page.locator(_web_composer_selector(platform)).first
    if should_stop():
        return
    composer.fill(message)
    if should_stop():
        return

    deadline = time.monotonic() + CHROMIUM_SEND_BUTTON_TIMEOUT_SECONDS
    keyboard_fallback_at = (
        time.monotonic() + GROK_KEYBOARD_SUBMIT_FALLBACK_SECONDS
        if platform == "grok"
        else None
    )
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        if should_stop():
            return
        result = page.evaluate(
            r"""({platform}) => {
                const isVisible = (element) => {
                    const style = window.getComputedStyle(element);
                    return element.getClientRects().length > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const labelFor = (button) => `${button.getAttribute('aria-label') || ''} ${button.getAttribute('title') || ''} ${button.innerText || button.textContent || ''}`.trim();
                const composer = document.querySelector('textarea, [contenteditable="true"]');
                const scope = composer?.closest('form') || composer?.parentElement?.parentElement || document;
                const scopedButtons = [...scope.querySelectorAll('button')].filter(isVisible);
                const allButtons = [...document.querySelectorAll('button')].filter(isVisible);
                const buttons = [...new Set([...scopedButtons, ...allButtons])];
                const sendButtons = buttons.filter((button) => {
                    const label = labelFor(button);
                    const testId = button.getAttribute('data-testid') || '';
                    return /send|submit|ask|发送|傳送|傳送訊息|发送消息|提交|提問|提问/i.test(label)
                        && !/attach|upload|share|feedback|copy|附加|上传|上傳/i.test(label)
                        || /send|submit|ask|chat-submit/i.test(testId);
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
                    platform,
                    sendButtons: sendButtons.map((button) => ({
                        ariaLabel: button.getAttribute('aria-label') || '',
                        dataTestId: button.getAttribute('data-testid') || '',
                        disabled: Boolean(button.disabled || button.getAttribute('aria-disabled') === 'true'),
                    })),
                };
            }""",
            {"platform": platform},
        )
        if isinstance(result, dict):
            last_state = result
            if result.get("clicked"):
                break
        if (
            platform == "grok"
            and keyboard_fallback_at is not None
            and time.monotonic() >= keyboard_fallback_at
        ):
            press = getattr(composer, "press", None)
            if callable(press):
                press("Enter")
                break
        page.wait_for_timeout(WEB_SEND_BUTTON_POLL_MILLISECONDS)
    else:
        details = json.dumps(last_state, ensure_ascii=False, separators=(",", ":"))[:500]
        raise RuntimeError(
            f"The Chromium browser did not expose an enabled {AGENT_PLATFORM_BY_KEY[platform]['label']} send button: {details}"
        )

    accepted_deadline = time.monotonic() + CHROMIUM_SUBMISSION_ACCEPT_TIMEOUT_SECONDS
    while time.monotonic() < accepted_deadline:
        if should_stop():
            return
        composer_empty = bool(
            page.evaluate(
                """() => {
                    const composer = document.querySelector('textarea, [contenteditable="true"]');
                    if (!composer) return true;
                    return !(composer.value || composer.innerText || composer.textContent || '').trim();
                }"""
            )
        )
        if (
            composer_empty
            or _web_count(page, "chromium", user_selector, platform) > baseline_user_count
            or _web_is_generating(page, "chromium")
        ):
            return
        page.wait_for_timeout(WEB_SEND_BUTTON_POLL_MILLISECONDS)
    raise RuntimeError(
        f"The Chromium browser clicked Send, but {AGENT_PLATFORM_BY_KEY[platform]['label']} did not accept the prompt."
    )


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
    if should_stop():
        return
    user_selector = '[data-message-author-role="user"]'
    baseline_user_count = _web_count(page, "chromium", user_selector)
    if should_stop():
        return
    composer = page.locator("#prompt-textarea")
    if should_stop():
        return
    composer.fill(message)
    if should_stop():
        return

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
    progress_text = normalized.casefold().rstrip(". …")
    provider_progress = re.fullmatch(
        r"(?:thinking|working|searching|analyzing|generating)(?:\s+for\s+\d+(?:\.\d+)?s)?",
        progress_text,
    )
    if not normalized or progress_text in WEB_PROGRESS_TEXT or provider_progress:
        return False
    if is_generating or now - submitted_at < WEB_RESPONSE_MINIMUM_SECONDS:
        return False
    return now - stable_since >= WEB_RESPONSE_STABLE_SECONDS


def _web_count(page: Any, browser_kind: str, selector: str, platform: str = DEFAULT_AGENT_PLATFORM) -> int:
    """Count provider message nodes through the active browser surface."""
    del platform
    if browser_kind == "safari":
        return int(page.evaluate("(selector) => document.querySelectorAll(selector).length", selector) or 0)
    return int(page.locator(selector).count())


def _web_last_text(page: Any, browser_kind: str, selector: str, platform: str = DEFAULT_AGENT_PLATFORM) -> str:
    """Read the last provider action while preserving fenced source text."""
    del platform
    if browser_kind == "safari":
        return str(
            page.evaluate(
                r"""(selector) => {
                    const elements = document.querySelectorAll(selector);
                    const element = elements[elements.length - 1];
                    if (!element) return '';
                    const codeBlocks = Array.from(element.querySelectorAll('pre code'));
                    const actionBlock = codeBlocks.reverse().find((block) =>
                        /[\"']action[\"']\s*:/.test(block.innerText || block.textContent || '')
                    );
                    return actionBlock
                        ? (actionBlock.innerText || actionBlock.textContent || '').trim()
                        : (element.innerText || element.textContent || '').trim();
                }""",
                selector,
            )
            or ""
        )
    elements = page.locator(selector)
    if elements.count() == 0:
        return ""
    latest = elements.last
    code_blocks = latest.locator("pre code")
    for index in range(min(code_blocks.count(), 8) - 1, -1, -1):
        candidate = code_blocks.nth(index).inner_text(timeout=5_000).strip()
        if re.search(r'[\"\']action[\"\']\s*:', candidate):
            return candidate
    return latest.inner_text(timeout=5_000).strip()


def _platform_web_count(page: Any, browser_kind: str, platform: str, selector: str) -> int:
    """Keep the legacy ChatGPT helper call shape while supporting other providers."""
    if platform == "chatgpt":
        return _web_count(page, browser_kind, selector)
    return _web_count(page, browser_kind, selector, platform)


def _platform_web_last_text(page: Any, browser_kind: str, platform: str, selector: str) -> str:
    """Read one provider's latest assistant node through the shared helper."""
    if platform == "chatgpt":
        return _web_last_text(page, browser_kind, selector)
    return _web_last_text(page, browser_kind, selector, platform)


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
                        || /停止(?:生成|回答|串流|流式传输|流式傳輸)?/.test(text)
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
                        || /停止(?:生成|回答|串流|流式传输|流式傳輸)?/.test(text)
                        || /stop-(button|generating|response|streaming)/.test(testId)
                    );
            });
            if (button) button.click();
            return Boolean(button);
        }"""
    )


def _web_wait(page: Any, browser_kind: str, milliseconds: int) -> None:
    page.wait_for_timeout(milliseconds)
