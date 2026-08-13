"""Minimal Safari automation primitives backed by Apple Events."""

# Code version: v1.7.5-codex.1

from __future__ import annotations

import base64
import contextlib
import fcntl
import json
import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlsplit


SAFARI_DOWNLOAD_RANGE_BYTES = 512 * 1024
SAFARI_BASE64_SLICE_BYTES = 96 * 1024
SAFARI_RESPONSE_TEXT_SLICE_CHARS = 96 * 1024
SAFARI_POLL_INTERVAL_SECONDS = 0.2
SAFARI_APPLESCRIPT_RETRY_LIMIT = 2
SAFARI_APPLESCRIPT_RETRY_DELAY_SECONDS = 0.25
SAFARI_NAVIGATION_RETRY_LIMIT = 3
SAFARI_NAVIGATION_RETRY_DELAY_SECONDS = 0.5
SAFARI_WRONG_PAGE_GRACE_SECONDS = 1.0
SAFARI_CLOSE_RETRY_LIMIT = 3
SAFARI_WINDOW_CREATION_LOCK = RLock()
SAFARI_WINDOW_CREATION_LOCK_PATH = Path(tempfile.gettempdir()) / "cachelikes-safari-window-creation.lock"
SAFARI_CAPTURE_FRONT_WINDOW_APPLESCRIPT = """
set previousWindowId to 0
set previousWindowWasVisible to false
set previousWindowWasMiniaturized to false
if (count of windows) > 0 then
    set previousWindowId to id of front window
    try
        set previousWindowWasVisible to visible of front window
    end try
    try
        set previousWindowWasMiniaturized to miniaturized of front window
    end try
end if
""".strip()
SAFARI_HIDE_WINDOW_APPLESCRIPT = """
set bounds of targetWindow to {-32000, -32000, -30720, -31100}
try
    set visible of targetWindow to false
end try
set miniaturized of targetWindow to true
""".strip()
SAFARI_RESTORE_FRONT_WINDOW_APPLESCRIPT = """
if previousWindowId is not 0 and previousWindowWasVisible and not previousWindowWasMiniaturized then
    try
        set index of (first window whose id is previousWindowId) to 1
    end try
end if
""".strip()
SAFARI_BACKGROUND_WINDOW_APPLESCRIPT = (
    f"{SAFARI_HIDE_WINDOW_APPLESCRIPT}\n{SAFARI_RESTORE_FRONT_WINDOW_APPLESCRIPT}"
)


logger = logging.getLogger(__name__)


def is_missing_safari_window_error(error: BaseException) -> bool:
    """Return whether Safari rejected an operation for a window that vanished."""
    message = str(error).lower()
    return (
        ("invalid index" in message and ("window" in message or "tab" in message))
        or "can't get current tab" in message
        or "can’t get current tab" in message
        or "can't get window" in message
        or "can’t get window" in message
    )


def safari_navigation_matches(target_url: str, current_url: str) -> bool:
    """Return whether Safari reached the requested page or its authentication flow."""
    normalized_target = str(target_url or "").strip()
    normalized_current = str(current_url or "").strip()
    if not normalized_target or not normalized_current:
        return False
    if normalized_target in {"about:blank", "favorites://"}:
        return normalized_current == normalized_target

    target = urlsplit(normalized_target)
    current = urlsplit(normalized_current)
    if target.scheme not in {"http", "https"}:
        return normalized_current == normalized_target
    if current.scheme not in {"http", "https"}:
        return False

    target_host = target.netloc.casefold()
    current_host = current.netloc.casefold()
    target_path = target.path.rstrip("/") or "/"
    current_path = current.path.rstrip("/") or "/"
    if current_host == target_host and current_path == target_path:
        return True

    authentication_hosts = {"auth.openai.com", "auth0.openai.com"}
    authentication_paths = ("/auth", "/login", "/i/flow/login", "/account/login")
    return current_host in authentication_hosts or (
        current_host == target_host and current_path.startswith(authentication_paths)
    )


def escape_applescript_text(value: str) -> str:
    """Escape text embedded in an AppleScript string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def run_applescript(source: str) -> str:
    """Run one AppleScript program and return its standard output."""
    last_error = ""
    for attempt_index in range(SAFARI_APPLESCRIPT_RETRY_LIMIT + 1):
        process = subprocess.run(
            ["osascript"],
            input=source,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode == 0:
            return (process.stdout or "").rstrip("\n")
        last_error = (process.stderr or process.stdout or "").strip()
        if attempt_index >= SAFARI_APPLESCRIPT_RETRY_LIMIT:
            break
        lowered = last_error.lower()
        if not any(
            marker in lowered
            for marker in ("-1712", "-1719", "-609", "-600", "timed out", "connection is invalid")
        ):
            break
        time.sleep(SAFARI_APPLESCRIPT_RETRY_DELAY_SECONDS * (attempt_index + 1))
    raise RuntimeError(last_error or "Safari automation failed.")


@contextlib.contextmanager
def safari_window_creation_guard():
    """Serialize front-window capture across threads and local app processes."""
    with SAFARI_WINDOW_CREATION_LOCK:
        with SAFARI_WINDOW_CREATION_LOCK_PATH.open("a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


@dataclass(slots=True)
class SafariRequest:
    """Expose request headers without exporting Safari cookies."""

    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SafariResponse:
    """Expose the browser-response surface used by authenticated resolvers."""

    status: int
    body_text: str
    headers: dict[str, str] = field(default_factory=dict)
    request: SafariRequest = field(default_factory=SafariRequest)

    @property
    def ok(self) -> bool:
        """Return whether the request completed successfully."""
        return 200 <= self.status < 300

    def text(self) -> str:
        """Return the response body."""
        return self.body_text


class SafariRequestClient:
    """Issue same-origin requests inside an authenticated Safari page."""

    def __init__(self, context: SafariContext) -> None:
        self._context = context

    def get(
        self,
        url: str,
        timeout: int,
        headers: dict[str, str] | None = None,
    ) -> SafariResponse:
        """Fetch one text response inside the authenticated Safari page."""
        return self.get_from_page(
            self._context.primary_page,
            url,
            timeout,
            headers,
            serialize=True,
        )

    def get_from_page(
        self,
        page: SafariPage,
        url: str,
        timeout: int,
        headers: dict[str, str] | None = None,
        *,
        serialize: bool = False,
    ) -> SafariResponse:
        """Fetch through one owned page so separate Safari windows can run concurrently."""
        if page.context is not self._context:
            raise RuntimeError("Safari request page belongs to a different browser context.")
        last_error: RuntimeError | None = None
        for attempt_index in range(3):
            try:
                return self._get_once(page, url, timeout, headers or {}, serialize=serialize)
            except RuntimeError as exc:
                last_error = exc
                error_text = str(exc).lower()
                retryable = any(
                    marker in error_text
                    for marker in (
                        "request state disappeared",
                        "load failed",
                        "failed to fetch",
                        "fetch is aborted",
                    )
                )
                if not retryable or attempt_index >= 2:
                    raise
                if "request state disappeared" in error_text:
                    page.wait_for_load_state(
                        "domcontentloaded",
                        min(max(1, int(timeout)), 60_000),
                    )
                if any(
                    marker in error_text
                    for marker in ("load failed", "failed to fetch", "fetch is aborted")
                ):
                    # Safari can reject fetch from a hidden/minimized document. Make the
                    # owned window render-active offscreen, then retry without stealing focus.
                    with contextlib.suppress(RuntimeError):
                        page.keep_rendering_offscreen()
                time.sleep(SAFARI_APPLESCRIPT_RETRY_DELAY_SECONDS)
        raise last_error or RuntimeError("Safari request failed.")

    def _get_once(
        self,
        page: SafariPage,
        url: str,
        timeout: int,
        headers: dict[str, str],
        *,
        serialize: bool,
    ) -> SafariResponse:
        request_headers, referrer = _split_fetch_headers(headers)
        timeout_ms = max(1, int(timeout))
        request_guard = self._context.request_lock if serialize else contextlib.nullcontext()
        with request_guard:
            page.evaluate(
                """(request) => {
                    const controller = new AbortController();
                    window.__cachelikesSafariRequest = {
                        state: "pending",
                        controller,
                    };
                    const timeoutId = setTimeout(() => controller.abort(), request.timeoutMs);
                    const options = {
                        credentials: "include",
                        cache: "no-store",
                        headers: request.headers,
                        signal: controller.signal,
                    };
                    if (request.referrer) options.referrer = request.referrer;
                    fetch(request.url, options).then(async (response) => {
                        const responseHeaders = {};
                        response.headers.forEach((value, key) => {
                            responseHeaders[key] = value;
                        });
                        const bodyText = await response.text();
                        clearTimeout(timeoutId);
                        window.__cachelikesSafariRequest = {
                            state: "ready",
                            status: response.status,
                            headers: responseHeaders,
                            bodyText,
                        };
                    }).catch((error) => {
                        clearTimeout(timeoutId);
                        window.__cachelikesSafariRequest = {
                            state: "failed",
                            error: String(error && error.message ? error.message : error),
                        };
                    });
                    return true;
                }""",
                {
                    "url": url,
                    "timeoutMs": timeout_ms,
                    "headers": request_headers,
                    "referrer": referrer,
                },
            )

            deadline = time.monotonic() + timeout_ms / 1_000 + 5
            metadata: dict[str, Any] = {}
            cleaned_inline = False
            try:
                while time.monotonic() < deadline:
                    raw_metadata = page.evaluate(
                        """(inlineLimit) => {
                            const current = window.__cachelikesSafariRequest;
                            if (!current) return { state: "missing" };
                            const bodyLength = current.bodyText ? current.bodyText.length : 0;
                            const result = {
                                state: current.state || "missing",
                                status: current.status || 0,
                                headers: current.headers || {},
                                bodyLength,
                                error: current.error || "",
                            };
                            if (current.state === "ready" && bodyLength <= inlineLimit) {
                                result.bodyText = current.bodyText || "";
                                result.cleanedInline = true;
                                delete window.__cachelikesSafariRequest;
                            }
                            return result;
                        }""",
                        SAFARI_RESPONSE_TEXT_SLICE_CHARS,
                    )
                    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                    state = str(metadata.get("state") or "missing")
                    if state == "ready":
                        break
                    if state == "failed":
                        raise RuntimeError(
                            f"Safari request failed: {metadata.get('error') or 'unknown error'}"
                        )
                    if state == "missing":
                        raise RuntimeError("Safari request state disappeared while the page was loading.")
                    time.sleep(SAFARI_POLL_INTERVAL_SECONDS)
                else:
                    raise RuntimeError(f"Safari request timed out after {timeout_ms:,} ms.")

                body_length = max(0, int(metadata.get("bodyLength") or 0))
                cleaned_inline = bool(metadata.get("cleanedInline"))
                body_parts: list[str] = [str(metadata.get("bodyText") or "")] if cleaned_inline else []
                slice_start = 0
                while not cleaned_inline and slice_start < body_length:
                    raw_slice = page.evaluate(
                        """(bounds) => {
                            const text = window.__cachelikesSafariRequest.bodyText || "";
                            let end = Math.min(text.length, bounds.end);
                            if (
                                end < text.length &&
                                end > bounds.start &&
                                /[\\uD800-\\uDBFF]/.test(text.charAt(end - 1))
                            ) {
                                end -= 1;
                            }
                            return { text: text.slice(bounds.start, end), end };
                        }""",
                        {
                            "start": slice_start,
                            "end": min(
                                body_length,
                                slice_start + SAFARI_RESPONSE_TEXT_SLICE_CHARS,
                            ),
                        },
                    )
                    if not isinstance(raw_slice, dict):
                        raise RuntimeError("Safari returned an invalid response text slice.")
                    slice_end = int(raw_slice.get("end") or 0)
                    if slice_end <= slice_start:
                        raise RuntimeError("Safari response text slicing stopped making progress.")
                    body_parts.append(str(raw_slice.get("text") or ""))
                    slice_start = slice_end
                response_headers = metadata.get("headers")
                return SafariResponse(
                    status=int(metadata.get("status") or 0),
                    body_text="".join(body_parts),
                    headers={
                        str(key).lower(): str(value)
                        for key, value in (
                            response_headers.items()
                            if isinstance(response_headers, dict)
                            else ()
                        )
                    },
                    request=SafariRequest(headers=dict(headers)),
                )
            finally:
                if not cleaned_inline:
                    with contextlib.suppress(RuntimeError):
                        page.evaluate(
                            """() => {
                                const current = window.__cachelikesSafariRequest;
                                if (current && current.controller) current.controller.abort();
                                delete window.__cachelikesSafariRequest;
                                return true;
                            }"""
                        )


class SafariLocator:
    """Expose the locator operation required by shared page-readiness checks."""

    def __init__(self, page: SafariPage, selector: str) -> None:
        self._page = page
        self._selector = selector

    def inner_text(self, timeout: int = 30_000) -> str:
        """Return text from the first matching element within a bounded wait."""
        deadline = time.monotonic() + max(0.001, int(timeout) / 1_000)
        while time.monotonic() < deadline:
            payload = self._page.evaluate(
                """(selector) => {
                    const element = document.querySelector(selector);
                    return {
                        found: Boolean(element),
                        text: element ? (element.innerText || element.textContent || "") : "",
                    };
                }""",
                self._selector,
            )
            if isinstance(payload, dict) and payload.get("found"):
                return str(payload.get("text") or "")
            time.sleep(SAFARI_POLL_INTERVAL_SECONDS)
        raise RuntimeError(f"Safari did not find selector {self._selector!r} within {timeout:,} ms.")


class SafariPage:
    """Represent one Safari window owned by the current sync."""

    def __init__(self, context: SafariContext, window_id: int) -> None:
        self._context = context
        self.window_id = int(window_id)
        self._closed = False
        self._rendering_active = False
        self._recovery_url = context.initial_url if not context.pages else "about:blank"

    @property
    def context(self) -> SafariContext:
        """Return the owning Safari context."""
        return self._context

    @property
    def url(self) -> str:
        """Return the current tab URL."""
        return self._run_in_window("return URL of current tab of targetWindow").strip()

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 60_000) -> None:
        """Navigate the current tab with retries and verify the destination URL."""
        target_url = str(url or "").strip()
        if not target_url:
            raise RuntimeError("Safari cannot navigate to an empty URL.")
        self._recovery_url = target_url
        accepted_states = {"complete"}
        if wait_until in {"commit", "domcontentloaded"}:
            accepted_states.add("interactive")

        timeout_seconds = max(1.0, int(timeout) / 1_000)
        deadline = time.monotonic() + timeout_seconds
        last_error: RuntimeError | None = None
        last_url = ""

        try:
            initial_state = self._read_navigation_state()
        except RuntimeError as exc:
            last_error = exc
            initial_state = None
        if initial_state is not None:
            last_url = str(initial_state.get("href") or "")
            if (
                str(initial_state.get("readyState") or "") in accepted_states
                and safari_navigation_matches(target_url, last_url)
            ):
                self._keep_in_background()
                return

        for attempt_index in range(SAFARI_NAVIGATION_RETRY_LIMIT):
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                break
            attempts_remaining = SAFARI_NAVIGATION_RETRY_LIMIT - attempt_index
            attempt_deadline = min(
                deadline,
                time.monotonic() + max(2.0, remaining_seconds / attempts_remaining),
            )
            try:
                self._run_in_window(
                    f'set URL of current tab of targetWindow to "{escape_applescript_text(target_url)}"'
                )
            except RuntimeError as exc:
                last_error = exc
                if attempt_index + 1 < SAFARI_NAVIGATION_RETRY_LIMIT:
                    time.sleep(
                        min(
                            SAFARI_NAVIGATION_RETRY_DELAY_SECONDS * (attempt_index + 1),
                            max(0.0, deadline - time.monotonic()),
                        )
                    )
                continue

            wrong_page_since = 0.0
            while time.monotonic() < attempt_deadline:
                try:
                    navigation_state = self._read_navigation_state()
                except RuntimeError as exc:
                    last_error = exc
                    navigation_state = None
                if navigation_state is not None:
                    ready_state = str(navigation_state.get("readyState") or "")
                    last_url = str(navigation_state.get("href") or "")
                    if ready_state in accepted_states and safari_navigation_matches(target_url, last_url):
                        self._keep_in_background()
                        return
                    if ready_state in accepted_states and last_url in {"about:blank", "favorites://"}:
                        if not wrong_page_since:
                            wrong_page_since = time.monotonic()
                        elif time.monotonic() - wrong_page_since >= SAFARI_WRONG_PAGE_GRACE_SECONDS:
                            break
                    else:
                        wrong_page_since = 0.0
                time.sleep(SAFARI_POLL_INTERVAL_SECONDS)

            if attempt_index + 1 < SAFARI_NAVIGATION_RETRY_LIMIT:
                time.sleep(
                    min(
                        SAFARI_NAVIGATION_RETRY_DELAY_SECONDS * (attempt_index + 1),
                        max(0.0, deadline - time.monotonic()),
                    )
                )

        details = []
        if last_url:
            details.append(f"last page was {last_url}")
        if last_error is not None:
            details.append(f"last Safari error was {last_error}")
        detail_text = f" ({'; '.join(details)})" if details else ""
        raise RuntimeError(
            f"Safari did not finish loading {target_url} within {int(timeout):,} ms{detail_text}."
        )

    def _keep_in_background(self) -> None:
        """Reassert the owned window's offscreen state after navigation commits."""
        self._rendering_active = False
        self._run_in_window(SAFARI_HIDE_WINDOW_APPLESCRIPT)

    def _read_navigation_state(self) -> dict[str, str] | None:
        """Return Safari's native URL and DOM readiness during navigation."""
        raw_state = self._run_in_window(
            """
set pageUrlValue to ""
set pageStateValue to ""
try
    set candidateUrl to URL of current tab of targetWindow
    if candidateUrl is not missing value then set pageUrlValue to candidateUrl as text
end try
try
    set candidateState to do JavaScript "document.readyState || ''" in current tab of targetWindow
    if candidateState is not missing value then set pageStateValue to candidateState as text
end try
return pageUrlValue & linefeed & pageStateValue
""".strip()
        )
        state_lines = raw_state.split("\n", maxsplit=1)
        return {
            "href": state_lines[0].strip() if state_lines else "",
            "readyState": state_lines[1].strip() if len(state_lines) > 1 else "",
        }

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        """Wait for DOM readiness; Safari does not expose network-idle state."""
        accepted_states = {"complete"}
        if state in {"commit", "domcontentloaded"}:
            accepted_states.add("interactive")
        deadline = time.monotonic() + max(1.0, timeout / 1_000)
        last_error: RuntimeError | None = None
        while time.monotonic() < deadline:
            try:
                if self.evaluate("() => document.readyState") in accepted_states:
                    return
            except RuntimeError as exc:
                last_error = exc
            time.sleep(SAFARI_POLL_INTERVAL_SECONDS)
        detail = f" Last Safari error: {last_error}" if last_error is not None else ""
        raise RuntimeError(f"Safari did not reach load state {state!r} within {timeout:,} ms.{detail}")

    def wait_for_timeout(self, milliseconds: int) -> None:
        """Pause for a Playwright-compatible millisecond interval."""
        time.sleep(max(0, int(milliseconds)) / 1_000)

    def title(self) -> str:
        """Return the current document title."""
        return str(self.evaluate("() => document.title"))

    def locator(self, selector: str) -> SafariLocator:
        """Return a minimal locator bound to this page."""
        return SafariLocator(self, selector)

    def evaluate(self, expression: str, argument: Any = None) -> Any:
        """Evaluate a Playwright-style page function and decode its result."""
        function_source = str(expression or "").strip()
        argument_json = json.dumps(argument, separators=(",", ":"))
        invocation = f"({function_source})({argument_json})"
        wrapper = f"""
(() => {{
    try {{
        const value = {invocation};
        return JSON.stringify({{ ok: true, value }});
    }} catch (error) {{
        return JSON.stringify({{
            ok: false,
            error: String(error && error.message ? error.message : error),
        }});
    }}
}})()
""".strip()
        raw_result = self._run_in_window(
            f'return do JavaScript "{escape_applescript_text(wrapper)}" in current tab of targetWindow'
        )
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Safari returned an unreadable JavaScript result.") from exc
        if not payload.get("ok"):
            raise RuntimeError(f"Safari JavaScript failed: {payload.get('error') or 'unknown error'}")
        return payload.get("value")

    def bring_to_front(self) -> None:
        """Bring the owned Safari window forward."""
        self._run_in_window("set index of targetWindow to 1")

    def keep_rendering_offscreen(self) -> None:
        """Keep an offscreen window render-active without replacing the user's front window."""
        self._run_in_window(
            """
set previousWindowId to 0
try
    set previousWindowId to id of front window
end try
set bounds of targetWindow to {-32000, -32000, -30720, -31100}
try
    set miniaturized of targetWindow to false
end try
try
    set visible of targetWindow to true
end try
        if previousWindowId is not 0 and previousWindowId is not id of targetWindow then
    try
        set index of (first window whose id is previousWindowId) to 1
    end try
end if
""".strip()
        )
        self._rendering_active = True

    def keep_background(self) -> None:
        """Keep the owned window hidden and minimized without changing Safari focus."""
        self._rendering_active = False
        self._run_in_window(SAFARI_HIDE_WINDOW_APPLESCRIPT)

    def close(self) -> None:
        """Release this page into an invisible reusable Safari window shell."""
        if self._closed:
            return
        with safari_window_creation_guard():
            last_error = self._release_to_background_shell()
        if last_error is not None:
            logger.warning(
                "Safari could not fully release background window %s: %s",
                self.window_id,
                last_error,
            )
        self._closed = True
        self._context._forget_page(self)

    def _release_to_background_shell(self) -> RuntimeError | None:
        """Navigate to a stable blank document before hiding and minimizing the window."""
        last_error: RuntimeError | None = None
        for attempt_index in range(SAFARI_CLOSE_RETRY_LIMIT):
            try:
                release_state = self._run_in_window(
                    """
if (count of tabs of targetWindow) > 0 then
    set URL of current tab of targetWindow to "about:blank"
    repeat with releasePollIndex from 1 to 10
        delay 0.1
        set releasedUrl to ""
        set releasedState to ""
        try
            set candidateUrl to URL of current tab of targetWindow
            if candidateUrl is not missing value then set releasedUrl to candidateUrl as text
        end try
        try
            set candidateState to do JavaScript "document.readyState || ''" in current tab of targetWindow
            if candidateState is not missing value then set releasedState to candidateState as text
        end try
        if releasedUrl is "about:blank" and releasedState is "complete" then exit repeat
    end repeat
end if
set bounds of targetWindow to {-32000, -32000, -30720, -31100}
try
    set visible of targetWindow to false
end try
set miniaturized of targetWindow to true
delay 0.1
set bounds of targetWindow to {-32000, -32000, -30720, -31100}
try
    set visible of targetWindow to false
end try
set miniaturized of targetWindow to true
set releasedUrl to ""
if (count of tabs of targetWindow) > 0 then
    try
        set candidateUrl to URL of current tab of targetWindow
        if candidateUrl is not missing value then set releasedUrl to candidateUrl as text
    end try
end if
return (count of tabs of targetWindow as text) & "|" & releasedUrl & "|" & ¬
    (visible of targetWindow as text) & "|" & (miniaturized of targetWindow as text)
""".strip(),
                    recover_missing=False,
                ).strip()
                if release_state == "1|about:blank|false|true":
                    last_error = None
                    break
                last_error = RuntimeError(
                    f"Safari window {self.window_id} returned unexpected release state {release_state!r}."
                )
            except RuntimeError as exc:
                if is_missing_safari_window_error(exc):
                    last_error = None
                    break
                last_error = exc
            if attempt_index + 1 < SAFARI_CLOSE_RETRY_LIMIT:
                time.sleep(SAFARI_APPLESCRIPT_RETRY_DELAY_SECONDS * (attempt_index + 1))
        return last_error

    def download_to_path(
        self,
        source_url: str,
        destination_path: Path,
        should_stop,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, bool]:
        """Stream an authenticated media URL from Safari into a local file."""
        with self._context.download_lock:
            if not self._rendering_active:
                with contextlib.suppress(RuntimeError):
                    self.keep_rendering_offscreen()
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            initial_bytes = destination_path.stat().st_size if destination_path.exists() else 0
            range_start = initial_bytes
            content_type = ""
            expected_total = 0

            restarted_after_range_error = False
            while expected_total == 0 or range_start < expected_total:
                if should_stop():
                    raise RuntimeError("Stop requested while downloading browser media.")

                range_end = range_start + SAFARI_DOWNLOAD_RANGE_BYTES - 1
                request_headers, referrer = _split_fetch_headers(headers or {})
                request_payload = {
                    "sourceUrl": source_url,
                    "rangeHeader": f"bytes={range_start}-{range_end}",
                    "headers": request_headers,
                    "referrer": referrer,
                }
                self.evaluate(
                    """(request) => {
                        window.__cachelikesSafariDownload = { state: "pending" };
                        const options = {
                            credentials: "include",
                            cache: "no-store",
                            headers: { ...request.headers, Range: request.rangeHeader },
                        };
                        if (request.referrer) options.referrer = request.referrer;
                        fetch(request.sourceUrl, options).then(async (response) => {
                            const bytes = new Uint8Array(await response.arrayBuffer());
                            window.__cachelikesSafariDownload = {
                                state: "ready",
                                status: response.status,
                                contentType: response.headers.get("content-type") || "",
                                contentRange: response.headers.get("content-range") || "",
                                contentLength: response.headers.get("content-length") || "",
                                bytes,
                            };
                        }).catch((error) => {
                            window.__cachelikesSafariDownload = {
                                state: "failed",
                                error: String(error && error.message ? error.message : error),
                            };
                        });
                        return true;
                    }""",
                    request_payload,
                )

                metadata = self._wait_for_download_chunk(should_stop)
                status = int(metadata.get("status") or 0)
                chunk_bytes = int(metadata.get("bytes") or 0)
                if status == 416 and range_start > 0 and not restarted_after_range_error:
                    # A stale partial file can be exactly at the remote EOF, or the
                    # asset may have changed since the partial was written. Safari
                    # reports that as 416 instead of returning an empty range.
                    destination_path.unlink(missing_ok=True)
                    range_start = 0
                    expected_total = 0
                    content_type = ""
                    restarted_after_range_error = True
                    self.evaluate(
                        """() => {
                            delete window.__cachelikesSafariDownload;
                            return true;
                        }"""
                    )
                    continue
                if status not in {200, 206} or chunk_bytes <= 0:
                    raise RuntimeError(
                        f"Safari media request returned HTTP {status} with {chunk_bytes:,} bytes."
                    )
                if range_start > 0 and status != 206:
                    destination_path.unlink(missing_ok=True)
                    if not restarted_after_range_error:
                        range_start = 0
                        expected_total = 0
                        content_type = ""
                        restarted_after_range_error = True
                        continue
                    raise RuntimeError("Safari media server did not honor the resume range.")

                content_range = str(metadata.get("contentRange") or "")
                range_match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range)
                if range_match:
                    response_start = int(range_match.group(1))
                    if response_start != range_start:
                        if not restarted_after_range_error:
                            destination_path.unlink(missing_ok=True)
                            range_start = 0
                            expected_total = 0
                            content_type = ""
                            restarted_after_range_error = True
                            continue
                        raise RuntimeError(
                            f"Safari media server resumed at byte {response_start:,}, expected {range_start:,}."
                        )
                    expected_total = int(range_match.group(3))
                elif status == 200:
                    expected_total = chunk_bytes

                content_type = str(metadata.get("contentType") or content_type)
                mode = "ab" if range_start > 0 else "wb"
                with destination_path.open(mode) as handle:
                    slice_start = 0
                    while slice_start < chunk_bytes:
                        if should_stop():
                            raise RuntimeError("Stop requested while downloading browser media.")
                        slice_end = min(chunk_bytes, slice_start + SAFARI_BASE64_SLICE_BYTES)
                        encoded = self.evaluate(
                            """(bounds) => {
                                const bytes = window.__cachelikesSafariDownload.bytes;
                                let binary = "";
                                for (let index = bounds.start; index < bounds.end; index += 1) {
                                    binary += String.fromCharCode(bytes[index]);
                                }
                                return btoa(binary);
                            }""",
                            {"start": slice_start, "end": slice_end},
                        )
                        handle.write(base64.b64decode(str(encoded)))
                        slice_start = slice_end

                range_start += chunk_bytes
                self.evaluate(
                    """() => {
                        delete window.__cachelikesSafariDownload;
                        return true;
                    }"""
                )
                if status == 200:
                    break

            return content_type, initial_bytes > 0

    def _wait_for_download_chunk(self, should_stop) -> dict[str, Any]:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if should_stop():
                raise RuntimeError("Stop requested while downloading Grok media.")
            metadata = self.evaluate(
                """() => {
                    const current = window.__cachelikesSafariDownload || { state: "missing" };
                    return {
                        state: current.state || "missing",
                        status: current.status || 0,
                        contentType: current.contentType || "",
                        contentRange: current.contentRange || "",
                        contentLength: current.contentLength || "",
                        bytes: current.bytes ? current.bytes.byteLength : 0,
                        error: current.error || "",
                    };
                }"""
            )
            if isinstance(metadata, dict) and metadata.get("state") == "ready":
                return metadata
            if isinstance(metadata, dict) and metadata.get("state") == "failed":
                raise RuntimeError(f"Safari media request failed: {metadata.get('error') or 'unknown error'}")
            time.sleep(SAFARI_POLL_INTERVAL_SECONDS)
        raise RuntimeError("Safari media request timed out.")

    def _run_in_window(self, statement: str, *, recover_missing: bool = True) -> str:
        if self._closed:
            raise RuntimeError("Safari window is already closed.")
        source = f"""
tell application "Safari"
    set targetWindow to first window whose id is {self.window_id}
    {statement}
end tell
"""
        try:
            return run_applescript(source)
        except RuntimeError as exc:
            if not recover_missing or not is_missing_safari_window_error(exc):
                raise
            self._context._recover_page(self)
            return run_applescript(source)


class SafariContext:
    """Own Safari windows created for one authenticated browser sync."""

    def __init__(self, initial_url: str) -> None:
        self.initial_url = initial_url
        self.pages: list[SafariPage] = []
        self.request = SafariRequestClient(self)
        self.request_lock = RLock()
        self.download_lock = RLock()

    @property
    def primary_page(self) -> SafariPage:
        """Return the first live page owned by this context."""
        if not self.pages:
            raise RuntimeError("Safari context has no open page.")
        return self.pages[0]

    def __enter__(self) -> SafariContext:
        self._create_page(self.initial_url)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False

    def new_page(self) -> SafariPage:
        """Create an additional owned Safari window."""
        return self._create_page("about:blank")

    def cookies(self, urls: list[str]) -> list[dict[str, str]]:
        """Avoid exporting Safari cookies; authenticated requests stay in-page."""
        del urls
        return []

    def close(self) -> None:
        """Close all Safari windows owned by this sync."""
        self.housekeep()

    def housekeep(self) -> int:
        """Close every tracked Safari window and return the number released."""
        closed_count = 0
        for page in list(reversed(self.pages)):
            was_tracked = page in self.pages
            page.close()
            if was_tracked and page not in self.pages:
                closed_count += 1
        return closed_count

    def _create_page(self, url: str) -> SafariPage:
        raw_window_id = self._create_window(url)
        if not raw_window_id.isdigit():
            raise RuntimeError("Safari did not return a usable window identifier.")
        page = SafariPage(self, int(raw_window_id))
        self.pages.append(page)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            page.close()
            raise
        return page

    def _create_window(self, url: str) -> str:
        source = f"""
tell application "Safari"
    launch
    {SAFARI_CAPTURE_FRONT_WINDOW_APPLESCRIPT}
    set targetWindow to missing value
    repeat with candidateWindow in every window
        try
            if visible of candidateWindow is false and (count of tabs of candidateWindow) is 1 then
                set candidateBounds to bounds of candidateWindow
                if candidateBounds is {{-32000, -32000, -30720, -31100}} then
                    set targetWindow to candidateWindow
                    exit repeat
                end if
            end if
        end try
    end repeat
    if targetWindow is missing value then
        set existingWindowIds to id of every window
        set emptyWindowIds to {{}}
        repeat with candidateWindow in every window
            if (count of tabs of candidateWindow) is 0 then set end of emptyWindowIds to id of candidateWindow
        end repeat
        make new document
        repeat with candidateWindow in every window
            if existingWindowIds does not contain (id of candidateWindow) then
                set targetWindow to candidateWindow
                exit repeat
            end if
        end repeat
        if targetWindow is missing value then
            repeat with candidateWindow in every window
                if emptyWindowIds contains (id of candidateWindow) and (count of tabs of candidateWindow) > 0 then
                    set targetWindow to candidateWindow
                    exit repeat
                end if
            end repeat
        end if
        if targetWindow is missing value then set targetWindow to front window
    end if
    set URL of current tab of targetWindow to "{escape_applescript_text(url)}"
    {SAFARI_BACKGROUND_WINDOW_APPLESCRIPT}
    return id of targetWindow
end tell
"""
        with safari_window_creation_guard():
            return run_applescript(source).strip()

    def _recover_page(self, page: SafariPage) -> None:
        """Replace a Safari page whose native window was closed externally."""
        raw_window_id = self._create_window(page._recovery_url)
        if not raw_window_id.isdigit():
            raise RuntimeError("Safari did not return a usable recovery window identifier.")
        page.window_id = int(raw_window_id)
        page._closed = False

    def _forget_page(self, page: SafariPage) -> None:
        with contextlib.suppress(ValueError):
            self.pages.remove(page)


def _split_fetch_headers(headers: dict[str, str]) -> tuple[dict[str, str], str]:
    """Move the forbidden Referer header into Fetch's referrer option."""
    request_headers: dict[str, str] = {}
    referrer = ""
    for key, value in headers.items():
        normalized_key = str(key).strip()
        normalized_value = str(value).strip()
        if not normalized_key or not normalized_value:
            continue
        if normalized_key.lower() == "referer":
            referrer = normalized_value
        else:
            request_headers[normalized_key] = normalized_value
    return request_headers, referrer
