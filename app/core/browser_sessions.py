"""Browser session probing helpers for X and Grok."""

# Code version: v1.2.0-codex.1

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CrawlConfig
from .scraper import detect_account_handle

try:  # pragma: no cover - depends on local runtime
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    PlaywrightError = RuntimeError
    sync_playwright = None


X_HOME_URL = "https://x.com/home"
GROK_FILES_URL = "https://grok.com/files"
EDGE_USER_DATA_DIR = Path.home() / "Library/Application Support/Microsoft Edge"
EDGE_PROFILE_DIRECTORY = "Default"
SAFARI_APPLESCRIPT_SOURCE_LIMIT = 500_000
X_AUTH_MARKERS = ("Sign in", "Log in", "登录", "注册")
X_LOGGED_OUT_SOURCE_MARKERS = ("bundle.LoggedOutShell", "bundle.LoggedOutRoutes", "Sign in to X")
TRANSIENT_BROWSER_ERROR_MARKERS = (
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_NETWORK_CHANGED",
    "ERR_TIMED_OUT",
    "ERR_CONNECTION_RESET",
)


@dataclass(frozen=True, slots=True)
class BrowserDescriptor:
    """Describe one browser option exposed in the UI."""

    browser_id: str
    label: str
    icon_filename: str
    engine: str
    user_data_dir: Path | None = None
    profile_directory: str = ""
    channel: str = ""


def build_browser_options(config: CrawlConfig) -> list[dict[str, str]]:
    """Return browser options for the sidebar selector."""
    return [
        {
            "id": descriptor.browser_id,
            "label": descriptor.label,
            "icon_filename": descriptor.icon_filename,
        }
        for descriptor in browser_descriptors(config).values()
    ]


def browser_descriptors(config: CrawlConfig) -> dict[str, BrowserDescriptor]:
    """Return runtime-aware browser descriptors."""
    return {
        "edge": BrowserDescriptor(
            browser_id="edge",
            label="Edge",
            icon_filename="images/browser.edge.png",
            engine="chromium",
            user_data_dir=EDGE_USER_DATA_DIR,
            profile_directory=EDGE_PROFILE_DIRECTORY,
            channel="msedge",
        ),
        "chrome": BrowserDescriptor(
            browser_id="chrome",
            label="Chrome",
            icon_filename="images/browser.chrome.png",
            engine="chromium",
            user_data_dir=Path(config.chrome_user_data_dir).expanduser(),
            profile_directory=config.chrome_profile_directory,
            channel="chrome",
        ),
        "safari": BrowserDescriptor(
            browser_id="safari",
            label="Safari",
            icon_filename="images/browser.safari.png",
            engine="safari",
        ),
    }


def probe_browser_session(platform_name: str, browser_name: str, config: CrawlConfig) -> dict[str, Any]:
    """Probe whether one browser is signed in for the requested platform."""
    descriptors = browser_descriptors(config)
    descriptor = descriptors.get(browser_name)
    if descriptor is None:
        raise ValueError(f"Unsupported browser: {browser_name}")

    platform_key = (platform_name or "").strip().lower()
    if platform_key not in {"x", "grok"}:
        raise ValueError(f"Unsupported platform: {platform_name}")

    result = {
        "platform": platform_key,
        "browser": descriptor.browser_id,
        "browser_label": descriptor.label,
        "icon_filename": descriptor.icon_filename,
        "logged_in": False,
        "can_download": False,
        "account_name": "",
        "message": "",
    }

    try:
        if descriptor.engine == "safari":
            if platform_key == "x":
                result.update(_probe_safari_x_session(descriptor))
            else:
                result.update(_probe_safari_grok_session(descriptor))
        elif platform_key == "x":
            result.update(_probe_chromium_x_session(descriptor))
        else:
            result.update(_probe_chromium_grok_session(descriptor))
    except Exception as exc:  # pragma: no cover - depends on local browser state
        result["message"] = str(exc)
        return result

    if not result["message"]:
        if result["can_download"]:
            result["message"] = f"{descriptor.label} is ready to download from {platform_key.upper()}."
        else:
            result["message"] = f"{descriptor.label} is not ready for {platform_key.upper()} yet."
    return result


def _probe_chromium_x_session(descriptor: BrowserDescriptor) -> dict[str, Any]:
    """Probe an X session from a Chromium-family browser profile."""
    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(playwright, descriptor, headless=True) as context:
            page = context.pages[0] if context.pages else context.new_page()
            goto_with_retry(page, X_HOME_URL)
            wait_for_x_page_ready(page, descriptor.label)
            account_handle = detect_account_handle(page)
            return {
                "logged_in": True,
                "can_download": True,
                "account_name": f"@{account_handle}",
                "message": f"{descriptor.label} is signed in to X as @{account_handle}.",
            }


def _probe_chromium_grok_session(descriptor: BrowserDescriptor) -> dict[str, Any]:
    """Probe a Grok session from a Chromium-family browser profile."""
    with sync_playwright_or_error() as playwright:
        with launch_chromium_context(playwright, descriptor, headless=False) as context:
            page = context.pages[0] if context.pages else context.new_page()
            goto_with_retry(page, GROK_FILES_URL)
            page.wait_for_timeout(8_000)
            body_text = page.locator("body").inner_text(timeout=10_000)
            html = page.content()
            account_name = parse_grok_account_label(html)
            if account_name:
                return {
                    "logged_in": True,
                    "can_download": True,
                    "account_name": account_name,
                    "message": f"{descriptor.label} is signed in to Grok as {account_name}.",
                }
            if any(marker in body_text for marker in ("Sign in", "Log in")):
                return {
                    "logged_in": False,
                    "can_download": False,
                    "account_name": "",
                    "message": f"{descriptor.label} is not signed in to Grok.",
                }
            raise RuntimeError(f"Could not detect the signed-in Grok account from {descriptor.label}.")


def _probe_safari_x_session(descriptor: BrowserDescriptor) -> dict[str, Any]:
    """Probe an X session from Safari by reading the rendered page source."""
    home_snapshot = fetch_safari_page_snapshot(X_HOME_URL)
    home_source = home_snapshot["source"]
    lowered_home_source = home_source.lower()
    if any(marker.lower() in lowered_home_source for marker in X_LOGGED_OUT_SOURCE_MARKERS):
        return {
            "logged_in": False,
            "can_download": False,
            "account_name": "",
            "message": "Safari is not signed in to X.",
        }

    account_handle = extract_x_account_from_source(home_source)
    if account_handle:
        return {
            "logged_in": True,
            "can_download": True,
            "account_name": f"@{account_handle}",
            "message": f"Safari is signed in to X as @{account_handle}.",
        }

    inferred_handle = extract_json_string_field(fetch_safari_page_snapshot(GROK_FILES_URL)["source"], "xUsername")
    if inferred_handle:
        return {
            "logged_in": True,
            "can_download": True,
            "account_name": f"@{inferred_handle}",
            "message": f"Safari X account inferred from the linked Grok session as @{inferred_handle}.",
        }

    return {
        "logged_in": False,
        "can_download": False,
        "account_name": "",
        "message": "Safari did not expose a verifiable X account handle from page source.",
    }


def _probe_safari_grok_session(descriptor: BrowserDescriptor) -> dict[str, Any]:
    """Probe a Grok session from Safari by reading the rendered page source."""
    for _attempt in range(2):
        safari_snapshot = fetch_safari_page_snapshot(GROK_FILES_URL, wait_seconds=10)
        account_name = parse_grok_account_label(safari_snapshot["source"])
        if account_name:
            return {
                "logged_in": True,
                "can_download": True,
                "account_name": account_name,
                "message": f"Safari is signed in to Grok as {account_name}.",
            }

    inferred_handle = extract_x_account_from_source(fetch_safari_page_snapshot(X_HOME_URL, wait_seconds=10)["source"])
    if inferred_handle:
        return {
            "logged_in": True,
            "can_download": True,
            "account_name": f"@{inferred_handle}",
            "message": f"Safari Grok account inferred from the linked X session as @{inferred_handle}.",
        }

    return {
        "logged_in": False,
        "can_download": False,
        "account_name": "",
        "message": "Safari is not signed in to Grok, or Grok did not expose the current account in page source.",
    }


def sync_playwright_or_error():
    """Return sync_playwright when the dependency is available."""
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed for the current interpreter. "
            "Run `/usr/local/bin/python3.13 -m pip install -r requirements.txt`."
        )
    return sync_playwright()


def wait_for_x_page_ready(page, browser_label: str) -> None:
    """Wait until the X page is usable or fail with a clear auth message."""
    ready_selectors = [
        "article",
        '[data-testid="emptyState"]',
        '[data-testid="primaryColumn"]',
        'a[href="/home"]',
        'a[data-testid="AppTabBar_Home_Link"]',
    ]

    deadline = time.time() + 30
    while time.time() < deadline:
        if any(page.locator(selector).count() for selector in ready_selectors):
            page.wait_for_timeout(1_500)
            return

        body_text = page.locator("body").inner_text(timeout=5_000)
        if any(marker in body_text for marker in X_AUTH_MARKERS):
            raise RuntimeError(f"{browser_label} is not signed in to X.")

        page.wait_for_timeout(1_000)

    raise RuntimeError(f"X page did not finish loading in {browser_label}.")


def goto_with_retry(page, url: str, attempts: int = 3) -> None:
    """Navigate with a small retry budget for transient browser tunnel errors."""
    last_error: Exception | None = None
    for attempt_index in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            return
        except Exception as exc:  # pragma: no cover - depends on local browser/network state
            last_error = exc
            error_text = str(exc)
            if attempt_index >= attempts or not any(marker in error_text for marker in TRANSIENT_BROWSER_ERROR_MARKERS):
                raise
            page.wait_for_timeout(1_500)
    if last_error is not None:
        raise last_error


def launch_chromium_context(playwright, descriptor: BrowserDescriptor, headless: bool):
    """Launch a Chromium-family browser against the selected profile."""
    user_data_dir = descriptor.user_data_dir
    if user_data_dir is None:
        raise RuntimeError(f"{descriptor.label} does not expose a Chromium profile directory.")
    if not user_data_dir.exists():
        raise RuntimeError(f"{descriptor.label} user data directory was not found: {user_data_dir}")

    temp_profile_dir: tempfile.TemporaryDirectory[str] | None = None

    def do_launch(target_user_data_dir: Path):
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(target_user_data_dir),
            channel=descriptor.channel,
            headless=headless,
            args=[f"--profile-directory={descriptor.profile_directory}"],
            ignore_default_args=["--use-mock-keychain", "--password-store=basic"],
            viewport={"width": 1440, "height": 1200},
        )

    try:
        context = do_launch(user_data_dir)
    except PlaywrightError as exc:
        error_text = str(exc)
        if "ProcessSingleton" not in error_text and "SingletonLock" not in error_text:
            raise
        temp_user_data_dir, temp_profile_dir = clone_browser_profile(descriptor)
        try:
            context = do_launch(temp_user_data_dir)
        except Exception:
            temp_profile_dir.cleanup()
            raise

    if temp_profile_dir is None:
        return contextlib.closing(context)

    class ManagedContext:
        def __enter__(self_nonlocal):
            return context

        def __exit__(self_nonlocal, exc_type, exc, tb):
            try:
                context.close()
            finally:
                temp_profile_dir.cleanup()
            return False

    return ManagedContext()


def clone_browser_profile(descriptor: BrowserDescriptor) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """Clone one Chromium browser profile to avoid singleton locks."""
    source_user_data_dir = descriptor.user_data_dir
    if source_user_data_dir is None:
        raise RuntimeError(f"{descriptor.label} does not expose a clonable profile.")

    source_profile_dir = source_user_data_dir / descriptor.profile_directory
    if not source_profile_dir.exists():
        raise RuntimeError(f"{descriptor.label} profile directory was not found: {source_profile_dir}")

    temp_dir = tempfile.TemporaryDirectory(prefix=f"cachelikes-{descriptor.browser_id}-")
    temp_root = Path(temp_dir.name)
    target_user_data_dir = temp_root / f"{descriptor.label.replace(' ', '')}UserData"
    target_profile_dir = target_user_data_dir / descriptor.profile_directory
    target_user_data_dir.mkdir(parents=True, exist_ok=True)

    local_state = source_user_data_dir / "Local State"
    if local_state.exists():
        local_state_target = target_user_data_dir / "Local State"
        local_state_target.write_bytes(local_state.read_bytes())

    def ignore_transient_files(_directory: str, names: list[str]) -> set[str]:
        ignored = {
            "SingletonCookie",
            "SingletonLock",
            "SingletonSocket",
            "lockfile",
        }
        ignored.update(name for name in names if name.endswith(".lock"))
        return ignored

    import shutil

    shutil.copytree(source_profile_dir, target_profile_dir, dirs_exist_ok=True, ignore=ignore_transient_files)
    return target_user_data_dir, temp_dir


def parse_grok_account_label(html: str) -> str:
    """Extract a user-facing Grok account label from injected page data."""
    if not html:
        return ""

    given_name = extract_json_string_field(html, "givenName")
    x_username = extract_json_string_field(html, "xUsername")
    email = extract_json_string_field(html, "email")
    user_id = extract_json_string_field(html, "userId")

    if given_name and x_username:
        return f"{given_name} (@{x_username})"
    if given_name:
        return given_name
    if x_username:
        return f"@{x_username}"
    if email:
        return email
    if user_id:
        return f"User {user_id[:8]}"
    return ""


def extract_json_string_field(text: str, field_name: str) -> str:
    """Extract one JSON string field from page source and decode escapes."""
    patterns = (
        rf'"{re.escape(field_name)}":"((?:[^"\\\\]|\\\\.)*)"',
        rf'\\"{re.escape(field_name)}\\":\\"((?:[^"\\\\]|\\\\.)*)\\"',
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return decode_js_string(match.group(1))
    return ""


def decode_js_string(value: str) -> str:
    """Decode one JavaScript JSON string literal payload."""
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def extract_x_account_from_source(source: str) -> str:
    """Try to infer the signed-in X account handle from page source."""
    patterns = (
        r'"screen_name":"([A-Za-z0-9_]{1,30})"',
        r'"screenName":"([A-Za-z0-9_]{1,30})"',
        r'"userName":"([A-Za-z0-9_]{1,30})"',
        r'"handle":"([A-Za-z0-9_]{1,30})"',
    )
    for pattern in patterns:
        match = re.search(pattern, source)
        if match:
            handle = match.group(1).strip()
            if handle and handle.lower() not in {"twitter", "x"}:
                return handle
    return ""


def fetch_safari_page_snapshot(url: str, wait_seconds: int = 8) -> dict[str, str]:
    """Open one URL in Safari, capture the page source, and close the temporary tab."""
    applescript = f"""
tell application "Safari"
    activate
    make new document
    set URL of front document to "{escape_applescript_text(url)}"
    delay {wait_seconds}
    set currentUrl to URL of front document
    set docSource to source of front document
    set sourceLength to length of docSource
    if sourceLength > {SAFARI_APPLESCRIPT_SOURCE_LIMIT} then
        set clippedSource to text 1 thru {SAFARI_APPLESCRIPT_SOURCE_LIMIT} of docSource
    else
        set clippedSource to docSource
    end if
    close front document
    return currentUrl & linefeed & clippedSource
end tell
"""
    process = subprocess.run(
        ["osascript"],
        input=applescript,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        stderr = (process.stderr or process.stdout or "").strip()
        raise RuntimeError(stderr or "Safari session probe failed.")

    current_url, _separator, source = process.stdout.partition("\n")
    return {"url": current_url.strip(), "source": source}


def escape_applescript_text(value: str) -> str:
    """Escape a Python string for insertion into AppleScript string literals."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
