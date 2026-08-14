"""Disposable-browser E2E coverage for the responsive sidebar and language boundaries.

Code version: v1.8.5-codex.1
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
def test_cache_source_switcher_reuses_the_complete_registry_across_cache_pages(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify every cache sidebar exposes the same complete source menu in Chromium."""
    expected_sources = ["chatgpt", "gemini", "grok", "x"]
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/chatgpt",
        1_280,
        900,
        touch=False,
    )
    try:
        for page_source in ("chatgpt", "gemini", "grok"):
            if page_source != "chatgpt":
                page.goto(f"{sidebar_server_url}/cache/{page_source}", wait_until="domcontentloaded")

            aside = page.locator("xpath=/html/body/main/div/aside")
            expect(aside).to_have_count(1)
            options = aside.locator("[data-cache-source-switcher-option]")
            expect(options).to_have_count(len(expected_sources))
            assert options.evaluate_all(
                "elements => elements.map(element => element.dataset.cacheSourceSwitcherOption)"
            ) == expected_sources
            expected_paths = (
                [
                    "/cache/chatgpt",
                    "/browser?view=text&session_view=1&q=&source=gemini&sort=newest",
                    "/browser?view=text&session_view=1&q=&source=grok&sort=newest",
                    "/cache/x",
                ]
                if page_source == "gemini"
                else ["/cache/chatgpt", "/cache/gemini", "/cache/grok", "/cache/x"]
            )
            assert options.evaluate_all(
                "elements => elements.map(element => element.dataset.cacheSourceSwitcherPath)"
            ) == expected_paths
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_cache_sidebars_reuse_the_chatgpt_base_contract(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify all provider sidebars reuse ChatGPT's shared control structure."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/chatgpt",
        1_280,
        900,
        touch=False,
    )
    try:
        for page_source in ("chatgpt", "gemini", "grok"):
            if page_source != "chatgpt":
                page.goto(f"{sidebar_server_url}/cache/{page_source}", wait_until="domcontentloaded")

            aside = page.locator("xpath=/html/body/main/div/aside")
            expect(aside).to_have_count(1)
            expect(aside.locator(":scope > .hero")).to_have_count(1)
            expect(aside.locator(":scope > .cache-page-content-mode-section")).to_have_count(1)
            expect(aside.locator("[data-cache-source-switcher]")).to_have_count(1)
            expect(aside.locator("[data-cache-source-switcher-option]")).to_have_count(4)
            expect(aside.locator("[data-browser-session-panel]")).to_have_count(1)
            expect(aside.locator(".browser-session-panel-label")).to_have_text("Authorized browser")
            expect(aside.locator(".cache-settings-link")).to_have_count(1)
            expect(aside.locator("[data-cache-action-row]")).to_have_count(1)
            expect(aside.locator("#start_button")).to_have_count(1)
            expect(aside.locator("#stop_button")).to_have_count(1)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_response_pagination_keeps_spatial_effects_visible(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify the Agent pagination shell is not clipped by its response ancestors."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent",
        1_280,
        900,
        touch=False,
    )
    try:
        contract = page.evaluate(
            """() => {
                const pagination = document.querySelector("#agent_response_pagination");
                const output = document.querySelector("#agent_response_output");
                const answer = document.querySelector("#agent_response_answer");
                const card = output?.closest(".agent-response-card");
                const task = card?.closest(".agent-task-card");
                if (!pagination || !output || !answer || !card || !task) return null;

                output.hidden = false;
                pagination.hidden = false;
                pagination.replaceChildren();
                const indicator = document.createElement("span");
                indicator.className = "local-store-pagination-indicator";
                indicator.setAttribute("aria-hidden", "true");
                pagination.append(indicator);
                const ellipsis = document.createElement("span");
                ellipsis.className = "local-store-page-ellipsis";
                ellipsis.setAttribute("aria-hidden", "true");
                const dots = document.createElement("span");
                dots.className = "local-store-page-ellipsis-dots";
                ellipsis.append(dots);
                pagination.append(ellipsis);
                for (let page = 1; page <= 5; page += 1) {
                    const button = document.createElement("button");
                    button.className = `local-store-page-button${page === 1 ? " is-active" : ""}`;
                    button.textContent = String(page);
                    pagination.append(button);
                }
                pagination.classList.add("is-animated");

                const read = (element) => {
                    const style = window.getComputedStyle(element);
                    return {
                        overflow: style.overflow,
                        overflowX: style.overflowX,
                        overflowY: style.overflowY,
                        position: style.position,
                        zIndex: style.zIndex,
                    };
                };
                return {
                    ancestors: [task, card, output, pagination].map(read),
                    answer: read(answer),
                    paginationWidth: pagination.getBoundingClientRect().width,
                    indicatorVisible: window.getComputedStyle(indicator).opacity === "1",
                };
            }""",
        )
        assert contract is not None
        assert contract["paginationWidth"] > 0
        assert contract["indicatorVisible"]
        assert all(item["overflow"] == "visible" for item in contract["ancestors"])
        assert contract["ancestors"][-1]["position"] == "relative"
        assert contract["ancestors"][-1]["zIndex"] == "2"
        assert contract["answer"]["overflowX"] == "hidden"
        assert contract["answer"]["overflowY"] == "auto"

        ellipsis = page.locator("#agent_response_pagination .local-store-page-ellipsis")
        expect(ellipsis).to_have_count(1)
        ellipsis.hover()
        hover_state = ellipsis.evaluate(
            "element => ({background: getComputedStyle(element).background, boxShadow: getComputedStyle(element).boxShadow})"
        )
        assert hover_state["background"] != "rgba(0, 0, 0, 0)"
        assert hover_state["boxShadow"] != "none"
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_model_and_sidebar_service_triggers_share_typography(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify the exact Agent model and sidebar service controls render matching label typography."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent",
        1_280,
        900,
        touch=False,
    )
    try:
        main_button = page.locator(
            "xpath=/html/body/main/div/section/div[2]/article/form/label/span/span/span[1]/button"
        )
        sidebar_button = page.locator(
            "xpath=/html/body/main/div/aside/form/div[2]/label/div/button"
        )
        expect(main_button).to_have_count(1)
        expect(sidebar_button).to_have_count(1)

        typography = page.evaluate(
            """([main, sidebar]) => {
                const readLabel = (button) => {
                    const label = button?.querySelector("[data-agent-combobox-selected-label]");
                    if (!label) return null;
                    const style = window.getComputedStyle(label);
                    return {
                        fontFamily: style.fontFamily,
                        fontSize: style.fontSize,
                        fontWeight: style.fontWeight,
                        lineHeight: style.lineHeight,
                    };
                };
                return [readLabel(main), readLabel(sidebar)];
            }""",
            [main_button.element_handle(), sidebar_button.element_handle()],
        )
        assert typography[0] is not None
        assert typography[0] == typography[1]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_browser_session_status_reuses_account_typography_for_terminal_and_cache(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify Agent and Cache status surfaces reuse the same non-bold status typography."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent",
        1_280,
        900,
        touch=False,
    )
    try:
        account = page.locator(
            "xpath=/html/body/main/div/aside/form/div[1]/label[2]/div/div[2]/div/div/div/strong"
        )
        terminal_label = page.locator(
            "xpath=/html/body/main/div/aside/form/div[1]/label[2]/div/div[2]/div/div/p/span[2]"
        )
        expect(account).to_have_count(1)
        expect(terminal_label).to_have_count(1)

        agent_typography = page.evaluate(
            """([accountElement, terminalElement]) => {
                const read = (element) => {
                    const style = window.getComputedStyle(element);
                    return {
                        fontFamily: style.fontFamily,
                        fontSize: style.fontSize,
                        fontWeight: style.fontWeight,
                        lineHeight: style.lineHeight,
                        textAlign: style.textAlign,
                    };
                };
                return [read(accountElement), read(terminalElement)];
            }""",
            [account.element_handle(), terminal_label.element_handle()],
        )
        assert agent_typography[0] == agent_typography[1]
        assert agent_typography[0]["fontWeight"] == "400"
        assert agent_typography[0]["textAlign"] == "left"

        page.goto(f"{sidebar_server_url}/cache/chatgpt", wait_until="domcontentloaded")
        cache_account = page.locator("aside .browser-session-status-account")
        expect(cache_account).to_have_count(1)
        cache_typography = cache_account.evaluate(
            "element => { const style = getComputedStyle(element); return {fontFamily: style.fontFamily, fontSize: style.fontSize, fontWeight: style.fontWeight, lineHeight: style.lineHeight, textAlign: style.textAlign}; }"
        )
        assert cache_typography == agent_typography[0]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_cache_shared_settings_link_opens_the_downloads_category(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify the shared cache settings link leaves the Cache form and opens Downloads."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/x",
        1_280,
        900,
        touch=False,
    )
    try:
        settings_link = page.locator(".cache-settings-link")
        expect(settings_link).to_have_count(1)
        expect(settings_link).to_have_attribute("href", "/settings#settings-downloads")
        expect(page.locator("#start_form section")).to_have_count(0)
        assert settings_link.evaluate("element => !element.closest('form')")

        settings_link.click()
        page.wait_for_url(re.compile(r"/settings#settings-downloads$"))

        expect(page.locator("[data-settings-category-shell]")).to_have_attribute(
            "data-active-category",
            "downloads",
        )
        expect(page.locator("#settings-downloads")).to_be_visible()
        expect(page.locator('[data-settings-category="downloads"]')).to_have_class(
            re.compile(r"\bis-active\b")
        )
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_cache_action_row_switches_stop_visibility_with_running_state(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify the primary Cache action uses the idle and running layouts."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/grok",
        1_280,
        900,
        touch=False,
    )
    try:
        action_row = page.locator("[data-cache-action-row]")
        stop_form = page.locator(".cache-action-row .sidebar-form-stop")
        start_button = page.locator("#start_button")
        expect(action_row).to_have_attribute("data-action-running", "false")
        expect(stop_form).to_be_hidden()
        expect(start_button).to_have_text("Start")
        idle_start_right = start_button.evaluate(
            """button => {
                return button.getBoundingClientRect().right;
            }"""
        )
        assert idle_start_right >= action_row.evaluate(
            "row => row.getBoundingClientRect().right - 2"
        )

        def fulfill_running_status(route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["running"] = True
            route.fulfill(response=response, json=payload)

        page.route("**/api/cache/grok/status", fulfill_running_status)
        page.reload(wait_until="domcontentloaded")
        expect(action_row).to_have_attribute("data-action-running", "true")
        expect(page.locator(".cache-action-row .sidebar-form-start")).to_be_hidden()
        expect(stop_form).to_be_visible()
        stop_button = stop_form.locator("#stop_button")
        expect(stop_button).to_have_class(re.compile(r"\bdanger-button\b"))
        running_stop_right = stop_button.evaluate(
            "button => button.getBoundingClientRect().right"
        )
        assert abs(running_stop_right - idle_start_right) <= 2
    finally:
        context.close()


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

                const sourceIdentity = document.createElement("button");
                sourceIdentity.id = "language-rendering-source-identity";
                sourceIdentity.textContent = "啓 啟 天后 吳 吴";
                document.body.append(sourceIdentity);
            }""",
        )

        assert page.locator("#language-rendering-dynamic-button").text_content() == "动态简体中文"
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
        assert page.locator("#language-rendering-traditional-boundary").text_content() == (
            "后续繁體中文仍保留边界"
        )
        assert page.locator("#language-rendering-source-identity").text_content() == "啓 啟 天后 吳 吴"
        assert page.locator("#language-rendering-english-only").get_attribute("lang") is None

        page.locator("#language-rendering-english-only").evaluate(
            "element => { element.textContent = '后续动态简体中文'; }"
        )
        expect(page.locator("#language-rendering-english-only")).to_have_attribute(
            "lang",
            "zh-CN",
        )

        page.goto(f"{sidebar_server_url}/agent", wait_until="domcontentloaded")
        session_mode_trigger = page.locator(
            "xpath=/html/body/main/div/aside/form/div[2]/label/div/button"
        )
        recent_session_trigger = page.locator(
            "xpath=/html/body/main/div/aside/form/div[2]/div[1]/div/button"
        )
        expect(session_mode_trigger).to_have_count(1)
        expect(recent_session_trigger).to_have_count(1)
        page.evaluate(
            """() => {
                document.querySelector(
                    ".agent-session-mode-combobox [data-agent-combobox-selected-label]"
                ).textContent = "简体中文会话标题";
                document.querySelector(
                    '[data-agent-session-list="recent"] [data-agent-combobox-selected-label]'
                ).textContent = "简体中文最近会话";
            }""",
        )
        session_mode_label = session_mode_trigger.locator("[data-agent-combobox-selected-label]")
        recent_session_label = recent_session_trigger.locator("[data-agent-combobox-selected-label]")
        expect(session_mode_label).to_have_attribute("lang", "zh-CN")
        expect(session_mode_trigger).to_contain_text("简体中文会话标题")
        expect(recent_session_label).to_have_attribute("lang", "zh-CN")
        expect(recent_session_trigger).to_contain_text("简体中文最近会话")

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
@pytest.mark.parametrize(
    ("platform", "platform_label", "session_url"),
    (
        ("gemini", "Gemini", "https://gemini.google.com/app/gemini-recent-session"),
        ("grok", "Grok", "https://grok.com/c/grok-recent-session"),
    ),
)
def test_agent_recent_provider_sessions_submit_agentic_task_target(
    disposable_browser: Browser,
    sidebar_server_url: str,
    platform: str,
    platform_label: str,
    session_url: str,
) -> None:
    """Verify Gemini and Grok serialize a selected recent session into Agent execution."""
    captured_ask_payloads: list[dict[str, str]] = []
    source_requests: list[str] = []

    def agent_payload(selected_platform: str) -> dict[str, object]:
        return {
            "runtime": {
                "ready": True,
                "host_operating_system": "macos",
                "message": "Computer Use is ready on this Mac.",
                "terminal_execution": {
                    "ready": True,
                    "status_label": "Granted",
                    "message": "Terminal execution is available.",
                },
            },
            "agent": {
                "running": False,
                "phase": "idle",
                "message": "Ready to use a signed-in Web AI session.",
                "prompt": "",
                "response": "",
                "response_html": "",
                "history": [],
                "activity": [],
                "conversation_url": "",
                "project_url": "",
                "session_title": "",
                "session_mode": "new",
                "platform": selected_platform,
                "model": "gemini-3.1-pro" if selected_platform == "gemini" else "grok-auto",
                "finished_at": "",
            },
        }

    def fulfill_agent_status(route) -> None:
        route.fulfill(json=agent_payload(platform))

    def fulfill_browser_status(route) -> None:
        browser_id = "chrome" if "browser=chrome" in route.request.url else "edge"
        route.fulfill(
            json={
                "platform": platform,
                "browser": browser_id,
                "browser_label": browser_id.title(),
                "logged_in": True,
                "can_download": True,
                "account_name": f"{platform_label} account",
                "message": f"{browser_id.title()} is ready for {platform_label} Web.",
            }
        )

    def fulfill_preferences(route) -> None:
        payload = route.request.post_data_json or {}
        route.fulfill(json=agent_payload(str(payload.get("platform") or platform)))

    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(
            json={
                "platform": platform,
                "browser_label": "Edge",
                "recent_sessions": [
                    {
                        "id": f"{platform}-recent-session",
                        "title": f"{platform_label} selected session",
                        "url": session_url,
                        "updated_at": "2026-08-14T04:00:00Z",
                    }
                ],
                "projects": [],
                "limit": 20,
            }
        )

    def fulfill_ask(route) -> None:
        captured_ask_payloads.append(route.request.post_data_json or {})
        route.fulfill(json=agent_payload(platform))

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 900},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route("**/api/agent/preferences", fulfill_preferences)
    page.route("**/api/agent/sources**", fulfill_sources)
    page.route("**/api/agent/ask", fulfill_ask)
    try:
        page.goto(f"{sidebar_server_url}/agent", wait_until="domcontentloaded")
        page.get_by_role("button", name="Web service: ChatGPT", exact=True).click()
        page.locator(
            f'.agent-platform-combobox [data-agent-combobox-option="{platform}"]'
        ).click()
        expect(page.get_by_role("button", name=f"Web service: {platform_label}", exact=True)).to_be_visible()

        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        page.locator(
            '.agent-session-mode-combobox [data-agent-combobox-option="recent"]'
        ).click()
        recent_option = page.locator(
            f'[data-agent-session-list="recent"] [data-agent-combobox-option="{session_url}"]'
        )
        expect(recent_option).to_have_count(1)
        page.locator('[data-agent-session-list="recent"] [data-agent-combobox-trigger]').click()
        expect(recent_option).to_be_visible()
        recent_option.click()

        expect(page.locator('[data-agent-prompt-session-mode]')).to_have_value("recent")
        expect(page.locator('[data-agent-prompt-conversation-url]')).to_have_value(session_url)
        expect(page.locator('[data-agent-prompt-session-title]')).to_have_value(
            f"{platform_label} selected session"
        )
        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        expect(
            page.locator('.agent-session-mode-combobox [data-agent-combobox-option="project"]')
        ).to_be_visible()
        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        expect(page.locator("#agent_ask_button")).to_be_enabled()

        page.locator('[data-agent-prompt-input]').fill(f"Inspect the {platform_label} task workspace.")
        with page.expect_request(re.compile(r"/api/agent/ask$")):
            page.locator("#agent_ask_button").click()
        assert len(captured_ask_payloads) == 1
        assert captured_ask_payloads[0]["platform"] == platform
        assert captured_ask_payloads[0]["session_mode"] == "recent"
        assert captured_ask_payloads[0]["conversation_url"] == session_url
        assert captured_ask_payloads[0]["session_title"] == f"{platform_label} selected session"
        assert any(f"platform={platform}" in url for url in source_requests)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("platform", "platform_label", "project_url"),
    (
        ("gemini", "Gemini", "https://gemini.google.com/notebook/gemini-project"),
        ("grok", "Grok", "https://grok.com/project/grok-project?tab=conversations"),
    ),
)
def test_agent_provider_projects_submit_agentic_task_target(
    disposable_browser: Browser,
    sidebar_server_url: str,
    platform: str,
    platform_label: str,
    project_url: str,
) -> None:
    """Verify provider-native project containers serialize as one Project choice."""
    captured_ask_payloads: list[dict[str, str]] = []
    source_requests: list[str] = []
    project_session_requests: list[str] = []

    def agent_payload(selected_platform: str) -> dict[str, object]:
        return {
            "runtime": {
                "ready": True,
                "host_operating_system": "macos",
                "message": "Computer Use is ready on this Mac.",
                "terminal_execution": {
                    "ready": True,
                    "status_label": "Granted",
                    "message": "Terminal execution is available.",
                },
            },
            "agent": {
                "running": False,
                "phase": "idle",
                "message": "Ready to use a signed-in Web AI session.",
                "prompt": "",
                "response": "",
                "response_html": "",
                "history": [],
                "activity": [],
                "conversation_url": "",
                "project_url": "",
                "session_title": "",
                "session_mode": "new",
                "platform": selected_platform,
                "model": "gemini-3.1-pro" if selected_platform == "gemini" else "grok-auto",
                "finished_at": "",
            },
        }

    def fulfill_agent_status(route) -> None:
        route.fulfill(json=agent_payload(platform))

    def fulfill_browser_status(route) -> None:
        browser_id = "chrome" if "browser=chrome" in route.request.url else "edge"
        route.fulfill(
            json={
                "platform": platform,
                "browser": browser_id,
                "browser_label": browser_id.title(),
                "logged_in": True,
                "can_download": True,
                "account_name": f"{platform_label} account",
                "message": f"{browser_id.title()} is ready for {platform_label} Web.",
            }
        )

    def fulfill_preferences(route) -> None:
        payload = route.request.post_data_json or {}
        route.fulfill(json=agent_payload(str(payload.get("platform") or platform)))

    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(
            json={
                "platform": platform,
                "browser_label": "Edge",
                "recent_sessions": [],
                "projects": [
                    {
                        "id": f"{platform}-project",
                        "title": f"{platform_label} project",
                        "url": project_url,
                        "updated_at": "2026-08-14T04:00:00Z",
                    }
                ],
                "limit": 20,
            }
        )

    def fulfill_project_sessions(route) -> None:
        project_session_requests.append(route.request.url)
        route.fulfill(
            json={
                "platform": platform,
                "project_url": project_url,
                "sessions": [],
                "limit": 20,
            }
        )

    def fulfill_ask(route) -> None:
        captured_ask_payloads.append(route.request.post_data_json or {})
        route.fulfill(json=agent_payload(platform))

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 900},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route("**/api/agent/preferences", fulfill_preferences)
    page.route("**/api/agent/sources**", fulfill_sources)
    page.route("**/api/agent/project-sessions**", fulfill_project_sessions)
    page.route("**/api/agent/ask", fulfill_ask)
    try:
        page.goto(f"{sidebar_server_url}/agent", wait_until="domcontentloaded")
        page.get_by_role("button", name="Web service: ChatGPT", exact=True).click()
        page.locator(
            f'.agent-platform-combobox [data-agent-combobox-option="{platform}"]'
        ).click()
        expect(page.get_by_role("button", name=f"Web service: {platform_label}", exact=True)).to_be_visible()

        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        page.locator(
            '.agent-session-mode-combobox [data-agent-combobox-option="project"]'
        ).click()
        project_option = page.locator(
            f'[data-agent-session-list="projects"] [data-agent-combobox-option="{project_url}"]'
        )
        expect(project_option).to_have_count(1)
        page.locator('[data-agent-session-list="projects"] [data-agent-combobox-trigger]').click()
        expect(project_option).to_be_visible()
        project_option.click()

        expect(page.locator('[data-agent-prompt-session-mode]')).to_have_value("project_new")
        expect(page.locator('[data-agent-prompt-project-url]')).to_have_value(project_url)
        expect(page.locator('[data-agent-prompt-conversation-url]')).to_have_value("")
        expect(page.locator("#agent_ask_button")).to_be_enabled()

        page.locator('[data-agent-prompt-input]').fill(f"Inspect the {platform_label} project workspace.")
        with page.expect_request(re.compile(r"/api/agent/ask$")):
            page.locator("#agent_ask_button").click()
        assert len(captured_ask_payloads) == 1
        assert captured_ask_payloads[0]["platform"] == platform
        assert captured_ask_payloads[0]["session_mode"] == "project_new"
        assert captured_ask_payloads[0]["project_url"] == project_url
        assert captured_ask_payloads[0]["conversation_url"] == ""
        assert any(f"platform={platform}" in url for url in source_requests)
        assert any("project_url=" in url for url in project_session_requests)
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
