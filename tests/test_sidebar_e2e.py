"""Disposable-browser E2E coverage for the responsive sidebar.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
from threading import Thread

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    BrowserType,
    Error as PlaywrightError,
    Page,
    Playwright,
    expect,
    sync_playwright,
)
from werkzeug.serving import BaseWSGIServer, make_server


OVERLAY_VIEWPORTS = (
    ("iPhone SE", 375, 667),
    ("iPhone 15 Pro", 393, 852),
    ("iPad mini portrait", 744, 1_133),
    ("iPad portrait", 768, 1_024),
    ("iPad Air portrait", 820, 1_180),
    ("11-inch iPad Pro portrait", 834, 1_194),
)
DESKTOP_VIEWPORTS = (
    ("iPad landscape and compact desktop", 1_024, 768),
    ("wide desktop", 1_512, 982),
)


@pytest.fixture(scope="module")
def sidebar_server_url() -> Iterator[str]:
    from app.core.config import LOCAL_STORE_ROOT
    from app.web.app import create_app

    application = create_app(LOCAL_STORE_ROOT)
    application.config.update(TESTING=True)
    server: BaseWSGIServer = make_server("127.0.0.1", 0, application, threaded=True)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def _launch_disposable_browser(playwright: Playwright) -> Browser:
    browser_type: BrowserType = playwright.chromium
    managed_executable = Path(browser_type.executable_path)
    if managed_executable.is_file():
        return browser_type.launch(headless=True)

    launch_errors: list[str] = []
    for channel in ("chrome", "msedge"):
        try:
            return browser_type.launch(channel=channel, headless=True)
        except PlaywrightError as error:  # pragma: no cover - depends on host browser inventory
            launch_errors.append(f"{channel}: {error}")
    raise AssertionError(
        "A Playwright-managed Chromium, Chrome, or Edge executable is required. "
        + " | ".join(launch_errors)
    )


@pytest.fixture(scope="module")
def disposable_browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = _launch_disposable_browser(playwright)
        try:
            yield browser
        finally:
            browser.close()


def _open_page(
    browser: Browser,
    url: str,
    width: int,
    height: int,
    *,
    touch: bool,
) -> tuple[Page, BrowserContext]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        has_touch=touch,
        is_mobile=touch,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.goto(url, wait_until="networkidle")
    return page, context


def _assert_hidden_backdrop(page: Page) -> None:
    backdrop = page.locator("#sidebar_backdrop")
    expect(backdrop).to_be_hidden()
    expect(backdrop).to_have_attribute("hidden", "")
    assert backdrop.evaluate("element => getComputedStyle(element).display") == "none"
    assert backdrop.evaluate("element => getComputedStyle(element).pointerEvents") == "none"


def _assert_toggle_hit_target(page: Page) -> None:
    assert page.locator("#sidebar_toggle").evaluate(
        """toggle => {
            const rect = toggle.getBoundingClientRect();
            const hit = document.elementFromPoint(
                rect.left + (rect.width / 2),
                rect.top + (rect.height / 2),
            );
            return Boolean(hit?.closest("#sidebar_toggle"));
        }"""
    )


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(("device_name", "width", "height"), OVERLAY_VIEWPORTS)
def test_overlay_sidebar_is_touch_safe_across_phone_and_ipad_portraits(
    disposable_browser: Browser,
    sidebar_server_url: str,
    device_name: str,
    width: int,
    height: int,
) -> None:
    page, context = _open_page(
        disposable_browser,
        sidebar_server_url,
        width,
        height,
        touch=True,
    )
    try:
        toggle = page.locator("#sidebar_toggle")
        sidebar = page.locator(".sidebar")
        backdrop = page.locator("#sidebar_backdrop")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(page.locator(".app-shell")).to_have_class(re.compile(r"\bis-sidebar-collapsed\b"))
        _assert_hidden_backdrop(page)
        assert sidebar.evaluate("element => getComputedStyle(element).pointerEvents") == "none"

        closed_geometry = toggle.evaluate(
            """toggle => {
                const rect = toggle.getBoundingClientRect();
                return {height: rect.height, left: rect.left, top: rect.top, width: rect.width};
            }"""
        )
        assert closed_geometry["width"] >= 44, device_name
        assert closed_geometry["height"] >= 44, device_name
        assert closed_geometry["left"] >= 0, device_name
        assert closed_geometry["top"] >= 0, device_name
        _assert_toggle_hit_target(page)

        toggle.tap()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(backdrop).to_be_visible()
        expect(backdrop).not_to_have_attribute("hidden", "")
        assert sidebar.evaluate("element => getComputedStyle(element).pointerEvents") == "auto"
        _assert_toggle_hit_target(page)

        layout = page.evaluate(
            """() => {
                const toggle = document.querySelector("#sidebar_toggle").getBoundingClientRect();
                const title = document.querySelector(".sidebar .hero").getBoundingClientRect();
                const dock = document.querySelector(".sidebar-dock").getBoundingClientRect();
                const actions = document.querySelector(".global-quick-actions").getBoundingClientRect();
                const sidebar = document.querySelector(".sidebar").getBoundingClientRect();
                const overlaps = (left, right) => !(
                    left.right <= right.left
                    || left.left >= right.right
                    || left.bottom <= right.top
                    || left.top >= right.bottom
                );
                return {
                    metricColumnCount: getComputedStyle(
                        document.querySelector(".metric-grid"),
                    ).gridTemplateColumns.split(" ").length,
                    dockOverlapsToggle: overlaps(dock, toggle),
                    actionsOverlapToggle: overlaps(actions, toggle),
                    titleOverlapsToggle: overlaps(title, toggle),
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) > document.documentElement.clientWidth,
                    sidebarInsideViewport: sidebar.left >= 0
                        && sidebar.top >= 0
                        && sidebar.right <= window.innerWidth
                        && sidebar.bottom <= window.innerHeight,
                };
            }"""
        )
        assert layout["metricColumnCount"] == (1 if width <= 560 else 3), device_name
        assert not layout["dockOverlapsToggle"], device_name
        assert not layout["actionsOverlapToggle"], device_name
        assert not layout["titleOverlapsToggle"], device_name
        assert not layout["horizontalOverflow"], device_name
        assert layout["sidebarInsideViewport"], device_name

        backdrop_hit = page.evaluate(
            """({x, y}) => document.elementFromPoint(x, y)?.id""",
            {"x": width - 2, "y": height / 2},
        )
        assert backdrop_hit == "sidebar_backdrop", device_name
        page.touchscreen.tap(width - 2, height / 2)
        expect(toggle).to_have_attribute("aria-expanded", "false")
        _assert_hidden_backdrop(page)

        toggle.tap()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _assert_toggle_hit_target(page)
        toggle.tap()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        _assert_hidden_backdrop(page)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(("device_name", "width", "height"), DESKTOP_VIEWPORTS)
def test_desktop_widths_keep_the_sidebar_in_the_docked_contract(
    disposable_browser: Browser,
    sidebar_server_url: str,
    device_name: str,
    width: int,
    height: int,
) -> None:
    page, context = _open_page(
        disposable_browser,
        sidebar_server_url,
        width,
        height,
        touch=False,
    )
    try:
        toggle = page.locator("#sidebar_toggle")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _assert_hidden_backdrop(page)
        assert page.locator(".sidebar").evaluate(
            "element => getComputedStyle(element).position"
        ) != "fixed", device_name
        assert not page.evaluate(
            "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
            "> document.documentElement.clientWidth"
        ), device_name
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_sidebar_state_remains_consistent_across_overlay_transitions(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    page, context = _open_page(
        disposable_browser,
        sidebar_server_url,
        393,
        852,
        touch=True,
    )
    try:
        toggle = page.locator("#sidebar_toggle")
        backdrop = page.locator("#sidebar_backdrop")
        expect(toggle).to_have_attribute("aria-expanded", "false")

        toggle.tap()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(backdrop).to_be_visible()

        page.set_viewport_size({"width": 1_024, "height": 768})
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _assert_hidden_backdrop(page)

        page.set_viewport_size({"width": 820, "height": 1_180})
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(backdrop).to_be_visible()
        _assert_toggle_hit_target(page)

        toggle.tap()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        _assert_hidden_backdrop(page)

        page.set_viewport_size({"width": 1_512, "height": 982})
        expect(toggle).to_have_attribute("aria-expanded", "false")
        _assert_hidden_backdrop(page)

        page.set_viewport_size({"width": 768, "height": 1_024})
        expect(toggle).to_have_attribute("aria-expanded", "false")
        _assert_hidden_backdrop(page)
        _assert_toggle_hit_target(page)
    finally:
        context.close()
