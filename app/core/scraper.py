"""Collect liked tweet URLs from the logged-in X account."""

from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
import time
from pathlib import Path

from .config import CrawlConfig
from .state import TaskState

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
    PlaywrightTimeoutError = Exception
    PlaywrightError = Exception


CANONICAL_X_ACCOUNT_HANDLE = "22cmProgrammer"
CANONICAL_X_LIKES_URL = f"https://x.com/{CANONICAL_X_ACCOUNT_HANDLE}/likes"
logger = logging.getLogger(__name__)


def ensure_playwright_available() -> None:
    """Raise a clear error when Playwright is not installed."""
    if sync_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Run `python3 -m pip install -r requirements.txt` "
            "and then `python3 -m playwright install chromium`."
        )


def clone_profile_for_playwright(config: CrawlConfig) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """Copy the selected Chrome profile into a temporary user data dir."""
    source_user_data_dir = Path(config.chrome_user_data_dir).expanduser()
    source_profile_dir = source_user_data_dir / config.chrome_profile_directory

    if not source_profile_dir.exists():
        raise RuntimeError(f"Chrome profile directory was not found: {source_profile_dir}")

    temp_dir = tempfile.TemporaryDirectory(prefix="cachelikes-chrome-")
    temp_root = Path(temp_dir.name)
    target_user_data_dir = temp_root / "ChromeUserData"
    target_profile_dir = target_user_data_dir / config.chrome_profile_directory

    target_user_data_dir.mkdir(parents=True, exist_ok=True)

    local_state = source_user_data_dir / "Local State"
    if local_state.exists():
        shutil.copy2(local_state, target_user_data_dir / "Local State")

    def ignore_transient_files(_directory: str, names: list[str]) -> set[str]:
        ignored = {
            "SingletonCookie",
            "SingletonLock",
            "SingletonSocket",
            "lockfile",
        }
        ignored.update(name for name in names if name.endswith(".lock"))
        return ignored

    shutil.copytree(source_profile_dir, target_profile_dir, dirs_exist_ok=True, ignore=ignore_transient_files)
    logger.info(
        "Cloned Chrome profile for Playwright.",
        extra={
            "source_profile_dir": str(source_profile_dir),
            "target_profile_dir": str(target_profile_dir),
        },
    )
    return target_user_data_dir, temp_dir


def detect_account_handle(page) -> str:
    """Extract the current account handle from the profile tab link."""
    selectors = [
        'a[data-testid="AppTabBar_Profile_Link"]',
        'a[aria-label*="Profile"]',
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count():
            href = locator.get_attribute("href") or ""
            handle = href.strip("/").split("/")[0]
            if handle and handle.lower() not in {"home", "explore"}:
                return handle

    anchors = page.locator('a[href^="/"]').evaluate_all(
        """(elements) => elements
        .map((element) => element.getAttribute("href"))
        .filter(Boolean)"""
    )
    for href in anchors:
        parts = href.strip("/").split("/")
        if len(parts) == 1 and parts[0] and parts[0] not in {"home", "explore", "notifications", "messages"}:
            return parts[0]

    raise RuntimeError("Could not detect the current X account handle from Chrome.")


def wait_for_likes_page_ready(page) -> None:
    """Wait until the likes page looks usable or fail with a clear auth message."""
    ready_selectors = [
        "article",
        '[data-testid="emptyState"]',
        '[data-testid="primaryColumn"]',
        'a[href="/home"]',
        'a[data-testid="AppTabBar_Home_Link"]',
    ]
    auth_markers = [
        "Sign in",
        "Log in",
        "登录",
        "注册",
    ]

    deadline = time.time() + 30
    while time.time() < deadline:
        if any(page.locator(selector).count() for selector in ready_selectors):
            page.wait_for_timeout(1_500)
            return

        body_text = page.locator("body").inner_text(timeout=5_000)
        if any(marker in body_text for marker in auth_markers):
            raise RuntimeError(
                "X did not appear logged in. Confirm the selected Chrome profile is signed in to X, "
                "and if Chrome is open, close its regular windows before retrying."
            )

        page.wait_for_timeout(1_000)

    raise RuntimeError("X likes page did not finish loading in time.")


def launch_context(playwright, config: CrawlConfig, state: TaskState):
    """Launch Chromium with the user's Chrome profile directory."""
    user_data_dir = Path(config.chrome_user_data_dir).expanduser()
    if not user_data_dir.exists():
        raise RuntimeError(f"Chrome user data directory was not found: {user_data_dir}")

    temp_profile_dir: tempfile.TemporaryDirectory[str] | None = None

    def do_launch(target_user_data_dir: Path):
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(target_user_data_dir),
            channel="chrome",
            headless=config.headless,
            args=[f"--profile-directory={config.chrome_profile_directory}"],
            ignore_default_args=["--use-mock-keychain", "--password-store=basic"],
            viewport={"width": 1440, "height": 1200},
        )

    try:
        context = do_launch(user_data_dir)
    except PlaywrightError as exc:
        error_text = str(exc)
        if "ProcessSingleton" in error_text or "SingletonLock" in error_text:
            state.append_event("Chrome profile is busy. Cloning the selected profile into a temporary workspace.")
            logger.warning(
                "Chrome profile busy, falling back to temporary clone.",
                extra={
                    "chrome_user_data_dir": str(user_data_dir),
                    "chrome_profile_directory": config.chrome_profile_directory,
                    "playwright_error": error_text,
                },
            )
            temp_user_data_dir, temp_profile_dir = clone_profile_for_playwright(config)
            try:
                context = do_launch(temp_user_data_dir)
            except Exception:
                if temp_profile_dir is not None:
                    temp_profile_dir.cleanup()
                raise
        else:
            raise

    if temp_profile_dir is None:
        return contextlib.closing(context)

    @contextlib.contextmanager
    def managed_context():
        try:
            yield context
        finally:
            with contextlib.suppress(Exception):
                context.close()
            temp_profile_dir.cleanup()

    return managed_context()


def collect_liked_tweet_urls(config: CrawlConfig, state: TaskState) -> tuple[str, list[str]]:
    """Open X likes and return the account handle plus all discovered tweet URLs."""
    ensure_playwright_available()
    logger.info(
        "Collecting liked tweet URLs.",
        extra={
            "likes_url": CANONICAL_X_LIKES_URL,
            "headless": config.headless,
            "max_scroll_rounds": config.max_scroll_rounds,
            "stale_round_limit": config.stale_round_limit,
        },
    )

    with sync_playwright() as playwright:
        with launch_context(playwright, config, state) as context:
            page = context.pages[0] if context.pages else context.new_page()
            state.append_event(f"Opening canonical likes page {CANONICAL_X_LIKES_URL}.")
            page.goto(CANONICAL_X_LIKES_URL, wait_until="domcontentloaded", timeout=120_000)
            wait_for_likes_page_ready(page)

            try:
                account_handle = detect_account_handle(page)
            except RuntimeError:
                account_handle = CANONICAL_X_ACCOUNT_HANDLE

            state.update(account_name=account_handle)
            state.append_event(f"Ready to collect likes for @{account_handle}.")
            logger.info(
                "Likes page ready.",
                extra={
                    "account_handle": account_handle,
                },
            )

            seen_urls: set[str] = set()
            stale_rounds = 0

            for round_index in range(config.max_scroll_rounds):
                links = page.locator('article a[href*="/status/"]').evaluate_all(
                    """(elements) => elements
                    .map((element) => element.href)
                    .filter((href) => href && href.includes("/status/"))
                    .map((href) => href.split("?")[0])"""
                )

                before_count = len(seen_urls)
                seen_urls.update(links)
                after_count = len(seen_urls)

                state.update(discovered_tweets=after_count, phase="collecting")
                state.append_event(
                    f"Scroll round {round_index + 1}: discovered {after_count} unique liked tweet URLs."
                )
                logger.info(
                    "Scroll round completed.",
                    extra={
                        "scroll_round": round_index + 1,
                        "discovered_tweets": after_count,
                        "newly_discovered_tweets": after_count - before_count,
                        "stale_rounds": stale_rounds,
                    },
                )

                if after_count == before_count:
                    stale_rounds += 1
                else:
                    stale_rounds = 0

                if stale_rounds >= config.stale_round_limit:
                    break

                page.mouse.wheel(0, 6000)
                time.sleep(config.scroll_pause_seconds)

            ordered_urls = sorted(seen_urls)
            if not ordered_urls:
                raise RuntimeError("No liked tweet URLs were found. The likes timeline may be empty or blocked.")

            logger.info(
                "Collected liked tweet URLs.",
                extra={
                    "account_handle": account_handle,
                    "discovered_tweets": len(ordered_urls),
                },
            )
            return account_handle, ordered_urls
