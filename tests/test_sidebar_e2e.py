"""Disposable-browser E2E coverage for the responsive sidebar and language boundaries.

Code version: v1.26.58-codex.1
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
import json
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

from app.core.computer_use_agent import (
    _ProviderSessionBinding,
    _provider_turn_snapshot,
    _select_web_model,
    _submit_chromium_web_prompt,
    load_computer_use_settings,
    parse_agent_action,
)
from app.core.gemini_downloader import inspect_gemini_session
from app.core.resource_persistence import CHATGPT_HISTORY_SCHEMA, write_parquet_rows_atomic


OVERLAY_VIEWPORTS = (
    ("iPhone SE", 375, 667),
    ("iPhone 15 Pro", 393, 852),
    ("Narrow layout breakpoint", 560, 844),
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
def sidebar_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    from app.web.app import create_app

    sandbox = tmp_path_factory.mktemp("cachelikes-sidebar-e2e")
    settings_path = sandbox / "settings" / "computer-use-agent.json"
    runtime_root = sandbox / "computer-use-runtime"
    application = create_app(
        sandbox / "local-store",
        computer_use_settings_path=settings_path,
        computer_use_runtime_root=runtime_root,
        agent_external_operations_enabled=False,
    )
    application.config.update(TESTING=True)
    assert application.extensions["computer_use_settings"]._settings_path == settings_path
    assert application.extensions["computer_use_agent_service"]._runtime_root == runtime_root
    server: BaseWSGIServer = make_server("127.0.0.1", 0, application, threaded=True)
    assert server.server_port != 8666
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


@pytest.fixture()
def seeded_chatgpt_browser_server_url(tmp_path: Path) -> Iterator[str]:
    from app.web.app import create_app

    root = tmp_path / "local-store"
    write_parquet_rows_atomic(
        root / "llm" / "chatgpt" / "history.parquet",
        [
            {
                "schema_version": 1,
                "platform": "chatgpt",
                "conversation_id": "chatgpt-wrap-demo",
                "conversation_url": "https://chatgpt.com/c/chatgpt-wrap-demo",
                "conversation_title": "ChatGPT timestamp wrapping",
                "message_key": "chatgpt-wrap-demo:0:user",
                "turn_index": 0,
                "message_index": 0,
                "role": "user",
                "author_label": "You",
                "content_text": "A timestamp layout regression fixture.",
                "content_html": "",
                "content_sha256": "chatgpt-wrap-demo-hash",
                "source_links": [],
                "model_label": "",
                "first_seen_at": "2026-08-12T04:59:00Z",
                "last_seen_at": "2026-08-12T05:00:00Z",
            }
        ],
        CHATGPT_HISTORY_SCHEMA,
    )
    application = create_app(
        root,
        computer_use_settings_path=tmp_path / "settings" / "computer-use-agent.json",
        computer_use_runtime_root=tmp_path / "computer-use-runtime",
        agent_external_operations_enabled=False,
    )
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
    reduced_motion: str | None = "reduce",
) -> tuple[Page, BrowserContext]:
    context_options = {
        "viewport": {"width": width, "height": height},
        "has_touch": touch,
        "is_mobile": touch,
    }
    if reduced_motion is not None:
        context_options["reduced_motion"] = reduced_motion
    context = browser.new_context(
        **context_options,
    )
    page = context.new_page()
    if init_script:
        page.add_init_script(init_script)
    page.goto(url, wait_until="domcontentloaded")
    return page, context


def _wait_for_global_title_rail(page: Page, title_selector: str) -> None:
    page.wait_for_function(
        """selector => {
            const centerY = element => {
                if (!(element instanceof HTMLElement)) return null;
                const rect = element.getBoundingClientRect();
                return rect.top + (rect.height / 2);
            };
            const title = centerY(document.querySelector(selector));
            const toggle = centerY(document.querySelector("#sidebar_toggle"));
            const theme = centerY(document.querySelector("#global_theme_toggle"));
            return title !== null
                && toggle !== null
                && theme !== null
                && Math.abs(title - toggle) <= 1
                && Math.abs(title - theme) <= 1;
        }""",
        arg=title_selector,
    )


def _assert_hidden_backdrop(page: Page) -> None:
    backdrop = page.locator("#sidebar_backdrop")
    expect(backdrop).to_be_hidden()
    expect(backdrop).to_have_attribute("hidden", "")
    assert backdrop.evaluate("element => getComputedStyle(element).display") == "none"
    assert backdrop.evaluate("element => getComputedStyle(element).pointerEvents") == "none"


def _assert_toggle_hit_target(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const toggle = document.querySelector("#sidebar_toggle");
            if (!(toggle instanceof HTMLElement)) return false;
            const rect = toggle.getBoundingClientRect();
            if (rect.width < 44 || rect.height < 44) return false;
            const hit = document.elementFromPoint(
                rect.left + (rect.width / 2),
                rect.top + (rect.height / 2),
            );
            const rectKey = [rect.left, rect.top, rect.width, rect.height]
                .map(value => value.toFixed(3))
                .join(",");
            const previousRectKey = window.__cachelikesStableToggleRect || "";
            window.__cachelikesStableToggleRect = rectKey;
            return previousRectKey === rectKey && Boolean(hit?.closest("#sidebar_toggle"));
        }"""
    )


def _tap_toggle_center(page: Page, toggle) -> None:
    box = toggle.bounding_box()
    assert box is not None
    page.touchscreen.tap(box["x"] + (box["width"] / 2), box["y"] + (box["height"] / 2))


def _assert_agent_session_source_menu_is_hit_testable(page: Page) -> None:
    """Verify the source menu stays above both the inline list and the Dock."""
    trigger = page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]")
    trigger.click()
    project_option = page.locator(
        '.agent-session-mode-combobox [data-agent-combobox-option="project"]'
    )
    expect(project_option).to_be_visible()
    hit_test = project_option.evaluate(
        """option => {
            const rect = option.getBoundingClientRect();
            const point = {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
            };
            const hit = document.elementFromPoint(point.x, point.y);
            const modeMenu = option.closest('.agent-session-mode-combobox')
                ?.querySelector('[data-agent-combobox-menu]');
            const dock = document.querySelector('.sidebar-dock');
            const modeMenuBox = modeMenu?.getBoundingClientRect();
            const dockBox = dock?.getBoundingClientRect();
            return {
                hitIsOption: hit === option || option.contains(hit),
                modeMenuAboveDock: modeMenuBox && dockBox
                    ? modeMenuBox.bottom <= dockBox.top + 1
                    : false,
                modeMenuZIndex: getComputedStyle(
                    option.closest('.agent-session-mode-combobox'),
                ).zIndex,
            };
        }"""
    )
    assert hit_test["modeMenuAboveDock"], hit_test
    assert hit_test["hitIsOption"], hit_test
    trigger.click()


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
    expected_sources = ["chatgpt", "claude", "gemini", "grok", "x"]
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/chatgpt",
        1_280,
        900,
        touch=False,
    )
    try:
        for page_source in ("chatgpt", "claude", "gemini", "grok"):
            if page_source != "chatgpt":
                page.goto(f"{sidebar_server_url}/cache/{page_source}", wait_until="domcontentloaded")

            aside = page.locator("xpath=/html/body/main/div/aside")
            expect(aside).to_have_count(1)
            options = aside.locator("[data-cache-source-switcher-option]")
            expect(options).to_have_count(len(expected_sources))
            assert options.evaluate_all(
                "elements => elements.map(element => element.dataset.cacheSourceSwitcherOption)"
            ) == expected_sources
            source_trigger = aside.locator("[data-cache-source-switcher-trigger]")
            browser_trigger = aside.locator('[data-role="browser-picker-trigger"]')
            assert source_trigger.evaluate("element => element.getBoundingClientRect().height") == 36
            assert browser_trigger.evaluate("element => element.getBoundingClientRect().height") == 36
            expect(page.locator('[data-dock-section="cache"]')).to_have_class(re.compile(r"\bis-active\b"))
            expect(page.locator('[data-dock-section="agent"]')).not_to_have_class(re.compile(r"\bis-active\b"))
            expected_paths = (
                [
                    "/cache/chatgpt",
                    "/cache/claude",
                    "/cache/gemini",
                    "/cache/grok",
                    "/cache/x",
                ]
                if page_source == "claude"
                else [
                    "/cache/chatgpt",
                    "/cache/claude",
                    "/cache/gemini",
                    "/cache/grok",
                    "/cache/x",
                ]
                if page_source == "gemini"
                else [
                    "/cache/chatgpt",
                    "/cache/claude",
                    "/cache/gemini",
                    "/cache/grok",
                    "/cache/x",
                ]
            )
            assert options.evaluate_all(
                "elements => elements.map(element => element.dataset.cacheSourceSwitcherPath)"
            ) == expected_paths
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_cache_status_stays_in_the_progress_panel_without_a_floating_banner(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep Cache status in the existing progress panel without duplicating it as a banner."""
    route = f"{sidebar_server_url}/cache/chatgpt"
    page, context = _open_page(
        disposable_browser,
        route,
        1_280,
        900,
        touch=False,
    )
    try:
        for width, height in ((1_280, 900), (715, 899), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(route, wait_until="domcontentloaded")
            expect(page.locator("#status_banner")).to_have_count(0)
            expect(page.locator('#message[data-status-field="message"]')).to_have_count(1)
            expect(page.locator('#message[data-status-field="message"]')).to_be_visible()
            status_card = page.locator(
                '[data-browser-session-panel] .browser-session-status-card'
            )
            expect(status_card).to_have_count(1)
            assert status_card.evaluate(
                "element => getComputedStyle(element).borderWidth"
            ) == "0px"
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_cache_events_card_stays_inside_content_scrollport_when_viewport_has_room(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep the empty Events surface inside the named scrollport on a tall desktop viewport."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/chatgpt",
        1_017,
        1_354,
        touch=False,
    )
    try:
        geometry = page.evaluate(
            """() => {
                const rect = selector => {
                    const element = document.querySelector(selector);
                    if (!element) return null;
                    const box = element.getBoundingClientRect();
                    return {top: box.top, bottom: box.bottom};
                };
                const scrollport = document.querySelector(
                    '[data-layout-role="content-scrollport"]',
                );
                return {
                    overview: rect('#overview'),
                    activity: rect('#activity'),
                    scrollport: rect('[data-layout-role="content-scrollport"]'),
                    scrollHeight: scrollport?.scrollHeight ?? 0,
                    clientHeight: scrollport?.clientHeight ?? 0,
                    documentOverflow: Math.max(
                        document.documentElement.scrollHeight,
                        document.body.scrollHeight,
                    ) - document.documentElement.clientHeight,
                };
            }"""
        )
        assert geometry["overview"] is not None
        assert geometry["activity"] is not None
        assert geometry["scrollport"] is not None
        assert geometry["activity"]["top"] >= geometry["overview"]["bottom"]
        assert geometry["activity"]["bottom"] <= geometry["scrollport"]["bottom"] + 1
        assert geometry["scrollHeight"] == geometry["clientHeight"]
        assert geometry["documentOverflow"] <= 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_cache_title_rail_stays_aligned_and_clear_when_the_sidebar_collapses(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Match the sibling title rail at desktop size in both sidebar states."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/chatgpt",
        1_024,
        900,
        touch=False,
    )
    try:
        toggle = page.locator("#sidebar_toggle")
        title = page.locator(".cache-overview-title-card .report-heading")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(title).to_have_text("ChatGPT cache overview")

        def read_geometry() -> dict[str, float]:
            return page.evaluate(
                """() => {
                    const toggle = document.querySelector("#sidebar_toggle").getBoundingClientRect();
                    const title = document.querySelector(
                        ".cache-overview-title-card .report-heading",
                    ).getBoundingClientRect();
                    const theme = document.querySelector("#global_theme_toggle").getBoundingClientRect();
                    const centerY = rect => rect.top + (rect.height / 2);
                    return {
                        titleCenterDelta: Math.abs(centerY(title) - centerY(toggle)),
                        themeCenterDelta: Math.abs(centerY(title) - centerY(theme)),
                        toggleGap: title.left - toggle.right,
                    };
                }"""
            )

        expanded = read_geometry()
        assert expanded["titleCenterDelta"] <= 1
        assert expanded["themeCenterDelta"] <= 1
        assert expanded["toggleGap"] >= 12

        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        page.wait_for_function(
            """() => {
                const toggle = document.querySelector("#sidebar_toggle").getBoundingClientRect();
                const title = document.querySelector(
                    ".cache-overview-title-card .report-heading",
                ).getBoundingClientRect();
                return title.left - toggle.right >= 12;
            }"""
        )
        collapsed = read_geometry()
        assert collapsed["titleCenterDelta"] <= 1
        assert collapsed["themeCenterDelta"] <= 1
        assert collapsed["toggleGap"] >= 12
        assert not page.evaluate(
            "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
            "> document.documentElement.clientWidth"
        )

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            """() => {
                const titleCard = document.querySelector(".cache-overview-title-card");
                return window.matchMedia("(max-width: 560px)").matches
                    && getComputedStyle(titleCard).paddingInlineEnd === "68px";
            }"""
        )
        expect(toggle).to_have_attribute("aria-expanded", "false")
        narrow = page.evaluate(
            """() => {
                const rectFor = selector => {
                    const rect = document.querySelector(selector).getBoundingClientRect();
                    return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
                };
                const overlaps = (left, right) => !(
                    left.right <= right.left
                    || left.left >= right.right
                    || left.bottom <= right.top
                    || left.top >= right.bottom
                );
                const toggle = rectFor("#sidebar_toggle");
                const titleElement = document.querySelector(
                    ".cache-overview-title-card .report-heading",
                );
                const title = rectFor(".cache-overview-title-card .report-heading");
                const theme = rectFor("#global_theme_toggle");
                const titleCard = rectFor(".cache-overview-title-card");
                const titleRow = rectFor(".cache-overview-title-card > .report-heading-row");
                const titleCardStyle = getComputedStyle(
                    document.querySelector(".cache-overview-title-card"),
                );
                const titleStyle = getComputedStyle(titleElement);
                const pageStyle = getComputedStyle(document.querySelector(".page"));
                return {
                    viewport: {
                        innerWidth: window.innerWidth,
                        clientWidth: document.documentElement.clientWidth,
                        devicePixelRatio: window.devicePixelRatio,
                    },
                    compactMediaMatches: window.matchMedia("(max-width: 560px)").matches,
                    pageClearance: pageStyle.getPropertyValue("--sidebar-toggle-quick-action-clearance"),
                    globalQuickActionsRight: pageStyle.getPropertyValue("--global-quick-actions-right"),
                    titleCard,
                    titleCardPaddingInlineEnd: titleCardStyle.paddingInlineEnd,
                    titleCardPaddingInlineStart: titleCardStyle.paddingInlineStart,
                    titleRow,
                    title,
                    titleWidth: titleElement.getBoundingClientRect().width,
                    titleMinWidth: titleStyle.minWidth,
                    titleMaxWidth: titleStyle.maxWidth,
                    theme,
                    toggle,
                    titleOverlapsTheme: overlaps(title, theme),
                    titleOverlapsToggle: overlaps(title, toggle),
                    toggleGap: title.left - toggle.right,
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) > document.documentElement.clientWidth,
                };
            }"""
        )
        narrow_debug = (
            f"viewport={narrow['viewport']}; titleCard={narrow['titleCard']}; "
            f"compact-media={narrow['compactMediaMatches']}; "
            f"page-clearance={narrow['pageClearance']}; "
            f"global-right={narrow['globalQuickActionsRight']}; "
            f"titleRow={narrow['titleRow']}; title={narrow['title']}; "
            f"theme={narrow['theme']}; toggle={narrow['toggle']}; "
            f"padding-inline={narrow['titleCardPaddingInlineStart']}/"
            f"{narrow['titleCardPaddingInlineEnd']}; "
            f"title-width={narrow['titleWidth']}; "
            f"title-min-width={narrow['titleMinWidth']}; "
            f"title-max-width={narrow['titleMaxWidth']}"
        )
        assert not narrow["titleOverlapsTheme"], narrow_debug
        assert not narrow["titleOverlapsToggle"], narrow_debug
        assert narrow["toggleGap"] >= 12, narrow_debug
        assert not narrow["horizontalOverflow"], narrow_debug
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_title_rail_stays_aligned_with_global_anchors_across_viewports(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep the Agent heading on the shared title rail without a stale status chip."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent/edge/chatgpt",
        1_280,
        720,
        touch=False,
        init_script="""
            (() => {
                const originalFetch = window.fetch.bind(window);
                window.fetch = (input, init) => {
                    const requestUrl = typeof input === "string" ? input : input?.url;
                    if (requestUrl && new URL(requestUrl, window.location.href).pathname === "/api/agent/status") {
                        return Promise.reject(new Error("Agent status polling is disabled for this layout test."));
                    }
                    return originalFetch(input, init);
                };
            })();
        """,
    )

    def read_geometry() -> dict[str, object]:
        return page.evaluate(
            """() => {
                const centerY = selector => {
                    const element = document.querySelector(selector);
                    if (!(element instanceof HTMLElement)) return null;
                    const rect = element.getBoundingClientRect();
                    return rect.top + (rect.height / 2);
                };
                const summary = document.querySelector(".agent-summary-card");
                if (!(summary instanceof HTMLElement)) return null;
                const summaryRect = summary.getBoundingClientRect();
                const summaryStyle = getComputedStyle(summary);
                const controlHeight = selector => {
                    const element = document.querySelector(selector);
                    return element instanceof HTMLElement
                        ? element.getBoundingClientRect().height
                        : null;
                };
                return {
                    headingCenterY: centerY("[data-agent-heading]"),
                    toggleCenterY: centerY("#sidebar_toggle"),
                    themeCenterY: centerY("#global_theme_toggle"),
                    summaryHeight: summaryRect.height,
                    summaryOverflow: summaryStyle.overflow,
                    chipCount: document.querySelectorAll("#agent_phase_chip").length,
                    readinessCount: document.querySelectorAll(".agent-readiness").length,
                    primaryControlHeights: [
                        controlHeight(".agent-platform-combobox [data-agent-combobox-trigger]"),
                        controlHeight(".agent-session-mode-combobox [data-agent-combobox-trigger]"),
                    ],
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) > document.documentElement.clientWidth,
                };
            }"""
        )

    try:
        _wait_for_global_title_rail(page, "[data-agent-heading]")
        desktop = read_geometry()
        assert desktop is not None
        assert abs(desktop["headingCenterY"] - desktop["toggleCenterY"]) <= 1
        assert abs(desktop["headingCenterY"] - desktop["themeCenterY"]) <= 1
        assert desktop["summaryHeight"] < 120
        assert desktop["summaryOverflow"] == "visible"
        assert desktop["chipCount"] == 0
        assert desktop["readinessCount"] == 0
        assert desktop["primaryControlHeights"] == [36, 36]
        assert not desktop["horizontalOverflow"]

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "() => window.matchMedia('(max-width: 560px)').matches"
        )
        _wait_for_global_title_rail(page, "[data-agent-heading]")
        narrow = read_geometry()
        assert narrow is not None
        assert abs(narrow["headingCenterY"] - narrow["toggleCenterY"]) <= 1
        assert abs(narrow["headingCenterY"] - narrow["themeCenterY"]) <= 1
        assert narrow["summaryHeight"] < 120
        assert narrow["summaryOverflow"] == "visible"
        assert narrow["chipCount"] == 0
        assert narrow["readinessCount"] == 0
        assert narrow["primaryControlHeights"] == [36, 36]
        assert not narrow["horizontalOverflow"]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_browser_title_rail_stays_aligned_with_global_anchors_across_viewports(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep the Cached text browser heading on the shared top anchor rail."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/browser?view=text&source=all&kind=all&q=&sort=newest&session_view=1",
        974,
        863,
        touch=False,
    )

    def read_geometry() -> dict[str, object]:
        return page.evaluate(
            """() => {
                const centerY = selector => {
                    const element = document.querySelector(selector);
                    if (!(element instanceof HTMLElement)) return null;
                    const rect = element.getBoundingClientRect();
                    return rect.top + (rect.height / 2);
                };
                const summary = document.querySelector(".browser-summary-card");
                if (!(summary instanceof HTMLElement)) return null;
                const summaryStyle = getComputedStyle(summary);
                return {
                    titleCenterY: centerY(".browser-heading-copy"),
                    sidebarCenterY: centerY("#browser_sidebar .hero h1"),
                    toggleCenterY: centerY("#sidebar_toggle"),
                    themeCenterY: centerY("#global_theme_toggle"),
                    summaryPaddingTop: summaryStyle.paddingTop,
                    summaryOverflow: summaryStyle.overflow,
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) > document.documentElement.clientWidth,
                };
            }"""
        )

    try:
        _wait_for_global_title_rail(page, ".browser-heading-copy")
        desktop = read_geometry()
        assert desktop is not None
        assert abs(desktop["titleCenterY"] - desktop["sidebarCenterY"]) <= 1
        assert abs(desktop["titleCenterY"] - desktop["toggleCenterY"]) <= 1
        assert abs(desktop["titleCenterY"] - desktop["themeCenterY"]) <= 1
        assert desktop["summaryPaddingTop"] == "10px"
        assert desktop["summaryOverflow"] == "visible"
        assert not desktop["horizontalOverflow"]

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function("() => window.matchMedia('(max-width: 560px)').matches")
        _wait_for_global_title_rail(page, ".browser-heading-copy")
        narrow = read_geometry()
        assert narrow is not None
        assert abs(narrow["titleCenterY"] - narrow["toggleCenterY"]) <= 1
        assert abs(narrow["titleCenterY"] - narrow["themeCenterY"]) <= 1
        assert narrow["summaryPaddingTop"] == "12px"
        assert narrow["summaryOverflow"] == "visible"
        assert not narrow["horizontalOverflow"]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_browser_filter_actions_stack_standard_buttons_across_viewports(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep the browser filter actions on separate rows at desktop and narrow widths."""
    route = f"{sidebar_server_url}/browser?view=text&session_view=1&source=all&sort=newest&q="
    page, context = _open_page(
        disposable_browser,
        route,
        1_280,
        900,
        touch=False,
    )
    try:
        for width, height in ((1_280, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(route, wait_until="domcontentloaded")
            actions = page.locator(".browser-filter-actions > :is(a, button)")
            expect(actions).to_have_count(2)
            expect(page.locator(".browser-chatgpt-media-link")).to_have_count(0)
            geometry = actions.evaluate_all(
                "elements => elements.map(element => {"
                "  const rect = element.getBoundingClientRect();"
                "  return {top: rect.top, height: rect.height};"
                "})"
            )
            assert geometry[1]["top"] >= geometry[0]["top"] + geometry[0]["height"] - 1, (
                width,
                geometry,
            )
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_browser_message_timestamps_keep_two_rows_across_viewports(
    disposable_browser: Browser,
    seeded_chatgpt_browser_server_url: str,
) -> None:
    """Keep the date and clock on separate rendered rows at every supported width."""
    page, context = _open_page(
        disposable_browser,
        f"{seeded_chatgpt_browser_server_url}/browser?view=text&source=chatgpt&sort=newest&session_view=1",
        1_280,
        900,
        touch=False,
    )
    try:
        session = page.locator(".browser-session-index-table a").first
        expect(session).to_be_visible()
        detail_url = session.get_attribute("href")
        assert detail_url

        for width, height in ((1_280, 900), (715, 899), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(
                f"{seeded_chatgpt_browser_server_url}{detail_url}",
                wait_until="domcontentloaded",
            )
            timestamp = page.locator(
                ".browser-session-detail-table time.browser-session-message-time"
            )
            expect(timestamp).to_have_count(1)
            expect(timestamp).to_be_visible()
            geometry = timestamp.evaluate(
                "element => {"
                "  const style = getComputedStyle(element);"
                "  return {"
                "    display: style.display,"
                "    whiteSpace: style.whiteSpace,"
                "    lines: [...element.children].map(child => {"
                "      const rect = child.getBoundingClientRect();"
                "      return {text: child.textContent.trim(), top: rect.top};"
                "    }),"
                "  };"
                "}"
            )
            assert geometry["display"] == "inline-grid", (width, geometry)
            assert geometry["whiteSpace"] == "normal", (width, geometry)
            assert [line["text"] for line in geometry["lines"]] == [
                "12/08/2026",
                "13:00:00 (HKT)",
            ], (width, geometry)
            assert geometry["lines"][1]["top"] > geometry["lines"][0]["top"], (
                width,
                geometry,
            )
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("route", "target_selector", "title_selector"),
    (
        (
            "/cache/chatgpt",
            ".cache-workspace-content",
            ".cache-overview-title-card > .report-heading-row",
        ),
        (
            "/browser",
            ".browser-content-card",
            ".browser-summary-card > .report-heading-row",
        ),
        (
            "/settings/style-tokens",
            ".style-token-shell",
            ".settings-summary-card > .report-heading-row",
        ),
        (
            "/agent",
            ".agent-workspace-grid",
            ".agent-summary-card > .report-heading-row",
        ),
        (
            "/settings",
            ".settings-category-shell",
            "#settings_workspace .workspace-summary-card > .report-heading-row",
        ),
    ),
)
def test_sidebar_gel_motion_is_content_only_across_product_surfaces(
    disposable_browser: Browser,
    sidebar_server_url: str,
    route: str,
    target_selector: str,
    title_selector: str,
) -> None:
    """Keep shared soft-body motion expressive without animating title geometry."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}{route}",
        1_024,
        900,
        touch=False,
        reduced_motion="no-preference",
    )
    try:
        target = page.locator(target_selector)
        title = page.locator(title_selector)
        expect(target).to_be_visible()
        expect(title).to_be_visible()
        expect(page.locator("#sidebar_toggle")).to_have_attribute("aria-expanded", "true")
        expect(target).to_have_attribute("data-sidebar-gel-content", "")
        page.wait_for_load_state("networkidle")
        page.evaluate("() => document.fonts.ready")

        expanded_baseline = target.evaluate(
            "element => { const rect = element.getBoundingClientRect(); "
            "return {left: rect.left, top: rect.top, width: rect.width}; }"
        )

        def sample_motion() -> dict[str, object]:
            return page.evaluate(
                """async ([targetSelector, titleSelector]) => {
                    const toggle = document.querySelector("#sidebar_toggle");
                    const shell = document.querySelector(".app-shell");
                    const content = document.querySelector(targetSelector);
                    const title = document.querySelector(titleSelector);
                    if (!(toggle instanceof HTMLElement)
                        || !(shell instanceof HTMLElement)
                        || !(content instanceof HTMLElement)
                        || !(title instanceof HTMLElement)) return null;

                    const frames = [];
                    const startedAt = performance.now();
                    toggle.click();
                    await new Promise(resolve => {
                        const sample = () => {
                            const transform = getComputedStyle(content).transform;
                            const matrix = transform === "none"
                                ? new DOMMatrixReadOnly()
                                : new DOMMatrixReadOnly(transform);
                            const contentRect = content.getBoundingClientRect();
                            const titleRect = title.getBoundingClientRect();
                            const toggleRect = toggle.getBoundingClientRect();
                            frames.push({
                                animationNames: content.getAnimations()
                                    .map(animation => animation.animationName || ""),
                                className: shell.className,
                                contentGap: contentRect.top - titleRect.bottom,
                                documentOverflow: Math.max(
                                    document.documentElement.scrollWidth,
                                    document.body.scrollWidth,
                                ) - document.documentElement.clientWidth,
                                offsetWidth: content.offsetWidth,
                                scaleX: matrix.a,
                                scaleY: matrix.d,
                                titleToggleGap: titleRect.left - toggleRect.right,
                                translateX: matrix.e,
                            });
                            if (performance.now() - startedAt >= 760) {
                                resolve();
                                return;
                            }
                            requestAnimationFrame(sample);
                        };
                        requestAnimationFrame(sample);
                    });
                    const finalRect = content.getBoundingClientRect();
                    return {
                        finalAnimationNames: content.getAnimations()
                            .map(animation => animation.animationName || ""),
                        finalClassName: shell.className,
                        finalRect: {
                            left: finalRect.left,
                            top: finalRect.top,
                            width: finalRect.width,
                        },
                        finalTransform: getComputedStyle(content).transform,
                        frames,
                    };
                }""",
                [target_selector, title_selector],
            )

        closing = sample_motion()
        assert closing is not None
        assert any(
            "is-sidebar-closing" in frame["className"]
            for frame in closing["frames"]
        )
        assert any(
            "workspace-sidebar-gel-close" in frame["animationNames"]
            for frame in closing["frames"]
        )
        assert max(abs(frame["translateX"]) for frame in closing["frames"]) > 8
        assert max(abs(frame["scaleX"] - 1) for frame in closing["frames"]) > 0.01
        assert max(abs(frame["scaleY"] - 1) for frame in closing["frames"]) > 0.01
        assert max(frame["documentOverflow"] for frame in closing["frames"]) <= 1
        assert min(frame["contentGap"] for frame in closing["frames"]) >= 0
        assert min(frame["titleToggleGap"] for frame in closing["frames"]) >= 11.5
        assert (
            max(frame["offsetWidth"] for frame in closing["frames"])
            - min(frame["offsetWidth"] for frame in closing["frames"])
        ) <= 1
        assert "is-sidebar-animating" not in closing["finalClassName"]
        assert closing["finalTransform"] == "none"
        assert not any(
            str(name).startswith("workspace-sidebar-gel-")
            for name in closing["finalAnimationNames"]
        )

        opening = sample_motion()
        assert opening is not None
        assert any(
            "workspace-sidebar-gel-open" in frame["animationNames"]
            for frame in opening["frames"]
        )
        assert max(frame["documentOverflow"] for frame in opening["frames"]) <= 1
        assert min(frame["contentGap"] for frame in opening["frames"]) >= 0
        assert min(frame["titleToggleGap"] for frame in opening["frames"]) >= 11.5
        assert "is-sidebar-animating" not in opening["finalClassName"]
        assert opening["finalTransform"] == "none"
        for key in ("left", "top", "width"):
            assert abs(opening["finalRect"][key] - expanded_baseline[key]) <= 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("width", "height", "touch", "reduced_motion"),
    (
        (1_024, 900, False, "reduce"),
        (390, 844, True, "no-preference"),
    ),
)
def test_sidebar_gel_motion_respects_reduced_motion_and_overlay_gates(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
    reduced_motion: str,
) -> None:
    """Prevent even a transient soft-body class outside the desktop motion contract."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/settings/style-tokens",
        width,
        height,
        touch=touch,
        reduced_motion=reduced_motion,
    )
    try:
        state = page.locator("#sidebar_toggle").evaluate(
            """toggle => {
                const shell = document.querySelector(".app-shell");
                const content = document.querySelector(".style-token-shell");
                toggle.click();
                return {
                    animationNames: content?.getAnimations()
                        .map(animation => animation.animationName || "") || [],
                    className: shell?.className || "",
                };
            }"""
        )
        assert "is-sidebar-animating" not in state["className"]
        assert not any(
            str(name).startswith("workspace-sidebar-gel-")
            for name in state["animationNames"]
        )
        assert page.evaluate(
            "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) "
            "- document.documentElement.clientWidth"
        ) <= 1
    finally:
        context.close()


def test_style_tokens_component_catalog_is_interactive_and_responsive(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Exercise the shared component lab at desktop and narrow widths."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/settings/style-tokens",
        1_280,
        720,
        touch=False,
    )
    try:
        cards = page.locator("[data-style-token-card]")
        expect(cards).to_have_count(21)
        assert page.evaluate(
            "document.documentElement.scrollWidth === document.documentElement.clientWidth"
        )
        assert len(
            page.locator("[data-style-token-card]").first.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns.split(' ')"
            )
        ) == 2
        assert page.locator("[data-style-token-agent-browser-menu]").is_hidden()

        resizer = page.locator("[data-style-token-resizer]")
        demo = page.locator(".style-token-demo").first
        resizer_box = resizer.bounding_box()
        initial_demo_width = demo.bounding_box()["width"]
        page.mouse.move(
            resizer_box["x"] + (resizer_box["width"] / 2),
            resizer_box["y"] + (resizer_box["height"] / 2),
        )
        page.mouse.down()
        page.mouse.move(resizer_box["x"] + 40, resizer_box["y"] + (resizer_box["height"] / 2))
        page.mouse.up()
        assert demo.bounding_box()["width"] > initial_demo_width

        refresh_button = page.locator("[data-style-token-secondary-button]")
        refresh_geometry = refresh_button.evaluate(
            "element => ({ width: element.getBoundingClientRect().width, previewWidth: element.parentElement.getBoundingClientRect().width, demoWidth: element.closest('[data-style-token-demo]').getBoundingClientRect().width })"
        )
        assert refresh_geometry["width"] <= refresh_geometry["previewWidth"] + 1
        assert refresh_geometry["previewWidth"] < refresh_geometry["demoWidth"]
        assert refresh_button.get_attribute("data-style-token-secondary-button-use-icon") == "false"

        tag_typography = page.locator("[data-style-token-prompt-tag]").evaluate(
            "element => { const style = getComputedStyle(element); return { fontSize: style.fontSize, fontWeight: style.fontWeight }; }"
        )
        assert tag_typography == {"fontSize": "12px", "fontWeight": "500"}

        sort_label_weight = page.locator(
            '#shared-select-filter [data-style-token-shared-filter-label]'
        ).evaluate("element => getComputedStyle(element).fontWeight")
        assert sort_label_weight == "400"

        agent_trigger = page.locator("[data-style-token-agent-browser-trigger]")
        assert agent_trigger.evaluate(
            "element => element.getBoundingClientRect().height"
        ) == 36
        selected_agent_option_radius = page.locator(
            '[data-style-token-agent-browser-option="edge"]'
        ).evaluate("element => getComputedStyle(element).borderRadius")
        assert selected_agent_option_radius == "999px"

        period_trigger = page.locator(
            "#shared-select-dropdown [data-style-token-shared-filter-trigger]"
        )
        period_trigger.focus()
        period_trigger.press("ArrowDown")
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        expect(page.locator("#shared-select-dropdown select")).to_have_value("max")

        agent_trigger.press("ArrowDown")
        page.keyboard.press("End")
        page.keyboard.press("Enter")
        expect(page.locator("[data-style-token-agent-browser-input]")).to_have_value(
            "chrome"
        )

        prompt_tag = page.locator("[data-style-token-prompt-tag]")
        page.locator("[data-style-token-prompt-tag-remove]").click()
        expect(prompt_tag).to_have_class(re.compile(r"style-token-dismissible-hidden"))
        expect(prompt_tag).not_to_have_class(
            re.compile(r"style-token-dismissible-hidden"),
            timeout=2_000,
        )

        page.locator("[data-style-token-text-input-clear]").click()
        expect(page.locator("[data-style-token-text-input]")).to_have_value("")

        action_package = page.locator("[data-style-token-action-package]")
        action_package_style = action_package.evaluate(
            "element => { const style = getComputedStyle(element); return { borderRadius: style.borderRadius, boxShadow: style.boxShadow, backdropFilter: style.backdropFilter }; }"
        )
        assert action_package_style["borderRadius"] == "10px"
        assert action_package_style["boxShadow"] != "none"
        assert "blur" in action_package_style["backdropFilter"]

        live_control = page.locator("[data-style-token-action-package-live]")
        live_marker = page.locator("[data-action-package-live-marker]")
        expect(live_marker).to_be_hidden()
        live_control.check()
        expect(live_marker).to_be_visible()
        live_control.uncheck()
        expect(live_marker).to_be_hidden()

        execution_option = page.locator(
            "#settings-execution-option .settings-general-option"
        )
        execution_option_style = execution_option.evaluate(
            "element => { const style = getComputedStyle(element); return { display: style.display, gridTemplateColumns: style.gridTemplateColumns, gap: style.gap, padding: style.padding, borderRadius: style.borderRadius, transition: style.transition }; }"
        )
        assert execution_option_style["display"] == "grid"
        grid_columns = execution_option_style["gridTemplateColumns"].split()
        assert len(grid_columns) == 2
        assert all(column.endswith("px") for column in grid_columns)
        assert float(grid_columns[0][:-2]) < float(grid_columns[1][:-2])
        assert execution_option_style["gap"] == "12px"
        assert execution_option_style["padding"] == "14px 16px"
        assert execution_option_style["borderRadius"] == "10px"
        assert "background-color" in execution_option_style["transition"]
        assert page.locator(
            "#settings-execution-option .settings-general-option-title"
        ).inner_text() == "Update existing cache entries"
        assert page.locator(
            "#settings-execution-option .settings-general-option-desc"
        ).inner_text() == (
            "When enabled, refresh existing metadata as well as newly discovered items."
        )
        assert page.locator("#global-theme-toggle [data-style-token-theme-toggle-label]").count() == 0
        assert page.locator("#pagination .style-token-component-kicker").count() == 0
        assert page.locator("#scrollable-data-table .style-token-component-kicker").count() == 0
        assert page.locator("#settings-execution-option legend").count() == 0
        assert page.locator("#tooltip .chart-tooltip-title").evaluate(
            "element => getComputedStyle(element).fontWeight"
        ) == "500"

        action_button = page.locator("[data-style-token-action-button]")
        action_button.click()
        expect(action_button).to_be_disabled()
        expect(action_button).to_be_enabled(timeout=2_000)

        table_filter = page.locator("[data-style-token-table-filter-trigger]")
        table_filter.click()
        page.locator('[data-style-token-table-filter-option="buy"]').click()
        expect(page.locator("[data-style-token-table-filter-summary]")).to_have_text(
            "5 filtered of 12 total"
        )
        expect(page.locator("[data-style-token-table-pagination]")).to_be_hidden()

        token_control = page.locator(
            '[data-style-token-name="--settings-round-icon-button-size"]'
        ).first
        expect(token_control).to_have_attribute("data-style-token-value", "36")
        token_control.locator('[data-style-token-stepper="up"]').click()
        expect(token_control).to_have_attribute("data-style-token-value", "37")
        assert page.locator("[data-style-token-shell]").evaluate(
            "element => element.style.getPropertyValue('--settings-round-icon-button-size')"
        ) == "37px"
    finally:
        context.close()

    narrow_page, narrow_context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/settings/style-tokens",
        390,
        844,
        touch=True,
    )
    try:
        assert narrow_page.evaluate(
            "document.documentElement.scrollWidth === document.documentElement.clientWidth"
        )
        assert narrow_page.locator("[data-style-token-card]").first.evaluate(
            "element => getComputedStyle(element).gridTemplateColumns.split(' ').length"
        ) == 1
        expect(narrow_page.locator("[data-style-token-resizer]")).to_be_hidden()
        title_left = narrow_page.locator(
            ".settings-summary-card .report-heading"
        ).bounding_box()["x"]
        toggle_box = narrow_page.locator("#sidebar_toggle").bounding_box()
        assert title_left >= toggle_box["x"] + toggle_box["width"]
    finally:
        narrow_context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_shared_segmented_controls_shrink_wrap_and_center(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep every Cache reuse of the shared blue pill compact and centered."""
    cases = (
        (
            "/settings/style-tokens",
            "#segmented-control .range-mode-shell",
            ".style-token-demo",
        ),
        (
            "/browser?view=text&session_view=1&q=&source=chatgpt&sort=newest",
            ".browser-content-mode-control",
            "#browser_filter_form",
        ),
        (
            "/cache/chatgpt",
            "[data-cache-content-mode]",
            ".cache-page-content-mode-section",
        ),
    )
    for width, height, touch in ((1_280, 900, False), (390, 844, True)):
        page, context = _open_page(
            disposable_browser,
            f"{sidebar_server_url}{cases[0][0]}",
            width,
            height,
            touch=touch,
        )
        try:
            for route, control_selector, owner_selector in cases:
                page.goto(f"{sidebar_server_url}{route}", wait_until="domcontentloaded")
                geometry = page.evaluate(
                    """({controlSelector, ownerSelector}) => {
                        const control = document.querySelector(controlSelector);
                        const owner = control?.closest(ownerSelector);
                        if (!(control instanceof HTMLElement) || !(owner instanceof HTMLElement)) {
                            return null;
                        }
                        const controlRect = control.getBoundingClientRect();
                        const ownerRect = owner.getBoundingClientRect();
                        const optionWidths = Array.from(
                            control.querySelectorAll('.segmented-control-option, .range-mode-option'),
                        ).map(option => option.getBoundingClientRect().width);
                        return {
                            centerDelta: Math.abs(
                                (controlRect.left + (controlRect.width / 2))
                                - (ownerRect.left + (ownerRect.width / 2)),
                            ),
                            compact: controlRect.width < ownerRect.width - 1,
                            horizontalOverflow: document.documentElement.scrollWidth
                                - document.documentElement.clientWidth,
                            optionWidths,
                        };
                    }""",
                    {"controlSelector": control_selector, "ownerSelector": owner_selector},
                )
                assert geometry is not None, (width, route)
                assert geometry["compact"], (width, route, geometry)
                assert geometry["centerDelta"] <= 1, (width, route, geometry)
                assert len(geometry["optionWidths"]) > 1, (width, route, geometry)
                assert (
                    max(geometry["optionWidths"]) - min(geometry["optionWidths"])
                ) <= 1, (width, route, geometry)
                assert geometry["horizontalOverflow"] <= 1, (width, route, geometry)
        finally:
            context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("page_source", ("chatgpt", "claude", "gemini", "grok", "x"))
def test_cache_source_switcher_click_matrix_stays_within_expected_destinations(
    disposable_browser: Browser,
    sidebar_server_url: str,
    page_source: str,
) -> None:
    """Verify every source option lands on its intentional local destination."""
    expected_paths = {
        "chatgpt": {
            "chatgpt": "/cache/chatgpt",
            "claude": "/cache/claude",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
        "gemini": {
            "chatgpt": "/cache/chatgpt",
            "claude": "/cache/claude",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
        "grok": {
            "chatgpt": "/cache/chatgpt",
            "claude": "/cache/claude",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
        "x": {
            "chatgpt": "/cache/chatgpt",
            "claude": "/cache/claude",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
        "claude": {
            "chatgpt": "/cache/chatgpt",
            "claude": "/cache/claude",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
    }[page_source]
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/{page_source}",
        1_280,
        900,
        touch=False,
    )
    try:
        for target_source, expected_path in expected_paths.items():
            page.goto(f"{sidebar_server_url}/cache/{page_source}", wait_until="domcontentloaded")
            if page_source != "x":
                page.locator('[data-cache-content-mode-option="text"]').click()
                page.goto(f"{sidebar_server_url}/cache/{page_source}", wait_until="domcontentloaded")
                expect(page.locator('[data-cache-content-mode-option="text"]')).to_have_attribute(
                    "aria-checked",
                    "true",
                )
            if target_source == "x" and page_source != "x":
                page.locator('[data-cache-content-mode-option="media"]').click()
                assert page.locator('[data-cache-source-switcher-option="x"]').evaluate(
                    "element => !element.hidden"
                )
            page.locator("[data-cache-source-switcher-trigger]").click()
            page.locator(
                f'[data-cache-source-switcher-option="{target_source}"]'
            ).click()
            expect(page).to_have_url(re.compile(rf"{re.escape(expected_path)}$"))
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("page_source", ("chatgpt", "claude", "gemini", "grok", "x"))
def test_cache_dock_click_preserves_the_current_cache_source(
    disposable_browser: Browser,
    sidebar_server_url: str,
    page_source: str,
) -> None:
    """Verify the second Dock item never falls back to another Cache source."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/{page_source}",
        1_280,
        900,
        touch=False,
    )
    try:
        page.get_by_role("link", name="Cache", exact=True).click()
        expect(page).to_have_url(re.compile(rf"/cache/{page_source}$"))
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
        for page_source in ("chatgpt", "claude", "gemini", "grok"):
            if page_source != "chatgpt":
                page.goto(f"{sidebar_server_url}/cache/{page_source}", wait_until="domcontentloaded")

            aside = page.locator("xpath=/html/body/main/div/aside")
            expect(aside).to_have_count(1)
            expect(aside.locator(":scope > .hero")).to_have_count(1)
            expect(aside.locator(":scope > .cache-page-content-mode-section")).to_have_count(1)
            expect(aside.locator("[data-cache-source-switcher]")).to_have_count(1)
            expect(aside.locator("[data-cache-source-switcher-option]")).to_have_count(5)
            expect(aside.locator("[data-browser-session-panel]")).to_have_count(1)
            expect(aside.locator(".browser-session-panel-label")).to_have_text("Authorized browser")
            expect(aside.locator(".cache-settings-link")).to_have_count(1)
            expect(aside.locator("[data-cache-action-row]")).to_have_count(1)
            expect(aside.locator("#start_button")).to_have_count(1)
            expect(aside.locator("#stop_button")).to_have_count(1)
            if page_source == "gemini":
                for field_name in (
                    "gemini_max_conversations",
                    "gemini_scroll_pause_seconds",
                    "gemini_stale_round_limit",
                ):
                    expect(aside.locator(f"#{field_name}")).to_have_count(0)
                expect(aside.locator("#start_form_gemini input")).to_have_count(1)
                expect(aside.locator(".cache-settings-link")).to_have_attribute(
                    "href",
                    "/settings#settings-llm",
                )
            if page_source == "grok":
                expect(aside.locator(".cache-secondary-action")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("width", "height", "touch"),
    ((1_280, 900, False), (390, 844, True)),
)
def test_agent_response_pagination_is_immersed_but_keeps_interactive_effects(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    """Verify the Agent pagination is surface-free without clipping its interactions."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent",
        width,
        height,
        touch=touch,
        init_script="""
            (() => {
                const originalFetch = window.fetch.bind(window);
                window.fetch = (input, init) => {
                    const requestUrl = typeof input === "string" ? input : input?.url;
                    if (requestUrl) {
                        const pathname = new URL(requestUrl, window.location.href).pathname;
                        if (pathname === "/api/agent/status" || pathname === "/api/browser-session") {
                            return Promise.reject(new Error("Live status polling is disabled for this layout test."));
                        }
                    }
                    return originalFetch(input, init);
                };
            })();
        """,
    )
    try:
        contract = page.evaluate(
            """() => {
                const pagination = document.querySelector("#agent_response_pagination");
                const output = document.querySelector("#agent_response_output");
                const answer = document.querySelector("#agent_response_answer");
                const card = output?.closest(".agent-response-card");
                const task = card?.closest(".agent-task-card");
                const composer = task?.querySelector(".agent-prompt-form");
                const answerContent = answer?.querySelector("[data-agent-response-answer-content]");
                if (!pagination || !output || !answer || !card || !task || !composer || !answerContent) return null;

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

                const readPosition = () => {
                    const paginationRect = pagination.getBoundingClientRect();
                    const composerRect = composer.getBoundingClientRect();
                    return {
                        paginationBottom: paginationRect.bottom,
                        composerTop: composerRect.top,
                        composerGap: composerRect.top - paginationRect.bottom,
                    };
                };
                answerContent.textContent = "Short answer";
                const shortPosition = readPosition();
                answerContent.textContent = Array.from(
                    {length: 160},
                    (_, index) => `Response line ${index + 1}`,
                ).join(" ");
                answer.scrollTop = answer.scrollHeight;
                const longPosition = readPosition();

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
                    ancestors: [task, pagination].map(read),
                    responseOutput: read(output),
                    answer: read(answer),
                    paginationParentIsTask: pagination.parentElement === task,
                    paginationWidth: pagination.getBoundingClientRect().width,
                    shortPosition,
                    longPosition,
                    indicatorVisible: window.getComputedStyle(indicator).opacity === "1",
                    paginationSurface: {
                        background: window.getComputedStyle(pagination).background,
                        borderWidth: window.getComputedStyle(pagination).borderWidth,
                        boxShadow: window.getComputedStyle(pagination).boxShadow,
                        padding: window.getComputedStyle(pagination).padding,
                    },
                };
            }""",
        )
        assert contract is not None
        assert contract["paginationWidth"] > 0
        assert contract["indicatorVisible"]
        assert contract["paginationSurface"]["background"].startswith("rgba(0, 0, 0, 0)")
        assert contract["paginationSurface"]["borderWidth"] == "0px"
        assert contract["paginationSurface"]["boxShadow"] == "none"
        assert contract["paginationSurface"]["padding"] == "0px"
        assert all(item["overflow"] == "visible" for item in contract["ancestors"])
        assert contract["ancestors"][-1]["position"] == "relative"
        assert contract["ancestors"][-1]["zIndex"] == "2"
        assert contract["responseOutput"]["overflow"] == "visible"
        assert contract["answer"]["overflowX"] == "hidden"
        assert contract["answer"]["overflowY"] == "auto"
        assert contract["paginationParentIsTask"]
        assert contract["shortPosition"]["composerGap"] >= 13
        assert contract["shortPosition"]["composerGap"] <= 15
        assert abs(
            contract["shortPosition"]["composerGap"]
            - contract["longPosition"]["composerGap"]
        ) <= 1
        assert contract["longPosition"]["paginationBottom"] <= contract["longPosition"]["composerTop"]

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
@pytest.mark.parametrize(
    ("width", "height", "touch"),
    ((1_280, 900, False), (390, 844, True)),
)
def test_agent_doctor_actions_keep_spatial_effects_visible(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    """Verify Doctor action shadows escape the panel at desktop and narrow widths."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent/edge/chatgpt",
        width,
        height,
        touch=touch,
        init_script="""
            (() => {
                const originalFetch = window.fetch.bind(window);
                window.fetch = (input, init) => {
                    const requestUrl = typeof input === "string" ? input : input?.url;
                    if (requestUrl) {
                        const pathname = new URL(requestUrl, window.location.href).pathname;
                        if (
                            pathname === "/api/agent/status"
                            || pathname === "/api/browser-session"
                            || pathname === "/api/agent/doctor"
                        ) {
                            return Promise.reject(new Error("Live Agent polling is disabled for this layout test."));
                        }
                    }
                    return originalFetch(input, init);
                };
            })();
        """,
    )
    try:
        contract = page.evaluate(
            """() => {
                const panel = document.querySelector("#agent_doctor_panel");
                const content = document.querySelector("#agent_doctor_panel .agent-doctor-content");
                const actions = document.querySelector("#agent_doctor_actions");
                if (!panel || !content || !actions) return null;

                panel.hidden = false;
                panel.open = true;
                actions.replaceChildren();
                for (const label of [
                    "Continue interrupted task",
                    "Clean up temporary context",
                    "Open provider conversation",
                    "Start a new task",
                ]) {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "secondary-button agent-doctor-action";
                    button.textContent = label;
                    actions.append(button);
                }

                const read = element => {
                    const style = getComputedStyle(element);
                    const rect = element.getBoundingClientRect();
                    return {
                        className: String(element.className || ""),
                        overflow: style.overflow,
                        overflowX: style.overflowX,
                        overflowY: style.overflowY,
                        boxShadow: style.boxShadow,
                        widthCss: style.width,
                        rect: {
                            left: rect.left,
                            top: rect.top,
                            right: rect.right,
                            bottom: rect.bottom,
                            width: rect.width,
                            height: rect.height,
                        },
                    };
                };
                const ancestors = [];
                for (let node = actions; node && node !== document.body; node = node.parentElement) {
                    ancestors.push(read(node));
                }
                const settingsLink = document.querySelector("[data-agent-llm-settings-link]");
                const settingsForm = settingsLink?.closest("form") || null;
                return {
                    panel: read(panel),
                    content: read(content),
                    actions: read(actions),
                    buttons: [...actions.children].map(read),
                    settingsLink: settingsLink ? read(settingsLink) : null,
                    settingsForm: settingsForm ? read(settingsForm) : null,
                    ancestors,
                    documentOverflow: document.documentElement.scrollWidth
                        - document.documentElement.clientWidth,
                };
            }"""
        )
        assert contract is not None
        assert contract["panel"]["overflow"] == "visible"
        assert contract["content"]["overflow"] == "visible"
        assert contract["actions"]["overflow"] == "visible"
        assert len(contract["buttons"]) == 4
        assert all(button["rect"]["width"] > 0 for button in contract["buttons"])
        assert all(button["boxShadow"] != "none" for button in contract["buttons"])
        button_widths = [button["rect"]["width"] for button in contract["buttons"]]
        assert max(button_widths) - min(button_widths) > 8
        assert all(
            button["rect"]["width"] < contract["actions"]["rect"]["width"] - 8
            for button in contract["buttons"]
        )
        assert contract["settingsLink"] is not None
        assert contract["settingsForm"] is not None
        assert "secondary-button" in contract["settingsLink"]["className"]
        assert all("secondary-button" in button["className"] for button in contract["buttons"])
        assert (
            contract["settingsLink"]["rect"]["width"]
            < contract["settingsForm"]["rect"]["width"] - 8
        )
        assert all(
            ancestor["overflowX"] == "visible" and ancestor["overflowY"] == "visible"
            for ancestor in contract["ancestors"][:4]
        ), contract["ancestors"]
        assert contract["documentOverflow"] <= 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_prompt_composer_stays_compact_until_expanded(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep a long Agent task readable without opening the Composer by default."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/agent",
        1_280,
        900,
        touch=False,
        init_script="""
            (() => {
                const originalFetch = window.fetch.bind(window);
                window.fetch = (input, init) => {
                    const requestUrl = typeof input === "string" ? input : input?.url;
                    if (requestUrl && new URL(requestUrl, window.location.href).pathname === "/api/agent/status") {
                        return Promise.reject(new Error("Agent status polling is disabled for this layout test."));
                    }
                    return originalFetch(input, init);
                };
            })();
        """,
    )
    try:
        prompt = page.locator("#agent_prompt_input")
        toggle = page.locator("[data-agent-composer-overflow-toggle]")
        expect(prompt).to_have_attribute("rows", "2")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(toggle).to_have_attribute("aria-label", "Expand question or task")
        expect(toggle).to_be_hidden()
        compact = prompt.evaluate(
            "element => ({height: element.clientHeight, weight: getComputedStyle(element).fontWeight, resize: getComputedStyle(element).resize})"
        )
        assert compact["height"] > 0
        assert compact["weight"] == "400"
        assert compact["resize"] == "none"
        control_heights = page.evaluate(
            """() => ({
                model: document.querySelector('.agent-model-trigger')?.getBoundingClientRect().height,
                effort: document.querySelector('.agent-effort-trigger')?.getBoundingClientRect().height,
            })"""
        )
        assert control_heights == {"model": 32, "effort": 32}

        effort_label = page.locator(".agent-effort-trigger-label")
        expect(effort_label).to_have_count(1)
        assert effort_label.evaluate("element => getComputedStyle(element).fontSize") == "15px"

        effort = page.locator(".agent-effort-trigger")
        effort_menu = page.locator(".agent-effort-dropdown")
        effort.click()
        expect(effort_menu).to_be_visible()
        effort_dropdown_geometry = page.evaluate(
            """() => {
                const trigger = document.querySelector('.agent-effort-trigger').getBoundingClientRect();
                const menu = document.querySelector('.agent-effort-dropdown').getBoundingClientRect();
                const style = getComputedStyle(document.querySelector('.agent-effort-dropdown'));
                return {
                    menuBottom: menu.bottom,
                    triggerTop: trigger.top,
                    position: style.position,
                };
            }"""
        )
        assert effort_dropdown_geometry["position"] == "absolute"
        assert effort_dropdown_geometry["menuBottom"] <= effort_dropdown_geometry["triggerTop"]
        effort.click()
        expect(effort_menu).to_be_hidden()

        prompt.fill("Short task.")
        expect(toggle).to_be_hidden()

        prompt.fill("\n".join(f"Task line {line}" for line in range(1, 9)))
        collapsed = prompt.evaluate(
            "element => ({height: element.clientHeight, scrollHeight: element.scrollHeight})"
        )
        assert collapsed["height"] == compact["height"]
        assert collapsed["scrollHeight"] > collapsed["height"]
        expect(toggle).to_be_visible()
        toggle_geometry = toggle.evaluate(
            """element => {
                const shell = element.closest('.agent-composer-shell').getBoundingClientRect();
                const rect = element.getBoundingClientRect();
                const style = getComputedStyle(element);
                return {
                    position: style.position,
                    top: style.top,
                    right: style.right,
                    topOffset: rect.top - shell.top,
                    rightOffset: shell.right - rect.right,
                };
            }"""
        )
        assert toggle_geometry["position"] == "absolute"
        assert toggle_geometry["top"] == "12px"
        assert toggle_geometry["right"] == "12px"
        assert toggle_geometry["topOffset"] == 13
        assert toggle_geometry["rightOffset"] == 13

        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(toggle).to_have_attribute("aria-label", "Collapse question or task")
        expanded = prompt.evaluate("element => ({height: element.clientHeight, scrollHeight: element.scrollHeight})")
        assert expanded["height"] > collapsed["height"]
        assert expanded["height"] >= min(expanded["scrollHeight"], 360)

        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        final_height = prompt.evaluate("element => element.clientHeight")
        assert final_height == compact["height"]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("width", "height", "touch"),
    ((1_008, 1_085, False), (390, 844, True), (320, 844, True)),
)
def test_chatgpt_effort_footer_keeps_the_fifteen_pixel_label_on_one_line(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    """Keep the ChatGPT effort controls compact, styled, and readable."""
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }
    context = disposable_browser.new_context(
        viewport={"width": width, "height": height},
        has_touch=touch,
        is_mobile=touch,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route(
        "**/api/agent/status",
        lambda route: route.fulfill(json=_finished_chatgpt_agent_payload()),
    )
    page.route(
        "**/api/browser-session**",
        lambda route: route.fulfill(json=browser_status),
    )
    page.route(
        "**/api/agent/sources**",
        lambda route: route.fulfill(json=catalog_payload),
    )
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        effort = page.locator(".agent-effort-trigger")
        model = page.locator(".agent-model-trigger")
        refresh = page.locator("[data-agent-effort-refresh]")
        submit = page.locator("#agent_ask_button")
        expect(effort).to_be_visible()
        expect(model).to_be_visible()
        expect(refresh).to_be_visible()
        expect(submit).to_be_visible()
        assert model.locator(".agent-model-trigger-label").text_content().strip() == "GPT-5.6 Sol"
        refresh_style = refresh.evaluate(
            """element => {
                const style = getComputedStyle(element);
                const icon = element.querySelector('.agent-effort-refresh-icon');
                const iconStyle = icon && getComputedStyle(icon);
                return {
                    background: style.backgroundColor,
                    color: style.color,
                    padding: style.padding,
                    maskImage: iconStyle?.maskImage,
                };
            }"""
        )
        assert refresh_style["background"] == "rgba(255, 255, 255, 0.82)"
        assert refresh_style["color"] == "rgb(0, 85, 204)"
        assert refresh_style["padding"] == "8px 12px"
        assert "arrow.trianglehead.2.clockwise.svg" in refresh_style["maskImage"]
        geometry = page.evaluate(
            """() => {
                const rect = selector => {
                    const element = document.querySelector(selector);
                    const value = element?.getBoundingClientRect();
                    return value && {
                        left: value.left,
                        right: value.right,
                        top: value.top,
                        bottom: value.bottom,
                        width: value.width,
                        height: value.height,
                    };
                };
                const label = document.querySelector('.agent-effort-trigger-label');
                const labelRect = label?.getBoundingClientRect();
                const labelStyle = label && getComputedStyle(label);
                const protectedZone = selector => {
                    const trigger = document.querySelector(selector);
                    const triggerRect = trigger?.getBoundingClientRect();
                    const labelRect = trigger?.querySelector('.trade-strategy-trigger-label')?.getBoundingClientRect();
                    const chevronRect = trigger?.querySelector('.browser-picker-trigger-chevron')?.getBoundingClientRect();
                    return {
                        labelRight: labelRect?.right,
                        chevronLeft: chevronRect?.left,
                        chevronRight: chevronRect?.right,
                        triggerRight: triggerRect?.right,
                    };
                };
                return {
                    footer: rect('.agent-composer-footer'),
                    effort: rect('.agent-effort-trigger'),
                    model: rect('.agent-model-trigger'),
                    refresh: rect('[data-agent-effort-refresh]'),
                    effortProtectedZone: protectedZone('.agent-effort-trigger'),
                    modelProtectedZone: protectedZone('.agent-model-trigger'),
                    submit: rect('#agent_ask_button'),
                    labelFontSize: labelStyle?.fontSize,
                    labelLineHeight: labelStyle?.lineHeight,
                    labelWhiteSpace: labelStyle?.whiteSpace,
                    labelHeight: labelRect?.height,
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) - document.documentElement.clientWidth,
                };
            }"""
        )
        assert geometry["labelFontSize"] == "15px"
        assert geometry["labelWhiteSpace"] == "nowrap"
        assert geometry["labelHeight"] <= float(geometry["labelLineHeight"][:-2]) + 1
        assert geometry["effort"]["height"] == 32
        assert geometry["model"]["height"] == 32
        assert geometry["model"]["width"] < 190
        assert geometry["submit"]["height"] == 32
        assert geometry["horizontalOverflow"] <= 1
        if width > 560:
            control_left = min(
                geometry[selector]["left"]
                for selector in ("model", "effort", "refresh", "submit")
            )
            control_right = max(
                geometry[selector]["right"]
                for selector in ("model", "effort", "refresh", "submit")
            )
            assert abs(
                (control_left + control_right) / 2
                - (geometry["footer"]["left"] + geometry["footer"]["right"]) / 2
            ) <= 1
            for selector in ("model", "effort", "refresh", "submit"):
                assert abs(
                    geometry[selector]["top"] - geometry["footer"]["top"]
                ) <= 1
        for protected_zone in (
            geometry["effortProtectedZone"],
            geometry["modelProtectedZone"],
        ):
            assert protected_zone["chevronLeft"] - protected_zone["labelRight"] >= 8
            assert protected_zone["triggerRight"] - protected_zone["chevronRight"] >= 8
        effort.click()
        effort_menu = page.locator(".agent-effort-dropdown")
        expect(effort_menu).to_be_visible()
        menu_geometry = page.evaluate(
            """() => {
                const menu = document.querySelector('.agent-effort-dropdown')?.getBoundingClientRect();
                const trigger = document.querySelector('.agent-effort-trigger')?.getBoundingClientRect();
                const options = [...document.querySelectorAll('.agent-effort-dropdown .trade-strategy-dropdown-text')].map(text => ({
                    label: text.textContent.trim(),
                    clientWidth: text.clientWidth,
                    scrollWidth: text.scrollWidth,
                }));
                return {
                    menuLeft: menu?.left,
                    menuBottom: menu?.bottom,
                    menuRight: menu?.right,
                    menuWidth: menu?.width,
                    triggerTop: trigger?.top,
                    options,
                };
            }"""
        )
        assert menu_geometry["menuBottom"] <= geometry["effort"]["top"] + 1
        assert menu_geometry["menuLeft"] >= -1
        assert menu_geometry["menuRight"] <= width + 1
        assert menu_geometry["menuWidth"] > geometry["effort"]["width"] + 1
        assert all(option["scrollWidth"] <= option["clientWidth"] + 1 for option in menu_geometry["options"])
        effort.click()
        expect(effort_menu).to_be_hidden()
        if width <= 560:
            assert geometry["model"]["bottom"] <= geometry["effort"]["top"]
            assert geometry["effort"]["right"] <= geometry["submit"]["left"]
            non_chatgpt = page.evaluate(
                """() => {
                    const effortField = document.querySelector('[data-agent-effort-field]');
                    const footer = document.querySelector('.agent-composer-footer');
                    const model = document.querySelector('.agent-model-trigger');
                    const submit = document.querySelector('#agent_ask_button');
                    if (!(effortField instanceof HTMLElement)) return null;
                    effortField.hidden = true;
                    return {
                        footerDisplay: getComputedStyle(footer).display,
                        modelTop: model.getBoundingClientRect().top,
                        submitTop: submit.getBoundingClientRect().top,
                    };
                }"""
            )
            assert non_chatgpt is not None
            assert non_chatgpt["footerDisplay"] == "flex"
            assert abs(non_chatgpt["modelTop"] - non_chatgpt["submitTop"]) <= 1
        else:
            assert abs(geometry["model"]["top"] - geometry["effort"]["top"]) <= 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_model_and_sidebar_service_triggers_follow_typography_contract(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify shared label metrics while keeping the Current project name readable."""
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

        platform_button = page.locator(
            ".agent-platform-combobox [data-agent-combobox-trigger]"
        )
        session_source_button = page.locator(
            ".agent-session-mode-combobox [data-agent-combobox-trigger]"
        )
        expect(platform_button).to_have_count(1)
        expect(session_source_button).to_have_count(1)
        assert platform_button.evaluate("element => element.getBoundingClientRect().height") == 36
        assert session_source_button.evaluate("element => element.getBoundingClientRect().height") == 36

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
        main_typography, sidebar_typography = typography
        assert main_typography is not None
        assert sidebar_typography is not None
        assert main_typography["fontFamily"] == sidebar_typography["fontFamily"]
        assert main_typography["fontSize"] == "15px"
        assert main_typography["lineHeight"] == "21.75px"
        assert sidebar_typography["fontSize"] == "13px"
        assert sidebar_typography["lineHeight"] == "18.85px"
        assert main_typography["fontWeight"] == "400"
        assert sidebar_typography["fontWeight"] == "400"
        project_name = page.locator("[data-agent-project-name]")
        expect(project_name).to_be_visible()
        assert project_name.evaluate("element => getComputedStyle(element).fontSize") == "17px"
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
def test_cache_browser_session_failure_message_matches_account_typography_and_hangs_after_status_icon(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep Cache failure copy the same size as its label with a status-icon hanging indent."""
    browser_status = {
        "can_download": False,
        "account_name": "Security verification required",
        "message": (
            "Grok showed a Cloudflare security verification page in Edge, so the "
            "signed-in account could not be verified."
        ),
    }
    context = disposable_browser.new_context(
        viewport={"width": 1_017, "height": 1_354},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/cache/grok", wait_until="domcontentloaded")
        account = page.locator(".browser-session-status-account")
        message = page.locator(
            '.browser-session-status-message[data-role="browser-session-message"]'
        )
        status_icon = page.locator(
            '.browser-session-status-item .browser-session-status-checkmark[data-status-state="error"]'
        )
        expect(account).to_have_count(1)
        expect(message).to_be_visible()
        expect(status_icon).to_be_visible()

        layout = page.evaluate(
            """() => {
                const account = document.querySelector('.browser-session-status-account');
                const message = document.querySelector('.browser-session-status-message[data-role="browser-session-message"]');
                const icon = document.querySelector('.browser-session-status-item .browser-session-status-checkmark[data-status-state="error"]');
                const item = document.querySelector('.browser-session-status-item');
                const card = document.querySelector('.browser-session-status-card');
                const readTypography = (element) => {
                    const style = getComputedStyle(element);
                    return {
                        fontFamily: style.fontFamily,
                        fontSize: style.fontSize,
                        fontWeight: style.fontWeight,
                        lineHeight: style.lineHeight,
                        textAlign: style.textAlign,
                    };
                };
                const messageStyle = getComputedStyle(message);
                const itemStyle = getComputedStyle(item);
                return {
                    accountTypography: readTypography(account),
                    messageTypography: readTypography(message),
                    messageMarginTop: messageStyle.marginTop,
                    messagePaddingInlineStart: messageStyle.paddingInlineStart,
                    messageTextIndent: messageStyle.textIndent,
                    iconRight: icon.getBoundingClientRect().right,
                    accountLeft: account.getBoundingClientRect().left,
                    itemGap: parseFloat(itemStyle.columnGap || itemStyle.gap),
                    messageRight: message.getBoundingClientRect().right,
                    cardRight: card.getBoundingClientRect().right,
                };
            }"""
        )
        assert layout["accountTypography"] == layout["messageTypography"]
        assert layout["messageMarginTop"] == "0px"
        assert layout["messagePaddingInlineStart"] == "26px"
        assert layout["messageTextIndent"] == "-26px"
        assert abs(layout["accountLeft"] - (layout["iconRight"] + layout["itemGap"])) <= 1
        assert layout["messageRight"] <= layout["cardRight"] + 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("source_key", "settings_category"),
    (("x", "downloads"), ("gemini", "llm")),
)
def test_cache_shared_settings_link_opens_the_expected_category(
    disposable_browser: Browser,
    sidebar_server_url: str,
    source_key: str,
    settings_category: str,
) -> None:
    """Verify each Cache settings link leaves the source form and opens its category."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/cache/{source_key}",
        1_280,
        900,
        touch=False,
    )
    try:
        settings_link = page.locator(".cache-settings-link")
        expect(settings_link).to_have_count(1)
        expect(settings_link).to_have_class(re.compile(r"\bsecondary-button\b"))
        expect(settings_link).to_have_attribute(
            "href",
            f"/settings#settings-{settings_category}",
        )
        expect(page.locator("#start_form section")).to_have_count(0)
        assert settings_link.evaluate("element => !element.closest('form')")
        if source_key == "gemini":
            for field_name in (
                "gemini_max_conversations",
                "gemini_scroll_pause_seconds",
                "gemini_stale_round_limit",
            ):
                expect(page.locator(f"#{field_name}")).to_have_count(0)

        settings_link.click()
        page.wait_for_url(re.compile(rf"/settings#settings-{settings_category}$"))

        expect(page.locator("[data-settings-category-shell]")).to_have_attribute(
            "data-active-category",
            settings_category,
        )
        expect(page.locator(f"#settings-{settings_category}")).to_be_visible()
        expect(page.locator(f'[data-settings-category="{settings_category}"]')).to_have_class(
            re.compile(r"\bis-active\b")
        )
        if source_key == "gemini":
            for field_name in (
                "gemini_max_conversations",
                "gemini_scroll_pause_seconds",
                "gemini_stale_round_limit",
            ):
                expect(page.locator(f"#{field_name}")).to_be_visible()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("width", "height", "touch"),
    (
        (1_034, 1_170, False),
        (390, 844, True),
    ),
)
def test_settings_reuse_shared_primary_and_numeric_control_contracts(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    """Verify Settings controls share the annotated visual and layout contracts."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/settings#settings-llm",
        width,
        height,
        touch=touch,
    )
    try:
        expect(page.locator("#settings")).to_have_count(0)
        expect(page.locator("#settings_workspace .workspace-kicker")).to_have_count(0)
        expect(page.locator("#settings_workspace .workspace-summary-card h2")).to_have_text(
            "Configuration center"
        )
        expect(page.locator("#settings_sidebar .hero h1")).to_have_text("Settings")
        expect(page.locator("#chatgpt_startup_timeout_seconds")).to_have_count(1)
        for field_name in (
            "gemini_max_conversations",
            "gemini_scroll_pause_seconds",
            "gemini_stale_round_limit",
        ):
            expect(page.locator(f"#{field_name}")).to_be_visible()
        assert page.locator("#chatgpt_startup_timeout_seconds").evaluate(
            "element => getComputedStyle(element).fontWeight"
        ) == "300"

        terminal_button = page.locator("[data-agent-terminal-authorization-button]")
        expect(terminal_button).to_have_count(1)
        assert terminal_button.evaluate(
            "element => getComputedStyle(element).fontWeight"
        ) == "500"

        page.goto(
            f"{sidebar_server_url}/settings#settings-cloud",
            wait_until="domcontentloaded",
        )
        expect(page.locator("#settings-cloud")).to_be_visible()
        expect(page.locator("#settings_workspace .workspace-kicker")).to_have_count(0)
        expect(page.locator("#shadow_backup_phase")).to_have_count(0)
        expect(page.locator("[data-shadow-backup-status-copy]")).to_have_count(1)
        sync_button = page.locator("#shadow_backup_sync_now")
        expect(sync_button).to_have_count(1)
        assert sync_button.evaluate(
            "element => getComputedStyle(element).fontWeight"
        ) == "500"

        page.goto(
            f"{sidebar_server_url}/settings#settings-maintenance",
            wait_until="domcontentloaded",
        )
        expect(page.locator("#settings-maintenance")).to_be_visible()
        expect(page.locator("#settings_workspace .workspace-kicker")).to_have_count(0)
        for selector in ("#reset_button", "#reset_chatgpt_button"):
            alignment = page.locator(selector).evaluate(
                """button => {
                    const form = button.closest("form");
                    return {
                        buttonRight: button.getBoundingClientRect().right,
                        formRight: form.getBoundingClientRect().right,
                    };
                }"""
            )
            assert abs(alignment["buttonRight"] - alignment["formRight"]) <= 1

        assert page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth"
        )
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("width", "height", "touch"),
    (
        (1_280, 900, False),
        (390, 844, True),
    ),
)
def test_settings_reuse_shared_content_control_and_effect_boundaries(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    """Verify the 640px/384px maxima and keep physical cards unclipped."""
    page, context = _open_page(
        disposable_browser,
        f"{sidebar_server_url}/settings#settings-agent",
        width,
        height,
        touch=touch,
    )
    try:
        expect(page.locator("#settings-agent")).to_be_visible()
        page.wait_for_function(
            """() => getComputedStyle(document.documentElement)
                .getPropertyValue("--layout-content-width").trim() === '640px'"""  # noqa: E501
        )
        geometry = page.evaluate(
            """() => {
                const rectWidth = selector => document.querySelector(selector)
                    ?.getBoundingClientRect().width ?? 0;
                const action = document.querySelector(".settings-agent-terminal-action");
                const scrollport = document.querySelector("[data-settings-content-scrollport]");
                const ancestorOverflow = [];
                for (let node = action; node && node !== scrollport; node = node.parentElement) {
                    const style = getComputedStyle(node);
                    ancestorOverflow.push({
                        selector: node.id || node.className || node.tagName,
                        x: style.overflowX,
                        y: style.overflowY,
                    });
                }
                return {
                    contentToken: getComputedStyle(document.documentElement)
                        .getPropertyValue("--layout-content-width").trim(),
                    controlToken: getComputedStyle(document.documentElement)
                        .getPropertyValue("--layout-control-width").trim(),
                    heading: rectWidth("#settings_workspace .workspace-summary-card > .report-heading-row"),
                    panel: rectWidth("#settings-agent"),
                    field: rectWidth("#settings-agent .field"),
                    action: rectWidth(".settings-agent-terminal-action"),
                    actionOverflow: action ? getComputedStyle(action).overflow : "missing",
                    actionShadow: action ? getComputedStyle(action).boxShadow : "none",
                    shellOverflow: getComputedStyle(
                        document.querySelector("#settings_workspace .workspace-summary-card")
                    ).overflow,
                    scrollportOverflow: scrollport
                        ? getComputedStyle(scrollport).overflow
                        : "missing",
                    scrollportBleed: action && scrollport
                        ? action.getBoundingClientRect().left
                            - scrollport.getBoundingClientRect().left
                        : 0,
                    ancestorOverflow,
                    documentOverflow: document.documentElement.scrollWidth
                        - document.documentElement.clientWidth,
                };
            }"""
        )

        assert geometry["contentToken"] == "640px"
        assert geometry["controlToken"] == "384px"
        expected_content_width = min(640, geometry["panel"])
        expected_control_width = min(384, geometry["panel"])
        assert abs(geometry["heading"] - geometry["panel"]) <= 1
        assert abs(geometry["action"] - expected_content_width) <= 1
        assert abs(geometry["field"] - expected_control_width) <= 1
        assert geometry["actionOverflow"] == "visible"
        assert geometry["actionShadow"] != "none"
        assert geometry["shellOverflow"] == "visible"
        assert geometry["scrollportOverflow"] == "hidden auto"
        assert geometry["scrollportBleed"] >= 47
        assert all(
            item["x"] == "visible" and item["y"] == "visible"
            for item in geometry["ancestorOverflow"]
        ), geometry["ancestorOverflow"]
        assert geometry["documentOverflow"] <= 1

        page.goto(
            f"{sidebar_server_url}/settings/style-tokens",
            wait_until="domcontentloaded",
        )
        style_geometry = page.evaluate(
            """() => ({
                heading: document.querySelector(".settings-shell-style-tokens > .settings-summary-card")
                    ?.getBoundingClientRect().width ?? 0,
                workspace: document.querySelector("#workspace_panel")
                    ?.getBoundingClientRect().width ?? 0,
                shellOverflow: getComputedStyle(
                    document.querySelector(".settings-workspace-header.settings-shell-style-tokens")
                ).overflow,
                cardOverflow: getComputedStyle(
                    document.querySelector(".settings-shell-style-tokens .style-token-card")
                ).overflow,
                documentOverflow: document.documentElement.scrollWidth
                    - document.documentElement.clientWidth,
            })"""
        )
        assert style_geometry["heading"] <= min(640, style_geometry["workspace"]) + 1
        if width >= 901:
            assert abs(style_geometry["heading"] - 640) <= 1
        assert style_geometry["shellOverflow"] == "visible"
        assert style_geometry["cardOverflow"] == "visible"
        assert style_geometry["documentOverflow"] <= 1
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
        stop_border = stop_button.evaluate(
            "button => ({width: getComputedStyle(button).borderWidth, "
            "color: getComputedStyle(button).borderColor})"
        )
        assert stop_border == {"width": "0px", "color": "rgba(0, 0, 0, 0)"}
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
        expect(session_mode_trigger).to_have_count(1)
        # Keep the production session-list shape while isolating the language
        # fixture from the Agent poller, which legitimately re-renders its live controls.
        page.evaluate(
            """() => {
                const fixture = document.createElement("div");
                fixture.id = "language-rendering-agent-session-fixture";
                const createTrigger = (source, label) => {
                    const trigger = source.cloneNode(true);
                    trigger.querySelector("[data-agent-combobox-selected-label]").textContent = label;
                    return trigger;
                };
                const recentList = document.createElement("div");
                recentList.dataset.agentSessionList = "recent";
                const recentOption = document.createElement("button");
                recentOption.type = "button";
                recentOption.textContent = "简体中文最近会话";
                recentList.append(recentOption);
                fixture.append(
                    createTrigger(
                        document.querySelector(
                            ".agent-session-mode-combobox [data-agent-combobox-trigger]"
                        ),
                        "简体中文会话标题",
                    ),
                    recentList,
                );
                document.body.append(fixture);
            }""",
        )
        fixture = page.locator("#language-rendering-agent-session-fixture")
        session_mode_trigger = fixture.locator("[data-agent-combobox-trigger]").nth(0)
        session_mode_label = session_mode_trigger.locator("[data-agent-combobox-selected-label]")
        recent_session_option = fixture.locator('[data-agent-session-list="recent"] button')
        expect(session_mode_label).to_have_attribute("lang", "zh-CN")
        expect(session_mode_trigger).to_contain_text("简体中文会话标题")
        expect(recent_session_option).to_have_attribute("lang", "zh-CN")
        expect(recent_session_option).to_contain_text("简体中文最近会话")

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
        closed_theme_geometry = page.locator("#global_theme_toggle").evaluate(
            """theme => {
                const rect = theme.getBoundingClientRect();
                return {top: rect.top, right: rect.right};
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
        page.wait_for_function(
            """() => {
                const dock = document.querySelector(".sidebar-dock");
                if (!(dock instanceof HTMLElement)) return false;
                const matrix = new DOMMatrix(getComputedStyle(dock).transform);
                return matrix.a > 0.999 && matrix.d > 0.999
                    && Number.parseFloat(getComputedStyle(dock).opacity) > 0.999;
            }"""
        )

        layout = page.evaluate(
            """() => {
                const toggle = document.querySelector("#sidebar_toggle").getBoundingClientRect();
                const title = document.querySelector(".sidebar .hero h1").getBoundingClientRect();
                const dock = document.querySelector(".sidebar-dock").getBoundingClientRect();
                const actions = document.querySelector(".global-quick-actions").getBoundingClientRect();
                const theme = document.querySelector("#global_theme_toggle").getBoundingClientRect();
                const sidebar = document.querySelector(".sidebar").getBoundingClientRect();
                const centerX = rect => rect.left + (rect.width / 2);
                const centerY = rect => rect.top + (rect.height / 2);
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
                    sidebarTopGap: sidebar.top,
                    sidebarLeftGap: sidebar.left,
                    sidebarBottomGap: window.innerHeight - sidebar.bottom,
                    dockCenterDelta: Math.abs(centerX(dock) - centerX(sidebar)),
                    dockBottomGap: sidebar.bottom - dock.bottom,
                    toggleRightGap: sidebar.right - toggle.right,
                    toggleTop: toggle.top,
                    themeTop: theme.top,
                    themeRightGap: window.innerWidth - theme.right,
                    titleCenterDelta: Math.abs(centerY(title) - centerY(toggle)),
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
        for key in ("sidebarTopGap", "sidebarLeftGap", "sidebarBottomGap", "dockBottomGap", "toggleRightGap"):
            assert abs(layout[key] - 10) <= 1, f"{device_name}: {key}={layout[key]}"
        assert layout["dockCenterDelta"] <= 1, device_name
        assert abs(layout["toggleTop"] - 20) <= 1, device_name
        assert abs(layout["themeTop"] - 20) <= 1, device_name
        assert abs(layout["themeRightGap"] - 20) <= 1, device_name
        assert layout["titleCenterDelta"] <= 1, device_name
        assert abs(closed_geometry["top"] - layout["toggleTop"]) <= 1, device_name
        assert abs(closed_theme_geometry["top"] - layout["themeTop"]) <= 1, device_name

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
def test_ipad_touch_toggle_does_not_move_its_hit_target_during_overlay_motion(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    page, context = _open_page(
        disposable_browser,
        sidebar_server_url,
        820,
        1_180,
        touch=True,
        reduced_motion=None,
    )
    try:
        toggle = page.locator("#sidebar_toggle")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        transition = toggle.evaluate(
            """element => ({
                pointerCoarse: matchMedia('(pointer: coarse)').matches,
                transitionProperty: getComputedStyle(element).transitionProperty,
            })"""
        )
        assert transition["pointerCoarse"]
        assert "transform" not in {
            value.strip() for value in transition["transitionProperty"].split(",")
        }

        _tap_toggle_center(page, toggle)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _assert_toggle_hit_target(page)
        _tap_toggle_center(page, toggle)
        expect(toggle).to_have_attribute("aria-expanded", "false")
        _assert_hidden_backdrop(page)
        _assert_toggle_hit_target(page)
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
    history_requests: list[str] = []

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
                "model": "gemini-3.1-pro" if selected_platform == "gemini" else "grok-build",
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
                        "id": f"{platform}-recent-session-{index}",
                        "title": f"{platform_label} earlier session {index}",
                        "url": f"{session_url}-{index}",
                        "updated_at": "2026-08-14T04:00:00Z",
                    }
                    for index in range(19)
                ] + [
                    {
                        "id": f"{platform}-recent-session-tail",
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

    def fulfill_grok_history(route) -> None:
        history_requests.append(route.request.url)
        route.fulfill(
            json={
                "conversation_url": session_url,
                "title": f"{platform_label} selected session",
                "history": [{
                    "prompt": "What changed?",
                    "response": "The selected recent session is now visible.",
                    "response_html": "<p>The selected recent session is now visible.</p>",
                }],
                "limit": 100,
            }
        )

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
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
    if platform == "grok":
        page.route("**/api/agent/grok-session-history**", fulfill_grok_history)
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
        recent_menu = page.locator(
            '[data-agent-session-list="recent"] [data-agent-combobox-menu]'
        )
        menu_box = recent_menu.bounding_box()
        dock_box = page.locator(".sidebar-dock").bounding_box()
        assert menu_box is not None
        assert dock_box is not None
        assert menu_box["y"] >= 0
        assert menu_box["y"] + menu_box["height"] <= 720
        assert menu_box["y"] + menu_box["height"] <= dock_box["y"]
        scroll_metrics = recent_menu.evaluate(
            """element => {
                const style = getComputedStyle(element);
                const dock = document.querySelector('.sidebar-dock');
                const elementBox = element.getBoundingClientRect();
                const dockBox = dock?.getBoundingClientRect();
                const dockGap = Number.parseFloat(
                    style.getPropertyValue('--agent-session-list-dock-gap')
                ) || 0;
                return {
                    clientHeight: element.clientHeight,
                    scrollHeight: element.scrollHeight,
                    overflowY: style.overflowY,
                    scrollbarWidth: style.scrollbarWidth,
                    scrollbarGutter: style.scrollbarGutter,
                    dockGap,
                    renderedDockGap: dockBox ? dockBox.top - elementBox.bottom : null,
                };
            }"""
        )
        assert scroll_metrics["scrollHeight"] > scroll_metrics["clientHeight"]
        assert scroll_metrics["overflowY"] == "auto"
        assert scroll_metrics["scrollbarWidth"] == "none"
        assert scroll_metrics["scrollbarGutter"] == "auto"
        assert scroll_metrics["renderedDockGap"] is not None
        # Short catalogs may shrink-wrap, so require the Dock clearance as a minimum.
        assert scroll_metrics["renderedDockGap"] >= scroll_metrics["dockGap"] - 1
        expect(recent_option).to_be_visible()
        if platform == "grok":
            immediate = recent_option.evaluate(
                """option => {
                    option.click();
                    const status = document.querySelector('#agent_response_status');
                    return {
                        state: status?.dataset.status || '',
                        copy: status?.textContent?.trim() || '',
                    };
                }"""
            )
            assert immediate["state"] == "loading"
            assert "Loading the selected Grok session history" in immediate["copy"]
            expect(page.locator("#agent_response_status")).to_have_attribute("data-status", "ready")
            expect(page.locator("#agent_response_question")).to_have_text("What changed?")
            expect(page.locator("[data-agent-response-answer-content]")).to_contain_text(
                "The selected recent session is now visible."
            )
            assert len(history_requests) == 1
        else:
            recent_option.click()

        expect(page.locator('[data-agent-prompt-session-mode]')).to_have_value("recent")
        expect(page.locator('[data-agent-prompt-conversation-url]')).to_have_value(session_url)
        expect(page.locator('[data-agent-prompt-session-title]')).to_have_value(
            f"{platform_label} selected session"
        )
        _assert_agent_session_source_menu_is_hit_testable(page)
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
def test_chatgpt_edge_recent_sessions_are_a_direct_scrollable_keyboard_list(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep ChatGPT/Edge recent sessions direct, scrollable, and keyboard-selectable."""
    session_count = 36
    first_session_url = "https://chatgpt.com/c/recent-session-keyboard-0"
    catalog_payload = _chatgpt_catalog_sessions(
        *[
            {
                "id": f"recent-session-{index}",
                "title": f"ChatGPT recent session {index:02d}",
                "url": f"https://chatgpt.com/c/recent-session-keyboard-{index}",
                "updated_at": "2026-08-31T00:00:00Z",
            }
            for index in range(session_count)
        ]
    )
    source_requests: list[str] = []
    browser_status_requests: list[str] = []

    def fulfill_agent_status(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_browser_status(route) -> None:
        browser_status_requests.append(route.request.url)
        route.fulfill(
            json={
                "platform": "chatgpt",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "ChatGPT account",
                "message": "Edge is ready for ChatGPT Web.",
                "agent_sources": catalog_payload,
            }
        )

    def fulfill_preferences(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(json=catalog_payload)

    def fulfill_history(route) -> None:
        route.fulfill(json={"title": "", "history": []})

    def assert_direct_list_geometry(width: int, height: int) -> None:
        page.wait_for_function(
            """() => {
                const menu = document.querySelector(
                    '[data-agent-session-list="recent"] [data-agent-combobox-menu]'
                );
                const dock = document.querySelector('.sidebar-dock');
                if (!(menu instanceof HTMLElement) || !(dock instanceof HTMLElement)) return false;
                const menuBox = menu.getBoundingClientRect();
                const dockBox = dock.getBoundingClientRect();
                const style = getComputedStyle(menu);
                const dockGap = Number.parseFloat(
                    style.getPropertyValue('--agent-session-list-dock-gap'),
                ) || 0;
                return menuBox.width > 0
                    && menuBox.height > 0
                    && dockBox.width > 0
                    && dockBox.height > 0
                    && menuBox.bottom <= dockBox.top + 1
                    && dockBox.top - menuBox.bottom >= dockGap - 1
                    && Number.parseFloat(
                        menu.style.getPropertyValue('--agent-session-list-menu-available-height'),
                    ) > 0;
            }"""
        )
        geometry = page.evaluate(
            """() => {
                const menu = document.querySelector(
                    '[data-agent-session-list="recent"] [data-agent-combobox-menu]'
                );
                const dock = document.querySelector('.sidebar-dock');
                if (!(menu instanceof HTMLElement) || !(dock instanceof HTMLElement)) return null;
                const menuBox = menu.getBoundingClientRect();
                const dockBox = dock.getBoundingClientRect();
                const style = getComputedStyle(menu);
                menu.scrollTop = menu.scrollHeight;
                return {
                    menu: {
                        bottom: menuBox.bottom,
                        left: menuBox.left,
                        right: menuBox.right,
                        top: menuBox.top,
                    },
                    dock: {top: dockBox.top},
                    clientHeight: menu.clientHeight,
                    scrollHeight: menu.scrollHeight,
                    scrollTop: menu.scrollTop,
                    overflowY: style.overflowY,
                    dockGap: Number.parseFloat(
                        style.getPropertyValue('--agent-session-list-dock-gap'),
                    ) || 0,
                    renderedDockGap: dockBox.top - menuBox.bottom,
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) - document.documentElement.clientWidth,
                    viewportWidth: window.innerWidth,
                };
            }"""
        )
        assert geometry is not None
        assert geometry["scrollHeight"] > geometry["clientHeight"], (width, height, geometry)
        assert geometry["scrollTop"] > 0, (width, height, geometry)
        assert geometry["overflowY"] == "auto", (width, height, geometry)
        assert geometry["menu"]["left"] >= -1, (width, height, geometry)
        assert geometry["menu"]["right"] <= geometry["viewportWidth"] + 1, (width, height, geometry)
        assert geometry["menu"]["bottom"] <= geometry["dock"]["top"] + 1, (width, height, geometry)
        assert geometry["renderedDockGap"] >= geometry["dockGap"] - 1, (width, height, geometry)
        assert geometry["horizontalOverflow"] <= 1, (width, height, geometry)

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
    page.route("**/api/agent/chatgpt-session-history**", fulfill_history)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        expect(
            page.locator(".agent-platform-combobox [data-agent-combobox-input]")
        ).to_have_value("chatgpt")
        expect(
            page.locator(".agent-browser-combobox [data-agent-combobox-input]")
        ).to_have_value("edge")

        session_mode_trigger = page.locator(
            ".agent-session-mode-combobox [data-agent-combobox-trigger]"
        )
        session_mode_trigger.click()
        page.locator(
            '.agent-session-mode-combobox [data-agent-combobox-option="recent"]'
        ).click()

        recent_field = page.locator("[data-agent-recent-session-field]")
        recent_list = page.locator('[data-agent-session-list="recent"]')
        recent_menu = recent_list.locator("[data-agent-combobox-menu]")
        first_option = recent_menu.locator(
            f'[data-agent-combobox-option="{first_session_url}"]'
        )
        expect(recent_field).to_be_visible()
        expect(recent_list).to_have_attribute("data-agent-direct-list", "true")
        expect(recent_list.locator("[data-agent-combobox-trigger]")).to_have_count(0)
        expect(recent_menu).to_be_visible()
        expect(recent_menu).to_have_attribute("role", "listbox")
        expect(recent_menu.locator("[data-agent-combobox-option]")).to_have_count(session_count)
        expect(first_option).to_have_attribute("role", "option")
        expect(first_option).to_have_attribute("tabindex", "0")
        assert first_option.evaluate("element => element.tagName") == "BUTTON"
        assert len(browser_status_requests) >= 2, (
            "Selecting Recent sessions must refresh the bootstrapped browser catalog."
        )
        assert any("refresh=1" in request_url for request_url in browser_status_requests)
        assert source_requests == []

        assert_direct_list_geometry(1_280, 900)

        session_mode_trigger.focus()
        page.keyboard.press("Tab")
        expect(first_option).to_be_focused()
        page.keyboard.press("Enter")

        expect(first_option).to_have_attribute("aria-selected", "true")
        expect(
            recent_menu.locator('[data-agent-combobox-option]:not([aria-selected="true"])')
        ).to_have_count(session_count - 1)
        expect(page.locator("[data-agent-prompt-session-mode]")).to_have_value("recent")
        expect(page.locator("[data-agent-recent-session-url]")).to_have_value(first_session_url)
        expect(page.locator("[data-agent-prompt-conversation-url]")).to_have_value(first_session_url)
        expect(page.locator("[data-agent-prompt-session-title]")).to_have_value(
            "ChatGPT recent session 00"
        )
        expect(page.locator("[data-agent-session-source]")).to_have_attribute(
            "data-agent-session-mode", "recent"
        )
        _assert_agent_session_source_menu_is_hit_testable(page)

        page.set_viewport_size({"width": 390, "height": 844})
        toggle = page.locator("#sidebar_toggle")
        if toggle.get_attribute("aria-expanded") != "true":
            _tap_toggle_center(page, toggle)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(recent_field).to_be_visible()
        page.wait_for_function(
            """() => {
                const dock = document.querySelector('.sidebar-dock');
                if (!(dock instanceof HTMLElement)) return false;
                const matrix = new DOMMatrix(getComputedStyle(dock).transform);
                return matrix.a > 0.999
                    && matrix.d > 0.999
                    && Math.abs(matrix.m42) <= 0.5
                    && Number.parseFloat(getComputedStyle(dock).opacity) > 0.999;
            }"""
        )
        assert_direct_list_geometry(390, 844)
        _assert_agent_session_source_menu_is_hit_testable(page)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("platform", "platform_label", "project_url"),
    (
        ("chatgpt", "ChatGPT", "https://chatgpt.com/g/g-p-chatgpt-project/project"),
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
                "model": (
                    "gpt-5.6-sol"
                    if selected_platform == "chatgpt"
                    else "gemini-3.1-pro"
                    if selected_platform == "gemini"
                    else "grok-build"
                ),
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
                        **(
                            {"icon": "currency-dollar", "icon_color": "#53B559"}
                            if platform == "chatgpt"
                            else {}
                        ),
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
        expect(
            page.locator(
                ".agent-session-mode-combobox [data-agent-combobox-selected-icon]"
            )
        ).to_have_attribute("src", re.compile(r"/static/images/folder\.fill\.svg$"))
        project_option = page.locator(
            f'[data-agent-session-list="projects"] [data-agent-combobox-option="{project_url}"]'
        )
        expect(project_option).to_have_count(1)
        page.locator('[data-agent-session-list="projects"] [data-agent-combobox-trigger]').click()
        expect(project_option).to_be_visible()
        project_option.click()

        if platform == "chatgpt":
            project_icon_shells = page.locator(
                ".agent-session-mode-combobox .browser-picker-selected-icon-shell, "
                '[data-agent-session-list="projects"] .browser-picker-selected-icon-shell, '
                '[data-agent-session-list="project-sessions"] .browser-picker-selected-icon-shell'
            )
            for width, height in ((1_280, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                expect(project_icon_shells).to_have_count(3)
                expect(project_icon_shells.first).to_be_visible()
                expect(
                    page.locator(
                        '[data-agent-session-list="projects"] [data-agent-combobox-selected-icon]'
                    )
                ).to_have_attribute("src", re.compile(r"^data:image/svg\+xml"))
                expect(project_option).to_have_attribute(
                    "data-agent-combobox-icon-name", "currency-dollar"
                )
                icon_centers = project_icon_shells.evaluate_all(
                    "nodes => nodes.map(node => { "
                    "const rect = node.getBoundingClientRect(); "
                    "return rect.left + rect.width / 2; "
                    "})"
                )
                assert max(icon_centers) - min(icon_centers) <= 1
            page.set_viewport_size({"width": 1_280, "height": 900})

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
def test_agent_project_session_selection_loads_grok_response_immediately(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Show loading immediately, then render the selected Grok project session."""
    project_url = "https://grok.com/project/grok-project?tab=conversations"
    session_url = "https://grok.com/project/grok-project?chat=grok-session"
    history_requests: list[str] = []

    def agent_payload() -> dict[str, object]:
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
                "platform": "grok",
                "model": "grok-build",
                "finished_at": "",
            },
        }

    def fulfill_agent_status(route) -> None:
        route.fulfill(json=agent_payload())

    def fulfill_browser_status(route) -> None:
        route.fulfill(
            json={
                "platform": "grok",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "Grok account",
                "message": "Edge is ready for Grok Web.",
            }
        )

    def fulfill_preferences(route) -> None:
        route.fulfill(json=agent_payload())

    def fulfill_sources(route) -> None:
        route.fulfill(
            json={
                "platform": "grok",
                "browser_label": "Edge",
                "recent_sessions": [],
                "projects": [{
                    "id": "grok-project",
                    "title": "Grok project",
                    "url": project_url,
                    "updated_at": "2026-09-02T01:00:00Z",
                }],
                "limit": 20,
            }
        )

    def fulfill_project_sessions(route) -> None:
        route.fulfill(
            json={
                "platform": "grok",
                "project_url": project_url,
                "sessions": [{
                    "id": "grok-session",
                    "title": "Renamed project session",
                    "url": session_url,
                    "updated_at": "2026-09-02T01:05:00Z",
                }],
                "limit": 20,
            }
        )

    def fulfill_history(route) -> None:
        history_requests.append(route.request.url)
        route.fulfill(
            json={
                "conversation_url": session_url,
                "title": "Renamed project session",
                "history": [{
                    "prompt": "What changed?",
                    "response": "The selected session is now visible.",
                    "response_html": "<p>The selected session is now visible.</p>",
                    "started_at": "2026-09-02T01:00:00Z",
                    "finished_at": "2026-09-02T01:00:02Z",
                }],
                "limit": 100,
            }
        )

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
    page.route("**/api/agent/grok-session-history**", fulfill_history)
    try:
        page.goto(f"{sidebar_server_url}/agent", wait_until="domcontentloaded")
        page.get_by_role("button", name="Web service: ChatGPT", exact=True).click()
        page.locator('.agent-platform-combobox [data-agent-combobox-option="grok"]').click()
        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        page.locator('.agent-session-mode-combobox [data-agent-combobox-option="project"]').click()

        project_option = page.locator(
            f'[data-agent-session-list="projects"] [data-agent-combobox-option="{project_url}"]'
        )
        expect(project_option).to_have_count(1)
        page.locator('[data-agent-session-list="projects"] [data-agent-combobox-trigger]').click()
        project_option.click()
        session_option = page.locator(
            f'[data-agent-session-list="project-sessions"] [data-agent-combobox-option="{session_url}"]'
        )
        expect(session_option).to_have_count(1)
        new_session_icon = page.locator(
            '[data-agent-session-list="project-sessions"] '
            '[data-agent-combobox-option="new"] .browser-picker-option-icon'
        )
        expect(new_session_icon).to_have_count(1)
        expect(new_session_icon).to_have_attribute("src", re.compile(r"/static/images/plus\.circle\.svg$"))
        selected_project_session_icon = page.locator(
            '[data-agent-session-list="project-sessions"] [data-agent-combobox-selected-icon]'
        )
        expect(selected_project_session_icon).to_be_visible()
        expect(selected_project_session_icon).to_have_attribute(
            "src", re.compile(r"/static/images/plus\.circle\.svg$")
        )

        immediate = session_option.evaluate(
            """option => {
                option.click();
                const status = document.querySelector('#agent_response_status');
                return {
                    state: status?.dataset.status || '',
                    copy: status?.textContent?.trim() || '',
                };
            }"""
        )
        assert immediate["state"] == "loading"
        assert "Loading the selected Grok session history" in immediate["copy"]
        expect(page.locator("#agent_response_status")).to_have_attribute("data-status", "ready")
        expect(page.locator("#agent_response_question")).to_have_text("What changed?")
        expect(page.locator("[data-agent-response-answer-content]")).to_contain_text(
            "The selected session is now visible."
        )
        assert len(history_requests) == 1
        assert "conversation_url=" in history_requests[0]
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
        browser_trigger = page.get_by_role("button", name="Browser: Edge", exact=True)
        assert browser_trigger.evaluate(
            "element => element.getBoundingClientRect().height"
        ) == 36
        browser_trigger.click()
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
@pytest.mark.parametrize("source_key", ("chatgpt", "grok", "gemini", "claude"))
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
        source_options = page.locator("[data-cache-source-switcher-option]")
        x_source_option = page.locator('[data-cache-source-switcher-option="x"]')
        expect(x_source_option).to_be_hidden()
        assert source_options.evaluate_all(
            "elements => elements.filter(element => !element.hidden).map(element => element.dataset.cacheSourceSwitcherOption)"
        ) == ["chatgpt", "claude", "gemini", "grok"]
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
        assert x_source_option.evaluate("element => !element.hidden")
        assert source_options.evaluate_all(
            "elements => elements.filter(element => !element.hidden).map(element => element.dataset.cacheSourceSwitcherOption)"
        ) == ["chatgpt", "claude", "gemini", "grok", "x"]
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
@pytest.mark.parametrize(
    ("width", "height", "touch"),
    ((1_280, 900, False), (390, 844, True)),
)
def test_chatgpt_media_uses_agent_recent_project_picker(
    disposable_browser: Browser,
    sidebar_server_url: str,
    width: int,
    height: int,
    touch: bool,
) -> None:
    """Choose a ChatGPT project from the live Agent source catalog contract."""
    project_url = "https://chatgpt.com/g/g-p-demo-project/project"
    catalog_payload = {
        "platform": "chatgpt",
        "browser_label": "Edge",
        "recent_sessions": [],
        "projects": [
            {
                "id": "demo-project",
                "title": "Demo project",
                "url": project_url,
                "updated_at": "2026-09-02T00:00:00Z",
            },
        ],
        "limit": 20,
    }
    context = disposable_browser.new_context(
        viewport={"width": width, "height": height},
        has_touch=touch,
        is_mobile=touch,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route(
        "**/api/agent/chatgpt-sources**",
        lambda route: route.fulfill(json=catalog_payload),
    )
    try:
        page.goto(f"{sidebar_server_url}/cache/chatgpt", wait_until="domcontentloaded")
        expect(page.locator('input[name="chatgpt_project_url"][type="url"]')).to_have_count(0)
        if touch:
            page.locator("#sidebar_toggle").click()

        page.locator('[data-cache-content-mode-option="media"]').click()
        picker = page.locator("[data-chatgpt-project-picker]")
        trigger = page.locator("[data-chatgpt-project-trigger]")
        project_option = page.locator(
            f'[data-chatgpt-project-option][data-chatgpt-project-url="{project_url}"]'
        )
        expect(picker).to_be_visible()
        expect(project_option).to_have_count(1)

        trigger.click()
        expect(page.locator("[data-chatgpt-project-menu]")).to_be_visible()
        project_option.click()
        expect(page.locator('[name="chatgpt_project_url"]')).to_have_value(project_url)
        expect(page.locator('[name="chatgpt_project_name"]')).to_have_value("Demo project")
        expect(trigger).to_have_text("Demo project")
        expect(project_option).to_have_attribute("aria-selected", "true")
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


FINISHED_SNAPSHOT_URL = "https://chatgpt.com/c/6a8d4fce-d1e8-83ee-9996-68e9ef114ef0"
AGENTIC_TROUBLESHOOTING_URL = "https://chatgpt.com/c/6a8d310f-7af4-83e8-acb4-6e3e825e984f"


def _finished_chatgpt_agent_payload() -> dict[str, object]:
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
            "paused": False,
            "phase": "finished",
            "message": "GPT-5.6 Sol completed the project task after local bodycheck.",
            "prompt": "",
            "response": "Read-only inspection finished.",
            "response_html": "<p>Read-only inspection finished.</p>",
            "history": [],
            "activity": [],
            "conversation_url": FINISHED_SNAPSHOT_URL,
            "project_url": "",
            "session_title": "Reused model verification",
            "session_mode": "recent",
            "platform": "chatgpt",
            "browser": "edge",
            "workspace_path": load_computer_use_settings().workspace_path,
            "model": "gpt-5.6-sol",
            "model_verified": True,
            "actual_model": "GPT-5.6 Sol",
            "bodycheck_passed": True,
            "started_at": "2026-08-25T09:02:38Z",
            "finished_at": "2026-08-25T09:03:57Z",
        },
    }


def _chatgpt_catalog_sessions(*sessions: dict[str, str]) -> dict[str, object]:
    return {
        "platform": "chatgpt",
        "browser_label": "Edge",
        "recent_sessions": list(sessions),
        "projects": [],
        "limit": 20,
    }


@pytest.mark.integration
@pytest.mark.parametrize(
    "unsupported_copy",
    (
        "Gemini isn’t currently supported in your country. Stay tuned!",
        "Gemini 目前不支持你所在的地区。敬请期待！",
        "Gemini 目前不支援你所在的地區。敬請期待！",
    ),
)
def test_gemini_session_dom_marks_a_signed_in_region_unavailable_page(
    disposable_browser: Browser,
    unsupported_copy: str,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button aria-label="Google Account: Demo account">Account</button>
            <main>{unsupported_copy}</main>
            """
        )

        snapshot = inspect_gemini_session(page)

        assert snapshot["accountLabel"] == "Google Account: Demo account"
        assert snapshot["signedOut"] is False
        assert snapshot["unsupportedRegion"] is True
        assert snapshot["hasComposer"] is False
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_session_dom_does_not_treat_conversation_copy_as_a_region_failure(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button aria-label="Google Account: Demo account">Account</button>
            <main>Gemini 目前不支持你所在的地区。敬请期待！</main>
            <textarea placeholder="Ask Gemini"></textarea>
            """
        )

        snapshot = inspect_gemini_session(page)

        assert snapshot["hasComposer"] is True
        assert snapshot["unsupportedRegion"] is False
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_session_dom_rejects_an_anonymous_composer_shell(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <header><button>Sign in</button></header>
            <nav><a href="https://gemini.google.com/app/anonymous-shell">Recent activity</a></nav>
            <textarea placeholder="Ask Gemini"></textarea>
            """
        )

        snapshot = inspect_gemini_session(page)

        assert snapshot["conversationLinks"] == 1
        assert snapshot["hasComposer"] is True
        assert snapshot["hasAuthAction"] is True
        assert snapshot["signedOut"] is True
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_session_dom_ignores_a_conversation_sign_in_decoy(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button aria-label="Google Account: Demo account">Account</button>
            <model-response><button>Sign in</button></model-response>
            <textarea placeholder="Ask Gemini"></textarea>
            """
        )

        snapshot = inspect_gemini_session(page)

        assert snapshot["hasAuthAction"] is False
        assert snapshot["signedOut"] is False
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    (
        "primary_text",
        "primary_style",
        "sublabel_text",
        "add_selected_class",
        "marker_style",
        "nested_popup",
        "expected",
        "expected_option_clicks",
    ),
    (
        pytest.param(
            "3.1 Pro", "", "Advanced reasoning", True, "", False, True, 1, id="exact-proof"
        ),
        pytest.param(
            "3.1 Pro", "", "Advanced reasoning", True, None, False, False, 1, id="class-only"
        ),
        pytest.param(
            "3.1 Pro", "", "Advanced reasoning", False, "", False, False, 1, id="marker-only"
        ),
        pytest.param(
            "3.1 Pro", "", "Advanced reasoning", True, "opacity: 0", False, False, 1, id="hidden-marker"
        ),
        pytest.param(
            "", "", "3.1 Pro", True, "", False, False, 0, id="subtitle-only"
        ),
        pytest.param(
            "3.1 Pro", "display: none", "Advanced reasoning", True, "", False, False, 0, id="hidden-primary"
        ),
        pytest.param(
            "Mode picker 3.1 Pro", "", "Advanced reasoning", True, "", False, False, 0, id="wrapper-primary"
        ),
        pytest.param(
            "Gemini 3.1 Pro", "", "Advanced reasoning", True, "", False, False, 0, id="full-brand-primary"
        ),
        pytest.param(
            "3.1 Pro", "", "Advanced reasoning", True, "", True, False, 0, id="nested-popup"
        ),
    ),
)
def test_gemini_model_dom_selection_requires_exact_controlled_selected_proof(
    disposable_browser: Browser,
    primary_text: str,
    primary_style: str,
    sublabel_text: str,
    add_selected_class: bool,
    marker_style: str | None,
    nested_popup: bool,
    expected: bool,
    expected_option_clicks: int,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        option_markup = f"""
            <button id="pro-option" role="menuitem">
                <span class="label" style="{primary_style}">{primary_text}</span>
                <span class="sublabel">{sublabel_text}</span>
            </button>
        """
        if nested_popup:
            option_markup = f'<div role="menu">{option_markup}</div>'
        page.set_content(
            f"""
            <button
                id="mode-picker"
                aria-label="Open mode picker, currently Flash"
                aria-haspopup="true"
                aria-expanded="false"
                aria-controls="mode-menu"
            >Flash</button>
            <div id="mode-menu" role="menu" hidden>
                <button id="flash-option" role="menuitem">
                    <span class="label">3.7 Flash</span>
                    <span class="sublabel">All-around help</span>
                </button>
                {option_markup}
            </div>
            <script>
                window.selectionAudit = {{triggerClicks: 0, optionClicks: 0}};
                const trigger = document.querySelector('#mode-picker');
                const menu = document.querySelector('#mode-menu');
                const option = document.querySelector('#pro-option');
                trigger.addEventListener('click', () => {{
                    window.selectionAudit.triggerClicks += 1;
                    const opening = menu.hidden;
                    menu.hidden = !opening;
                    trigger.setAttribute('aria-expanded', String(opening));
                }});
                option.addEventListener('click', () => {{
                    window.selectionAudit.optionClicks += 1;
                    trigger.setAttribute('aria-label', 'Open mode picker, currently Pro');
                    trigger.textContent = 'Pro';
                    menu.hidden = true;
                    trigger.setAttribute('aria-expanded', 'false');
                    if ({str(add_selected_class).lower()}) {{
                        option.classList.add('selected');
                    }}
                    if ({str(marker_style is not None).lower()}) {{
                        const marker = document.createElement('span');
                        marker.setAttribute('aria-label', 'Selected');
                        marker.setAttribute('style', {json.dumps(marker_style or '')});
                        marker.textContent = '✓';
                        option.prepend(marker);
                    }}
                }});
            </script>
            """
        )

        assert (
            _select_web_model(page, "chromium", "gemini", "gemini-3.1-pro")
            is expected
        )
        assert page.evaluate("window.selectionAudit.optionClicks") == expected_option_clicks
        assert page.locator("#mode-picker").get_attribute("aria-expanded") == "false"
        assert page.locator("#mode-menu").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_model_dom_selection_rejects_the_anonymous_model_menu(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="mode-picker"
                aria-label="Open mode picker, currently Flash-Lite"
                aria-haspopup="true"
                aria-expanded="false"
                aria-controls="mode-menu"
            >Flash-Lite</button>
            <div id="mode-menu" role="menu" hidden>
                <gem-menu-item class="selected" role="menuitem">
                    <gem-icon aria-label="Selected"></gem-icon>
                    <span class="label">3.5 Flash-Lite</span>
                </gem-menu-item>
                <gem-menu-item id="pro-option" role="menuitem">
                    <span class="label">3.1 Pro</span>
                    <span class="sublabel">Advanced reasoning</span>
                </gem-menu-item>
                <gem-menu-item role="menuitem">
                    <span class="label">Sign in for all models</span>
                </gem-menu-item>
            </div>
            <script>
                window.selectionAudit = {triggerClicks: 0, optionClicks: 0};
                const trigger = document.querySelector('#mode-picker');
                const menu = document.querySelector('#mode-menu');
                trigger.addEventListener('click', () => {
                    window.selectionAudit.triggerClicks += 1;
                    const opening = menu.hidden;
                    menu.hidden = !opening;
                    trigger.setAttribute('aria-expanded', String(opening));
                });
                document.querySelector('#pro-option').addEventListener('click', () => {
                    window.selectionAudit.optionClicks += 1;
                });
            </script>
            """
        )
        observation: dict[str, object] = {}

        assert (
            _select_web_model(
                page,
                "chromium",
                "gemini",
                "gemini-3.1-pro",
                observation,
            )
            is False
        )
        assert observation["reason"] == "signed-out"
        assert page.evaluate("window.selectionAudit.optionClicks") == 0
        assert page.locator("#mode-picker").get_attribute("aria-expanded") == "false"
        assert page.locator("#mode-menu").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_model_dom_selection_waits_for_delayed_hydration(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <textarea placeholder="Ask Gemini"></textarea>
            <button aria-label="Navigation">Navigation</button>
            <script>
                window.selectionAudit = {
                    mounted: false,
                    triggerClicks: 0,
                    optionClicks: 0,
                };
                const mountModelControl = () => {
                    const trigger = document.createElement('button');
                    trigger.id = 'mode-picker';
                    trigger.setAttribute('aria-label', 'Open mode picker, currently Flash');
                    trigger.setAttribute('aria-haspopup', 'true');
                    trigger.setAttribute('aria-expanded', 'false');
                    trigger.setAttribute('aria-controls', 'mode-menu');
                    trigger.textContent = 'Flash';

                    const menu = document.createElement('div');
                    menu.id = 'mode-menu';
                    menu.setAttribute('role', 'menu');
                    menu.hidden = true;

                    const option = document.createElement('button');
                    option.id = 'pro-option';
                    option.setAttribute('role', 'menuitem');
                    option.innerHTML = `
                        <span class="label">3.1 Pro</span>
                        <span class="sublabel">Advanced reasoning</span>
                    `;
                    menu.append(option);

                    trigger.addEventListener('click', () => {
                        window.selectionAudit.triggerClicks += 1;
                        const opening = menu.hidden;
                        menu.hidden = !opening;
                        trigger.setAttribute('aria-expanded', String(opening));
                    });
                    option.addEventListener('click', () => {
                        window.selectionAudit.optionClicks += 1;
                        option.classList.add('selected');
                        const marker = document.createElement('span');
                        marker.setAttribute('aria-label', 'Selected');
                        marker.textContent = '✓';
                        option.prepend(marker);
                        trigger.setAttribute('aria-label', 'Open mode picker, currently Pro');
                        trigger.textContent = 'Pro';
                        menu.hidden = true;
                        trigger.setAttribute('aria-expanded', 'false');
                    });

                    document.body.append(trigger, menu);
                    window.selectionAudit.mounted = true;
                };
                window.setTimeout(mountModelControl, 500);
            </script>
            """
        )

        observation: dict[str, object] = {}
        assert (
            _select_web_model(
                page,
                "chromium",
                "gemini",
                "gemini-3.1-pro",
                observation,
            )
            is True
        )
        assert page.evaluate("window.selectionAudit") == {
            "mounted": True,
            "triggerClicks": 3,
            "optionClicks": 1,
        }
        assert observation["observed"] == "3.1 pro"
        assert page.locator("#mode-picker").get_attribute("aria-expanded") == "false"
        assert page.locator("#mode-menu").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
def test_web_model_failure_diagnostic_excludes_dom_text(
    disposable_browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.computer_use_agent as computer_use_agent

    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <title>Confidential flight acquisition</title>
            <textarea placeholder="Ask Gemini"></textarea>
            <button>Project confidential-alpha</button>
            """
        )
        monkeypatch.setattr(computer_use_agent, "WEB_MODEL_CONTROL_WAIT_ATTEMPTS", 1)
        monkeypatch.setattr(computer_use_agent, "WEB_MODEL_CONTROL_POLL_SECONDS", 0)
        observation: dict[str, object] = {}

        assert (
            _select_web_model(
                page,
                "chromium",
                "gemini",
                "gemini-3.1-pro",
                observation,
            )
            is False
        )
        serialized = json.dumps(observation, ensure_ascii=False)
        assert "Confidential" not in serialized
        assert "confidential" not in serialized
        assert observation["visible_buttons"] == []
        assert observation["diagnostic"] == {
            "ready_state": "complete",
            "visible_button_count": 1,
            "visible_composer_count": 1,
            "semantic_trigger_count": 0,
            "visible_menu_count": 0,
        }
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_model_dom_selection_accepts_a_remounted_controlled_menu(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="mode-picker"
                aria-label="Open mode picker, currently Flash"
                aria-haspopup="true"
                aria-expanded="false"
                aria-controls="mode-menu"
            >Flash</button>
            <script>
                window.selectionAudit = {mounts: 0, optionClicks: 0};
                let selected = false;
                const trigger = document.querySelector('#mode-picker');
                const removeMenu = () => {
                    document.querySelector('#mode-menu')?.remove();
                    trigger.setAttribute('aria-expanded', 'false');
                };
                const mountMenu = () => {
                    window.selectionAudit.mounts += 1;
                    const menu = document.createElement('div');
                    menu.id = 'mode-menu';
                    menu.setAttribute('role', 'menu');
                    const option = document.createElement('button');
                    option.id = 'pro-option';
                    option.setAttribute('role', 'menuitem');
                    if (selected) option.classList.add('selected');
                    option.innerHTML = `
                        ${selected ? '<span aria-label="Selected">✓</span>' : ''}
                        <span class="label">3.1 Pro</span>
                        <span class="sublabel">Advanced reasoning</span>
                    `;
                    option.addEventListener('click', () => {
                        window.selectionAudit.optionClicks += 1;
                        selected = true;
                        trigger.setAttribute('aria-label', 'Open mode picker, currently Pro');
                        trigger.textContent = 'Pro';
                        removeMenu();
                    });
                    menu.append(option);
                    document.body.append(menu);
                    trigger.setAttribute('aria-expanded', 'true');
                };
                trigger.addEventListener('click', () => {
                    if (document.querySelector('#mode-menu')) removeMenu();
                    else mountMenu();
                });
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "gemini", "gemini-3.1-pro") is True
        assert page.evaluate("window.selectionAudit") == {"mounts": 2, "optionClicks": 1}
        assert page.locator("#mode-menu").count() == 0
        assert page.locator("#mode-picker").get_attribute("aria-expanded") == "false"
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_model_dom_selection_accepts_a_remounted_controlled_trigger(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <div id="trigger-host"></div>
            <script>
                window.selectionAudit = {
                    triggerMounts: 0,
                    triggerClicks: 0,
                    menuMounts: 0,
                    optionClicks: 0,
                };
                let selected = false;
                const host = document.querySelector('#trigger-host');
                const removeMenu = () => document.querySelector('#mode-menu')?.remove();
                const mountTrigger = (expanded) => {
                    window.selectionAudit.triggerMounts += 1;
                    const trigger = document.createElement('button');
                    trigger.id = 'mode-picker';
                    trigger.setAttribute(
                        'aria-label',
                        `Open mode picker, currently ${selected ? 'Pro' : 'Flash'}`
                    );
                    trigger.setAttribute('aria-haspopup', 'true');
                    trigger.setAttribute('aria-expanded', String(expanded));
                    trigger.setAttribute('aria-controls', 'mode-menu');
                    trigger.textContent = selected ? 'Pro' : 'Flash';
                    trigger.addEventListener('click', () => {
                        window.selectionAudit.triggerClicks += 1;
                        if (document.querySelector('#mode-menu')) {
                            removeMenu();
                            mountTrigger(false);
                        } else {
                            mountMenu();
                            mountTrigger(true);
                        }
                    });
                    host.replaceChildren(trigger);
                };
                const mountMenu = () => {
                    window.selectionAudit.menuMounts += 1;
                    const menu = document.createElement('div');
                    menu.id = 'mode-menu';
                    menu.setAttribute('role', 'menu');
                    const option = document.createElement('button');
                    option.id = 'pro-option';
                    option.setAttribute('role', 'menuitem');
                    if (selected) option.classList.add('selected');
                    option.innerHTML = `
                        ${selected ? '<span aria-label="Selected">✓</span>' : ''}
                        <span class="label">3.1 Pro</span>
                        <span class="sublabel">Advanced reasoning</span>
                    `;
                    option.addEventListener('click', () => {
                        window.selectionAudit.optionClicks += 1;
                        selected = true;
                        removeMenu();
                        mountTrigger(false);
                    });
                    menu.append(option);
                    document.body.append(menu);
                };
                mountTrigger(false);
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "gemini", "gemini-3.1-pro") is True
        assert page.evaluate("window.selectionAudit") == {
            "triggerMounts": 5,
            "triggerClicks": 3,
            "menuMounts": 2,
            "optionClicks": 1,
        }
        assert page.locator("#mode-menu").count() == 0
        assert page.locator("#mode-picker").get_attribute("aria-expanded") == "false"
    finally:
        context.close()


@pytest.mark.integration
def test_gemini_model_dom_selection_rejects_ambiguous_controlled_triggers(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                class="mode-picker"
                aria-label="Open mode picker, currently Flash"
                aria-haspopup="true"
                aria-expanded="false"
                aria-controls="mode-menu"
            >Flash</button>
            <button
                class="mode-picker"
                aria-label="Open mode picker, currently Flash"
                aria-haspopup="true"
                aria-expanded="false"
                aria-controls="mode-menu"
            >Flash</button>
            <div id="mode-menu" role="menu" hidden>
                <button role="menuitem">
                    <span class="label">3.1 Pro</span>
                </button>
            </div>
            <script>
                window.triggerClicks = 0;
                document.querySelectorAll('.mode-picker').forEach((trigger) => {
                    trigger.addEventListener('click', () => {
                        window.triggerClicks += 1;
                    });
                });
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "gemini", "gemini-3.1-pro") is False
        assert page.evaluate("window.triggerClicks") == 0
        assert page.locator("#mode-menu").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("controls_id", "surface_id", "surface_role", "expected_trigger_clicks"),
    (
        ("", "mode-menu", "menu", 0),
        ("missing-menu", "mode-menu", "menu", 1),
        ("mode-menu", "mode-menu", "", 0),
    ),
)
def test_gemini_model_dom_selection_rejects_an_invalid_controlled_surface(
    disposable_browser: Browser,
    controls_id: str,
    surface_id: str,
    surface_role: str,
    expected_trigger_clicks: int,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        controls_attribute = f'aria-controls="{controls_id}"' if controls_id else ""
        role_attribute = f'role="{surface_role}"' if surface_role else ""
        page.set_content(
            f"""
            <button
                id="mode-picker"
                aria-label="Open mode picker, currently Flash"
                aria-haspopup="true"
                aria-expanded="false"
                {controls_attribute}
            >Flash</button>
            <div id="{surface_id}" {role_attribute} hidden>
                <button role="menuitem"><span class="label">3.1 Pro</span></button>
            </div>
            <script>
                window.triggerClicks = 0;
                document.querySelector('#mode-picker').addEventListener('click', () => {{
                    window.triggerClicks += 1;
                }});
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "gemini", "gemini-3.1-pro") is False
        assert page.evaluate("window.triggerClicks") == expected_trigger_clicks
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize("failed_close_stage", ["selection", "verification"])
def test_gemini_model_dom_selection_fails_closed_when_menu_closure_is_unproved(
    disposable_browser: Browser,
    failed_close_stage: str,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button
                id="mode-picker"
                aria-label="Open mode picker, currently Flash"
                aria-haspopup="true"
                aria-expanded="false"
                aria-controls="mode-menu"
            >Flash</button>
            <div id="mode-menu" role="menu" hidden>
                <button id="pro-option" role="menuitem">
                    <span class="label">3.1 Pro</span>
                    <span class="sublabel">Advanced reasoning</span>
                </button>
            </div>
            <script>
                const failedStage = {json.dumps(failed_close_stage)};
                let selectionMade = false;
                let verificationOpened = false;
                const trigger = document.querySelector('#mode-picker');
                const menu = document.querySelector('#mode-menu');
                const option = document.querySelector('#pro-option');
                trigger.addEventListener('click', () => {{
                    if (failedStage === 'verification' && verificationOpened && !menu.hidden) return;
                    const opening = menu.hidden;
                    menu.hidden = !opening;
                    trigger.setAttribute('aria-expanded', String(opening));
                    if (opening && selectionMade) verificationOpened = true;
                }});
                option.addEventListener('click', () => {{
                    selectionMade = true;
                    option.classList.add('selected');
                    const marker = document.createElement('span');
                    marker.setAttribute('aria-label', 'Selected');
                    marker.textContent = '✓';
                    option.prepend(marker);
                    trigger.setAttribute('aria-label', 'Open mode picker, currently Pro');
                    trigger.textContent = 'Pro';
                    if (failedStage !== 'selection') {{
                        menu.hidden = true;
                        trigger.setAttribute('aria-expanded', 'false');
                    }}
                }});
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "gemini", "gemini-3.1-pro") is False
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("platform", "model", "label"),
    (
        ("claude", "claude-auto", "Auto"),
    ),
)
def test_provider_model_dom_selection_accepts_a_semantic_model_trigger(
    disposable_browser: Browser,
    platform: str,
    model: str,
    label: str,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button
                id="model-selector"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
            >{label}</button>
            """
        )

        assert _select_web_model(page, "chromium", platform, model) is True
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("platform", "model"),
    (("grok", "grok-build"), ("claude", "claude-auto")),
)
def test_auto_model_dom_selection_rejects_an_unrelated_auto_popup(
    disposable_browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    model: str,
) -> None:
    import app.core.computer_use_agent as computer_use_agent

    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="playback-trigger"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="playback-options"
            >Auto</button>
            <div id="playback-options" role="menu" hidden>
                <button role="menuitem">Auto</button>
                <button role="menuitem">1×</button>
            </div>
            <script>
                window.unrelatedAutoClicks = 0;
                document.querySelector('#playback-trigger').addEventListener('click', () => {
                    window.unrelatedAutoClicks += 1;
                    document.querySelector('#playback-options').hidden = false;
                });
            </script>
            """
        )
        monkeypatch.setattr(computer_use_agent, "WEB_MODEL_CONTROL_WAIT_ATTEMPTS", 1)
        monkeypatch.setattr(computer_use_agent, "GROK_MODEL_CONTROL_WAIT_ATTEMPTS", 1)

        assert _select_web_model(page, "chromium", platform, model) is False
        assert page.evaluate("window.unrelatedAutoClicks") == 0
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("platform", "model", "decoy_id"),
    (
        ("grok", "grok-build", "modern-theme"),
        ("grok", "grok-build", "breakfast-options"),
        ("claude", "claude-auto", "modern-theme"),
        ("claude", "claude-auto", "octopus-picker"),
    ),
)
def test_auto_model_dom_selection_rejects_metadata_substring_decoys(
    disposable_browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    model: str,
    decoy_id: str,
) -> None:
    import app.core.computer_use_agent as computer_use_agent

    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button
                id="{decoy_id}"
                aria-haspopup="menu"
                aria-expanded="false"
            >Auto</button>
            """
        )
        monkeypatch.setattr(computer_use_agent, "WEB_MODEL_CONTROL_WAIT_ATTEMPTS", 1)
        monkeypatch.setattr(computer_use_agent, "GROK_MODEL_CONTROL_WAIT_ATTEMPTS", 1)

        assert _select_web_model(page, "chromium", platform, model) is False
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("platform", "model", "decoy_id", "decoy_label"),
    (
        ("grok", "grok-build", "grok-options", "Modern theme"),
        ("claude", "claude-auto", "claude-options", "Octopus picker"),
    ),
)
def test_auto_model_dom_selection_rejects_label_substring_decoys(
    disposable_browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    model: str,
    decoy_id: str,
    decoy_label: str,
) -> None:
    import app.core.computer_use_agent as computer_use_agent

    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button
                id="{decoy_id}"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="decoy-options"
            >{decoy_label}</button>
            <div id="decoy-options" role="menu" hidden>
                <button id="decoy-auto" role="menuitem">Auto</button>
            </div>
            <script>
                window.decoyClicks = 0;
                const trigger = document.querySelector('#{decoy_id}');
                trigger.addEventListener('click', () => {{
                    window.decoyClicks += 1;
                    document.querySelector('#decoy-options').hidden = false;
                }});
                document.querySelector('#decoy-auto').addEventListener('click', () => {{
                    trigger.textContent = 'Auto';
                }});
            </script>
            """
        )
        monkeypatch.setattr(computer_use_agent, "WEB_MODEL_CONTROL_WAIT_ATTEMPTS", 1)
        monkeypatch.setattr(computer_use_agent, "GROK_MODEL_CONTROL_WAIT_ATTEMPTS", 1)

        assert _select_web_model(page, "chromium", platform, model) is False
        assert page.evaluate("window.decoyClicks") == 0
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("aria_checked", "data_state", "trigger_label", "expected", "reason"),
    (
        ("true", "checked", "Build Beta", True, ""),
        ("true", "unchecked", "Build Beta", False, "model-selection-proof-conflict"),
        ("false", "checked", "Build Beta", False, "model-selection-proof-conflict"),
        ("true", "checked", "Auto", False, "model-readback-mismatch"),
        ("false", "unchecked", "Auto", False, "model-readback-mismatch"),
    ),
)
def test_grok_model_dom_selection_requires_current_radix_contract_and_dual_proof(
    disposable_browser: Browser,
    aria_checked: str,
    data_state: str,
    trigger_label: str,
    expected: bool,
    reason: str,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button id="bare-build">Build</button>
            <button id="build-plan" aria-label="SuperGrok Build plan">Build</button>
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-surface"
            >Auto</button>
            <div id="model-surface" role="menu" hidden>
                <button
                    id="build-option"
                    role="menuitemradio"
                    aria-label="Build"
                    aria-checked="false"
                    data-state="unchecked"
                >Build</button>
            </div>
            <script>
                window.selectionAudit = {{
                    bareBuildClicks: 0,
                    buildPlanClicks: 0,
                    optionClicks: 0,
                }};
                const trigger = document.querySelector('#model-select-trigger');
                const surface = document.querySelector('#model-surface');
                const option = document.querySelector('#build-option');
                document.querySelector('#bare-build').addEventListener('click', () => {{
                    window.selectionAudit.bareBuildClicks += 1;
                }});
                document.querySelector('#build-plan').addEventListener('click', () => {{
                    window.selectionAudit.buildPlanClicks += 1;
                }});
                trigger.addEventListener('click', () => {{
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    surface.hidden = !opening;
                }});
                option.addEventListener('click', () => {{
                    window.selectionAudit.optionClicks += 1;
                    surface.hidden = true;
                    trigger.setAttribute('aria-expanded', 'false');
                    option.setAttribute('aria-checked', {json.dumps(aria_checked)});
                    option.setAttribute('data-state', {json.dumps(data_state)});
                    trigger.textContent = {json.dumps(trigger_label)};
                }});
            </script>
            """
        )
        observation: dict[str, object] = {}
        assert (
            _select_web_model(
                page,
                "chromium",
                "grok",
                "grok-build",
                observation,
            )
            is expected
        )
        assert page.evaluate("window.selectionAudit") == {
            "bareBuildClicks": 0,
            "buildPlanClicks": 0,
            "optionClicks": 1,
        }
        if reason:
            assert observation["reason"] == reason
        assert page.get_attribute("#model-select-trigger", "aria-expanded") == "false"
        assert page.locator("#model-surface").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
def test_grok_build_selection_accepts_nested_controlled_menu_and_exact_aria_label(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
            <div id="model-menu" role="menu" hidden>
                <div class="nested-options">
                    <button
                        id="build-plan"
                        role="menuitemradio"
                        aria-label="SuperGrok Build plan"
                        aria-checked="false"
                        data-state="unchecked"
                    >
                        <span class="label">Build</span>
                        <small>Upgrade your SuperGrok plan</small>
                    </button>
                    <button
                        id="build-option"
                        role="menuitemradio"
                        aria-label="Build"
                        aria-checked="false"
                        data-state="unchecked"
                    >
                        <span class="label">Build</span>
                        <small>Use Build mode for agentic tasks</small>
                    </button>
                </div>
            </div>
            <script>
                window.selectionAudit = {planClicks: 0, optionClicks: 0};
                const trigger = document.querySelector('#model-select-trigger');
                const menu = document.querySelector('#model-menu');
                const option = document.querySelector('#build-option');
                trigger.addEventListener('click', () => {
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    menu.hidden = !opening;
                });
                document.querySelector('#build-plan').addEventListener('click', () => {
                    window.selectionAudit.planClicks += 1;
                });
                option.addEventListener('click', () => {
                    window.selectionAudit.optionClicks += 1;
                    option.setAttribute('aria-checked', 'true');
                    option.setAttribute('data-state', 'checked');
                    trigger.textContent = 'Build Beta';
                    trigger.setAttribute('aria-expanded', 'false');
                    menu.hidden = true;
                });
            </script>
            """
        )

        selected = _select_web_model(
            page,
            "chromium",
            "grok",
            "grok-build",
        )

        assert selected is True
        assert page.evaluate("window.selectionAudit") == {
            "planClicks": 0,
            "optionClicks": 1,
        }
    finally:
        context.close()


@pytest.mark.integration
def test_grok_build_selection_accepts_an_already_selected_option(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Build Beta</button>
            <div id="model-menu" role="menu" hidden>
                <button
                    id="build-option"
                    role="menuitemradio"
                    aria-label="Build"
                    aria-checked="true"
                    data-state="checked"
                >Build</button>
            </div>
            <script>
                window.optionClicks = 0;
                const trigger = document.querySelector('#model-select-trigger');
                const menu = document.querySelector('#model-menu');
                trigger.addEventListener('click', () => {
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    menu.hidden = !opening;
                });
                document.querySelector('#build-option').addEventListener('click', () => {
                    window.optionClicks += 1;
                });
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "grok", "grok-build") is True
        assert page.evaluate("window.optionClicks") == 0
        assert page.get_attribute("#model-select-trigger", "aria-expanded") == "false"
        assert page.locator("#model-menu").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
def test_grok_build_selection_dismisses_only_the_two_known_onboarding_dialogs(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
            <div id="model-menu" role="menu" hidden>
                <button
                    id="build-option"
                    role="menuitemradio"
                    aria-label="Build"
                    aria-checked="false"
                    data-state="unchecked"
                >Build</button>
            </div>
            <div id="first-promo" role="dialog" aria-label="Meet Grok Bot">
                <button id="first-dismiss">Dismiss</button>
            </div>
            <script>
                window.selectionAudit = {
                    dismissClicks: 0,
                    optionClicks: 0,
                    triggerClicks: 0,
                    untrustedClicks: 0,
                };
                const trigger = document.querySelector('#model-select-trigger');
                const menu = document.querySelector('#model-menu');
                const option = document.querySelector('#build-option');
                trigger.addEventListener('click', (event) => {
                    window.selectionAudit.triggerClicks += 1;
                    if (!event.isTrusted) window.selectionAudit.untrustedClicks += 1;
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    menu.hidden = !opening;
                });
                document.querySelector('#first-dismiss').addEventListener('click', (event) => {
                    window.selectionAudit.dismissClicks += 1;
                    if (!event.isTrusted) window.selectionAudit.untrustedClicks += 1;
                    document.querySelector('#first-promo').remove();
                    document.body.insertAdjacentHTML(
                        'beforeend',
                        '<div id="second-promo" role="dialog" aria-label="Introducing Build Mode">'
                            + '<button id="second-dismiss">Dismiss</button></div>'
                    );
                    document.querySelector('#second-dismiss').addEventListener('click', (event) => {
                        window.selectionAudit.dismissClicks += 1;
                        if (!event.isTrusted) window.selectionAudit.untrustedClicks += 1;
                        document.querySelector('#second-promo').remove();
                    });
                });
                option.addEventListener('click', (event) => {
                    window.selectionAudit.optionClicks += 1;
                    if (!event.isTrusted) window.selectionAudit.untrustedClicks += 1;
                    option.setAttribute('aria-checked', 'true');
                    option.setAttribute('data-state', 'checked');
                    trigger.textContent = 'Build Beta';
                    trigger.setAttribute('aria-expanded', 'false');
                    menu.hidden = true;
                });
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "grok", "grok-build") is True
        assert page.evaluate("window.selectionAudit") == {
            "dismissClicks": 2,
            "optionClicks": 1,
            "triggerClicks": 3,
            "untrustedClicks": 0,
        }
        assert page.locator('[role="dialog"]').count() == 0
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("dialog_role", "aria_modal", "dialog_label", "dismiss_disabled"),
    (
        ("dialog", "false", "Upgrade to SuperGrok", False),
        ("dialog", "false", "Meet Grok Bot", True),
        ("alertdialog", "false", "Upgrade to SuperGrok", False),
        ("none", "true", "Upgrade to SuperGrok", False),
    ),
)
def test_grok_build_selection_rejects_unknown_or_non_actionable_dialogs(
    disposable_browser: Browser,
    dialog_role: str,
    aria_modal: str,
    dialog_label: str,
    dismiss_disabled: bool,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        disabled = "disabled" if dismiss_disabled else ""
        page.set_content(
            f"""
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
            <div id="model-menu" role="menu" hidden>
                <button
                    id="build-option"
                    role="menuitemradio"
                    aria-label="Build"
                    aria-checked="false"
                    data-state="unchecked"
                >Build</button>
            </div>
            <div role="{dialog_role}" aria-modal="{aria_modal}" aria-label="{dialog_label}">
                <button id="dismiss" {disabled}>Dismiss</button>
            </div>
            <script>
                window.selectionAudit = {{dismissClicks: 0, triggerClicks: 0}};
                document.querySelector('#dismiss').addEventListener('click', () => {{
                    window.selectionAudit.dismissClicks += 1;
                }});
                document.querySelector('#model-select-trigger').addEventListener('click', () => {{
                    window.selectionAudit.triggerClicks += 1;
                }});
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "grok", "grok-build") is False
        assert page.evaluate("window.selectionAudit") == {
            "dismissClicks": 0,
            "triggerClicks": 0,
        }
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("auto_aria_checked", "auto_data_state", "expected_option_clicks"),
    (("true", "unchecked", 0), ("true", "checked", 1)),
)
def test_grok_build_selection_rejects_conflicting_or_duplicate_radio_proof(
    disposable_browser: Browser,
    auto_aria_checked: str,
    auto_data_state: str,
    expected_option_clicks: int,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            f"""
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
            <div id="model-menu" role="menu" hidden>
                <button
                    id="auto-option"
                    role="menuitemradio"
                    aria-label="Auto"
                    aria-checked="{auto_aria_checked}"
                    data-state="{auto_data_state}"
                >Auto</button>
                <button
                    id="build-option"
                    role="menuitemradio"
                    aria-label="Build"
                    aria-checked="false"
                    data-state="unchecked"
                >Build</button>
            </div>
            <script>
                window.optionClicks = 0;
                const trigger = document.querySelector('#model-select-trigger');
                const menu = document.querySelector('#model-menu');
                const build = document.querySelector('#build-option');
                trigger.addEventListener('click', () => {{
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    menu.hidden = !opening;
                }});
                build.addEventListener('click', () => {{
                    window.optionClicks += 1;
                    build.setAttribute('aria-checked', 'true');
                    build.setAttribute('data-state', 'checked');
                    trigger.textContent = 'Build Beta';
                    trigger.setAttribute('aria-expanded', 'false');
                    menu.hidden = true;
                }});
            </script>
            """
        )
        observation: dict[str, object] = {}

        assert (
            _select_web_model(
                page,
                "chromium",
                "grok",
                "grok-build",
                observation,
            )
            is False
        )
        assert observation["reason"] == "model-selection-proof-conflict"
        assert page.evaluate("window.optionClicks") == expected_option_clicks
        assert page.get_attribute("#model-select-trigger", "aria-expanded") == "false"
        assert page.locator("#model-menu").is_hidden()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("variant", "expected_reason"),
    (
        ("duplicate-trigger", "model-control-ambiguous"),
        ("duplicate-surface", "model-surface-ambiguous"),
        ("duplicate-choice", "model-option-ambiguous"),
        ("unrelated-menu", "model-surface-not-found"),
    ),
)
def test_grok_build_selection_binds_exactly_one_controlled_menu_and_choice(
    disposable_browser: Browser,
    variant: str,
    expected_reason: str,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        trigger = """
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
        """
        if variant == "duplicate-trigger":
            trigger += trigger
        choice = """
            <button
                class="build-option"
                role="menuitemradio"
                aria-label="Build"
                aria-checked="false"
                data-state="unchecked"
            >Build</button>
        """
        surface_role = "listbox" if variant == "unrelated-menu" else "menu"
        surface_choices = "" if variant == "unrelated-menu" else choice
        if variant == "duplicate-choice":
            surface_choices += choice
        surface = f"""
            <div id="model-menu" role="{surface_role}" hidden>{surface_choices}</div>
        """
        if variant == "duplicate-surface":
            surface += surface
        unrelated = (
            f'<div id="unrelated-menu" role="menu">{choice}</div>'
            if variant == "unrelated-menu"
            else ""
        )
        page.set_content(
            f"""
            {trigger}
            {surface}
            {unrelated}
            <script>
                window.selectionAudit = {{triggerClicks: 0, choiceClicks: 0}};
                document.querySelectorAll('#model-select-trigger').forEach((button) => {{
                    button.addEventListener('click', () => {{
                        window.selectionAudit.triggerClicks += 1;
                        const opening = button.getAttribute('aria-expanded') !== 'true';
                        button.setAttribute('aria-expanded', String(opening));
                        document.querySelectorAll('[id="model-menu"]').forEach((menu) => {{
                            menu.hidden = !opening;
                        }});
                    }});
                }});
                document.querySelectorAll('.build-option').forEach((button) => {{
                    button.addEventListener('click', () => {{
                        window.selectionAudit.choiceClicks += 1;
                    }});
                }});
            </script>
            """
        )
        observation: dict[str, object] = {}

        assert (
            _select_web_model(
                page,
                "chromium",
                "grok",
                "grok-build",
                observation,
            )
            is False
        )
        assert observation["reason"] == expected_reason
        assert page.evaluate("window.selectionAudit.choiceClicks") == 0
    finally:
        context.close()


@pytest.mark.integration
def test_grok_build_selection_rebinds_a_remounted_radix_menu(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
            <script>
                window.selectionAudit = {
                    menuMounts: 0,
                    optionClicks: 0,
                    triggerClicks: 0,
                    selected: false,
                };
                const trigger = document.querySelector('#model-select-trigger');
                const unmount = () => document.querySelector('#model-menu')?.remove();
                const mount = () => {
                    unmount();
                    window.selectionAudit.menuMounts += 1;
                    const menu = document.createElement('div');
                    menu.id = 'model-menu';
                    menu.setAttribute('role', 'menu');
                    const option = document.createElement('button');
                    option.setAttribute('role', 'menuitemradio');
                    option.setAttribute('aria-label', 'Build');
                    option.setAttribute(
                        'aria-checked',
                        String(window.selectionAudit.selected)
                    );
                    option.setAttribute(
                        'data-state',
                        window.selectionAudit.selected ? 'checked' : 'unchecked'
                    );
                    option.textContent = 'Build';
                    option.addEventListener('click', () => {
                        window.selectionAudit.optionClicks += 1;
                        window.selectionAudit.selected = true;
                        trigger.textContent = 'Build Beta';
                        trigger.setAttribute('aria-expanded', 'false');
                        unmount();
                    });
                    menu.append(option);
                    document.body.append(menu);
                };
                trigger.addEventListener('click', () => {
                    window.selectionAudit.triggerClicks += 1;
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    if (opening) mount();
                    else unmount();
                });
            </script>
            """
        )

        assert _select_web_model(page, "chromium", "grok", "grok-build") is True
        assert page.evaluate("window.selectionAudit") == {
            "menuMounts": 2,
            "optionClicks": 1,
            "triggerClicks": 3,
            "selected": True,
        }
        assert page.locator("#model-menu").count() == 0
        assert page.get_attribute("#model-select-trigger", "aria-expanded") == "false"
    finally:
        context.close()


@pytest.mark.integration
def test_grok_build_selection_fails_before_an_extra_click_on_a_late_paywall(
    disposable_browser: Browser,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(
            """
            <button
                id="model-select-trigger"
                aria-label="Model select"
                aria-haspopup="menu"
                aria-expanded="false"
                aria-controls="model-menu"
            >Auto</button>
            <div id="model-menu" role="menu" hidden>
                <button
                    id="build-option"
                    role="menuitemradio"
                    aria-label="Build"
                    aria-checked="false"
                    data-state="unchecked"
                >Build</button>
            </div>
            <script>
                window.selectionAudit = {triggerClicks: 0, optionClicks: 0};
                const trigger = document.querySelector('#model-select-trigger');
                const menu = document.querySelector('#model-menu');
                const option = document.querySelector('#build-option');
                trigger.addEventListener('click', () => {
                    window.selectionAudit.triggerClicks += 1;
                    const opening = trigger.getAttribute('aria-expanded') !== 'true';
                    trigger.setAttribute('aria-expanded', String(opening));
                    menu.hidden = !opening;
                });
                option.addEventListener('click', () => {
                    window.selectionAudit.optionClicks += 1;
                    option.setAttribute('aria-checked', 'true');
                    option.setAttribute('data-state', 'checked');
                    trigger.textContent = 'Build Beta';
                    trigger.setAttribute('aria-expanded', 'false');
                    menu.hidden = true;
                    document.body.insertAdjacentHTML(
                        'beforeend',
                        '<div role="alertdialog" aria-modal="true" '
                            + 'aria-label="Upgrade to SuperGrok">Upgrade</div>'
                    );
                });
            </script>
            """
        )
        observation: dict[str, object] = {}

        assert (
            _select_web_model(
                page,
                "chromium",
                "grok",
                "grok-build",
                observation,
            )
            is False
        )
        assert observation["reason"] == "blocking-dialog"
        assert page.evaluate("window.selectionAudit") == {
            "triggerClicks": 1,
            "optionClicks": 1,
        }
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("platform", "body"),
    (
        (
            "gemini",
            """
            <user-query><div data-test-id="user-query-content">prompt</div></user-query>
            <model-response>
                <message-content>
                    <div class="model-response-text"><pre><code>{"action":"bodycheck"}</code></pre></div>
                </message-content>
                <div class="response-actions"><button>Copy</button></div>
            </model-response>
            <rich-textarea>
                <div contenteditable="true" aria-label="Enter a prompt"></div>
            </rich-textarea>
            """,
        ),
        (
            "grok",
            """
            <article data-role="user">prompt</article>
            <article data-testid="assistant-message">
                <div data-testid="response-content"><pre><code>{"action":"bodycheck"}</code></pre></div>
                <div data-testid="response-actions"><button>Copy</button></div>
            </article>
            <div data-testid="user-composer"><textarea aria-label="Ask Grok"></textarea></div>
            """,
        ),
    ),
)
def test_provider_turn_snapshot_uses_canonical_outer_turn_roots(
    disposable_browser: Browser,
    platform: str,
    body: str,
) -> None:
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(body)

        snapshot = _provider_turn_snapshot(page, platform)

        assert snapshot["count"] == 1
        assert snapshot["userCount"] == 1
        assert snapshot["latestUserText"] == "prompt"
        assert snapshot["assistantAfterLatestUser"] is True
        assert snapshot["text"].startswith("```json\n")
        assert parse_agent_action(snapshot["text"])["action"] == "bodycheck"
        assert "Copy" not in snapshot["text"]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize("platform", ["gemini", "grok"])
def test_provider_turn_snapshot_rejects_assistant_before_latest_user(
    disposable_browser: Browser,
    platform: str,
) -> None:
    assistant = (
        '<model-response><pre><code>{"action":"final","summary":"stale"}</code></pre></model-response>'
        if platform == "gemini"
        else '<article data-testid="assistant-message"><pre><code>{"action":"final","summary":"stale"}</code></pre></article>'
    )
    user = (
        "<user-query>new prompt</user-query>"
        if platform == "gemini"
        else '<article data-role="user">new prompt</article>'
    )
    composer = (
        '<rich-textarea><div contenteditable="true" aria-label="Enter a prompt"></div></rich-textarea>'
        if platform == "gemini"
        else '<textarea aria-label="Ask Grok"></textarea>'
    )
    context = disposable_browser.new_context()
    page = context.new_page()
    try:
        page.set_content(f"{assistant}{user}{composer}")

        snapshot = _provider_turn_snapshot(page, platform)

        assert snapshot["assistantAfterLatestUser"] is False
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("receipt_case", "expects_receipt"),
    [
        pytest.param("composer", False, id="marker-only-in-composer"),
        pytest.param("assistant", False, id="marker-only-in-assistant-message"),
        pytest.param("stale-user", False, id="marker-only-in-earlier-user-message"),
        pytest.param("latest-user", True, id="marker-in-latest-visible-user-message"),
    ],
)
def test_grok_submission_receipt_requires_marker_in_latest_visible_user_message(
    disposable_browser: Browser,
    receipt_case: str,
    expects_receipt: bool,
) -> None:
    marker = "agent-transfer-e2e-receipt-marker"
    bodies = {
        "composer": (
            f'<div data-testid="user-composer" contenteditable="true">{marker}</div>'
        ),
        "assistant": (
            f'<article data-message-author-role="assistant">{marker}</article>'
        ),
        "stale-user": (
            f'<article data-role="user">Earlier prompt {marker}</article>'
            '<article data-role="user">Latest prompt without a receipt</article>'
        ),
        "latest-user": (
            '<article data-role="user">Earlier prompt without a receipt</article>'
            f'<article data-role="user">Latest prompt {marker}</article>'
            '<article data-role="user" hidden>Hidden later prompt without a receipt</article>'
        ),
    }
    conversation_url = "https://grok.com/c/receipt-contract-e2e"
    context = disposable_browser.new_context()
    page = context.new_page()
    page.route(
        conversation_url,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body=f"<!doctype html><html><body>{bodies[receipt_case]}</body></html>",
        ),
    )
    try:
        page.goto(conversation_url, wait_until="domcontentloaded")
        binding = _ProviderSessionBinding(
            page,
            "grok",
            conversation_url,
            "recent",
        )
        binding.submission_marker = marker

        receipt_url = binding._current_submission_receipt_url()

        assert receipt_url == (conversation_url if expects_receipt else "")
    finally:
        context.close()


@pytest.mark.integration
def test_fresh_grok_send_atomically_rejects_an_old_conversation_target(
    disposable_browser: Browser,
) -> None:
    actual_url = "https://grok.com/c/old"
    expected_url = "https://grok.com/"
    context = disposable_browser.new_context()
    page = context.new_page()
    page.route(
        actual_url,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="""
                <!doctype html>
                <html>
                    <body>
                        <form>
                            <textarea aria-label="Ask Grok"></textarea>
                            <button id="send" type="button" aria-label="Send">Send</button>
                        </form>
                        <script>
                            window.sendClickAudit = 0;
                            document.querySelector('#send').addEventListener('click', () => {
                                window.sendClickAudit += 1;
                            });
                        </script>
                    </body>
                </html>
            """,
        ),
    )
    try:
        page.goto(actual_url, wait_until="domcontentloaded")

        with pytest.raises(RuntimeError, match="selected provider tab changed"):
            _submit_chromium_web_prompt(
                page,
                "grok",
                "Start a fresh agentic task",
                lambda: False,
                expected_target_url=expected_url,
                session_mode="new",
            )

        assert page.url == actual_url
        assert page.evaluate("window.sendClickAudit") == 0
    finally:
        context.close()


@pytest.mark.integration
def test_fresh_grok_send_accepts_the_expected_root_landing(
    disposable_browser: Browser,
) -> None:
    landing_url = "https://grok.com/"
    prompt = "Start a fresh agentic task"
    context = disposable_browser.new_context()
    page = context.new_page()
    page.route(
        landing_url,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="""
                <!doctype html>
                <html>
                    <body>
                        <form>
                            <textarea aria-label="Ask Grok"></textarea>
                            <button id="send" type="button" aria-label="Send">Send</button>
                        </form>
                        <script>
                            window.sendClickAudit = 0;
                            const composer = document.querySelector('textarea');
                            document.querySelector('#send').addEventListener('click', () => {
                                window.sendClickAudit += 1;
                                const userMessage = document.createElement('article');
                                userMessage.setAttribute('data-role', 'user');
                                userMessage.textContent = composer.value;
                                document.body.append(userMessage);
                                composer.value = '';
                                composer.dispatchEvent(new Event('input', {bubbles: true}));
                            });
                        </script>
                    </body>
                </html>
            """,
        ),
    )
    try:
        page.goto(landing_url, wait_until="domcontentloaded")

        _submit_chromium_web_prompt(
            page,
            "grok",
            prompt,
            lambda: False,
            expected_target_url=landing_url,
            session_mode="new",
        )

        assert page.url == landing_url
        assert page.evaluate("window.sendClickAudit") == 1
        assert page.locator("textarea").input_value() == ""
        expect(page.locator('[data-role="user"]')).to_have_text(prompt)
    finally:
        context.close()


@pytest.mark.integration
def test_grok_send_uses_visible_composer_and_nearest_bounded_semantic_scope(
    disposable_browser: Browser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.computer_use_agent as computer_use_agent

    monkeypatch.setattr(computer_use_agent, "CHROMIUM_SEND_BUTTON_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(
        computer_use_agent,
        "CHROMIUM_SUBMISSION_ACCEPT_TIMEOUT_SECONDS",
        2,
    )
    landing_url = "https://grok.com/"
    prompt = "Use the visible composer"
    receipt_marker = "agent-turn-" + ("d" * 32)
    wire_prompt = f"{prompt}\n\nController turn receipt: {receipt_marker}"
    context = disposable_browser.new_context()
    page = context.new_page()
    page.route(
        landing_url,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="""
                <!doctype html>
                <html>
                    <body>
                        <button id="unrelated-send" type="button" aria-label="Send">Send</button>
                        <div role="dialog" aria-label="Feedback">
                            <textarea id="feedback-composer" aria-label="Feedback"></textarea>
                            <button id="feedback-submit" type="button">Submit</button>
                        </div>
                        <main id="composer-scope">
                            <textarea id="hidden-composer" hidden></textarea>
                            <div><section><div>
                                <div
                                    id="visible-composer"
                                    contenteditable="true"
                                    role="textbox"
                                    aria-label="Ask Grok anything"
                                ></div>
                            </div></section></div>
                            <button
                                id="provider-send"
                                type="button"
                                aria-label="Send"
                                data-testid="chat-submit"
                            >Send</button>
                        </main>
                        <script>
                            window.sendAudit = {provider: 0, unrelated: 0, feedback: 0};
                            window.injectTrailingComposerText = false;
                            const buildComposer = document.querySelector('#visible-composer');
                            const renderBuildText = (value) => {
                                buildComposer.replaceChildren(
                                    ...value.split('\\n').map((line) => {
                                        const paragraph = document.createElement('p');
                                        if (line) paragraph.textContent = line;
                                        else paragraph.append(document.createElement('br'));
                                        return paragraph;
                                    })
                                );
                            };
                            let pendingBuildText = '';
                            buildComposer.addEventListener('beforeinput', (event) => {
                                if (typeof event.data === 'string') {
                                    pendingBuildText = event.data;
                                }
                            });
                            buildComposer.addEventListener('input', () => {
                                if (!pendingBuildText) return;
                                const value = pendingBuildText;
                                pendingBuildText = '';
                                renderBuildText(value);
                                if (window.injectTrailingComposerText) {
                                    buildComposer.append(document.createTextNode(' unexpected'));
                                }
                            });
                            document.querySelector('#unrelated-send').addEventListener('click', () => {
                                window.sendAudit.unrelated += 1;
                            });
                            document.querySelector('#provider-send').addEventListener('click', () => {
                                window.sendAudit.provider += 1;
                                const composer = document.querySelector('#visible-composer');
                                const message = document.createElement('article');
                                message.setAttribute('data-role', 'user');
                                message.textContent = [...composer.children]
                                    .map((paragraph) => paragraph.textContent || '')
                                    .join('\\n');
                                document.querySelector('#composer-scope').append(message);
                                composer.replaceChildren();
                            });
                            document.querySelector('#feedback-submit').addEventListener('click', () => {
                                window.sendAudit.feedback += 1;
                            });
                        </script>
                    </body>
                </html>
            """,
        ),
    )
    try:
        page.goto(landing_url, wait_until="domcontentloaded")
        assert page.evaluate("window.sendAudit") == {
            "provider": 0,
            "unrelated": 0,
            "feedback": 0,
        }

        accepted = _submit_chromium_web_prompt(
            page,
            "grok",
            wire_prompt,
            lambda: False,
            expected_target_url=landing_url,
            session_mode="new",
            baseline_snapshot={
                "url": landing_url,
                "count": 0,
                "userCount": 0,
                "latestUserText": "",
                "text": "",
            },
            submission_receipt_marker=receipt_marker,
        )

        assert accepted is True
        assert page.evaluate("window.sendAudit") == {
            "provider": 1,
            "unrelated": 0,
            "feedback": 0,
        }
        assert page.locator("#hidden-composer").input_value() == ""
        assert page.locator("#visible-composer").inner_text() == ""
        assert page.locator("#feedback-composer").input_value() == ""
        expect(page.locator('[data-role="user"]')).to_have_text(wire_prompt)

        page.evaluate("window.injectTrailingComposerText = true")
        rejected_marker = "agent-turn-" + ("e" * 32)
        rejected_prompt = (
            "Reject an ambiguous composer"
            f"\n\nController turn receipt: {rejected_marker}"
        )
        with pytest.raises(RuntimeError, match="did not preserve"):
            _submit_chromium_web_prompt(
                page,
                "grok",
                rejected_prompt,
                lambda: False,
                expected_target_url=landing_url,
                session_mode="new",
                baseline_snapshot=_provider_turn_snapshot(page, "grok"),
                submission_receipt_marker=rejected_marker,
            )
        assert page.evaluate("window.sendAudit") == {
            "provider": 1,
            "unrelated": 0,
            "feedback": 0,
        }
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_finished_snapshot_does_not_auto_select_recent_chatgpt_session(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    captured_ask_payloads: list[dict[str, str]] = []
    source_requests: list[str] = []
    catalog_payload = _chatgpt_catalog_sessions(
        {
            "id": "qqqm-session",
            "title": "比较 QQQM 与 QQQ",
            "url": FINISHED_SNAPSHOT_URL,
            "updated_at": "2026-08-25T09:03:57Z",
        },
        {
            "id": "agentic-troubleshooting",
            "title": "Agentic Troubleshooting",
            "url": AGENTIC_TROUBLESHOOTING_URL,
            "updated_at": "2026-08-26T01:00:00Z",
        },
    )

    def fulfill_agent_status(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_browser_status(route) -> None:
        route.fulfill(
            json={
                "platform": "chatgpt",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "ChatGPT account",
                "message": "Edge is ready for ChatGPT Web.",
                "agent_sources": catalog_payload,
            }
        )

    def fulfill_preferences(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(json=catalog_payload)

    def fulfill_ask(route) -> None:
        captured_ask_payloads.append(route.request.post_data_json or {})
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_history(route) -> None:
        route.fulfill(json={"title": "", "history": []})

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
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
    page.route("**/api/agent/chatgpt-session-history**", fulfill_history)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        expect(page.locator(".agent-session-mode-combobox [data-agent-combobox-selected-label]")).to_have_text(
            "New session"
        )
        expect(page.locator("[data-agent-prompt-session-mode]")).to_have_value("new")
        expect(page.locator("[data-agent-prompt-conversation-url]")).to_have_value("")
        expect(page.locator("[data-agent-prompt-session-title]")).to_have_value("")
        expect(page.locator("#agent_conversation_link")).to_have_attribute("href", FINISHED_SNAPSHOT_URL)
        expect(
            page.locator(
                f'[data-agent-session-list="recent"] [data-agent-combobox-option="{FINISHED_SNAPSHOT_URL}"]'
            )
        ).to_have_count(1)
        page.wait_for_timeout(500)
        assert source_requests == [], (
            "An initial finished snapshot must consume bootstrapped sources without "
            "starting a second browser collection."
        )

        expect(page.locator("#agent_ask_button")).to_be_enabled()
        page.locator("[data-agent-prompt-input]").fill("Inspect the workspace without changing files.")
        with page.expect_request(re.compile(r"/api/agent/ask$")):
            page.locator("#agent_ask_button").click()
        assert captured_ask_payloads
        payload = captured_ask_payloads[0]
        assert payload["session_mode"] == "new"
        assert payload.get("conversation_url", "") == ""
        assert payload.get("session_title", "") == ""
        assert payload["prompt"] == "Inspect the workspace without changing files."

        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        page.locator('.agent-session-mode-combobox [data-agent-combobox-option="recent"]').click()
        snapshot_option = page.locator(
            f'[data-agent-session-list="recent"] [data-agent-combobox-option="{FINISHED_SNAPSHOT_URL}"]'
        )
        expect(snapshot_option).to_have_count(1)
        expect(page.locator("[data-agent-prompt-session-mode]")).to_have_value("recent")
        expect(page.locator("[data-agent-prompt-conversation-url]")).to_have_value("")
        expect(page.locator("[data-agent-recent-session-url]")).to_have_value("")
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_incomplete_chatgpt_effort_catalog_hides_stale_snapshot_options(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Incomplete browser payloads and Agent snapshots cannot add provider options."""
    agent_payload = _finished_chatgpt_agent_payload()
    agent_payload["agent"].update(
        {
            "available_efforts": ["Expired subscription tier"],
            "thinking_effort": "Expired subscription tier",
        }
    )
    incomplete_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web; live effort catalog unavailable.",
        "agent_sources_error": "Live source catalog unavailable.",
        "available_efforts": ["Stale live tier"],
        "thinking_effort": "Stale live tier",
        "effort_catalog_complete": False,
    }

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route(
        "**/api/agent/status",
        lambda route: route.fulfill(json=agent_payload),
    )
    page.route(
        "**/api/browser-session**",
        lambda route: route.fulfill(json=incomplete_status),
    )
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        expect(page.locator(".browser-session-status-account")).to_have_text("ChatGPT account")
        effort_options = page.locator(
            ".agent-effort-dropdown [data-agent-combobox-option]"
        )
        expect(effort_options).to_have_count(1)
        expect(effort_options).to_have_attribute(
            "data-agent-combobox-option",
            "highest_available",
        )
        expect(page.locator("[data-agent-effort-input]")).to_have_value(
            "highest_available"
        )
        refresh_options = page.locator("[data-agent-effort-refresh]")
        expect(refresh_options).to_be_visible()
        expect(refresh_options).to_have_text("Refresh options")
        assert [text.strip() for text in effort_options.all_text_contents()] == [
            "Highest available"
        ]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize(
    ("freshness_kind", "expect_provider_options"),
    (
        ("server_cache", True),
        ("stale_cache", True),
        ("unknown", False),
        ("live_browser", True),
    ),
)
def test_complete_chatgpt_effort_catalog_accepts_verified_browser_session_provenance(
    disposable_browser: Browser,
    sidebar_server_url: str,
    freshness_kind: str,
    expect_provider_options: bool,
) -> None:
    """Expose complete provider labels from verified browser-session provenance only."""
    agent_payload = _finished_chatgpt_agent_payload()
    agent_payload["agent"].update(
        {
            "available_efforts": ["Saved snapshot label"],
            "thinking_effort": "Saved snapshot label",
        }
    )
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": _chatgpt_catalog_sessions(),
        "available_efforts": ["Live first", "Live maximum"],
        "thinking_effort": "Live maximum",
        "effort_catalog_complete": True,
        "browser_session_freshness": {
            "kind": freshness_kind,
            "cache_status": {
                "live_browser": "refreshed",
                "server_cache": "hit",
                "stale_cache": "stale",
                "unknown": "hit",
            }[freshness_kind],
            "cached_at": "2026-08-31T00:00:00Z",
            "age_seconds": 0 if freshness_kind == "live_browser" else 30,
        },
    }
    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", lambda route: route.fulfill(json=agent_payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        effort_options = page.locator(
            ".agent-effort-dropdown [data-agent-combobox-option]"
        )
        expected_values = (
            ["highest_available", "Live first", "Live maximum"]
            if expect_provider_options
            else ["highest_available"]
        )
        expect(effort_options).to_have_count(len(expected_values))
        assert effort_options.evaluate_all(
            "options => options.map((option) => option.dataset.agentComboboxOption)"
        ) == expected_values
        assert "Saved snapshot label" not in effort_options.all_text_contents()
        if expect_provider_options:
            expect(page.locator("[data-agent-effort-field]")).to_have_attribute(
                "data-agent-effort-catalog-freshness",
                freshness_kind,
            )
            page.locator(
                ".agent-effort-combobox [data-agent-combobox-trigger]"
            ).click()
            page.locator(
                '.agent-effort-dropdown [data-agent-combobox-option="Live first"]'
            ).click()
            expect(page.locator("[data-agent-effort-input]")).to_have_value("Live first")
        else:
            assert page.locator("[data-agent-effort-field]").get_attribute(
                "data-agent-effort-catalog-freshness"
            ) is None
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_client_cached_chatgpt_effort_catalog_exposes_verified_options_until_explicit_refresh(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """A verified client cache is visible, while explicit refresh remains live-only."""
    browser_status_requests: list[str] = []
    cached_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Cached but formerly live ChatGPT status.",
        "agent_sources": _chatgpt_catalog_sessions(),
        "available_efforts": ["Old live maximum"],
        "thinking_effort": "Old live maximum",
        "effort_catalog_complete": True,
        "browser_session_freshness": {
            "kind": "live_browser",
            "cache_status": "refreshed",
            "cached_at": "2026-08-31T00:00:00Z",
            "age_seconds": 0,
        },
    }
    refreshed_status = {
        **cached_status,
        "message": "Fresh ChatGPT effort catalog.",
        "available_efforts": ["Fresh first", "Fresh maximum"],
        "thinking_effort": "Fresh maximum",
        "browser_session_freshness": {
            "kind": "live_browser",
            "cache_status": "refreshed",
            "cached_at": "2026-08-31T00:00:01Z",
            "age_seconds": 0,
        },
    }
    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="no-preference",
    )
    page = context.new_page()
    cache_key = "cachelikes:browser-session:v6:agent:chatgpt:edge"
    page.add_init_script(
        f"sessionStorage.setItem({json.dumps(cache_key)}, JSON.stringify({{"
        f"cached_at: Date.now(), payload: {json.dumps(cached_status)}}}));"
    )
    page.add_init_script(
        """(() => {
            const originalFetch = window.fetch.bind(window);
            let releaseRefresh;
            const refreshGate = new Promise(resolve => { releaseRefresh = resolve; });
            window.__releaseAgentEffortRefresh = releaseRefresh;
            window.fetch = (input, init) => {
                const requestUrl = typeof input === "string" ? input : input?.url;
                if (
                    requestUrl
                    && requestUrl.includes("/api/browser-session")
                    && requestUrl.includes("refresh=1")
                ) {
                    return originalFetch(input, init).then(async response => {
                        await refreshGate;
                        return response;
                    });
                }
                return originalFetch(input, init);
            };
        })();"""
    )
    page.route("**/api/agent/status", lambda route: route.fulfill(json=_finished_chatgpt_agent_payload()))
    def fulfill_browser_status(route) -> None:
        browser_status_requests.append(route.request.url)
        assert "refresh=1" in route.request.url
        route.fulfill(json=refreshed_status)

    page.route("**/api/browser-session**", fulfill_browser_status)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        effort_options = page.locator(
            ".agent-effort-dropdown [data-agent-combobox-option]"
        )
        expect(effort_options).to_have_count(2)
        assert effort_options.evaluate_all(
            "options => options.map((option) => option.dataset.agentComboboxOption)"
        ) == ["highest_available", "Old live maximum"]
        expect(page.locator("[data-agent-effort-field]")).to_have_attribute(
            "data-agent-effort-catalog-freshness",
            "client_cache",
        )
        assert browser_status_requests == []

        refresh = page.locator("[data-agent-effort-refresh]")
        with page.expect_request(
            lambda request: "/api/browser-session" in request.url
            and "refresh=1" in request.url,
        ):
            refresh.click()
        expect(refresh).to_have_attribute("aria-busy", "true")
        expect(refresh).to_have_class(re.compile(r"\bis-refreshing\b"))
        assert refresh.locator(".agent-effort-refresh-icon").evaluate(
            "element => getComputedStyle(element).animationName"
        ) == "agent-effort-refresh-spin"
        page.evaluate("() => window.__releaseAgentEffortRefresh()")
        expect(effort_options).to_have_count(3)
        assert effort_options.evaluate_all(
            "options => options.map((option) => option.dataset.agentComboboxOption)"
        ) == ["highest_available", "Fresh first", "Fresh maximum"]
        assert len(browser_status_requests) == 1
        assert "refresh=1" in browser_status_requests[0]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_running_chatgpt_agent_locks_model_effort_and_refresh_controls(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Prevent runtime model and effort changes while an Agent task is running."""
    agent_payload = _finished_chatgpt_agent_payload()
    agent_payload["agent"].update(
        {
            "running": True,
            "phase": "running",
            "run_id": "running-composer-lock",
            "run_revision": 1,
            "started_at": "2026-09-02T08:00:00Z",
            "finished_at": "",
            "activity": [],
        }
    )
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": _chatgpt_catalog_sessions(),
        "available_efforts": ["Live first", "Live maximum"],
        "thinking_effort": "Live maximum",
        "effort_catalog_complete": True,
        "browser_session_freshness": {
            "kind": "live_browser",
            "cache_status": "refreshed",
            "cached_at": "2026-09-02T08:00:00Z",
            "age_seconds": 0,
        },
    }
    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", lambda route: route.fulfill(json=agent_payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        model = page.locator(".agent-model-trigger")
        effort = page.locator(".agent-effort-trigger")
        refresh = page.locator("[data-agent-effort-refresh]")
        expect(model).to_be_disabled()
        expect(effort).to_be_disabled()
        expect(refresh).to_be_disabled()
        expect(model).to_have_attribute("aria-expanded", "false")
        expect(effort).to_have_attribute("aria-expanded", "false")
        expect(page.locator(".agent-model-dropdown")).to_be_hidden()
        expect(page.locator(".agent-effort-dropdown")).to_be_hidden()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_foreign_running_agent_poll_keeps_only_neutral_stop_state(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """A later global running snapshot cannot leak another project's task data."""
    foreign_workspace = "/tmp/foreign-agent-workspace"
    sentinels = (
        "FOREIGN_AGENT_PROMPT_SENTINEL",
        "FOREIGN_AGENT_RESPONSE_SENTINEL",
        "FOREIGN_AGENT_ERROR_SENTINEL",
        "FOREIGN_AGENT_ACTIVITY_SENTINEL",
        foreign_workspace,
    )
    payload = _finished_chatgpt_agent_payload()
    payload["agent"] = {
        **payload["agent"],
        "running": True,
        "paused": False,
        "phase": "running",
        "workspace_path": foreign_workspace,
        "prompt": sentinels[0],
        "response": sentinels[1],
        "response_html": f"<p>{sentinels[1]}</p>",
        "last_error": sentinels[2],
        "error_traceback": sentinels[2],
        "activity": [
            {
                "status": "running",
                "label": "Read",
                "detail": sentinels[3],
                "meta": "Turn 1",
            }
        ],
        "history": [
            {
                "prompt": sentinels[0],
                "response": sentinels[1],
                "response_html": f"<p>{sentinels[1]}</p>",
            }
        ],
        "message": "FOREIGN_AGENT_MESSAGE_SENTINEL",
        "conversation_url": "https://chatgpt.com/c/foreign-agent-sentinel",
    }
    status_requests = 0

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(json=payload)

    def fulfill_browser_status(route) -> None:
        route.fulfill(
            json={
                "platform": "chatgpt",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "ChatGPT account",
                "message": "Edge is ready for ChatGPT Web.",
            }
        )

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", fulfill_browser_status)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').some((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            )"""
        )
        assert status_requests >= 1
        expect(page.locator("#agent_ask_button")).to_have_attribute(
            "data-agent-action", "stop"
        )
        expect(page.locator("#agent_ask_button")).to_have_attribute(
            "aria-label", "Stop Agent task"
        )
        expect(page.locator("#agent_response_status")).to_have_attribute(
            "data-status", "running"
        )
        expect(page.locator("#agent_response_status")).to_contain_text(
            "An Agent task is running in another project."
        )
        expect(page.locator("#agent_response_output")).to_be_hidden()
        expect(page.locator("#agent_activity_panel")).to_be_hidden()
        expect(page.locator("#agent_error_record")).to_be_hidden()
        expect(page.locator("[data-agent-workspace-input]")).not_to_have_value(
            foreign_workspace
        )
        body_text = page.locator("body").inner_text()
        for sentinel in sentinels:
            assert sentinel not in body_text
        assert "FOREIGN_AGENT_MESSAGE_SENTINEL" not in body_text
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_response_copy_uses_raw_history_text_and_the_global_action_rail(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Copy raw answers across history pages without shifting the global action rail."""
    older_raw_response = "Older source **Markdown**\n\nKeep this exact text."
    latest_raw_response = "Latest source `payload`\n\nKeep this exact text too."
    agent_payload = _finished_chatgpt_agent_payload()
    agent_payload["agent"].update(
        {
            "prompt": "Latest prompt",
            "response": latest_raw_response,
            "response_html": "<p>Rendered latest answer only.</p>",
            "history": [
                {
                    "prompt": "Older prompt",
                    "response": older_raw_response,
                    "response_html": "<p>Rendered older answer only.</p>",
                    "started_at": "2026-08-31T00:00:00Z",
                    "finished_at": "2026-08-31T00:01:00Z",
                },
                {
                    "prompt": "Latest prompt",
                    "response": latest_raw_response,
                    "response_html": "<p>Rendered latest answer only.</p>",
                    "started_at": "2026-08-31T00:02:00Z",
                    "finished_at": "2026-08-31T00:03:00Z",
                },
            ],
        }
    )
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": _chatgpt_catalog_sessions(),
    }
    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 900},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.add_init_script(
        """
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: {
                writeText: async (value) => {
                    window.__agentResponseCopiedText = value;
                },
            },
        });
        """
    )
    page.route("**/api/agent/status", lambda route: route.fulfill(json=agent_payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        answer = page.locator("[data-agent-response-answer-content]")
        copy_button = page.locator("[data-agent-response-copy]")
        expect(answer).to_have_text("Rendered latest answer only.")
        expect(copy_button).to_be_visible()

        copy_button.click()
        page.wait_for_function(
            "expected => window.__agentResponseCopiedText === expected",
            arg=latest_raw_response,
        )
        expect(copy_button).to_have_attribute("aria-label", "Answer copied")

        page.get_by_role("button", name="Conversation page 1", exact=True).click()
        expect(answer).to_have_text("Rendered older answer only.")
        copy_button.click()
        page.wait_for_function(
            "expected => window.__agentResponseCopiedText === expected",
            arg=older_raw_response,
        )

        for width, height in ((1_280, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate(
                """() => new Promise(resolve => {
                    requestAnimationFrame(() => requestAnimationFrame(resolve));
                })"""
            )
            page.wait_for_function(
                """() => {
                    const copy = document.querySelector("[data-agent-response-copy]");
                    const theme = document.querySelector("#global_theme_toggle");
                    const answer = document.querySelector("[data-agent-response-answer]");
                    if (!(copy instanceof HTMLElement)
                        || !(theme instanceof HTMLElement)
                        || !(answer instanceof HTMLElement)) return false;
                    const copyRect = copy.getBoundingClientRect();
                    const themeRect = theme.getBoundingClientRect();
                    const answerRect = answer.getBoundingClientRect();
                    return Math.abs(copyRect.right - themeRect.right) <= 1
                        && copyRect.top >= answerRect.top
                        && copyRect.left >= answerRect.left
                        && copyRect.right <= answerRect.right + 1
                        && document.documentElement.scrollWidth <= window.innerWidth;
                }"""
            )
            rail = page.evaluate(
                """() => {
                    const copy = document.querySelector("[data-agent-response-copy]");
                    const theme = document.querySelector("#global_theme_toggle");
                    const answer = document.querySelector("[data-agent-response-answer]");
                    if (!(copy instanceof HTMLElement)
                        || !(theme instanceof HTMLElement)
                        || !(answer instanceof HTMLElement)) return null;
                    const copyRect = copy.getBoundingClientRect();
                    const themeRect = theme.getBoundingClientRect();
                    const answerRect = answer.getBoundingClientRect();
                    return {
                        answer: {left: answerRect.left, right: answerRect.right, top: answerRect.top},
                        copy: {left: copyRect.left, right: copyRect.right, top: copyRect.top},
                        theme: {right: themeRect.right},
                        hasHorizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
                    };
                }"""
            )
            assert rail is not None
            assert abs(rail["copy"]["right"] - rail["theme"]["right"]) <= 1, (width, rail)
            assert rail["copy"]["top"] >= rail["answer"]["top"]
            assert rail["copy"]["left"] >= rail["answer"]["left"]
            assert rail["copy"]["right"] <= rail["answer"]["right"] + 1
            assert not rail["hasHorizontalOverflow"]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_response_action_rail_survives_a_short_crowded_viewport(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep Safari, question expansion, and copy actions separated in a short view."""
    payload = _finished_chatgpt_agent_payload()
    payload["agent"].update(
        {
            "prompt": "请检查这个项目使用了哪些机器学习算法？" * 18,
            "response": "回答内容。" * 160,
            "response_html": f"<p>{'回答内容。' * 160}</p>",
        }
    )
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": _chatgpt_catalog_sessions(),
    }
    context = disposable_browser.new_context(
        viewport={"width": 390, "height": 400},
        has_touch=True,
        is_mobile=True,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", lambda route: route.fulfill(json=payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        question_toggle = page.locator(
            ".agent-response-question-header .agent-response-overflow-toggle"
        )
        answer_toggle = page.locator(
            "#agent_response_answer .agent-response-overflow-toggle"
        )
        expect(question_toggle).to_be_visible()
        expect(answer_toggle).to_be_visible()
        expect(page.locator("[data-agent-open-conversation]")).to_be_visible()
        expect(page.locator("[data-agent-response-copy]")).to_be_visible()

        layout = page.evaluate(
            """() => {
                const selector = {
                    toolbar: '.agent-response-toolbar',
                    header: '#agent_response_question_header',
                    question: '[data-agent-response-question]',
                    safari: '[data-agent-open-conversation]',
                    expand: '.agent-response-question-header .agent-response-overflow-toggle',
                    copy: '[data-agent-response-copy]',
                    answerExpand: '#agent_response_answer .agent-response-overflow-toggle',
                    theme: '#global_theme_toggle',
                    };
                const rect = value => {
                    const element = document.querySelector(value);
                    if (!(element instanceof HTMLElement)) return null;
                    const box = element.getBoundingClientRect();
                    return {left: box.left, right: box.right, top: box.top, bottom: box.bottom, height: box.height};
                };
                const boxes = Object.fromEntries(
                    Object.entries(selector).map(([key, value]) => [key, rect(value)]),
                );
                const overlap = (left, right) => left && right
                    && left.left < right.right
                    && left.right > right.left
                    && left.top < right.bottom
                    && left.bottom > right.top;
                return {
                    boxes,
                    headerClientHeight: document.querySelector('#agent_response_question_header')?.clientHeight,
                    questionLineHeight: Number.parseFloat(getComputedStyle(
                        document.querySelector('[data-agent-response-question]'),
                    ).lineHeight),
                    overlaps: {
                        safariExpand: overlap(boxes.safari, boxes.expand),
                        expandCopy: overlap(boxes.expand, boxes.copy),
                        answerExpandCopy: overlap(boxes.answerExpand, boxes.copy),
                        questionExpand: overlap(boxes.question, boxes.expand),
                    },
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) - document.documentElement.clientWidth,
                };
            }"""
        )
        assert layout["headerClientHeight"] >= 36
        assert layout["headerClientHeight"] >= layout["questionLineHeight"]
        assert layout["boxes"]["toolbar"]["height"] >= layout["boxes"]["safari"]["height"]
        assert not any(layout["overlaps"].values()), layout
        assert layout["boxes"]["safari"]["right"] == pytest.approx(
            layout["boxes"]["expand"]["right"], abs=1
        )
        assert layout["boxes"]["expand"]["right"] == pytest.approx(
            layout["boxes"]["copy"]["right"], abs=1
        )
        for action in ("safari", "expand", "copy", "answerExpand"):
            assert layout["boxes"][action]["right"] == pytest.approx(
                layout["boxes"]["theme"]["right"], abs=1
            ), layout
        assert layout["horizontalOverflow"] <= 1

        page.set_viewport_size({"width": 1_159, "height": 863})
        page.evaluate(
            """() => new Promise(resolve => {
                requestAnimationFrame(() => requestAnimationFrame(resolve));
            })"""
        )
        desktop_rail = page.evaluate(
            """() => {
                const selectors = {
                    theme: '#global_theme_toggle',
                    safari: '[data-agent-open-conversation]',
                    expand: '.agent-response-question-header .agent-response-overflow-toggle',
                    copy: '[data-agent-response-copy]',
                    answerExpand: '#agent_response_answer .agent-response-overflow-toggle',
                };
                const rect = selector => {
                    const element = document.querySelector(selector);
                    if (!(element instanceof HTMLElement)) return null;
                    const box = element.getBoundingClientRect();
                    return {right: box.right, top: box.top, bottom: box.bottom};
                };
                return Object.fromEntries(
                    Object.entries(selectors).map(([key, selector]) => [key, rect(selector)]),
                );
            }"""
        )
        assert all(desktop_rail[key] is not None for key in ("theme", "safari", "expand", "copy"))
        for action in ("safari", "expand", "copy"):
            assert desktop_rail[action]["right"] == pytest.approx(
                desktop_rail["theme"]["right"], abs=1
            ), desktop_rail
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_response_scroll_stays_at_the_bottom_during_status_refresh(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep a user's bottom position when a refreshed answer grows in place."""
    initial_lines = "\n".join(f"Response line {line}" for line in range(1, 161))
    updated_lines = f"{initial_lines}\nResponse line 161"
    initial_payload = _finished_chatgpt_agent_payload()
    initial_payload["agent"].update(
        {
            "prompt": "Keep the answer scroll position stable.",
            "response": initial_lines,
            "response_html": f"<pre>{initial_lines}</pre>",
        }
    )
    updated_payload = _finished_chatgpt_agent_payload()
    updated_payload["agent"].update(
        {
            "prompt": "Keep the answer scroll position stable.",
            "response": updated_lines,
            "response_html": f"<pre>{updated_lines}</pre>",
        }
    )
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": _chatgpt_catalog_sessions(),
    }
    status_requests = 0

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(json=initial_payload if status_requests == 1 else updated_payload)

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        answer_content = page.locator("[data-agent-response-answer-content]")
        page.wait_for_function(
            """() => {
                const answer = document.querySelector('[data-agent-response-answer]');
                return answer && answer.scrollHeight > answer.clientHeight + 100;
            }"""
        )
        page.evaluate(
            """() => {
                const answer = document.querySelector('[data-agent-response-answer]');
                answer.scrollTop = answer.scrollHeight;
            }"""
        )
        expect(answer_content).to_contain_text("Response line 160")
        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 2"""
        )
        expect(answer_content).to_contain_text("Response line 161")
        scroll_state = page.evaluate(
            """() => {
                const answer = document.querySelector('[data-agent-response-answer]');
                const style = getComputedStyle(answer);
                return {
                    atBottom: answer.scrollHeight - answer.clientHeight - answer.scrollTop <= 1,
                    overflowAnchor: style.overflowAnchor,
                    scrollTop: answer.scrollTop,
                    scrollHeight: answer.scrollHeight,
                    clientHeight: answer.clientHeight,
                };
            }"""
        )
        assert scroll_state["atBottom"]
        assert scroll_state["scrollTop"] > 0
        assert scroll_state["overflowAnchor"] == "none"
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_browser_status_retries_a_fresh_negative_cache_and_force_refreshes(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    browser_status_requests: list[str] = []
    negative_status = {
        "platform": "gemini",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": False,
        "can_download": False,
        "account_name": "",
        "message": "Edge is not signed in to Gemini.",
    }
    ready_status = {
        **negative_status,
        "logged_in": True,
        "can_download": True,
        "account_name": "Gemini account",
        "message": "Edge verified an authenticated Gemini Web session.",
    }

    def fulfill_browser_status(route) -> None:
        browser_status_requests.append(route.request.url)
        route.fulfill(json=ready_status)

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    cache_key = "cachelikes:browser-session:v6:agent:gemini:edge"
    page.add_init_script(
        f"sessionStorage.setItem({json.dumps(cache_key)}, JSON.stringify({{"
        f"cached_at: Date.now(), payload: {json.dumps(negative_status)}}}));"
    )
    page.route(
        "**/api/agent/status",
        lambda route: route.fulfill(json=_finished_chatgpt_agent_payload()),
    )
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route(
        "**/api/agent/sources**",
        lambda route: route.fulfill(
            json={
                "platform": "gemini",
                "browser_label": "Edge",
                "recent_sessions": [],
                "projects": [],
                "limit": 20,
            }
        ),
    )
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/gemini", wait_until="domcontentloaded")
        expect(page.locator(".agent-readiness")).to_have_count(0)
        expect(page.locator("#agent_ask_button")).to_be_enabled()
        assert len(browser_status_requests) == 1

        page.evaluate(
            """async () => {
                const root = document.querySelector('[data-agent-browser-session]');
                const controller = window.CACHELIKES_BROWSER_SESSION_STATUS.init(root, {
                    platform: 'gemini',
                    browserId: 'edge',
                    scope: 'agent',
                });
                await controller.refresh();
            }"""
        )
        assert len(browser_status_requests) == 2
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_status_stays_objective_while_browser_verification_is_pending(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Show a neutral checking state until the browser probe has completed."""
    pending_payload = _finished_chatgpt_agent_payload()
    pending_payload["agent"] = {
        **pending_payload["agent"],
        "phase": "",
        "message": "",
        "response": "",
        "response_html": "",
        "conversation_url": "",
        "started_at": "",
        "finished_at": "",
    }
    browser_status_requests: list[str] = []

    def hold_browser_status(route) -> None:
        browser_status_requests.append(route.request.url)
        # Keep the probe unresolved so the page remains in its verification state.

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", lambda route: route.fulfill(json=pending_payload))
    page.route("**/api/browser-session**", hold_browser_status)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        response_status = page.locator("#agent_response_status")
        response_status_copy = page.locator("[data-agent-response-status-copy]")
        response_status_spinner = page.locator("[data-agent-response-status-spinner]")
        expect(response_status).to_be_visible()
        expect(response_status).to_have_attribute("data-status", "loading")
        expect(response_status_spinner).to_be_visible()
        expect(response_status_copy).to_contain_text("Checking")
        expect(response_status_copy).not_to_contain_text("Unavailable")
        assert len(browser_status_requests) == 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_project_path_prefers_trailing_directories_without_overflow(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep the useful end of a long project path visible in the current-project input."""
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
    }
    long_path = "/Users/lightwing/Desktop/agenticContext/projects/ABC/DEF"
    context = disposable_browser.new_context(
        viewport={"width": 1_024, "height": 768},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route(
        "**/api/agent/status",
        lambda route: route.fulfill(json=_finished_chatgpt_agent_payload()),
    )
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    page.route(
        "**/api/agent/sources**",
        lambda route: route.fulfill(
            json={
                "platform": "chatgpt",
                "browser_label": "Edge",
                "recent_sessions": [],
                "projects": [],
                "limit": 20,
            }
        ),
    )
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        project_path = page.locator("#agent_project_path")
        project_path.fill(long_path)
        geometry = project_path.evaluate(
            """input => {
                const style = getComputedStyle(input);
                return {
                    direction: style.direction,
                    textAlign: style.textAlign,
                    textOverflow: style.textOverflow,
                    value: input.value,
                    documentOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) > document.documentElement.clientWidth,
                };
            }"""
        )
        assert geometry["value"] == long_path
        assert geometry["direction"] == "rtl"
        assert geometry["textAlign"] == "left"
        assert geometry["textOverflow"] == "ellipsis"
        assert not geometry["documentOverflow"]
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_agent_bootstrap_replaces_ready_cache_without_catalog(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Avoid a second source collection when an older ready status lacks bootstrap data."""
    browser_status_requests: list[str] = []
    source_requests: list[str] = []
    session_url = "https://chatgpt.com/c/bootstrap-cache-session"
    catalog_payload = {
        "platform": "chatgpt",
        "browser_label": "Edge",
        "recent_sessions": [
            {
                "id": "bootstrap-cache-session",
                "title": "Bootstrap cache session",
                "url": session_url,
                "updated_at": "2026-08-30T00:00:00Z",
            }
        ],
        "projects": [],
        "limit": 20,
    }
    fresh_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }

    def fulfill_browser_status(route) -> None:
        browser_status_requests.append(route.request.url)
        route.fulfill(json=fresh_status)

    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(json=catalog_payload)

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    cache_key = "cachelikes:browser-session:v6:agent:chatgpt:edge"
    cached_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Cached ChatGPT status",
        "agent_sources_error": "Stale catalog failure",
    }
    page.add_init_script(
        f"sessionStorage.setItem({json.dumps(cache_key)}, "
        f"JSON.stringify({{cached_at: Date.now(), payload: {json.dumps(cached_status)}}}));"
    )
    page.route(
        "**/api/agent/status",
        lambda route: route.fulfill(json=_finished_chatgpt_agent_payload()),
    )
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route("**/api/agent/sources**", fulfill_sources)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        expect(
            page.locator(
                f'[data-agent-session-list="recent"] [data-agent-combobox-option="{session_url}"]'
            )
        ).to_have_count(1)
        assert len(browser_status_requests) == 1
        assert source_requests == []
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_fresh_grok_bootstrap_supersedes_a_stale_cached_catalog_error(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    source_requests: list[str] = []
    session_url = "https://grok.com/c/fresh-bootstrap-session"
    catalog_payload = {
        "platform": "grok",
        "browser_label": "Edge",
        "recent_sessions": [
            {
                "id": "fresh-bootstrap-session",
                "title": "Fresh Grok session",
                "url": session_url,
                "updated_at": "2026-08-26T12:00:00Z",
            }
        ],
        "projects": [],
        "limit": 20,
    }
    stale_status = {
        "platform": "grok",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "Grok account",
        "message": "Cached Grok status",
        "agent_sources_error": "Stale catalog failure",
    }
    fresh_status = {
        **stale_status,
        "message": "Edge verified an authenticated Grok Web session.",
        "agent_sources_error": "",
        "agent_sources": catalog_payload,
    }
    agent_payload = _finished_chatgpt_agent_payload()
    agent_payload["agent"] = {
        **agent_payload["agent"],
        "platform": "grok",
        "model": "grok-build",
        "actual_model": "Build Beta",
        "conversation_url": session_url,
    }

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    cache_key = "cachelikes:browser-session:v6:agent:grok:edge"
    cache_entry = json.dumps(
        {"cached_at": 0, "payload": stale_status},
        ensure_ascii=False,
    )
    page.add_init_script(
        f"sessionStorage.setItem({json.dumps(cache_key)}, {json.dumps(cache_entry)});"
        "const value = JSON.parse(sessionStorage.getItem("
        f"{json.dumps(cache_key)}));"
        "value.cached_at = Date.now() - 360000;"
        f"sessionStorage.setItem({json.dumps(cache_key)}, JSON.stringify(value));"
    )
    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(json=catalog_payload)

    page.route("**/api/agent/status", lambda route: route.fulfill(json=agent_payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=fresh_status))
    page.route("**/api/agent/sources**", fulfill_sources)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/grok", wait_until="domcontentloaded")
        fresh_option = page.locator(
            f'[data-agent-session-list="recent"] [data-agent-combobox-option="{session_url}"]'
        )
        expect(fresh_option).to_have_count(1)
        expect(fresh_option).to_contain_text("Fresh Grok session")
        page.wait_for_timeout(300)
        assert source_requests == []
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_stale_chatgpt_probe_failure_cannot_overwrite_grok_ready_state(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    pending_chatgpt_routes = []
    browser_session_requests: list[str] = []
    grok_ready_message = "Edge verified Grok after the provider switch."
    stale_chatgpt_error = "The superseded ChatGPT probe failed."
    grok_catalog = {
        "platform": "grok",
        "browser_label": "Edge",
        "recent_sessions": [],
        "projects": [],
        "limit": 20,
    }
    finished_chatgpt_payload = _finished_chatgpt_agent_payload()
    finished_chatgpt_payload["agent"]["prompt"] = "STALE_CHATGPT_PROMPT_SENTINEL"

    def fulfill_browser_status(route) -> None:
        request_url = route.request.url
        browser_session_requests.append(request_url)
        if "platform=chatgpt" in request_url:
            pending_chatgpt_routes.append(route)
            return
        assert "platform=grok" in request_url
        route.fulfill(
            json={
                "platform": "grok",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "Grok account",
                "message": grok_ready_message,
                "agent_sources": grok_catalog,
            }
        )

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route(
        "**/api/agent/status",
        lambda route: route.fulfill(json=finished_chatgpt_payload),
    )
    page.route("**/api/browser-session**", fulfill_browser_status)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        assert len(pending_chatgpt_routes) == 1
        expect(page.locator("#agent_response_output")).to_be_visible()
        expect(page.locator("[data-agent-response-answer-content]")).to_have_text(
            "Read-only inspection finished."
        )

        page.get_by_role("button", name="Web service: ChatGPT", exact=True).click()
        page.locator(
            '.agent-platform-combobox [data-agent-combobox-option="grok"]'
        ).click()

        expect(page.get_by_role("button", name="Web service: Grok", exact=True)).to_be_visible()
        expect(page.locator(".agent-readiness")).to_have_count(0)
        expect(page.locator("#agent_ask_button")).to_be_enabled()
        expect(page.locator("#agent_phase_chip")).to_have_count(0)
        expect(page.locator("#agent_response_output")).to_be_hidden()
        expect(page.locator("[data-agent-response-question]")).to_be_empty()
        expect(page.locator("[data-agent-response-answer-content]")).to_be_empty()
        expect(page.locator("[data-agent-prompt-input]")).to_have_value("")
        expect(page.locator("#agent_activity_panel")).to_be_hidden()
        assert len(browser_session_requests) == 2
        assert "platform=grok" in browser_session_requests[-1]

        with page.expect_response(
            lambda response: "platform=chatgpt" in response.url and response.status == 409
        ):
            pending_chatgpt_routes[0].fulfill(
                status=409,
                json={"error": stale_chatgpt_error},
            )
        page.evaluate("() => new Promise((resolve) => setTimeout(resolve, 0))")

        expect(page.get_by_role("button", name="Web service: Grok", exact=True)).to_be_visible()
        expect(page.locator(".agent-readiness")).to_have_count(0)
        expect(page.locator("#agent_ask_button")).to_be_enabled()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_running_agent_status_shows_elapsed_turn_count_and_activity_time(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep live Agent telemetry readable with a two-line running status."""
    started_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = _finished_chatgpt_agent_payload()
    payload["agent"] = {
        **payload["agent"],
        "running": True,
        "phase": "running",
        "finished_at": "",
        "started_at": started_at,
        "turn_count": 3,
        "activity": [
            {
                "status": "running",
                "label": "Read",
                "detail": "app/services/very-long-agent-activity-path-that-must-wrap-cleanly.py",
                "meta": "Turn 3",
                "timestamp": "2026-09-02T08:00:00Z",
            }
        ],
        "message": "Controller observation sent; waiting for the next ChatGPT action.",
    }
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
    }
    context = disposable_browser.new_context(
        viewport={"width": 390, "height": 844},
        has_touch=True,
        is_mobile=True,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", lambda route: route.fulfill(json=payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        status = page.locator("#agent_response_status")
        status_copy = page.locator("[data-agent-response-status-copy]")
        activity_meta = page.locator("#agent_activity_list .agent-activity-meta").first
        expect(status).to_contain_text("Working")
        expect(status).to_contain_text("3 turns")
        expect(status_copy.locator("br")).to_have_count(1)
        expect(status_copy.locator("[data-agent-response-status-leading]")).to_have_text(
            re.compile(r"^Working · \d{2}:\d{2}:\d{2} · 3 turns$")
        )
        expect(status_copy.locator("[data-agent-response-status-detail]")).to_have_text(
            "Controller observation sent; waiting for the next ChatGPT action."
        )
        expect(activity_meta).to_have_text("Turn 3 · 16:00:00")
        status_text_before = status_copy.text_content()
        page.wait_for_function(
            """previous => document.querySelector('[data-agent-response-status-copy]')?.textContent !== previous""",
            arg=status_text_before,
        )
        layout = page.evaluate(
            """() => {
                const copy = document.querySelector('[data-agent-response-status-copy]');
                const leading = copy?.querySelector('[data-agent-response-status-leading]');
                const statusDetail = copy?.querySelector('[data-agent-response-status-detail]');
                const spinner = document.querySelector('[data-agent-response-status-spinner]');
                const activityDetail = document.querySelector('#agent_activity_list .agent-activity-detail');
                const read = element => element ? {
                    clientHeight: element.clientHeight,
                    clientWidth: element.clientWidth,
                    lineHeight: Number.parseFloat(getComputedStyle(element).lineHeight),
                    scrollWidth: element.scrollWidth,
                } : null;
                return {
                    copy: read(copy),
                    statusLeadingLeft: leading?.getBoundingClientRect().left || null,
                    statusDetailLeft: statusDetail?.getBoundingClientRect().left || null,
                    spinnerRight: spinner?.getBoundingClientRect().right || null,
                    detail: read(activityDetail),
                };
            }"""
        )
        assert layout["statusLeadingLeft"] == pytest.approx(layout["statusDetailLeft"], abs=1)
        assert layout["statusLeadingLeft"] >= layout["spinnerRight"]
        assert layout["copy"]["clientHeight"] > layout["copy"]["lineHeight"]
        assert layout["copy"]["clientHeight"] <= layout["copy"]["lineHeight"] * 2 + 2
        assert layout["copy"]["scrollWidth"] <= layout["copy"]["clientWidth"] + 1
        assert layout["detail"]["scrollWidth"] <= layout["detail"]["clientWidth"] + 1
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_observed_agent_completion_does_not_refresh_sources(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    source_requests: list[str] = []
    status_requests = 0
    finished_payload = _finished_chatgpt_agent_payload()
    running_payload = {
        **finished_payload,
        "agent": {
            **finished_payload["agent"],
            "running": True,
            "phase": "running",
            "finished_at": "",
            "conversation_url": "",
        },
    }
    catalog_payload = _chatgpt_catalog_sessions()

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(json=running_payload if status_requests == 1 else finished_payload)

    def fulfill_browser_status(route) -> None:
        route.fulfill(
            json={
                "platform": "chatgpt",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "ChatGPT account",
                "message": "Edge is ready for ChatGPT Web.",
            }
        )

    def fulfill_sources(route) -> None:
        source_requests.append(route.request.url)
        route.fulfill(json=catalog_payload)

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route("**/api/agent/sources**", fulfill_sources)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        response_status = page.locator("#agent_response_status")
        response_status_spinner = page.locator("[data-agent-response-status-spinner]")
        expect(response_status).to_be_visible()
        expect(response_status).to_have_attribute("data-status", "running")
        expect(response_status_spinner).to_be_visible()
        expect(response_status).to_have_attribute("data-status", "finished")
        page.wait_for_timeout(2_800)
        assert status_requests >= 2
        assert source_requests == []
        expect(response_status).to_contain_text("Finished")
        expect(response_status_spinner).to_be_hidden()
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_successful_agent_completion_collapses_activity_without_erasing_a_new_draft(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Keep completed tool turns available on demand while returning focus to the answer."""
    completed_prompt = " ".join(
        [
            "Review the Agent implementation and report the completed verification.",
            "Preserve the exact source evidence, current tests, and known limitations.",
        ]
        * 12
    )
    activity = [
        {
            "status": "complete",
            "label": ("Read", "Replace", "Run")[(turn - 1) % 3],
            "detail": f"tests/e2e/critical-flows-{turn}.spec.mjs",
            "meta": f"Turn {turn}",
        }
        for turn in range(1, 70)
    ]
    finished_payload = _finished_chatgpt_agent_payload()
    finished_agent = {
        **finished_payload["agent"],
        "run_id": "run-hydrated-finished",
        "run_revision": 7,
        "prompt": completed_prompt,
        "response": "Completed Agent answer.",
        "response_html": "<p>Completed Agent answer.</p>",
        "history": [
            {
                "prompt": completed_prompt,
                "response": "Completed Agent answer.",
                "response_html": "<p>Completed Agent answer.</p>",
            }
        ],
        "activity": activity,
    }
    finished_payload["agent"] = finished_agent
    running_payload = {
        **finished_payload,
        "agent": {
            **finished_agent,
            "running": True,
            "phase": "running",
            "finished_at": "",
            "conversation_url": "",
        },
    }
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }
    status_requests = 0

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(json=running_payload if status_requests == 1 else finished_payload)

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route(
        "**/api/browser-session**",
        lambda route: route.fulfill(json=browser_status),
    )
    page.route(
        "**/api/agent/sources**",
        lambda route: route.fulfill(json=catalog_payload),
    )
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        activity_panel = page.locator("#agent_activity_panel")
        prompt = page.locator("#agent_prompt_input")
        expect(activity_panel).to_have_count(1)
        expect(activity_panel).to_have_js_property("open", True)
        expect(page.locator("#agent_activity_list > .agent-activity-item")).to_have_count(69)
        page.evaluate(
            """value => {
                document.querySelector('#agent_prompt_input').value = value;
            }""",
            completed_prompt,
        )

        page.wait_for_function(
            """expectedPrompt => {
                const panel = document.querySelector('#agent_activity_panel');
                const prompt = document.querySelector('#agent_prompt_input');
                const question = document.querySelector('[data-agent-response-question]');
                return panel instanceof HTMLDetailsElement
                    && !panel.open
                    && prompt instanceof HTMLTextAreaElement
                    && prompt.value === ''
                    && question?.textContent === expectedPrompt;
            }""",
            arg=completed_prompt,
        )
        expect(page.locator("#agent_activity_list")).to_be_hidden()

        question_layout = page.evaluate(
            """() => {
                const header = document.querySelector('#agent_response_question_header');
                const question = document.querySelector('[data-agent-response-question]');
                const output = document.querySelector('#agent_response_output');
                const composer = document.querySelector('#agent_prompt_form');
                const headerRect = header?.getBoundingClientRect();
                const outputRect = output?.getBoundingClientRect();
                const composerRect = composer?.getBoundingClientRect();
                return {
                    headerClientHeight: header?.clientHeight,
                    headerScrollHeight: header?.scrollHeight,
                    questionClientWidth: question?.clientWidth,
                    questionScrollWidth: question?.scrollWidth,
                    questionFontWeight: question ? getComputedStyle(question).fontWeight : null,
                    outputBottom: outputRect?.bottom,
                    composerTop: composerRect?.top,
                    headerBottom: headerRect?.bottom,
                    horizontalOverflow: Math.max(
                        document.documentElement.scrollWidth,
                        document.body.scrollWidth,
                    ) - document.documentElement.clientWidth,
                };
            }"""
        )
        assert question_layout["headerScrollHeight"] > question_layout["headerClientHeight"]
        assert question_layout["questionScrollWidth"] <= question_layout["questionClientWidth"] + 1
        assert question_layout["questionFontWeight"] == "500"
        assert question_layout["outputBottom"] <= question_layout["composerTop"] + 1
        assert question_layout["horizontalOverflow"] <= 1

        activity_panel.locator("summary").click()
        expect(activity_panel).to_have_js_property("open", True)
        expect(page.locator("#agent_activity_list")).to_be_visible()
        prompt.fill("A new task draft")
        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 3"""
        )
        assert status_requests >= 3
        expect(activity_panel).to_have_js_property("open", True)
        expect(prompt).to_have_value("A new task draft")
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("edit_same_text", (False, True))
def test_hydrated_running_agent_handles_the_first_finished_status_without_losing_a_same_text_draft(
    disposable_browser: Browser,
    sidebar_server_url: str,
    edit_same_text: bool,
) -> None:
    """Use the SSR run identity when the first client status already reports completion."""
    completed_prompt = "Verify the first completed Agent status after hydration."
    finished_payload = _finished_chatgpt_agent_payload()
    finished_agent = {
        **finished_payload["agent"],
        "run_id": "run-hydrated-finished",
        "run_revision": 7,
        "prompt": completed_prompt,
        "response": "Hydrated completion answer.",
        "response_html": "<p>Hydrated completion answer.</p>",
        "history": [
            {
                "prompt": completed_prompt,
                "response": "Hydrated completion answer.",
                "response_html": "<p>Hydrated completion answer.</p>",
            }
        ],
        "activity": [
            {
                "status": "complete",
                "label": "Read",
                "detail": "tests/test_sidebar_e2e.py",
                "meta": "Turn 1",
            }
        ],
    }
    finished_payload["agent"] = finished_agent
    run_identity = str(finished_agent["run_id"])
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }
    pending_status_routes = []

    def hydrate_running_markup(route) -> None:
        response = route.fetch()
        body = response.text()
        body, running_replacements = re.subn(
            (
                r'data-agent-running="[^"]*" data-agent-run-id="[^"]*" '
                r'data-agent-run-revision="[^"]*" data-agent-started-at="[^"]*"'
            ),
            (
                f'data-agent-running="true" data-agent-run-id="{run_identity}" '
                f'data-agent-run-revision="{finished_agent["run_revision"]}" '
                f'data-agent-started-at="{finished_agent["started_at"]}"'
            ),
            body,
            count=1,
        )
        assert running_replacements == 1
        body = body.replace(
            'data-agent-prompt-input required></textarea>',
            f'data-agent-prompt-input required>{completed_prompt}</textarea>',
            1,
        )
        body = body.replace(
            '<details class="agent-activity-panel" id="agent_activity_panel" hidden>',
            '<details class="agent-activity-panel" id="agent_activity_panel" open>',
            1,
        )
        route.fulfill(response=response, body=body)

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/agent/edge/chatgpt", hydrate_running_markup)
    page.route("**/api/agent/status", lambda route: pending_status_routes.append(route))
    page.route(
        "**/api/browser-session**",
        lambda route: route.fulfill(json=browser_status),
    )
    page.route(
        "**/api/agent/sources**",
        lambda route: route.fulfill(json=catalog_payload),
    )
    try:
        with page.expect_request(
            lambda request: "/api/agent/status" in request.url,
        ):
            page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        prompt = page.locator("#agent_prompt_input")
        activity_panel = page.locator("#agent_activity_panel")
        expect(prompt).to_have_value(completed_prompt)
        expect(activity_panel).to_have_js_property("open", True)
        assert len(pending_status_routes) == 1
        if edit_same_text:
            prompt.fill(completed_prompt)
        pending_status_routes[0].fulfill(json=finished_payload)

        expected_prompt = completed_prompt if edit_same_text else ""
        page.wait_for_function(
            """expected => {
                const page = document.querySelector('[data-agent-route-prefix]');
                const panel = document.querySelector('#agent_activity_panel');
                const prompt = document.querySelector('#agent_prompt_input');
                const question = document.querySelector('[data-agent-response-question]');
                return page?.dataset.agentRunning === 'false'
                    && panel instanceof HTMLDetailsElement
                    && !panel.open
                    && prompt instanceof HTMLTextAreaElement
                    && prompt.value === expected.prompt
                    && question?.textContent === expected.question;
            }""",
            arg={"prompt": expected_prompt, "question": completed_prompt},
        )
        expect(page.locator("#agent_activity_list > .agent-activity-item")).to_have_count(1)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_late_prior_run_status_cannot_overwrite_the_new_running_agent_draft(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Reject a delayed terminal snapshot from a prior Agent run."""
    base_payload = _finished_chatgpt_agent_payload()
    prior_agent = {
        **base_payload["agent"],
        "run_id": "run-prior",
        "run_revision": 41,
        "started_at": "2026-08-26T10:00:00Z",
        "finished_at": "",
        "running": True,
        "phase": "running",
        "prompt": "Prior run prompt.",
        "response": "",
        "response_html": "",
        "activity": [{"status": "running", "label": "Prior running event", "detail": "", "meta": ""}],
    }
    current_agent = {
        **prior_agent,
        "run_id": "run-current",
        "run_revision": 42,
        "prompt": "Current run prompt.",
        "response": "",
        "response_html": "",
        "activity": [{"status": "running", "label": "Current running event", "detail": "", "meta": ""}],
    }
    prior_payload = {**base_payload, "agent": prior_agent}
    prior_terminal_payload = {
        **base_payload,
        "agent": {
            **prior_agent,
            "running": False,
            "phase": "finished",
            "finished_at": "2026-08-26T10:00:01Z",
            "response": "Prior terminal answer.",
            "response_html": "<p>Prior terminal answer.</p>",
            "activity": [{"status": "complete", "label": "Prior terminal event", "detail": "", "meta": ""}],
        },
    }
    current_payload = {**base_payload, "agent": current_agent}
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }
    status_requests = 0

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(
            json=(
                prior_payload
                if status_requests == 1
                else current_payload
                if status_requests == 2
                else prior_terminal_payload
            )
        )

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    page.route("**/api/agent/sources**", lambda route: route.fulfill(json=catalog_payload))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        prompt = page.locator("#agent_prompt_input")
        activity_panel = page.locator("#agent_activity_panel")
        page.wait_for_function(
            """() => document.querySelector('[data-agent-route-prefix]')?.dataset.agentRunId === 'run-prior'"""
        )
        expect(activity_panel).to_have_js_property("open", True)
        expect(page.locator("#agent_activity_list")).to_contain_text("Prior running event")

        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 2"""
        )
        expect(page.locator("[data-agent-route-prefix]")).to_have_attribute("data-agent-run-id", "run-current")
        expect(page.locator("[data-agent-route-prefix]")).to_have_attribute("data-agent-run-revision", "42")
        expect(page.locator("#agent_activity_list")).to_contain_text("Current running event")
        prompt.fill("Keep this current-run draft.")

        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 3"""
        )
        assert status_requests >= 3
        expect(page.locator("[data-agent-route-prefix]")).to_have_attribute("data-agent-run-id", "run-current")
        expect(page.locator("[data-agent-route-prefix]")).to_have_attribute("data-agent-running", "true")
        expect(activity_panel).to_have_js_property("open", True)
        expect(page.locator("#agent_activity_list")).to_contain_text("Current running event")
        expect(prompt).to_have_value("Keep this current-run draft.")
        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 4""",
            timeout=1_800,
        )
        assert status_requests >= 4
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_superseding_finished_run_never_clears_an_idle_local_draft(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """A terminal snapshot from another run must not mutate an unsent draft."""
    idle_draft = "Keep this unsent idle draft."
    base_payload = _finished_chatgpt_agent_payload()
    prior_agent = {
        **base_payload["agent"],
        "run_id": "run-prior",
        "started_at": "2026-08-26T09:00:00Z",
        "finished_at": "2026-08-26T09:01:00Z",
        "prompt": "Prior completed prompt.",
        "response": "Prior completed answer.",
        "response_html": "<p>Prior completed answer.</p>",
    }
    later_agent = {
        **prior_agent,
        "run_id": "run-later",
        "started_at": "2026-08-26T10:00:00Z",
        "finished_at": "2026-08-26T10:01:00Z",
        "prompt": idle_draft,
        "response": "Later completed answer.",
        "response_html": "<p>Later completed answer.</p>",
    }
    later_running_agent = {
        **later_agent,
        "running": True,
        "phase": "running",
        "finished_at": "",
    }
    prior_payload = {**base_payload, "agent": prior_agent}
    later_running_payload = {**base_payload, "agent": later_running_agent}
    later_payload = {**base_payload, "agent": later_agent}
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }
    status_requests = 0

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(
            json=(
                prior_payload
                if status_requests == 1
                else later_running_payload
                if status_requests == 2
                else later_payload
            )
        )

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    page.route("**/api/agent/sources**", lambda route: route.fulfill(json=catalog_payload))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        prompt = page.locator("#agent_prompt_input")
        page.wait_for_function(
            """() => document.querySelector('[data-agent-route-prefix]')?.dataset.agentRunId === 'run-prior'"""
        )
        prompt.fill(idle_draft)

        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 3"""
        )
        assert status_requests >= 3
        expect(page.locator("[data-agent-route-prefix]")).to_have_attribute("data-agent-run-id", "run-later")
        expect(prompt).to_have_value(idle_draft)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_rejected_ask_keeps_the_draft_when_an_old_finished_status_arrives(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """A failed Ask must clear its pending marker before the next status poll."""
    rejected_prompt = "Keep this draft after the rejected Ask request."
    finished_payload = _finished_chatgpt_agent_payload()
    finished_payload["agent"] = {
        **finished_payload["agent"],
        "run_id": "run-old-finished",
        "prompt": "Old finished prompt.",
        "response": "Old finished answer.",
        "response_html": "<p>Old finished answer.</p>",
    }
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }
    status_requests = 0

    def fulfill_agent_status(route) -> None:
        nonlocal status_requests
        status_requests += 1
        route.fulfill(json=finished_payload)

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    page.route("**/api/agent/sources**", lambda route: route.fulfill(json=catalog_payload))
    page.route(
        "**/api/agent/ask",
        lambda route: route.fulfill(status=409, json={"error": "Ask request was rejected."}),
    )
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        prompt = page.locator("#agent_prompt_input")
        ask = page.locator("#agent_ask_button")
        expect(ask).to_be_enabled()
        prompt.fill(rejected_prompt)
        with page.expect_response(
            lambda response: "/api/agent/ask" in response.url and response.status == 409
        ):
            ask.click()

        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').filter((entry) =>
                String(entry.name || '').includes('/api/agent/status')
            ).length >= 2"""
        )
        assert status_requests >= 2
        expect(prompt).to_have_value(rejected_prompt)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_successful_ask_acknowledges_a_distinct_same_second_run_id(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """The Ask response is authoritative when two run starts share one second."""
    submitted_prompt = "Accept this same-second Agent run acknowledgement."
    base_payload = _finished_chatgpt_agent_payload()
    prior_agent = {
        **base_payload["agent"],
        "run_id": "run-prior-same-second",
        "started_at": "2026-08-26T10:00:00Z",
        "finished_at": "2026-08-26T10:00:01Z",
        "prompt": "Prior completed prompt.",
        "response": "Prior completed answer.",
        "response_html": "<p>Prior completed answer.</p>",
    }
    acknowledged_agent = {
        **prior_agent,
        "run_id": "run-acknowledged-same-second",
        "finished_at": "2026-08-26T10:00:02Z",
        "prompt": submitted_prompt,
        "response": "Acknowledged current answer.",
        "response_html": "<p>Acknowledged current answer.</p>",
    }
    prior_payload = {**base_payload, "agent": prior_agent}
    acknowledged_payload = {**base_payload, "agent": acknowledged_agent}
    catalog_payload = _chatgpt_catalog_sessions()
    browser_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Edge is ready for ChatGPT Web.",
        "agent_sources": catalog_payload,
    }

    context = disposable_browser.new_context(
        viewport={"width": 1_008, "height": 1_085},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", lambda route: route.fulfill(json=prior_payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json=browser_status))
    page.route("**/api/agent/sources**", lambda route: route.fulfill(json=catalog_payload))
    page.route("**/api/agent/ask", lambda route: route.fulfill(json=acknowledged_payload))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        page.wait_for_function(
            """() => document.querySelector('[data-agent-route-prefix]')?.dataset.agentRunId === 'run-prior-same-second'"""
        )
        prompt = page.locator("#agent_prompt_input")
        ask = page.locator("#agent_ask_button")
        expect(ask).to_be_enabled()
        prompt.fill(submitted_prompt)
        with page.expect_response(
            lambda response: "/api/agent/ask" in response.url and response.status == 200
        ):
            ask.click()

        page.wait_for_function(
            """expected => {
                const agentPage = document.querySelector('[data-agent-route-prefix]');
                const prompt = document.querySelector('#agent_prompt_input');
                const question = document.querySelector('[data-agent-response-question]');
                return agentPage?.dataset.agentRunId === expected.runId
                    && agentPage.dataset.agentRunning === 'false'
                    && prompt instanceof HTMLTextAreaElement
                    && prompt.value === ''
                    && question?.textContent === expected.prompt;
            }""",
            arg={"runId": "run-acknowledged-same-second", "prompt": submitted_prompt},
        )
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_missing_snapshot_url_is_not_synthesized_into_session_catalog(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    def fulfill_agent_status(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_browser_status(route) -> None:
        route.fulfill(
            json={
                "platform": "chatgpt",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "ChatGPT account",
                "message": "Edge is ready for ChatGPT Web.",
            }
        )

    def fulfill_preferences(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_sources(route) -> None:
        route.fulfill(
            json=_chatgpt_catalog_sessions(
                {
                    "id": "agentic-troubleshooting",
                    "title": "Agentic Troubleshooting",
                    "url": AGENTIC_TROUBLESHOOTING_URL,
                    "updated_at": "2026-08-26T01:00:00Z",
                }
            )
        )

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route("**/api/agent/preferences", fulfill_preferences)
    page.route("**/api/agent/sources**", fulfill_sources)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        expect(page.locator("[data-agent-prompt-session-mode]")).to_have_value("new")
        expect(page.locator("[data-agent-prompt-conversation-url]")).to_have_value("")
        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        page.locator('.agent-session-mode-combobox [data-agent-combobox-option="recent"]').click()
        expect(
            page.locator(
                f'[data-agent-session-list="recent"] [data-agent-combobox-option="{FINISHED_SNAPSHOT_URL}"]'
            )
        ).to_have_count(0)
        expect(
            page.locator(
                f'[data-agent-session-list="recent"] [data-agent-combobox-option="{AGENTIC_TROUBLESHOOTING_URL}"]'
            )
        ).to_have_count(1)
        expect(page.locator("[data-agent-prompt-conversation-url]")).to_have_value("")
        expect(page.locator("#agent_conversation_link")).to_have_attribute("href", FINISHED_SNAPSHOT_URL)
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
def test_explicit_agentic_troubleshooting_session_is_the_only_reused_target(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    captured_ask_payloads: list[dict[str, str]] = []

    def fulfill_agent_status(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_browser_status(route) -> None:
        route.fulfill(
            json={
                "platform": "chatgpt",
                "browser": "edge",
                "browser_label": "Edge",
                "logged_in": True,
                "can_download": True,
                "account_name": "ChatGPT account",
                "message": "Edge is ready for ChatGPT Web.",
            }
        )

    def fulfill_preferences(route) -> None:
        route.fulfill(json=_finished_chatgpt_agent_payload())

    def fulfill_sources(route) -> None:
        route.fulfill(
            json=_chatgpt_catalog_sessions(
                {
                    "id": "qqqm-session",
                    "title": "比较 QQQM 与 QQQ",
                    "url": FINISHED_SNAPSHOT_URL,
                    "updated_at": "2026-08-25T09:03:57Z",
                },
                {
                    "id": "agentic-troubleshooting",
                    "title": "Agentic Troubleshooting",
                    "url": AGENTIC_TROUBLESHOOTING_URL,
                    "updated_at": "2026-08-26T01:00:00Z",
                },
            )
        )

    def fulfill_history(route) -> None:
        route.fulfill(
            json={
                "title": "Agentic Troubleshooting",
                "history": [],
            }
        )

    def fulfill_ask(route) -> None:
        captured_ask_payloads.append(route.request.post_data_json or {})
        route.fulfill(json=_finished_chatgpt_agent_payload())

    context = disposable_browser.new_context(
        viewport={"width": 1_280, "height": 720},
        has_touch=False,
        is_mobile=False,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/agent/status", fulfill_agent_status)
    page.route("**/api/browser-session**", fulfill_browser_status)
    page.route("**/api/agent/preferences", fulfill_preferences)
    page.route("**/api/agent/sources**", fulfill_sources)
    page.route("**/api/agent/chatgpt-session-history**", fulfill_history)
    page.route("**/api/agent/ask", fulfill_ask)
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt", wait_until="domcontentloaded")
        expect(page.locator("[data-agent-prompt-session-mode]")).to_have_value("new")
        page.locator(".agent-session-mode-combobox [data-agent-combobox-trigger]").click()
        page.locator('.agent-session-mode-combobox [data-agent-combobox-option="recent"]').click()
        page.locator(
            f'[data-agent-session-list="recent"] [data-agent-combobox-option="{AGENTIC_TROUBLESHOOTING_URL}"]'
        ).click()
        expect(page.locator("[data-agent-prompt-session-mode]")).to_have_value("recent")
        expect(page.locator("[data-agent-prompt-conversation-url]")).to_have_value(
            AGENTIC_TROUBLESHOOTING_URL
        )
        expect(page.locator("[data-agent-prompt-session-title]")).to_have_value(
            "Agentic Troubleshooting"
        )
        page.locator("[data-agent-prompt-input]").fill("Continue the existing troubleshooting session.")
        with page.expect_request(re.compile(r"/api/agent/ask$")):
            page.locator("#agent_ask_button").click()
        assert captured_ask_payloads
        payload = captured_ask_payloads[0]
        assert payload["session_mode"] == "recent"
        assert payload["conversation_url"] == AGENTIC_TROUBLESHOOTING_URL
        assert payload["session_title"] == "Agentic Troubleshooting"
        assert payload["conversation_url"] != FINISHED_SNAPSHOT_URL
    finally:
        context.close()
