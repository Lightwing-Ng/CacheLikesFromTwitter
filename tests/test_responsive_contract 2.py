"""Responsive sidebar contract tests.

Code version: v1.0.1-codex.1
"""

from __future__ import annotations

from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = PROJECT_ROOT / "app/web/static/style.css"
RESPONSIVE_SCRIPT_PATH = PROJECT_ROOT / "app/web/static/responsive.js"
STATIC_SCRIPT_ROOT = PROJECT_ROOT / "app/web/static"
TEMPLATE_ROOT = PROJECT_ROOT / "app/web/templates"
EXPECTED_BREAKPOINTS = {
    "compact-content-max": 600,
    "sidebar-overlay-max": 900,
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_block(source: str, marker: str) -> str:
    start = source.index(marker)
    opening_brace = source.index("{", start)
    depth = 0
    for index in range(opening_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Unclosed CSS block: {marker}")


def test_css_and_javascript_share_one_semantic_sidebar_registry() -> None:
    stylesheet = _read(STYLE_PATH)
    responsive_script = _read(RESPONSIVE_SCRIPT_PATH)
    css_registry = {
        name: int(value)
        for name, value in re.findall(
            r"--responsive-breakpoint-([a-z0-9-]+):\s*([0-9]+)px;",
            stylesheet,
        )
    }

    assert {name: css_registry[name] for name in EXPECTED_BREAKPOINTS} == EXPECTED_BREAKPOINTS
    assert "compactContentMax: 600," in responsive_script
    assert "sidebarOverlayMax: 900," in responsive_script
    assert '"--responsive-breakpoint-compact-content-max"' in responsive_script
    assert '"--responsive-breakpoint-sidebar-overlay-max"' in responsive_script
    assert "window.CACHELIKES_RESPONSIVE = Object.freeze" in responsive_script

    direct_width_query = re.compile(r"matchMedia\(\s*[\"'`][^\"'`]*(?:min|max)-width")
    for script_path in STATIC_SCRIPT_ROOT.glob("*.js"):
        if script_path == RESPONSIVE_SCRIPT_PATH:
            continue
        assert direct_width_query.search(_read(script_path)) is None, script_path


def test_sidebar_overlay_and_compact_content_are_independent() -> None:
    stylesheet = _read(STYLE_PATH)
    overlay_block = _extract_block(stylesheet, "@media (max-width: 900px)")
    compact_block = _extract_block(stylesheet, "@media (max-width: 600px)")

    for fragment in (
        ".sidebar {",
        "z-index: auto;",
        "position: fixed;",
        "top: var(--sidebar-overlay-inset-top);",
        "bottom: var(--sidebar-overlay-inset-bottom);",
        ".sidebar-backdrop {",
        ".sidebar-backdrop:not([hidden]) {",
        "pointer-events: auto;",
        ".page > .sidebar-toggle {",
        "width: 44px;",
        "height: 44px;",
        "z-index: var(--layer-sidebar-toggle);",
    ):
        assert fragment in overlay_block

    for mobile_content_fragment in (
        ".workspace-grid {",
        ".log-card {",
        ".metric-grid {",
        ".progress-metric-grid {",
    ):
        assert mobile_content_fragment not in overlay_block
        assert mobile_content_fragment in compact_block

    assert "@media (max-width: 720px)" not in stylesheet


def test_hidden_and_pointer_event_contracts_are_authoritative() -> None:
    stylesheet = _read(STYLE_PATH)

    assert "[hidden] {\n    display: none !important;\n}" in stylesheet
    assert ".sidebar-backdrop {\n    display: none;\n    visibility: hidden;\n    pointer-events: none;\n}" in stylesheet
    assert "html.sidebar-memory-collapsed .app-shell .sidebar {" in stylesheet
    assert "html.sidebar-memory-collapsed .sidebar-backdrop {" in stylesheet


def test_sidebar_pages_load_the_responsive_contract_before_bootstrap() -> None:
    for template_name in ("_cache_page.html", "browser.html", "settings.html"):
        source = _read(TEMPLATE_ROOT / template_name)
        assert "viewport-fit=cover" in source
        assert "responsive-v1.0.0-codex.1" in source
        assert '{% include "_sidebar_bootstrap.html" %}' in source
        assert source.index("responsive-v1.0.0-codex.1") < source.index(
            '{% include "_sidebar_bootstrap.html" %}'
        )

    bootstrap_source = _read(TEMPLATE_ROOT / "_sidebar_bootstrap.html")
    assert 'window.sessionStorage.getItem("cachelikes:sidebar-open")' in bootstrap_source
    assert 'window.CACHELIKES_RESPONSIVE?.media?.("sidebarOverlayMax")' in bootstrap_source
    assert 'document.documentElement.classList.add("sidebar-memory-collapsed")' in bootstrap_source


def test_sidebar_toggle_is_outside_the_shell_stacking_context() -> None:
    stylesheet = _read(STYLE_PATH)
    for template_name in ("_cache_page.html", "browser.html", "settings.html"):
        source = _read(TEMPLATE_ROOT / template_name)
        toggle_index = source.index('id="sidebar_toggle"')
        shell_index = source.index('class="app-shell')
        assert toggle_index < shell_index, template_name

    assert ".page > .sidebar-toggle" in stylesheet
