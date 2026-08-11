"""Regression tests for synchronized sibling-project color tokens.

Code version: v1.5.0-codex.1
"""

from pathlib import Path


STYLE_PATH = Path(__file__).resolve().parents[1] / "app/web/static/style.css"


def _stylesheet() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


def test_light_color_tokens_match_the_sibling_theme() -> None:
    """Keep the light palette aligned with antigravity/config.toml."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--theme-background: #ffffff;",
        "--theme-panel: rgba(255, 255, 255, 0.68);",
        "--theme-panel-strong: rgba(255, 255, 255, 0.82);",
        "--theme-text: #0b0c0c;",
        "--theme-muted: #505a5f;",
        "--theme-accent-primary: #0055cc;",
        "--theme-accent-secondary: #ff2f92;",
        "--theme-accent-positive: #16a34a;",
        "--theme-error: #c81e1e;",
        "--theme-error-strong: #991b1b;",
        "--theme-warning: #f4c542;",
        "--theme-warning-text: #6b5200;",
        "--theme-success: #16a34a;",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_dark_color_tokens_match_the_sibling_theme() -> None:
    """Keep the dark palette aligned with antigravity/config.toml."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--theme-background: #0b0c0c;",
        "--theme-panel: rgba(255, 255, 255, 0.04);",
        "--theme-panel-strong: rgba(255, 255, 255, 0.08);",
        "--theme-text: #f3f4f6;",
        "--theme-muted: #94a3b8;",
        "--theme-accent-primary: #0055cc;",
        "--theme-accent-secondary: #f472b6;",
        "--theme-accent-positive: #2fff9c;",
        "--theme-error: #ef4444;",
        "--theme-error-strong: #b91c1c;",
        "--theme-warning: #f4c542;",
        "--theme-warning-text: #f4c542;",
        "--theme-success: #2fff9c;",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_synchronized_color_aliases_cover_interactive_surfaces() -> None:
    """Protect aliases that let components consume the shared palette."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--accent-focus-ring: color-mix(in srgb, var(--accent) 16%, transparent);",
        "--accent-focus-glow: color-mix(in srgb, var(--accent) 18%, transparent);",
        "--color-success: var(--theme-success);",
        "--color-error: var(--theme-error);",
        "--color-warning: var(--theme-warning);",
        "--glass-mask-background: var(--glass-surface-background-strong);",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_sidebar_actions_consume_shared_semantic_tokens() -> None:
    """Keep the cache controls on the sibling project's tokenized button system."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--sidebar-action-primary-background: var(--theme-accent-primary);",
        "--sidebar-action-primary-background-disabled: color-mix(in srgb, var(--theme-muted) 28%, transparent);",
        "--sidebar-action-danger-background: var(--theme-error-translucent);",
        "--sidebar-action-danger-background-hover: var(--theme-error);",
        "--sidebar-action-danger-color: var(--theme-error-strong);",
        "background: var(--sidebar-action-primary-background);",
        "background: var(--sidebar-action-danger-background);",
        "box-shadow: 0 0 0 3px var(--accent-focus-ring);",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_sidebar_shell_and_dock_consume_frosted_glass_tokens() -> None:
    """Keep the sidebar shell and dock on the sibling frosted-glass surface system."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".sidebar {",
        "background: var(--frosted-glass-background);",
        "border: var(--frosted-glass-border);",
        "box-shadow: var(--frosted-glass-shadow);",
        "backdrop-filter: var(--frosted-glass-blur);",
        ".sidebar-dock {",
        ".sidebar-dock-item.is-active {",
        "color: var(--accent-text);",
        ".sidebar-toggle {",
        "border: var(--settings-round-icon-button-border);",
        ".sidebar-section > .section-heading {",
        "min-height: var(--settings-round-icon-button-size);",
        "padding-right: calc(var(--settings-round-icon-button-size) + 20px);",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_events_table_consumes_shared_scrollable_table_tokens() -> None:
    """Protect the log stream table against drifting away from sibling table tokens."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".events-table-shell {",
        "background: var(--frosted-glass-background);",
        "border: var(--scrollable-data-table-summary-border);",
        "background: var(--scrollable-data-table-summary-background);",
        "box-shadow: var(--scrollable-data-table-summary-shadow);",
        "backdrop-filter: var(--scrollable-data-table-summary-blur);",
        "padding: var(--scrollable-data-table-header-padding);",
        "padding: var(--scrollable-data-table-cell-padding);",
        "color: var(--scrollable-data-table-header-color);",
        "background: var(--scrollable-data-table-row-background);",
        "background: var(--scrollable-data-table-row-background-alt);",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_cache_dock_menu_and_gallery_use_shared_tokens() -> None:
    """Protect the sibling-style cache menu and local media browser compatibility layer."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".sidebar-dock:has(> .sidebar-dock-cache-menu > .sidebar-dock-item.is-active)",
        ".sidebar-dock-cache-dropdown {",
        ".sidebar-dock-cache-menu.is-cache-source-menu-open .sidebar-dock-cache-dropdown {",
        "width: min(248px, calc(100vw - 24px));",
        ".sidebar-dock-cache-dropdown .sidebar-dock-cache-option",
        ".sidebar-dock-cache-option .cache-source-mark",
        ".cache-source-mark::before",
        "mask-image: var(--cache-source-mark);",
        "background-color: currentColor;",
        ".sidebar-dock-cache-current",
        ".dock-icon-cache",
        "mask: url(\"/static/images/externaldrive.fill.badge.checkmark.svg\")",
        ".dock-icon-browser",
        "mask: url(\"/static/images/square.grid.2x2.fill.svg\")",
        ".browser-gallery",
        "grid-template-columns: repeat(4, minmax(0, 1fr));",
        ".browser-media-remove[hidden]",
        ".browser-dialog::backdrop",
        "--browser-media-viewer-control-gap: clamp(12px, 1.5vw, 18px);",
        ".browser-video-nav-button:first-child",
        ".browser-video-nav-button:last-child",
        "top: calc(var(--browser-media-frame-radius) - (var(--browser-media-viewer-control-size) / 2));",
        "background: var(--frosted-glass-background);",
        "border: var(--frosted-glass-border);",
        "box-shadow: var(--frosted-glass-shadow);",
        "backdrop-filter: var(--frosted-glass-blur);",
        "@media (prefers-reduced-motion: reduce)",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_waiting_feedback_uses_the_sibling_vector_spinner_and_modal() -> None:
    """Keep waiting states informative and aligned with the sibling workspace dialog."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".suggestion-loading-spinner {",
        'mask: url("/static/images/loading.spinner.svg") center/contain no-repeat;',
        "animation: ticker-suggestion-loading 700ms linear infinite;",
        ".workspace-modal-overlay {",
        "place-items: center;",
        ".workspace-modal-dialog {",
        "grid-template-columns: var(--workspace-modal-icon-size) minmax(0, 1fr);",
        ".workspace-modal-copy {",
        ".browser-media-loading-notice {",
        ".shadow-backup-status-spinner {",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_chatgpt_prompt_preview_stays_fixed_while_the_dialog_expands() -> None:
    """Keep long Markdown prompts from changing neighboring card heights."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".browser-media-prompt {",
        ".browser-media-prompt-preview {",
        "height: 4.2em;",
        ".browser-media-prompt-markdown blockquote {",
        ".browser-media-prompt-markdown pre {",
        ".browser-prompt-dialog {",
        "max-height: calc(100svh - 48px);",
        ".browser-prompt-dialog-content {",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_browser_pagination_matches_the_sibling_floating_control_states() -> None:
    """Keep unselected browser pagination controls visually transparent by default."""
    stylesheet = _stylesheet()
    button_start = stylesheet.index(".browser-pagination .local-store-page-button {")
    button_rule = stylesheet[button_start:stylesheet.index("\n}", button_start)]
    hover_start = stylesheet.index(
        ".browser-pagination .local-store-page-button:not(.is-active):not(.local-store-page-placeholder):hover,"
    )
    hover_rule = stylesheet[hover_start:stylesheet.index("\n}", hover_start)]

    for token in (
        "border-radius: 50%;",
        "border-color: transparent;",
        "background: transparent;",
        "box-shadow: none;",
        "backdrop-filter: none;",
        "color: var(--theme-text);",
    ):
        assert token in button_rule

    assert "border: var(--frosted-glass-border);" in hover_rule
    assert "transform:" not in hover_rule
