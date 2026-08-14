"""Disposable-browser E2E coverage for the responsive sidebar and language boundaries.

Code version: v1.7.0-codex.2
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
import re
from threading import Thread

import pytest
from PIL import Image, ImageChops
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
    init_script: str | None = None,
) -> tuple[Page, BrowserContext]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        has_touch=touch,
        is_mobile=touch,
        reduced_motion="reduce",
    )
    page = context.new_page()
    if init_script:
        page.add_init_script(init_script)
    page.goto(url, wait_until="domcontentloaded")
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


def _tap_toggle_center(page: Page, toggle) -> None:
    box = toggle.bounding_box()
    assert box is not None
    page.touchscreen.tap(box["x"] + (box["width"] / 2), box["y"] + (box["height"] / 2))


def _decode_screenshot(png_bytes: bytes) -> Image.Image:
    with Image.open(BytesIO(png_bytes)) as image:
        return image.convert("RGBA")


@pytest.mark.integration
@pytest.mark.slow
def test_simplified_chinese_language_boundary_runs_in_real_browser(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify the language boundary after startup and dynamic DOM mutations."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/x",
        1_280,
        900,
        touch=False,
        init_script="""
            document.addEventListener("DOMContentLoaded", () => {
                const button = document.createElement("button");
                button.id = "language-rendering-startup-button";
                button.textContent = "首屏简体中文";
                document.body.append(button);
            }, {once: true});
        """,
    )
    try:
        expect(page.locator('script[src*="language-rendering.js"]')).to_have_count(1)
        expect(page.locator("#language-rendering-startup-button")).to_have_attribute(
            "lang",
            "zh-CN",
        )

        # This is the production browser-session trigger shape: the visible
        # label is nested inside the button named by the original issue.
        trigger = page.locator('[data-role="browser-picker-trigger"]')
        expect(trigger).to_have_count(1)
        selected_label = trigger.locator('[data-role="browser-picker-selected-label"]')
        selected_label.evaluate("element => { element.textContent = '简体中文按钮'; }")
        expect(selected_label).to_have_attribute("lang", "zh-CN")
        assert selected_label.evaluate("element => element.matches(':lang(zh-CN)')")

        page.evaluate(
            """() => {
                const button = document.createElement("button");
                button.id = "language-rendering-dynamic-button";
                button.textContent = "动态简体中文";
                document.body.append(button);

                const attributeButton = document.createElement("button");
                attributeButton.id = "language-rendering-attribute-button";
                attributeButton.textContent = "English fallback";
                document.body.append(attributeButton);
                attributeButton.setAttribute("aria-label", "简体中文标签");
                attributeButton.setAttribute("title", "简体中文标题");

                const input = document.createElement("input");
                input.id = "language-rendering-input";
                document.body.append(input);
                input.value = "简体中文输入";
                input.dispatchEvent(new Event("input", {bubbles: true}));

                const traditional = document.createElement("span");
                traditional.id = "language-rendering-traditional-boundary";
                traditional.lang = "zh-Hant";
                traditional.textContent = "繁體中文保留边界";
                document.body.append(traditional);
                traditional.textContent = "后续繁體中文仍保留边界";

                const english = document.createElement("button");
                english.id = "language-rendering-english-only";
                english.textContent = "English only";
                document.body.append(english);
            }""",
        )

        expect(page.locator("#language-rendering-dynamic-button")).to_have_attribute(
            "lang",
            "zh-CN",
        )
        expect(page.locator("#language-rendering-attribute-button")).to_have_attribute(
            "lang",
            "zh-CN",
        )
        expect(page.locator("#language-rendering-input")).to_have_attribute("lang", "zh-CN")
        expect(page.locator("#language-rendering-traditional-boundary")).to_have_attribute(
            "lang",
            "zh-Hant",
        )
        assert page.locator("#language-rendering-english-only").get_attribute("lang") is None

        page.locator("#language-rendering-english-only").evaluate(
            "element => { element.textContent = '后续动态简体中文'; }"
        )
        expect(page.locator("#language-rendering-english-only")).to_have_attribute(
            "lang",
            "zh-CN",
        )

        page.evaluate(
            """() => {
                const host = document.createElement("div");
                host.id = "language-rendering-glyph-fixture";
                host.style.cssText = "font-family: sans-serif; font-size: 64px; line-height: 1;";
                const createSample = (id, language) => {
                    const sample = document.createElement("span");
                    sample.id = id;
                    sample.style.cssText = "display: inline-block; white-space: nowrap;";
                    if (language) sample.lang = language;
                    sample.textContent = "骨直着令";
                    host.append(sample);
                };
                createSample("language-rendering-glyph-target", "");
                createSample("language-rendering-glyph-simplified", "zh-CN");
                document.body.append(host);
            }""",
        )
        expect(page.locator("#language-rendering-glyph-target")).to_have_attribute("lang", "zh-CN")
        page.evaluate("() => document.fonts.ready")
        target_glyph = _decode_screenshot(
            page.locator("#language-rendering-glyph-target").screenshot()
        )
        simplified_glyph = _decode_screenshot(
            page.locator("#language-rendering-glyph-simplified").screenshot()
        )
        assert target_glyph.size == simplified_glyph.size
        assert ImageChops.difference(target_glyph, simplified_glyph).getbbox() is None

        for page_index, entry_point in enumerate(("/cache/x", "/browser", "/settings", "/agent")):
            page.goto(f"{sidebar_server_url}{entry_point}", wait_until="domcontentloaded")
            expect(page.locator('script[src*="language-rendering.js"]')).to_have_count(1)
            marker_id = f"language-rendering-entry-point-{page_index}"
            page.evaluate(
                """markerId => {
                    const button = document.createElement("button");
                    button.id = markerId;
                    button.textContent = "全局简体中文入口";
                    document.body.append(button);
                }""",
                marker_id,
            )
            expect(page.locator(f"#{marker_id}")).to_have_attribute("lang", "zh-CN")
    finally:
        context.close()


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
        assert toggle.evaluate(
            "element => element.parentElement?.classList.contains('page')"
        ), device_name

        _tap_toggle_center(page, toggle)
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

        _tap_toggle_center(page, toggle)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _assert_toggle_hit_target(page)
        _tap_toggle_center(page, toggle)
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

        _tap_toggle_center(page, toggle)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(backdrop).to_be_visible()

        page.set_viewport_size({"width": 1_024, "height": 768})
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _assert_hidden_backdrop(page)

        page.set_viewport_size({"width": 820, "height": 1_180})
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(backdrop).to_be_visible()
        _assert_toggle_hit_target(page)

        _tap_toggle_center(page, toggle)
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


@pytest.mark.integration
@pytest.mark.slow
def test_agent_connection_selection_survives_cache_navigation(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent",
        1_280,
        900,
        touch=False,
    )
    try:
        page.get_by_role("button", name="Browser: Edge", exact=True).click()
        with page.expect_response(re.compile(r"/api/agent/preferences$")):
            page.get_by_role("option", name="Chrome", exact=True).click()
        expect(page.locator('#agent_runtime_form input[name="browser"]')).to_have_value(
            "chrome"
        )
        expect(page.get_by_role("button", name="Browser: Chrome", exact=True)).to_be_visible()

        page.get_by_role("link", name="Cache", exact=True).click()
        expect(page).to_have_url(re.compile(r"/cache/chatgpt$"))
        expect(page.locator('[data-dock-section="cache"]')).to_have_attribute("aria-current", "page")
        expect(page.locator('[data-dock-section="agent"]')).not_to_have_attribute("aria-current", "page")
        page.get_by_role("link", name="Agent", exact=True).click()

        expect(page.get_by_role("button", name="Browser: Chrome", exact=True)).to_be_visible()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_browser_text_media_switch_defaults_to_text_and_remembers_selection(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/browser",
        1_280,
        900,
        touch=False,
    )
    try:
        text_input = page.locator("#browser_view_text")
        media_input = page.locator("#browser_view_media")
        expect(text_input).to_be_checked()
        expect(media_input).not_to_be_checked()
        expect(page.locator(".browser-content-mode-control")).to_have_attribute(
            "data-segmented-active-index",
            "0",
        )

        page.locator('label[for="browser_view_media"]').click()
        expect(page).to_have_url(re.compile(r"/browser\?view=media"))
        expect(media_input).to_be_checked()
        expect(page.locator(".browser-content-mode-control")).to_have_attribute(
            "data-segmented-active-index",
            "1",
        )

        page.goto(f"{sidebar_server_url}/agent")
        page.goto(f"{sidebar_server_url}/browser")
        expect(page).to_have_url(re.compile(r"/browser\?view=media"))
        expect(page.locator("#browser_view_media")).to_be_checked()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("source_key", ("chatgpt", "grok", "gemini"))
def test_cache_sidebar_text_media_switcher_defaults_to_text(
    disposable_browser: Browser,
    sidebar_server_url: str,
    source_key: str,
) -> None:
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/{source_key}",
        1_280,
        900,
        touch=False,
    )
    try:
        mode_control = page.locator("[data-cache-content-mode]")
        text_option = page.locator('[data-cache-content-mode-option="text"]')
        media_option = page.locator('[data-cache-content-mode-option="media"]')
        expect(mode_control).to_be_visible()
        expect(mode_control).to_have_attribute("data-segmented-active-index", "0")
        expect(text_option).to_have_attribute("aria-checked", "true")
        expect(media_option).to_have_attribute("aria-checked", "false")
        if source_key == "chatgpt":
            expect(page.locator("#start_form_chatgpt > label")).to_have_count(0)
            expect(page.locator("[data-chatgpt-media-config]")).to_be_hidden()
            expect(page.locator('[name="chatgpt_project_url"]')).to_be_disabled()

        media_option.click()
        expect(page).to_have_url(re.compile(rf"/cache/{source_key}$"))
        expect(page.locator('[data-cache-content-mode-option="media"]')).to_have_attribute(
            "aria-checked",
            "true",
        )
        expect(page.locator("[data-cache-content-mode]")).to_have_attribute(
            "data-segmented-active-index",
            "1",
        )
        if source_key == "chatgpt":
            expect(page.locator("#start_form_chatgpt > label")).to_have_count(0)
            expect(page.locator("[data-chatgpt-media-config]")).to_be_visible()
            expect(page.locator('[name="chatgpt_project_url"]')).to_be_enabled()

        page.locator('[data-cache-content-mode-option="text"]').click()
        if source_key == "chatgpt":
            expect(page).to_have_url(re.compile(r"/cache/chatgpt$"))
            expect(page.locator("[data-chatgpt-media-config]")).to_be_hidden()
            expect(page.locator("[data-chatgpt-content-mode-input]")).to_have_value("text")
            expect(page.locator('[name="chatgpt_project_url"]')).to_be_disabled()
        else:
            expect(page).to_have_url(
                re.compile(rf"/browser\?view=text.*session_view=1.*source={source_key}"),
            )
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_gemini_cache_source_switcher_opens_chatgpt_cache_page(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/gemini",
        1_512,
        982,
        touch=False,
    )
    try:
        page.locator("[data-cache-source-switcher-trigger]").click()
        page.locator('[data-cache-source-switcher-option="chatgpt"]').click()
        expect(page).to_have_url(re.compile(r"/cache/chatgpt$"))
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("device_name", "width", "height", "touch"),
    (
        ("iPhone 15 Pro", 393, 852, True),
        ("wide desktop", 1_512, 982, False),
    ),
)
def test_gemini_source_mark_preserves_full_color_at_target_viewports(
    disposable_browser: Browser,
    sidebar_server_url: str,
    device_name: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/gemini",
        width,
        height,
        touch=touch,
    )
    try:
        mark = page.locator(
            ".cache-source-switcher-trigger .cache-source-mark.is-full-color"
        )
        expect(mark).to_have_count(1)
        rendering = mark.evaluate(
            """element => {
                const before = getComputedStyle(element, "::before");
                return {
                    backgroundImage: before.backgroundImage,
                    height: before.height,
                    maskImage: before.maskImage,
                    width: before.width,
                };
            }"""
        )
        assert "Google_Gemini_logo_2025_symbol.svg" in rendering["backgroundImage"], device_name
        assert rendering["maskImage"] == "none", device_name
        assert rendering["width"] == rendering["height"] == "16px", device_name
    finally:
        context.close()
