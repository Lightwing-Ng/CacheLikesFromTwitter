"""Managed DevSpace MCP runtime and subscription web-agent bridge.

Code version: v1.3.2-codex.1
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import subprocess
from threading import Event, RLock, Thread
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from .browser_sessions import (
    browser_descriptors,
    goto_with_retry,
    launch_chromium_context,
    sync_playwright_or_error,
)
from .config import CrawlConfig, PROJECT_ROOT
from .safari_automation import SafariContext
from .state import utc_now


LOGGER = logging.getLogger(__name__)
DEFAULT_DEVSPACE_SOURCE_DIR = Path("/Users/lightwing/Desktop/openSource/devspace")
DEFAULT_DEVSPACE_PORT = 7676
DEFAULT_DEVSPACE_SETTINGS_PATH = (
    Path.home()
    / "Library/Application Support/CacheLikesFromTwitter/devspace-agent.json"
)
DEFAULT_DEVSPACE_SECRET_PATH = (
    Path.home()
    / "Library/Application Support/CacheLikesFromTwitter/devspace-owner.json"
)
CHATGPT_HOME_URL = "https://chatgpt.com/"
CHATGPT_HOSTS = {"chatgpt.com", "www.chatgpt.com"}
AGENT_PLATFORM_DEFAULT = "chatgpt"
AGENT_PLATFORM_CONFIG = {
    "chatgpt": {"label": "ChatGPT", "url": CHATGPT_HOME_URL, "hosts": CHATGPT_HOSTS},
    "gemini": {
        "label": "Gemini",
        "url": "https://gemini.google.com/app",
        "hosts": {"gemini.google.com"},
    },
    "grok": {"label": "Grok", "url": "https://grok.com/", "hosts": {"grok.com", "www.grok.com"}},
}
AGENT_PLATFORM_OPTIONS = (
    {"key": "chatgpt", "label": "ChatGPT", "icon_filename": "images/ChatGPT-Logo.svg"},
    {"key": "gemini", "label": "Gemini", "icon_filename": "images/Google_Gemini_logo_2025_symbol.svg"},
    {"key": "grok", "label": "Grok", "icon_filename": "images/grok.svg"},
)


@dataclass(frozen=True, slots=True)
class DevSpaceSettings:
    """Persist the non-secret local DevSpace integration settings."""

    source_dir: str = str(DEFAULT_DEVSPACE_SOURCE_DIR)
    allowed_root: str = str(PROJECT_ROOT)
    public_base_url: str = f"http://127.0.0.1:{DEFAULT_DEVSPACE_PORT}"
    platform: str = AGENT_PLATFORM_DEFAULT
    target_url: str = CHATGPT_HOME_URL
    browser: str = "safari"
    port: int = DEFAULT_DEVSPACE_PORT


@dataclass(slots=True)
class AgentRunSnapshot:
    """Describe one subscription web-agent request without exposing credentials."""

    running: bool = False
    phase: str = "idle"
    message: str = "Ready to ask the selected web agent through DevSpace."
    prompt: str = ""
    workspace_path: str = ""
    response: str = ""
    conversation_url: str = ""
    started_at: str = ""
    finished_at: str = ""
    last_error: str = ""


def is_loopback_address(value: str | None) -> bool:
    """Return whether one request address is local to this machine."""
    candidate = (value or "").strip().split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return candidate.lower() == "localhost"


def load_devspace_settings(
    settings_path: Path = DEFAULT_DEVSPACE_SETTINGS_PATH,
) -> DevSpaceSettings:
    """Load validated DevSpace settings, falling back to local defaults."""
    if not settings_path.exists():
        return DevSpaceSettings()
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        return validate_devspace_settings(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        LOGGER.warning("Ignoring invalid DevSpace integration settings at %s.", settings_path)
        return DevSpaceSettings()


def save_devspace_settings(
    settings: DevSpaceSettings,
    settings_path: Path = DEFAULT_DEVSPACE_SETTINGS_PATH,
) -> None:
    """Persist non-secret DevSpace settings with owner-only permissions."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(asdict(settings), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    settings_path.chmod(0o600)


def validate_devspace_settings(payload: dict[str, Any]) -> DevSpaceSettings:
    """Normalize and validate settings received from the local control page."""
    source_dir = Path(str(payload.get("source_dir", DEFAULT_DEVSPACE_SOURCE_DIR))).expanduser().resolve()
    allowed_root = Path(str(payload.get("allowed_root", PROJECT_ROOT))).expanduser().resolve()
    if not source_dir.is_dir() or not (source_dir / "package.json").is_file():
        raise ValueError(f"DevSpace source directory is invalid: {source_dir}")
    if not allowed_root.is_dir():
        raise ValueError(f"Allowed workspace root is invalid: {allowed_root}")

    try:
        port = int(payload.get("port", DEFAULT_DEVSPACE_PORT))
    except (TypeError, ValueError) as exc:
        raise ValueError("DevSpace port must be an integer.") from exc
    if port < 1_024 or port > 65_535:
        raise ValueError("DevSpace port must be from 1,024 through 65,535.")

    public_base_url = str(
        payload.get("public_base_url", f"http://127.0.0.1:{port}")
    ).strip().rstrip("/")
    public_parts = urlsplit(public_base_url)
    if public_parts.scheme not in {"http", "https"} or not public_parts.hostname:
        raise ValueError("Public base URL must be an HTTP or HTTPS origin.")
    if public_parts.path not in {"", "/"} or public_parts.query or public_parts.fragment:
        raise ValueError("Public base URL must be an origin without /mcp, query, or fragment.")

    platform = str(payload.get("platform", AGENT_PLATFORM_DEFAULT)).strip().lower()
    platform_config = AGENT_PLATFORM_CONFIG.get(platform)
    if platform_config is None:
        raise ValueError("Agent platform must be ChatGPT, Gemini, or Grok.")

    target_url = str(
        payload.get("target_url", payload.get("chatgpt_url", platform_config["url"]))
    ).strip()
    target_parts = urlsplit(target_url)
    if target_parts.scheme != "https" or (target_parts.hostname or "").lower() not in platform_config["hosts"]:
        raise ValueError(f"{platform_config['label']} URL must use the official HTTPS host.")

    browser = str(payload.get("browser", "safari")).strip().lower()
    if browser not in {"chrome", "edge", "safari"}:
        raise ValueError("The Agent workspace supports Safari, Chrome, or Edge.")

    return DevSpaceSettings(
        source_dir=str(source_dir),
        allowed_root=str(allowed_root),
        public_base_url=public_base_url,
        platform=platform,
        target_url=target_url,
        browser=browser,
        port=port,
    )


def resolve_workspace_path(workspace_path: str, allowed_root: str) -> Path:
    """Resolve one workspace and enforce the configured DevSpace root."""
    root = Path(allowed_root).expanduser().resolve()
    workspace = Path(workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace directory was not found: {workspace}")
    try:
        workspace.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Workspace must stay inside the allowed root: {root}") from exc
    return workspace


def get_devspace_owner_token(secret_path: Path = DEFAULT_DEVSPACE_SECRET_PATH) -> str:
    """Return a stable local OAuth owner token without exposing it to the UI."""
    if secret_path.exists():
        try:
            token = str(json.loads(secret_path.read_text(encoding="utf-8"))["owner_token"]).strip()
            if len(token) >= 16:
                return token
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    secret_path.write_text(json.dumps({"owner_token": token}) + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return token


class DevSpaceRuntimeManager:
    """Start and inspect the upstream DevSpace server as an isolated process."""

    def __init__(self, log_path: Path) -> None:
        self._lock = RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None
        self._log_path = log_path
        self._settings = load_devspace_settings()

    @property
    def settings(self) -> DevSpaceSettings:
        return self._settings

    def update_settings(self, settings: DevSpaceSettings) -> None:
        """Persist DevSpace settings when its managed process is stopped."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("Stop DevSpace before changing its settings.")
            save_devspace_settings(settings)
            self._settings = settings

    def snapshot(self) -> dict[str, Any]:
        """Return runtime readiness without leaking the OAuth owner token."""
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None
            ready = self._healthcheck(self._settings.port)
            source_ready = (Path(self._settings.source_dir) / "dist/cli.js").is_file()
            return {
                "running": process_running or ready,
                "managed": process_running,
                "ready": ready,
                "source_ready": source_ready,
                "local_mcp_url": f"http://127.0.0.1:{self._settings.port}/mcp",
                "log_path": str(self._log_path),
                "settings": asdict(self._settings),
            }

    def start(self, settings: DevSpaceSettings) -> dict[str, Any]:
        """Start the built upstream DevSpace server with narrow local authority."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("DevSpace is already running under this application.")
            if self._healthcheck(settings.port):
                raise RuntimeError(f"Port {settings.port} already exposes a DevSpace-compatible service.")

            cli_path = Path(settings.source_dir) / "dist/cli.js"
            if not cli_path.is_file():
                raise RuntimeError(
                    "DevSpace has not been built. Run npm ci --include=dev and npm run build "
                    f"inside {settings.source_dir}."
                )

            save_devspace_settings(settings)
            self._settings = settings
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = self._log_path.open("ab", buffering=0)
            environment = os.environ.copy()
            environment.update(
                {
                    "HOST": "127.0.0.1",
                    "PORT": str(settings.port),
                    "DEVSPACE_ALLOWED_ROOTS": settings.allowed_root,
                    "DEVSPACE_PUBLIC_BASE_URL": settings.public_base_url,
                    "DEVSPACE_OAUTH_OWNER_TOKEN": get_devspace_owner_token(),
                    "DEVSPACE_TOOL_MODE": "codex",
                    "DEVSPACE_WIDGETS": "full",
                    "DEVSPACE_SUBAGENTS": "0",
                }
            )
            self._process = subprocess.Popen(
                ["node", str(cli_path), "serve"],
                cwd=settings.source_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self._healthcheck(settings.port):
                return self.snapshot()
            with self._lock:
                if self._process is not None and self._process.poll() is not None:
                    exit_code = self._process.returncode
                    self._close_log()
                    raise RuntimeError(f"DevSpace exited during startup with code {exit_code}.")
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("DevSpace did not become ready within 15 seconds.")

    def stop(self) -> dict[str, Any]:
        """Stop only the DevSpace process started by this manager."""
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                self._close_log()
                return self.snapshot()
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            finally:
                self._process = None
                self._close_log()
            return self.snapshot()

    def stop_managed_process_at_exit(self) -> None:
        """Avoid leaving the managed child behind without probing idle test instances."""
        with self._lock:
            process_running = self._process is not None and self._process.poll() is None
        if process_running:
            self.stop()

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    @staticmethod
    def _healthcheck(port: int) -> bool:
        try:
            with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.6) as response:
                return response.status == 200
        except (OSError, URLError, ValueError):
            return False


class ChatGPTWebAgentService:
    """Submit one DevSpace-directed request through a signed-in web product."""

    def __init__(
        self,
        runtime: DevSpaceRuntimeManager,
        runner: Callable[..., tuple[str, str]] | None = None,
    ) -> None:
        self._runtime = runtime
        self._runner = runner or run_chatgpt_web_agent
        self._lock = RLock()
        self._snapshot = AgentRunSnapshot()
        self._stop_requested = Event()
        self._worker: Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)

    def start(self, prompt: str, workspace_path: str, config: CrawlConfig) -> None:
        clean_prompt = str(prompt or "").strip()
        if not clean_prompt:
            raise ValueError("Enter a question or task for the agent.")
        settings = self._runtime.settings
        workspace = resolve_workspace_path(workspace_path, settings.allowed_root)
        if not self._runtime.snapshot()["ready"]:
            raise RuntimeError("Start the DevSpace MCP runtime before asking the agent.")

        with self._lock:
            if self._snapshot.running:
                raise RuntimeError("An Agent request is already running.")
            self._stop_requested.clear()
            self._snapshot = AgentRunSnapshot(
                running=True,
                phase="starting",
                message=f"Opening the signed-in {settings.platform.title()} web session.",
                prompt=clean_prompt,
                workspace_path=str(workspace),
                started_at=utc_now(),
            )
            self._worker = Thread(
                target=self._run,
                args=(clean_prompt, str(workspace), config, settings),
                daemon=True,
            )
            self._worker.start()

    def request_stop(self) -> bool:
        with self._lock:
            if not self._snapshot.running:
                return False
            self._stop_requested.set()
            self._snapshot.phase = "stopping"
            self._snapshot.message = "Stop requested. Waiting for the browser task to end."
            return True

    def _run(
        self,
        prompt: str,
        workspace_path: str,
        config: CrawlConfig,
        settings: DevSpaceSettings,
    ) -> None:
        try:
            response, conversation_url = self._runner(
                prompt=prompt,
                workspace_path=workspace_path,
                config=config,
                settings=settings,
                should_stop=self._stop_requested.is_set,
                update=self._update,
            )
            with self._lock:
                stopped = self._stop_requested.is_set()
                self._snapshot.running = False
                self._snapshot.phase = "stopped" if stopped else "finished"
                self._snapshot.message = "Agent request stopped." if stopped else "Agent response completed."
                self._snapshot.response = response
                self._snapshot.conversation_url = conversation_url
                self._snapshot.finished_at = utc_now()
        except Exception as exc:
            LOGGER.exception("Subscription web-agent request failed.")
            with self._lock:
                self._snapshot.running = False
                self._snapshot.phase = "failed"
                self._snapshot.message = str(exc).splitlines()[0][:500]
                self._snapshot.last_error = str(exc)
                self._snapshot.finished_at = utc_now()

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                if hasattr(self._snapshot, key):
                    setattr(self._snapshot, key, value)


def run_chatgpt_web_agent(
    *,
    prompt: str,
    workspace_path: str,
    config: CrawlConfig,
    settings: DevSpaceSettings,
    should_stop: Callable[[], bool],
    update: Callable[..., None],
) -> tuple[str, str]:
    """Run one visible subscription web-agent turn against the DevSpace plugin."""
    descriptor = browser_descriptors(config)[settings.browser]
    platform_config = AGENT_PLATFORM_CONFIG[settings.platform]

    agent_prompt = (
        f"Use the DevSpace plugin for this {platform_config['label']} request. First call open_workspace with "
        f"path {workspace_path!r} in checkout mode. Reuse the returned workspaceId for every "
        "later DevSpace tool call. Follow all project instruction files, work autonomously, "
        "verify material changes, and report the outcome.\n\nUser request:\n"
        f"{prompt}"
    )
    if descriptor.engine == "safari":
        with SafariContext(settings.target_url) as context:
            return _run_safari_web_agent(
                context.primary_page,
                context,
                settings.port,
                agent_prompt,
                platform_config["label"],
                should_stop,
                update,
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
            goto_with_retry(page, settings.target_url, attempts=2, timeout_ms=90_000)
            return _run_chromium_web_agent(
                page,
                context,
                settings.port,
                agent_prompt,
                platform_config["label"],
                should_stop,
                update,
            )

    raise RuntimeError("ChatGPT did not finish the agent request within 30 minutes.")


def _run_chromium_web_agent(
    page: Any,
    context: Any,
    devspace_port: int,
    agent_prompt: str,
    platform_label: str,
    should_stop: Callable[[], bool],
    update: Callable[..., None],
) -> tuple[str, str]:
    """Submit and monitor one agent turn through a Chromium-compatible page."""
    composer_selectors = {
        "chatgpt": "#prompt-textarea",
        "gemini": "textarea",
        "grok": "textarea",
    }
    platform_key = next(
        (key for key, value in AGENT_PLATFORM_CONFIG.items() if value["label"] == platform_label),
        AGENT_PLATFORM_DEFAULT,
    )
    approved_pages: set[int] = set()
    composer = page.locator(composer_selectors[platform_key])
    composer.wait_for(state="visible", timeout=60_000)
    message_selectors = {
        "ChatGPT": '[data-message-author-role="assistant"]',
        "Gemini": "model-response, .model-response-text",
        "Grok": "[data-testid*='response'], [data-testid*='message']",
    }
    assistant_turns = page.locator(message_selectors[platform_label])
    baseline_assistant_count = assistant_turns.count()
    if should_stop():
        return "", page.url

    update(phase="submitting", message=f"Submitting the request to {platform_label}.")
    composer.fill(agent_prompt)
    composer.press("Enter")
    conversation_url = page.url
    update(
        phase="running",
        message=f"{platform_label} is coordinating the DevSpace tools.",
        conversation_url=conversation_url,
    )

    deadline = time.monotonic() + 1_800
    response_text = ""
    while time.monotonic() < deadline:
        if should_stop():
            stop_button = page.get_by_role("button", name="Stop generating")
            if stop_button.count() and stop_button.first.is_visible():
                stop_button.first.click()
            return response_text, page.url

        _approve_pending_devspace_oauth(
            page,
            context,
            devspace_port,
            approved_pages,
            update,
        )
        conversation_url = page.url
        assistant_count = assistant_turns.count()
        if assistant_count > baseline_assistant_count:
            response_text = assistant_turns.last.inner_text(timeout=5_000).strip()
        stop_buttons = page.get_by_role("button", name="Stop generating")
        is_generating = bool(stop_buttons.count() and stop_buttons.first.is_visible())
        approval_buttons = page.locator(
            'button:has-text("Allow"), button:has-text("Approve"), '
            'button:has-text("Confirm"), button:has-text("Continue")'
        )
        if approval_buttons.count() and approval_buttons.first.is_visible():
            update(
                phase="awaiting_approval",
                message=f"{platform_label} is waiting for approval in the live conversation.",
                response=response_text,
                conversation_url=conversation_url,
            )
        else:
            update(
                phase="running",
                message=f"{platform_label} is coordinating the DevSpace tools.",
                response=response_text,
                conversation_url=conversation_url,
            )
        if response_text and not is_generating:
            return response_text, conversation_url
        page.wait_for_timeout(1_000)

    raise RuntimeError(f"{platform_label} did not finish the agent request within 30 minutes.")


def _run_safari_web_agent(
    page: Any,
    context: Any,
    devspace_port: int,
    agent_prompt: str,
    platform_label: str,
    should_stop: Callable[[], bool],
    update: Callable[..., None],
) -> tuple[str, str]:
    """Submit and monitor one agent turn through an authenticated Safari page."""
    selectors = {
        "ChatGPT": {
            "composer": "#prompt-textarea",
            "messages": '[data-message-author-role="assistant"]',
        },
        "Gemini": {
            "composer": "textarea",
            "messages": "model-response, .model-response-text",
        },
        "Grok": {
            "composer": "textarea",
            "messages": "[data-testid*='message'], [data-testid*='response']",
        },
    }[platform_label]
    composer = page.locator(selectors["composer"])
    composer.inner_text(timeout=60_000)
    baseline_count = _safari_count(page, selectors["messages"])
    if should_stop():
        return "", page.url

    update(phase="submitting", message=f"Submitting the request to {platform_label} in Safari.")
    page.evaluate(
        """({selector, value}) => {
            const element = document.querySelector(selector);
            if (!element) throw new Error(`Composer not found: ${selector}`);
            element.focus();
            const setter = Object.getOwnPropertyDescriptor(
                element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLElement.prototype,
                "value",
            )?.set;
            if (setter) setter.call(element, value);
            else element.textContent = value;
            element.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: value}));
            element.dispatchEvent(new KeyboardEvent("keydown", {bubbles: true, key: "Enter", code: "Enter"}));
            element.dispatchEvent(new KeyboardEvent("keyup", {bubbles: true, key: "Enter", code: "Enter"}));
            return true;
        }""",
        {"selector": selectors["composer"], "value": agent_prompt},
    )
    conversation_url = page.url
    update(phase="running", message=f"{platform_label} is coordinating the DevSpace tools.", conversation_url=conversation_url)

    deadline = time.monotonic() + 1_800
    approved_pages: set[int] = set()
    response_text = ""
    while time.monotonic() < deadline:
        if should_stop():
            return response_text, page.url
        _approve_pending_devspace_oauth(
            page,
            context,
            devspace_port,
            approved_pages,
            update,
        )
        count = _safari_count(page, selectors["messages"])
        if count > baseline_count:
            response_text = _safari_last_text(page, selectors["messages"])
        approval_visible = _safari_has_approval(page)
        update(
            phase="awaiting_approval" if approval_visible else "running",
            message=(
                f"{platform_label} is waiting for approval in the live conversation."
                if approval_visible
                else f"{platform_label} is coordinating the DevSpace tools."
            ),
            response=response_text,
            conversation_url=page.url,
        )
        if response_text and not _safari_is_generating(page):
            return response_text, page.url
        page.wait_for_timeout(1_000)
    raise RuntimeError(f"{platform_label} did not finish the agent request within 30 minutes.")


def _approve_pending_devspace_oauth(
    primary_page: Any,
    context: Any,
    devspace_port: int,
    approved_pages: set[int],
    update: Callable[..., None],
) -> bool:
    """Authorize the exact local DevSpace owner-password page without user copy/paste."""
    pages = list(getattr(context, "pages", ()) or ())
    if primary_page not in pages:
        pages.insert(0, primary_page)

    for page in pages:
        page_id = id(page)
        if page_id in approved_pages or not _is_local_devspace_page(page, devspace_port):
            continue
        try:
            submitted = bool(
                page.evaluate(
                    """({ownerToken}) => {
                        const input = document.querySelector(
                            'input#owner_token[name="owner_token"]',
                        );
                        const form = input?.form;
                        const submit = form?.querySelector('button[type="submit"]');
                        if (!input || !form || !submit) return false;
                        const setter = Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype,
                            "value",
                        )?.set;
                        if (setter) setter.call(input, ownerToken);
                        else input.value = ownerToken;
                        input.dispatchEvent(new Event("input", {bubbles: true}));
                        input.dispatchEvent(new Event("change", {bubbles: true}));
                        if (typeof form.requestSubmit === "function") form.requestSubmit(submit);
                        else submit.click();
                        return true;
                    }""",
                    {"ownerToken": get_devspace_owner_token()},
                )
            )
        except Exception as exc:  # Browser pages can disappear during OAuth redirects.
            LOGGER.debug("DevSpace OAuth page was unavailable during automatic approval: %s", exc)
            continue
        if submitted:
            approved_pages.add(page_id)
            update(
                phase="authorizing",
                message="Authorizing the local DevSpace connection automatically.",
            )
            return True
    return False


def _is_local_devspace_page(page: Any, devspace_port: int) -> bool:
    """Return whether a browser page is the configured local DevSpace origin."""
    try:
        parsed = urlsplit(str(page.url or ""))
        page_port = parsed.port
    except Exception:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost"}
        and page_port == int(devspace_port)
    )


def _safari_count(page: Any, selector: str) -> int:
    """Count matching Safari DOM elements through the page's JavaScript bridge."""
    return int(page.evaluate("(selector) => document.querySelectorAll(selector).length", selector) or 0)


def _safari_last_text(page: Any, selector: str) -> str:
    """Read the last matching Safari DOM element as plain text."""
    return str(
        page.evaluate(
            """(selector) => {
                const elements = document.querySelectorAll(selector);
                const element = elements[elements.length - 1];
                return element ? (element.innerText || element.textContent || "").trim() : "";
            }""",
            selector,
        )
        or ""
    )


def _safari_has_approval(page: Any) -> bool:
    """Detect explicit approval controls without clicking them automatically."""
    return bool(
        page.evaluate(
            """() => Array.from(document.querySelectorAll("button")).some((button) => {
                const text = (button.innerText || button.textContent || "").trim().toLowerCase();
                return button.offsetParent !== null && /allow|approve|confirm|continue/.test(text);
            })"""
        )
    )


def _safari_is_generating(page: Any) -> bool:
    """Detect an active generation indicator in Safari."""
    return bool(
        page.evaluate(
            """() => Array.from(document.querySelectorAll("button")).some((button) => {
                const text = (button.innerText || button.textContent || "").trim().toLowerCase();
                return button.offsetParent !== null && /stop generating|stop response/.test(text);
            })"""
        )
    )
