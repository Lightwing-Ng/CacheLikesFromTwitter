"""Disposable-browser E2E coverage for the responsive sidebar and language boundaries.

Code version: v1.26.2-codex.15
"""

from __future__ import annotations

from collections.abc import Iterator
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
    parse_agent_action,
)
from app.core.gemini_downloader import inspect_gemini_session


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
                    "/cache/gemini",
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
        expect(cards).to_have_count(22)
        assert page.evaluate(
            "document.documentElement.scrollWidth === document.documentElement.clientWidth"
        )
        assert len(
            page.locator("[data-style-token-card]").first.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns.split(' ')"
            )
        ) == 2
        assert page.locator("[data-style-token-agent-browser-menu]").is_hidden()

        refresh_button = page.locator("[data-style-token-secondary-button]")
        refresh_geometry = refresh_button.evaluate(
            "element => ({ width: element.getBoundingClientRect().width, parentWidth: element.parentElement.getBoundingClientRect().width })"
        )
        assert refresh_geometry["width"] < refresh_geometry["parentWidth"]

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
@pytest.mark.parametrize("page_source", ("chatgpt", "gemini", "grok", "x"))
def test_cache_source_switcher_click_matrix_stays_within_expected_destinations(
    disposable_browser: Browser,
    sidebar_server_url: str,
    page_source: str,
) -> None:
    """Verify every source option lands on its intentional local destination."""
    expected_paths = {
        "chatgpt": {
            "chatgpt": "/cache/chatgpt",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
        "gemini": {
            "chatgpt": "/cache/chatgpt",
            "gemini": "/cache/gemini",
            "grok": "/browser?view=text&session_view=1&q=&source=grok&sort=newest",
            "x": "/cache/x",
        },
        "grok": {
            "chatgpt": "/cache/chatgpt",
            "gemini": "/cache/gemini",
            "grok": "/cache/grok",
            "x": "/cache/x",
        },
        "x": {
            "chatgpt": "/cache/chatgpt",
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
            page.locator("[data-cache-source-switcher-trigger]").click()
            page.locator(
                f'[data-cache-source-switcher-option="{target_source}"]'
            ).click()
            expect(page).to_have_url(re.compile(rf"{re.escape(expected_path)}$"))
    finally:
        context.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("page_source", ("chatgpt", "gemini", "grok", "x"))
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
def test_agent_response_pagination_is_immersed_but_keeps_interactive_effects(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify the Agent pagination is surface-free without clipping its interactions."""
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
        assert compact["weight"] == "300"
        assert compact["resize"] == "none"
        control_heights = page.evaluate(
            """() => ({
                model: document.querySelector('.agent-model-trigger')?.getBoundingClientRect().height,
                effort: document.querySelector('.agent-effort-trigger')?.getBoundingClientRect().height,
            })"""
        )
        assert control_heights == {"model": 32, "effort": 32}

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
def test_agent_model_and_sidebar_service_triggers_follow_typography_contract(
    disposable_browser: Browser,
    sidebar_server_url: str,
) -> None:
    """Verify shared label metrics while preserving the model trigger's intended emphasis."""
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
        assert main_typography["fontWeight"] == "500"
        assert sidebar_typography["fontWeight"] == "400"
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
        expect(settings_link).to_have_class(re.compile(r"\bsecondary-button\b"))
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
        f"{sidebar_server_url}/settings#settings-chatgpt",
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
        assert abs(scroll_metrics["renderedDockGap"] - scroll_metrics["dockGap"]) <= 1
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
    """Only a complete live probe may add provider effort options to the UI."""
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
        assert [text.strip() for text in effort_options.all_text_contents()] == [
            "Highest available"
        ]
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
    cache_key = "cachelikes:browser-session:v5:agent:gemini:edge"
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
    cache_key = "cachelikes:browser-session:v5:agent:chatgpt:edge"
    cached_status = {
        "platform": "chatgpt",
        "browser": "edge",
        "browser_label": "Edge",
        "logged_in": True,
        "can_download": True,
        "account_name": "ChatGPT account",
        "message": "Cached ChatGPT status",
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
    cache_key = "cachelikes:browser-session:v5:agent:grok:edge"
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
def test_observed_agent_completion_refreshes_sources_exactly_once(
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
                "agent_sources": catalog_payload,
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
        page.wait_for_function(
            """() => window.performance.getEntriesByType('resource').some((entry) =>
                String(entry.name || '').includes('/api/agent/sources')
                && String(entry.name || '').includes('refresh=1')
            )"""
        )
        assert status_requests >= 2
        assert len(source_requests) == 1
        assert "refresh=1" in source_requests[0]
        expect(response_status).to_have_attribute("data-status", "finished")
        expect(response_status).to_contain_text("Finished")
        expect(response_status_spinner).to_be_hidden()
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
