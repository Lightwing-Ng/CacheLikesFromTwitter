"""Regression tests for synchronized sibling-project color tokens.

Code version: v1.24.2-codex.1
"""

from pathlib import Path


STYLE_PATH = Path(__file__).resolve().parents[1] / "app/web/static/style.css"


def _stylesheet() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


def test_settings_fields_use_a_single_column_layout() -> None:
    """Keep every Settings category free of side-by-side field groups."""
    stylesheet = _stylesheet()

    assert ".settings-category-panel .field-grid {" in stylesheet
    assert "grid-template-columns: minmax(0, 1fr);" in stylesheet


def test_cache_sidebar_parameter_grids_use_one_field_per_row() -> None:
    """Prevent cache sidebar parameter fields from sharing a horizontal row."""
    stylesheet = _stylesheet()
    selector_start = stylesheet.index(".sidebar-section .field-grid {")
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert "grid-template-columns: minmax(0, 1fr);" in selector_rule


def test_settings_save_action_reuses_the_sibling_action_package() -> None:
    """Keep the Settings save control on the sibling composite-card pattern."""
    stylesheet = _stylesheet()

    expected_fragments = (
        ".settings-action-package {",
        "grid-template-columns: 36px minmax(0, 1fr);",
        "--settings-action-package-max-width: 680px;",
        ".settings-action-package-icon-shell {",
        ".settings-action-package-copy {",
        "display: contents;",
        ".settings-action-package-form {",
        "justify-self: end;",
        ".settings-inline-button-primary {",
    )
    for fragment in expected_fragments:
        assert fragment in stylesheet


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


def test_theme_toggle_and_session_view_use_sibling_pressed_controls() -> None:
    """Keep global appearance and session mode controls on the sibling interaction pattern."""
    stylesheet = _stylesheet()

    expected_fragments = (
        '.global-theme-toggle[data-effective-theme="light"] .icon {',
        'mask-image: url("/static/images/moon.fill.svg");',
        '.global-theme-toggle[data-effective-theme="dark"] .icon {',
        'mask-image: url("/static/images/sun.max.fill.svg");',
        '.browser-session-control-button[aria-pressed="true"] {',
        "transform: translateY(1px) scale(0.985);",
        ':root:not([data-theme-override="light"]) {',
        ':root[data-theme-override="dark"] {',
    )
    for fragment in expected_fragments:
        assert fragment in stylesheet


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
        ".sidebar-backdrop[hidden] {",
        "display: none !important;",
        ".sidebar-section > .section-heading {",
        "position: relative;",
        "min-height: var(--settings-round-icon-button-size);",
        "padding-right: 0;",
        ".section-heading > .cache-source-switcher-combobox {",
        "flex: 1 1 100%;",
        "width: 100%;",
        ".sidebar-section > .section-heading > .cache-phase-live-marker {",
        "right: 38px;",
        "pointer-events: none;",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_sidebar_titles_reuse_sibling_hero_tokens() -> None:
    """Keep sidebar titles aligned with the sibling project's shared hero rail."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--font-card-title: var(--font-title-md);",
        "--workspace-title-rail-control-height: var(--settings-round-icon-button-size);",
        "font-size: var(--font-card-title);",
        "line-height: 1.18;",
        "letter-spacing: 0;",
        ".sidebar .hero {",
        "margin-bottom: 24px;",
        "min-height: var(--workspace-title-rail-control-height);",
    )

    for token in expected_tokens:
        assert token in stylesheet

    assert ".hero::after" not in stylesheet


def test_cache_source_heading_uses_the_shared_picker_and_live_marker() -> None:
    """Keep the cache heading aligned with the sibling picker and breathing marker."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--cache-phase-live-marker-size: 8px;",
        "--cache-phase-live-marker-color: var(--theme-accent-positive);",
        "--cache-phase-live-marker-duration: 1.8s;",
        ".section-heading > .cache-source-switcher-combobox {",
        "flex: 1 1 auto;",
        ".cache-source-switcher-combobox.is-cache-source-menu-open .cache-source-switcher-dropdown {",
        ".cache-phase-live-marker {",
        "box-shadow: 0 0 0 2px color-mix(in srgb, var(--cache-phase-live-marker-color) 18%, transparent);",
        ".cache-phase-live-marker::before,",
        "animation: cachePhaseLiveBreath var(--cache-phase-live-marker-duration) var(--motion-emphasized) infinite;",
        "animation-delay: 0.9s;",
        "@keyframes cachePhaseLiveBreath {",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_events_table_consumes_shared_scrollable_table_tokens() -> None:
    """Protect the log stream table against drifting away from sibling table tokens."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".events-table-shell {",
        "background: var(--frosted-glass-background);",
        "border: var(--frosted-glass-border);",
        "box-shadow: var(--frosted-glass-shadow);",
        "backdrop-filter: var(--frosted-glass-blur);",
        "padding: var(--scrollable-data-table-header-padding);",
        "padding: var(--scrollable-data-table-cell-padding);",
        "color: var(--scrollable-data-table-header-color);",
        "background: var(--scrollable-data-table-row-background);",
        "background: var(--scrollable-data-table-row-background-alt);",
        ".browser-pagination.events-pagination {",
        "bottom: var(--events-pagination-edge-inset);",
        ".browser-pagination.events-pagination .local-store-page-button {",
    )

    for token in expected_tokens:
        assert token in stylesheet

    assert ".events-page-button" not in stylesheet
    assert ".events-page-indicator" not in stylesheet


def test_cache_dock_direct_link_and_gallery_use_shared_tokens() -> None:
    """Protect the direct cache dock link and local media browser compatibility layer."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".sidebar-dock:has(> .sidebar-dock-item:nth-child(1).is-active)",
        ".cache-source-mark::before",
        "mask-image: var(--cache-source-mark);",
        "background-color: currentColor;",
        ".dock-icon-cache",
        "mask: url(\"/static/images/externaldrive.fill.badge.checkmark.svg\")",
        ".dock-icon-browser",
        "mask: url(\"/static/images/photo.stack.svg\")",
        ".browser-empty-icon::before",
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

    for removed_menu_selector in (
        ".sidebar-dock-cache-menu",
        ".sidebar-dock-cache-trigger",
        ".sidebar-dock-cache-dropdown",
        ".sidebar-dock-cache-option",
    ):
        assert removed_menu_selector not in stylesheet


def test_waiting_feedback_uses_the_sibling_vector_spinner_and_modal() -> None:
    """Keep waiting states informative and aligned with the sibling workspace dialog."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".suggestion-loading-spinner {",
        ".suggestion-loading-spinner[hidden] {",
        "display: none;",
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


def test_browser_session_refresh_uses_the_modal_dialog_banner_message() -> None:
    """Match the sibling floating modal banner for completed session refreshes."""
    stylesheet = _stylesheet()

    for token in (
        ".browser-session-refresh-banner {",
        ".notice-floating-banner-global.browser-session-refresh-banner {",
        "animation-name: browserSessionRefreshBannerFadeIn;",
        "grid-template-columns: var(--workspace-modal-icon-size) minmax(0, 1fr);",
        "calc(var(--workspace-modal-pad-inline) + var(--workspace-modal-title-margin-end))",
        ".browser-session-refresh-banner-icon {",
        'mask: url("/static/images/info.circle.fill.svg") center/contain no-repeat;',
        ".browser-session-refresh-banner-heading {",
        ".browser-session-refresh-banner-copy {",
    ):
        assert token in stylesheet


def test_browser_session_controls_use_standard_round_buttons_and_frosted_tooltips() -> None:
    """Render both session controls as round icon buttons with structured frosted tooltips."""
    stylesheet = _stylesheet()
    rule_start = stylesheet.index(".browser-session-control-button {")
    rule = stylesheet[rule_start:stylesheet.index("\n}", rule_start)]

    for token in (
        "width: var(--settings-round-icon-button-size);",
        "height: var(--settings-round-icon-button-size);",
        "border: var(--settings-round-icon-button-border);",
        "border-radius: var(--settings-round-icon-button-radius);",
        "background: var(--settings-round-icon-button-background);",
        "box-shadow: var(--settings-round-icon-button-shadow);",
        "color: var(--settings-round-icon-button-color);",
    ):
        assert token in rule

    for token in (
        ".browser-session-control-tooltip {",
        "border: var(--tooltip-border);",
        "background: var(--tooltip-background);",
        "box-shadow: var(--tooltip-shadow);",
        "backdrop-filter: var(--tooltip-blur);",
        "opacity: 0;",
        "visibility: hidden;",
        ".browser-session-control-button:hover > .browser-session-control-tooltip,",
        ".browser-session-control-button:focus-visible > .browser-session-control-tooltip {",
        ".browser-session-control-tooltip-title {",
        ".browser-session-control-tooltip-copy {",
    ):
        assert token in stylesheet

    assert ".browser-session-view-icon {" in stylesheet
    assert 'mask: url("/static/images/text.line.magnify.svg") center/contain no-repeat;' in stylesheet
    assert ".browser-session-refresh-icon {" in stylesheet
    assert 'mask: url("/static/images/icloud.and.arrow.down.svg") center/contain no-repeat;' in stylesheet
    assert ".browser-session-refresh-button::after" not in stylesheet


def test_chatgpt_prompt_expands_vertically_inside_its_media_card() -> None:
    """Keep prompt expansion inline, width-stable, and aligned with sibling round controls."""
    stylesheet = _stylesheet()
    gallery_start = stylesheet.index(".browser-gallery {")
    gallery_rule = stylesheet[gallery_start:stylesheet.index("\n}", gallery_start)]

    expected_tokens = (
        ".browser-media-prompt {",
        ".browser-media-prompt-expand {",
        ".browser-media-prompt-expand[hidden] {",
        "border-radius: 50%;",
        'mask: url("/static/images/rectangle.expand.vertical.svg") center/contain no-repeat;',
        'mask-image: url("/static/images/rectangle.compress.vertical.svg");',
        ".browser-media-prompt-preview {",
        "max-height: 4.2em;",
        ".browser-media-prompt.is-expanded .browser-media-prompt-preview {",
        ".browser-media-prompt.is-fully-visible .browser-media-prompt-preview::after {",
        "max-height: min(42rem, 70svh);",
        "overflow-y: auto;",
        ".browser-media-prompt-markdown blockquote {",
        ".browser-media-prompt-markdown pre {",
    )

    for token in expected_tokens:
        assert token in stylesheet

    assert "align-items: start;" in gallery_rule
    assert ".browser-prompt-dialog {" not in stylesheet


def test_prompt_label_matches_card_metadata_label_on_one_line() -> None:
    """Keep the prompt heading aligned with metadata terms without wrapping."""
    stylesheet = _stylesheet()
    label_start = stylesheet.index(".browser-media-prompt-label {")
    label_rule = stylesheet[label_start:stylesheet.index("\n}", label_start)]

    for token in (
        "display: block;",
        "color: var(--theme-muted);",
        "font-size: var(--font-ui-xs);",
        "font-weight: var(--font-weight-semibold);",
        "line-height: 1.35;",
        "white-space: nowrap;",
    ):
        assert token in label_rule

    prompt_start = stylesheet.index(".browser-media-prompt {")
    prompt_rule = stylesheet[prompt_start:stylesheet.index("\n}", prompt_start)]
    assert "margin: 0 0 10px;" in prompt_rule
    assert "padding: 8px 11px 9px;" in prompt_rule


def test_browser_media_actions_use_standard_round_icon_controls() -> None:
    """Keep Safari, copy, and file-manager actions visually consistent."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".browser-media-card {",
        "overflow: visible;",
        ".browser-media-card:hover,",
        "z-index: var(--layer-control-affordance);",
        ".browser-media-round-action {",
        "width: var(--settings-round-icon-button-size);",
        "height: var(--settings-round-icon-button-size);",
        "border-radius: 50%;",
        'mask: url("/static/images/safari.svg") center/contain no-repeat;',
        'mask: url("/static/images/finder.svg") center/contain no-repeat;',
        ".browser-media-reveal.is-revealed {",
        "border-radius: 0 0 calc(var(--radius-panel) - 1px) calc(var(--radius-panel) - 1px);",
        "border-radius: calc(var(--radius-panel) - 1px) calc(var(--radius-panel) - 1px) 0 0;",
        "border-radius: calc(var(--radius-panel) - 1px) 0 0 calc(var(--radius-panel) - 1px);",
    )

    for token in expected_tokens:
        assert token in stylesheet

    assert ".browser-media-source-link-label {" not in stylesheet
    assert ".browser-media-source-link-url," not in stylesheet


def test_browser_view_dock_switches_between_grid_and_list_layouts() -> None:
    """Keep media view controls aligned with the existing frosted dock system."""
    stylesheet = _stylesheet()

    expected_tokens = (
        ".browser-view-dock {",
        ".browser-view-dock::before {",
        ".browser-view-dock-item {",
        ".browser-view-dock-item.is-active {",
        'mask: url("/static/images/list.dash.header.rectangle.svg") center/contain no-repeat;',
        'mask: url("/static/images/film.circle.svg") center/contain no-repeat;',
        '.browser-gallery[data-view="list"] {',
        '.browser-gallery[data-view="list"] .browser-media-open {',
        "grid-column: 1 / 3;",
        "grid-row: 1 / 4;",
        "grid-template-columns: 168px minmax(0, 1fr);",
        "grid-template-rows: subgrid;",
        "grid-template-rows: auto minmax(90px, 1fr) auto;",
        "place-items: center;",
        "object-fit: contain;",
        '.browser-gallery[data-view="list"] .browser-media-card-body {',
        "grid-row: 1;",
        "align-content: start;",
        "align-items: start;",
        "padding: 12px 14px 4px;",
        "grid-template-columns: 96px minmax(0, 1fr);",
        "justify-items: start;",
        "text-align: left;",
        "grid-template-rows: auto minmax(0, 1fr);",
        '.browser-gallery[data-view="list"] .browser-media-prompt-heading {',
        "align-items: flex-start;",
        "min-height: 72px;",
        '.browser-gallery[data-view="list"] .browser-media-prompt-label::after {',
        '.browser-gallery[data-view="list"] .browser-media-source-actions {',
        "grid-column: 2;",
        "grid-row: 3;",
        "justify-self: end;",
        "align-self: end;",
        '.browser-gallery[data-view="list"] .browser-media-remove {',
        "left: 12px;",
        '.browser-gallery[data-view="list"] .browser-media-remove-label {',
        "text-overflow: ellipsis;",
    )

    for token in expected_tokens:
        assert token in stylesheet


def test_browser_grid_filename_wraps_without_hiding_its_extension() -> None:
    """Allow grid filenames to wrap fully while keeping list rows compact."""
    stylesheet = _stylesheet()
    title_start = stylesheet.index(".browser-media-card-title {")
    title_rule = stylesheet[title_start:stylesheet.index("\n}", title_start)]
    list_title_start = stylesheet.index(
        '.browser-gallery[data-view="list"] .browser-media-card-title {'
    )
    list_title_rule = stylesheet[
        list_title_start:stylesheet.index("\n}", list_title_start)
    ]

    assert "display: block;" in title_rule
    assert "overflow-wrap: anywhere;" in title_rule
    assert "word-break: break-word;" in title_rule
    assert "-webkit-line-clamp" not in title_rule
    assert "display: block;" in list_title_rule
    assert "white-space: nowrap;" in list_title_rule


def test_chatgpt_session_metrics_put_the_session_name_on_its_own_row() -> None:
    """Keep the consolidated ChatGPT session metrics readable across breakpoints."""
    stylesheet = _stylesheet()

    for token in (
        ".browser-metric-grid.browser-session-metric-grid {",
        "grid-template-columns: repeat(2, minmax(0, 1fr));",
        ".browser-session-name-metric {",
        "grid-column: 1 / -1;",
        ".browser-session-controls-row {",
        "justify-content: flex-end;",
    ):
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


def test_browser_pagination_range_menu_uses_glass_and_gel_motion_tokens() -> None:
    """Keep range expansion aligned with the sibling popover motion language."""
    stylesheet = _stylesheet()

    for token in (
        ".browser-pagination-range-menu {",
        "background: var(--frosted-glass-opaque-background, var(--frosted-glass-background));",
        "background-clip: padding-box;",
        "backdrop-filter: var(--frosted-glass-blur);",
        "overflow-y: hidden;",
        ".browser-pagination-range-menu.is-scrollable {",
        "overflow-y: auto;",
        "border-radius: var(--radius-soft);",
        "animation: browser-pagination-range-gel-in 300ms var(--motion-bouncy) both;",
        "@keyframes browser-pagination-range-gel-in {",
        "grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));",
    ):
        assert token in stylesheet
