"""Regression tests for synchronized sibling-project color tokens.

Code version: v1.36.0-codex.1
"""

from pathlib import Path


STYLE_PATH = Path(__file__).resolve().parents[1] / "app/web/static/style.css"


def _stylesheet() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


def test_typography_matches_the_sibling_font_contract() -> None:
    """Keep the local font family, primitives, and semantic aliases in sync."""
    stylesheet = _stylesheet()

    expected_tokens = (
        '@font-face {',
        'font-family: "Univers Next for HSBC";',
        'src: url("/static/fonts/UniversNextforHSBC.ttc#UniversNextforHSBC-Regular")',
        "--font-size-1: 11px;",
        "--font-size-2: 12px;",
        "--font-size-3: 13px;",
        "--font-size-4: 14px;",
        "--font-size-5: 15px;",
        "--font-size-6: 24px;",
        "--font-size-7: 32px;",
        "--font-size-8: 36px;",
        '--font-family-brand: "Univers Next for HSBC";',
        "--font-ui-md: var(--font-size-4);",
        "--font-ui-lg: var(--font-size-5);",
        "--font-title-md: var(--font-size-6);",
        "--font-metric-xl: var(--font-size-8);",
        "--font-table-head: var(--font-size-3);",
        "--font-card-subtitle: var(--font-ui-lg);",
        "--font-metric-value: var(--font-metric-md);",
        "--font-numeric-fraction-scale: 0.76;",
    )
    for token in expected_tokens:
        assert token in stylesheet


def test_settings_fields_use_a_single_column_layout() -> None:
    """Keep every Settings category free of side-by-side field groups."""
    stylesheet = _stylesheet()

    assert ".settings-category-panel .field-grid {" in stylesheet
    assert "grid-template-columns: minmax(0, 1fr);" in stylesheet


def test_form_inputs_use_regular_weight_monospace_text() -> None:
    """Keep path and numeric values legible without an inherited bold weight."""
    stylesheet = _stylesheet()
    selector_start = stylesheet.index('input[type="text"],\ninput[type="number"] {')
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert 'font-family: "SFMono-Regular", "SF Mono", Menlo, monospace;' in selector_rule
    assert "font-weight: var(--font-weight-regular);" in selector_rule


def test_cache_sidebar_cards_and_url_inputs_use_the_shared_control_treatment() -> None:
    """Keep shared configuration tactile and URL values legible in monospace."""
    stylesheet = _stylesheet()

    cache_card_start = stylesheet.index(".cache-common-config--physical {")
    cache_card_rule = stylesheet[cache_card_start:stylesheet.index("\n}", cache_card_start)]
    url_input_start = stylesheet.index('input[type="url"].text-input-control {')
    url_input_rule = stylesheet[url_input_start:stylesheet.index("\n}", url_input_start)]
    action_row_start = stylesheet.index('.page[data-cache-source="grok"] .sidebar-action-row {')
    action_row_rule = stylesheet[action_row_start:stylesheet.index("\n}", action_row_start)]

    for token in (
        "border: var(--frosted-glass-border);",
        "background: var(--frosted-glass-background);",
        "box-shadow: var(--frosted-glass-shadow),",
        "backdrop-filter: var(--frosted-glass-blur);",
    ):
        assert token in cache_card_rule

    assert 'font-family: "SFMono-Regular", "SF Mono", Menlo, monospace;' in url_input_rule
    assert "font-weight: var(--font-weight-regular);" in url_input_rule
    assert "padding-block: 10px;" in action_row_rule


def test_settings_directory_picker_uses_the_folder_icon() -> None:
    """Keep directory picker buttons compact and backed by the local folder asset."""
    stylesheet = _stylesheet()

    assert ".settings-directory-choose-icon {" in stylesheet
    assert "width: var(--settings-round-icon-button-size);" in stylesheet
    assert "height: var(--settings-round-icon-button-icon-size);" in stylesheet
    assert 'mask: url("/static/images/folder.fill.svg") center/contain no-repeat;' in stylesheet


def test_cache_sidebar_parameter_grids_use_one_field_per_row() -> None:
    """Prevent cache sidebar parameter fields from sharing a horizontal row."""
    stylesheet = _stylesheet()
    selector_start = stylesheet.index(".sidebar-section .field-grid {")
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert "grid-template-columns: minmax(0, 1fr);" in selector_rule


def test_browser_grid_cards_stretch_to_the_row_height() -> None:
    """Keep media cards bottom-aligned when their content heights differ."""
    stylesheet = _stylesheet()
    selector_start = stylesheet.index(".browser-gallery {")
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert "align-items: stretch;" in selector_rule


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


def test_non_pill_corner_radii_use_the_shared_ten_pixel_value() -> None:
    """Keep ordinary rounded surfaces at 10px while preserving pill and circle shapes."""
    stylesheet = _stylesheet()

    expected_tokens = (
        "--radius-panel: 10px;",
        "--radius-soft: 10px;",
        "--strategy-stepper-radius: 10px;",
        "--browser-media-frame-radius: var(--radius-panel);",
        "border-radius: var(--browser-media-frame-radius, var(--radius-panel));",
        "border-radius: 0 0 var(--radius-panel) var(--radius-panel);",
        "border-radius: var(--radius-panel) var(--radius-panel) 0 0;",
        "border-radius: var(--radius-panel) 0 0 var(--radius-panel);",
    )
    for token in expected_tokens:
        assert token in stylesheet

    for non_shared_radius in ("6px", "8px", "9px", "12px", "18px", "20px", "24px", "30px"):
        assert f"border-radius: {non_shared_radius};" not in stylesheet


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
        "[hidden] {",
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
        ".sidebar-dock:has(> .sidebar-dock-item:nth-child(4).is-active)",
        ".cache-source-mark::before",
        "mask-image: var(--cache-source-mark);",
        "background-color: currentColor;",
        ".cache-source-mark.is-full-color::before",
        "background: var(--cache-source-mark) center / contain no-repeat;",
        "mask-image: none;",
        ".dock-icon-chats",
        "mask: url(\"/static/images/arrow.down.message.fill.svg\")",
        ".dock-icon-cache",
        "mask: url(\"/static/images/photo.badge.arrow.down.fill.svg\")",
        ".dock-icon-local-resources",
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

    assert "align-items: stretch;" in gallery_rule
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
        "border-radius: 0 0 var(--radius-panel) var(--radius-panel);",
        "border-radius: var(--radius-panel) var(--radius-panel) 0 0;",
        "border-radius: var(--radius-panel) 0 0 var(--radius-panel);",
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


def test_motion_tokens_match_the_sibling_non_linear_motion_contract() -> None:
    """Keep shared transitions valid and aligned with the sibling motion foundation."""
    stylesheet = _stylesheet()

    for token in (
        "--motion-duration-fast: 160ms;",
        "--motion-duration-standard: 240ms;",
        "--motion-duration-emphasized: 420ms;",
        "--motion-duration-spatial: 560ms;",
        "--motion-standard: cubic-bezier(0.2, 0, 0, 1);",
        "--motion-emphasized: cubic-bezier(0.16, 1, 0.3, 1);",
        "--motion-inertial: cubic-bezier(0.16, 1, 0.3, 1);",
        "--motion-bouncy: cubic-bezier(0.34, 1.56, 0.64, 1);",
        "--motion-overshoot: cubic-bezier(0.34, 1.32, 0.64, 1);",
    ):
        assert token in stylesheet


def test_browser_pagination_indicator_uses_composited_spatial_motion() -> None:
    """Keep pagination indicator movement smooth when page controls are rebuilt."""
    stylesheet = _stylesheet()
    indicator_start = stylesheet.index(".browser-pagination .local-store-pagination-indicator {")
    indicator_rule = stylesheet[indicator_start:stylesheet.index("\n}", indicator_start)]

    for token in (
        "transform: translate3d(0, 0, 0) scale(1);",
        "transition:",
        "transform var(--local-store-pagination-motion-duration) var(--local-store-pagination-motion-easing),",
        "opacity var(--motion-duration-standard) var(--motion-standard);",
        "will-change: transform, opacity;",
    ):
        assert token in indicator_rule


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


def test_browser_content_mode_control_uses_the_sibling_blue_pill_pattern() -> None:
    """Keep the media/text switcher aligned with the sibling segmented control."""
    stylesheet = _stylesheet()

    for token in (
        ".browser-content-mode-control {",
        "grid-template-columns: repeat(var(--browser-mode-option-count), minmax(0, 1fr));",
        "border-radius: var(--radius-pill);",
        "background: var(--accent-fill);",
        ".browser-content-mode-control:has(> .browser-content-mode-option:last-child input:checked)::before {",
        "transform: translateX(calc(100% + 4px));",
        ".browser-content-mode-option input:checked + span {",
        "color: var(--accent-contrast);",
        ".browser-chat-list {",
        ".browser-chat-message {",
        ".browser-chat-message-link {",
        ".chart-panel.workspace.browser-workspace {",
        ".browser-text-summary-card {",
        "height: auto;",
        ".browser-session-table-number {",
        "text-align: center;",
        ".browser-chat-role-mark {",
        ".browser-session-table-role {",
        "display: table-cell;",
        ".browser-session-detail-actions {",
        ".browser-session-neighbor-nav {",
        ".browser-session-neighbor-button:disabled {",
        ".browser-session-neighbor-prev-icon {",
        ".browser-session-neighbor-next-icon {",
        ".browser-session-actions {",
        ".browser-session-actions-trigger {",
        ".browser-session-actions-drawer {",
        ".browser-session-action-link {",
        ".browser-session-export-icon {",
        ".browser-session-index-table .browser-session-col-number {",
        ".browser-session-table-source {",
        ".browser-session-source-mark,",
        ".browser-session-table-role > .browser-chat-role-mark,",
        "display: grid;",
        "margin-inline: auto;",
        ".browser-session-table-updated-link {",
    ):
        assert token in stylesheet


def test_browser_workspace_prefers_simplified_chinese_font_fallbacks() -> None:
    """Keep Local resources text rendered with Simplified Chinese glyph forms."""
    stylesheet = _stylesheet()
    workspace_start = stylesheet.index(".browser-workspace {")
    workspace_rule = stylesheet[workspace_start:stylesheet.index("\n}", workspace_start)]
    font_family = 'font-family: var(--font-family-brand), "Helvetica Neue", Helvetica, Arial, "PingFang SC", "PingFang TC", "PingFang HK", "Microsoft YaHei", "Microsoft JhengHei", sans-serif;'

    assert font_family in workspace_rule
    assert workspace_rule.index('"PingFang SC"') < workspace_rule.index('"PingFang HK"')
    assert workspace_rule.index('"Microsoft YaHei"') < workspace_rule.index('"Microsoft JhengHei"')


def test_browser_summary_card_aligns_pagination_with_the_sidebar_dock() -> None:
    """Let the session table consume the space above the shared bottom dock."""
    stylesheet = _stylesheet()
    summary_start = stylesheet.index(".browser-summary-card {")
    summary_rule = stylesheet[summary_start:stylesheet.index("\n}", summary_start)]

    assert "padding-bottom: var(--sidebar-dock-bottom-gap);" in summary_rule
    assert ".browser-text-summary-card .browser-session-table-shell {" in stylesheet
    assert ".browser-text-summary-card .browser-session-table-scroll {" in stylesheet


def test_agent_workspace_reuses_shared_glass_and_responsive_tokens() -> None:
    """Keep the fourth dock item and Agent workspace aligned with the shared shell."""
    stylesheet = _stylesheet()

    for token in (
        "/* Code version: v2.62.0-codex.1 */",
        ".dock-brand-icon {",
        "width: 22px;",
        "height: 22px;",
        "/* Native subscription Agent with an optional DevSpace web bridge. */",
        ".agent-connect-fields {",
        "grid-template-columns: minmax(0, 1fr);",
        "gap: 14px;",
        ".agent-combobox.is-agent-combobox-open .agent-combobox-dropdown:not([hidden]) {",
        ".agent-runtime-log-open-icon {",
        'mask: url("/static/images/finder.svg") center/contain no-repeat;',
        ".agent-port-field {",
        "grid-column: auto;",
        ".settings-category-nav-item-agent {",
        "--settings-category-active-index: 5;",
        ".agent-workspace-grid {",
        "grid-template-columns: minmax(0, 1fr);",
        "grid-template-rows: auto minmax(260px, 1fr);",
        ".agent-composer-shell:focus-within {",
        ".agent-composer-submit-icon {",
        "border-radius: var(--radius-soft);",
        ".agent-readiness[data-ready=\"true\"] .agent-readiness-dot,",
        ".agent-activity-panel {",
        ".agent-activity-item[data-status=\"completed\"] .agent-activity-status {",
        ".settings-agent-runtime-status {",
        ".agent-response-output {",
        ".agent-response-output h1,",
        "font-size: var(--font-card-title);",
        "@media (max-width: 1100px) {",
    ):
        assert token in stylesheet
