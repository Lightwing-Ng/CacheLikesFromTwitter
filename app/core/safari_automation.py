"""Minimal Safari automation primitives backed by Apple Events."""

# Code version: v1.1.0-codex.1

from __future__ import annotations

import base64
import contextlib
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


SAFARI_DOWNLOAD_RANGE_BYTES = 512 * 1024
SAFARI_BASE64_SLICE_BYTES = 96 * 1024
SAFARI_POLL_INTERVAL_SECONDS = 0.2
SAFARI_APPLESCRIPT_RETRY_LIMIT = 2
SAFARI_APPLESCRIPT_RETRY_DELAY_SECONDS = 0.25


def is_missing_safari_window_error(error: BaseException) -> bool:
    """Return whether Safari rejected an operation for a window that vanished."""
    message = str(error).lower()
    return "invalid index" in message and "window" in message


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


@dataclass(slots=True)
class SafariResponse:
    """Expose the small response surface used by the Grok resolver."""

    status: int
    body_text: str

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

    def get(self, url: str, timeout: int) -> SafariResponse:
        """Fetch one URL synchronously inside the library page."""
        page = self._context.primary_page
        payload = page.evaluate(
            """(request) => {
                const xhr = new XMLHttpRequest();
                xhr.open("GET", request.url, false);
                xhr.withCredentials = true;
                xhr.send();
                return {
                    status: xhr.status,
                    bodyText: xhr.responseText || "",
                };
            }""",
            {"url": url, "timeout": max(1, int(timeout))},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Safari returned an invalid Grok API response.")
        return SafariResponse(
            status=int(payload.get("status") or 0),
            body_text=str(payload.get("bodyText") or ""),
        )


class SafariPage:
    """Represent one Safari window owned by the current sync."""

    def __init__(self, context: SafariContext, window_id: int) -> None:
        self._context = context
        self.window_id = int(window_id)
        self._closed = False
        self._recovery_url = context.initial_url if not context.pages else "about:blank"

    @property
    def url(self) -> str:
        """Return the current tab URL."""
        return self._run_in_window("return URL of current tab of targetWindow").strip()

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 60_000) -> None:
        """Navigate the current tab and wait for the requested ready state."""
        del wait_until
        self._recovery_url = url
        source = f"""
tell application "Safari"
    set targetWindow to first window whose id is {self.window_id}
    set URL of current tab of targetWindow to "{escape_applescript_text(url)}"
end tell
"""
        run_applescript(source)

        deadline = time.monotonic() + max(1.0, timeout / 1_000)
        while time.monotonic() < deadline:
            with contextlib.suppress(RuntimeError):
                ready_state = self.evaluate("() => document.readyState")
                if ready_state in {"interactive", "complete"}:
                    return
            time.sleep(SAFARI_POLL_INTERVAL_SECONDS)
        raise RuntimeError(f"Safari did not finish loading {url} within {timeout:,} ms.")

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        """Wait for DOM readiness; Safari does not expose network-idle state."""
        del state
        deadline = time.monotonic() + max(1.0, timeout / 1_000)
        while time.monotonic() < deadline:
            if self.evaluate("() => document.readyState") == "complete":
                return
            time.sleep(SAFARI_POLL_INTERVAL_SECONDS)

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

    def close(self) -> None:
        """Close this owned Safari window."""
        if self._closed:
            return
        with contextlib.suppress(RuntimeError):
            self._run_in_window("close targetWindow")
        self._closed = True
        self._context._forget_page(self)

    def download_to_path(
        self,
        source_url: str,
        destination_path: Path,
        should_stop,
    ) -> tuple[str, bool]:
        """Stream an authenticated media URL from Safari into a local file."""
        with self._context.download_lock:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            initial_bytes = destination_path.stat().st_size if destination_path.exists() else 0
            range_start = initial_bytes
            content_type = ""
            expected_total = 0

            restarted_after_range_error = False
            while expected_total == 0 or range_start < expected_total:
                if should_stop():
                    raise RuntimeError("Stop requested while downloading Grok media.")

                range_end = range_start + SAFARI_DOWNLOAD_RANGE_BYTES - 1
                request_payload = {
                    "sourceUrl": source_url,
                    "rangeHeader": f"bytes={range_start}-{range_end}",
                }
                self.evaluate(
                    """(request) => {
                        window.__cachelikesSafariDownload = { state: "pending" };
                        fetch(request.sourceUrl, {
                            credentials: "include",
                            headers: { Range: request.rangeHeader },
                        }).then(async (response) => {
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
                    raise RuntimeError("Safari media server did not honor the resume range.")

                content_range = str(metadata.get("contentRange") or "")
                range_match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range)
                if range_match:
                    response_start = int(range_match.group(1))
                    if response_start != range_start:
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
                            raise RuntimeError("Stop requested while downloading Grok media.")
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

    def _run_in_window(self, statement: str) -> str:
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
            if "close targetWindow" in statement or not is_missing_safari_window_error(exc):
                raise
            self._context._recover_page(self)
            return run_applescript(source)


class SafariContext:
    """Own Safari windows created for one Grok sync."""

    def __init__(self, initial_url: str) -> None:
        self.initial_url = initial_url
        self.pages: list[SafariPage] = []
        self.request = SafariRequestClient(self)
        self.download_lock = RLock()

    @property
    def primary_page(self) -> SafariPage:
        """Return the first live page owned by this context."""
        if not self.pages:
            raise RuntimeError("Safari Grok context has no open page.")
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
        return page

    def _create_window(self, url: str) -> str:
        source = f"""
tell application "Safari"
    launch
    make new document
    set targetWindow to front window
    set URL of current tab of targetWindow to "{escape_applescript_text(url)}"
    return id of targetWindow
end tell
"""
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
