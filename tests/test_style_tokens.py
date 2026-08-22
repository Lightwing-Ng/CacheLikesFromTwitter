"""Regression tests for synchronized sibling-project color tokens.

Code version: v1.47.12-codex.6
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
        '--font-family-cjk: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;',
        '--font-family-mono-cjk: ui-monospace, "SFMono-Regular", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", monospace;',
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


def test_routine_labels_use_restrained_font_weights() -> None:
    """Keep ordinary labels readable while reserving bold for explicit emphasis."""
    stylesheet = _stylesheet()

    expected_rules = {
        ".workspace-kicker,": "font-weight: var(--font-weight-semibold);",
        ".browser-session-panel-label {": "font-weight: var(--font-weight-regular);",
        ".field > span,": "font-weight: var(--font-weight-regular);",
        ".field > .field-help {": "font-weight: var(--font-weight-regular);",
        ".cache-common-config-title {": "font-weight: var(--font-weight-regular);",
        ".cache-number-label {": "font-weight: var(--font-weight-regular);",
        ".summary-row dt {": "font-weight: var(--font-weight-regular);",
        ".events-table thead th {": "font-weight: var(--font-weight-semibold);",
    }

    for selector, declaration in expected_rules.items():
        selector_start = stylesheet.index(selector)
        selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]
        assert declaration in selector_rule
        assert "font-weight: var(--font-weight-bold);" not in selector_rule


def test_settings_fields_use_a_single_column_layout() -> None:
    """Keep every Settings category free of side-by-side field groups."""
    stylesheet = _stylesheet()

    assert ".settings-category-panel .field-grid {" in stylesheet
    assert "grid-template-columns: minmax(0, 1fr);" in stylesheet


def test_browser_filter_labels_use_the_medium_weight_token() -> None:
    """Give Local resources filter labels the shared medium emphasis."""
    stylesheet = _stylesheet()
    selector_start = stylesheet.index(".browser-filter-field > span {")
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert "font-weight: var(--font-weight-medium);" in selector_rule


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
    action_slot_start = stylesheet.index(".cache-action-row {")
    action_slot_rule = stylesheet[action_slot_start:stylesheet.index("\n}", action_slot_start)]
    action_slot_buttons_start = stylesheet.index(".cache-action-row .sidebar-form-stop,")
    action_slot_buttons_rule = stylesheet[
        action_slot_buttons_start:stylesheet.index("\n}", action_slot_buttons_start)
    ]

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
    assert "grid-template-columns: minmax(0, 1fr);" in action_slot_rule
    assert "grid-column: 1;" in action_slot_buttons_rule
    assert "justify-self: end;" in action_slot_buttons_rule


def test_settings_directory_picker_uses_the_folder_icon() -> None:
    """Keep directory picker buttons compact and backed by the local folder asset."""
    stylesheet = _stylesheet()

    assert ".settings-directory-choose-icon {" in stylesheet
    assert "width: var(--settings-round-icon-button-size);" in stylesheet
    assert "height: var(--settings-round-icon-button-icon-size);" in stylesheet
    assert 'mask: url("/static/images/folder.fill.svg") center/contain no-repeat;' in stylesheet


def test_cache_status_message_hangs_under_the_account_label() -> None:
    """Keep wrapped readiness copy aligned after the leading status icon."""
    stylesheet = _stylesheet()
    selector_start = stylesheet.index('.browser-session-status-message[data-role="browser-session-message"] {')
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert "--browser-session-status-indent: calc(18px + 8px);" in selector_rule
    assert "padding-inline-start: var(--browser-session-status-indent);" in selector_rule
    assert "text-indent: calc(-1 * var(--browser-session-status-indent));" in selector_rule


def test_cache_output_directory_reuses_the_standard_folder_button() -> None:
    """Keep the Cache output action on the shared circular directory-control contract."""
    stylesheet = _stylesheet()

    assert ".output-directory-status {" in stylesheet
    assert ".settings-directory-choose-button," in stylesheet
    assert ".settings-directory-choose-icon {" in stylesheet


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


def test_settings_action_packages_reuse_the_sibling_composite_card() -> None:
    """Keep Settings action surfaces on the sibling composite-card pattern."""
    stylesheet = _stylesheet()

    expected_fragments = (
        ".settings-action-package {",
        "grid-template-columns: 36px minmax(0, 1fr);",
        "--settings-action-package-row-gap: 8px;",
        "--settings-action-package-max-width: 680px;",
        "background: var(--settings-action-package-background);",
        "border: var(--settings-action-package-border);",
        ".settings-action-package-icon-shell {",
        ".settings-action-package-copy {",
        "display: contents;",
        ".settings-action-package-form {",
        "justify-self: end;",
        ".settings-action-package:has(.settings-service-name) {",
        ".settings-agent-terminal-authorization-status {",
        ".settings-agent-terminal-authorization-status[hidden] {",
        "--settings-action-button-min-height: 32px;",
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
        "--workspace-title-rail-collapsed-pad-inline-start: calc(var(--settings-round-icon-button-size) + 22px);",
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


def test_inline_notice_banner_keeps_copy_wide_and_status_chip_compact() -> None:
    """Keep icon-free inline notices readable beside their status chip."""
    stylesheet = _stylesheet()
    inline_start = stylesheet.index(".notice-inline-banner {")
    inline_rule = stylesheet[inline_start:stylesheet.index("\n}", inline_start)]

    for token in (
        "grid-template-columns: minmax(0, 1fr) auto;",
        "column-gap: var(--workspace-modal-column-gap);",
    ):
        assert token in inline_rule

    assert ".notice-inline-banner > .notice-floating-copy {" in stylesheet
    assert ".notice-inline-banner > .status-chip {" in stylesheet
    assert "grid-column: 1;" in stylesheet[stylesheet.index(".notice-inline-banner > .notice-floating-copy {"):]
    assert "justify-self: end;" in stylesheet[stylesheet.index(".notice-inline-banner > .status-chip {"):]
    assert "grid-template-columns: minmax(0, 1fr);" in stylesheet[stylesheet.index("@media (max-width: 560px)"):]


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
        "--browser-view-dock-item-step: calc(var(--settings-round-icon-button-size) + 6px);",
        ".browser-view-dock::before {",
        "width: var(--settings-round-icon-button-size);",
        "transform: translateX(var(--browser-view-active-shift, 0px));",
        ".browser-view-dock-item {",
        "width: var(--settings-round-icon-button-size);",
        "height: var(--settings-round-icon-button-size);",
        ".browser-view-dock-item.is-active {",
        "transform: none;",
        "width: var(--settings-round-icon-button-icon-size);",
        "height: var(--settings-round-icon-button-icon-size);",
        'mask: url("/static/images/rectangle.grid.1x3.fill.svg") center/contain no-repeat;',
        'mask: url("/static/images/rectangle.grid.3x2.fill.svg") center/contain no-repeat;',
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


def test_browser_cached_media_previews_preserve_full_image_ratio() -> None:
    """Keep cached image previews complete instead of forcing a crop box."""
    stylesheet = _stylesheet()
    preview_start = stylesheet.index(".browser-media-preview {")
    preview_rule = stylesheet[preview_start:stylesheet.index("\n}", preview_start)]
    media_start = stylesheet.index(".browser-media-preview img,\n.browser-media-preview video {")
    media_rule = stylesheet[media_start:stylesheet.index("\n}", media_start)]

    for token in ("height: auto;", "align-self: flex-start;"):
        assert token in preview_rule

    for token in (
        "height: auto;",
        "max-height: none;",
        "object-fit: contain;",
        "object-position: center;",
    ):
        assert token in media_rule

    assert "aspect-ratio: 4 / 3;" not in preview_rule
    assert "object-fit: cover;" not in media_rule


def test_browser_compact_actions_reuse_one_local_resources_pattern() -> None:
    """Keep compact utility links separate from the standard refresh button."""
    stylesheet = _stylesheet()
    for token in (
        "--control-compact-height: 28px;",
        "--control-form-height: 36px;",
    ):
        assert token in stylesheet

    compact_start = stylesheet.index(".ghost-link--compact {")
    compact_rule = stylesheet[compact_start:stylesheet.index("\n}", compact_start)]
    select_start = stylesheet.index(".trade-strategy-select,\n.form-select {")
    select_rule = stylesheet[select_start:stylesheet.index("\n}", select_start)]
    source_start = stylesheet.index(".trade-strategy-select.browser-source-filter-trigger {")
    source_rule = stylesheet[source_start:stylesheet.index("\n}", source_start)]
    status_start = stylesheet.index(".status-chip,\n.ghost-link {")
    status_rule = stylesheet[status_start:stylesheet.index("\n}", status_start)]
    icon_start = stylesheet.index(".browser-source-filter-trigger .browser-picker-selected-icon-shell {")
    icon_rule = stylesheet[icon_start:stylesheet.index("\n}", icon_start)]

    assert "min-height: var(--control-compact-height);" in compact_rule
    assert "height: var(--control-compact-height);" in compact_rule
    assert "padding-inline: 4px;" in compact_rule
    assert "font-size: var(--font-size-3);" in compact_rule
    assert "line-height: 1;" in compact_rule
    assert "min-height: var(--control-form-height);" in select_rule
    assert "min-height: var(--control-form-height);" in source_rule
    assert "min-height: var(--control-compact-height);" in status_rule
    assert "width: 18px;" in icon_rule
    assert "height: 18px;" in icon_rule

    browser_template = (
        STYLE_PATH.parents[1] / "templates/browser.html"
    ).read_text(encoding="utf-8")
    assert ".browser-filter-actions .ghost-link--compact {" in stylesheet
    assert ".browser-filter-actions .secondary-button {" in stylesheet
    media_start = stylesheet.index(".browser-chatgpt-media-link {")
    media_rule = stylesheet[media_start:stylesheet.index("\n}", media_start)]
    assert "width: fit-content;" in media_rule
    assert "justify-self: center;" in media_rule
    assert "width: 100%;" not in media_rule
    for markup in (
        'class="ghost-link ghost-link--compact browser-chatgpt-media-link"',
        'class="ghost-link ghost-link--compact browser-clear-link"',
        'class="ghost-link ghost-link--compact browser-session-back-link"',
    ):
        assert markup in browser_template
    assert 'class="secondary-button browser-refresh-button"' in browser_template

    cache_template = (
        STYLE_PATH.parents[1] / "templates/_cache_page.html"
    ).read_text(encoding="utf-8")
    assert 'class="ghost-link ghost-link--compact cache-settings-link"' in cache_template


def test_browser_session_actions_use_the_13px_annotation_size() -> None:
    """Keep the annotated Local resources actions on the shared text-size token."""
    stylesheet = _stylesheet()
    compact_start = stylesheet.index(".ghost-link--compact {")
    compact_rule = stylesheet[compact_start:stylesheet.index("\n}", compact_start)]
    media_start = stylesheet.index(".browser-chatgpt-media-link {")
    media_rule = stylesheet[media_start:stylesheet.index("\n}", media_start)]
    refresh_start = stylesheet.index(".browser-refresh-button {")
    refresh_rule = stylesheet[refresh_start:stylesheet.index("\n}", refresh_start)]

    assert "font-size: var(--font-size-3);" in compact_rule
    assert "font-size: var(--font-size-3);" not in media_rule
    assert "font-size: var(--font-size-3);" in refresh_rule


def test_browser_filter_select_uses_the_standard_frosted_popover_contract() -> None:
    """Keep Local resources select menus on the shared 10px frosted surface."""
    stylesheet = _stylesheet()
    dropdown_start = stylesheet.index(".trade-strategy-dropdown {")
    dropdown_rule = stylesheet[dropdown_start:stylesheet.index("\n}", dropdown_start)]
    select_shell_start = stylesheet.index(".browser-filter-select {")
    select_shell_rule = stylesheet[select_shell_start:stylesheet.index("\n}", select_shell_start)]
    open_rule_start = stylesheet.index(".browser-filter-select.is-open .browser-filter-select-dropdown {")
    open_rule = stylesheet[open_rule_start:stylesheet.index("\n}", open_rule_start)]

    for token in (
        "border-radius: var(--radius-soft);",
        "background: var(--glass-popover-background);",
        "box-shadow: var(--glass-popover-shadow),",
        "backdrop-filter: var(--glass-popover-blur);",
        "-webkit-backdrop-filter: var(--glass-popover-blur);",
    ):
        assert token in dropdown_rule
    assert "position: relative;" in select_shell_rule
    assert "z-index: var(--layer-global-popover);" in stylesheet
    assert "display: grid;" in open_rule


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
        "border-radius: 0;",
        ".browser-session-controls-row {",
        "justify-content: flex-end;",
    ):
        assert token in stylesheet

    session_name_start = stylesheet.index(".browser-metric-grid .browser-session-name-metric strong {")
    session_name_rule = stylesheet[session_name_start:stylesheet.index("\n}", session_name_start)]
    assert "background: none;" in session_name_rule
    assert "color: var(--accent-text);" in session_name_rule


def test_browser_media_primary_metric_and_prompt_copy_use_shared_sizes() -> None:
    """Keep media totals and inline prompt copy on the shared type scale."""
    stylesheet = _stylesheet()

    metric_start = stylesheet.index(".browser-media-primary-metric strong {")
    metric_rule = stylesheet[metric_start:stylesheet.index("\n}", metric_start)]
    prompt_start = stylesheet.index(".browser-media-prompt-preview {")
    prompt_rule = stylesheet[prompt_start:stylesheet.index("\n}", prompt_start)]

    assert "font-size: var(--font-metric-lg);" in metric_rule
    assert "font-size: var(--font-ui-sm);" in prompt_rule


def test_browser_media_preview_kind_uses_regular_weight() -> None:
    """Keep Image and Video preview labels on the regular UI weight."""
    stylesheet = _stylesheet()
    kind_start = stylesheet.index(".browser-preview-kind {")
    kind_rule = stylesheet[kind_start:stylesheet.index("\n}", kind_start)]

    assert "font-weight: var(--font-weight-regular);" in kind_rule


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

    ellipsis_start = stylesheet.index(".browser-pagination .local-store-page-ellipsis {")
    ellipsis_rule = stylesheet[ellipsis_start:stylesheet.index("\n}", ellipsis_start)]
    ellipsis_hover_start = stylesheet.index(
        ".browser-pagination .local-store-page-ellipsis:is(:hover, :focus-within) {"
    )
    ellipsis_hover_rule = stylesheet[ellipsis_hover_start:stylesheet.index("\n}", ellipsis_hover_start)]
    assert "border-radius: var(--radius-pill);" in ellipsis_rule
    assert "transition:" in ellipsis_rule
    assert "background: var(--frosted-glass-background-hover);" in ellipsis_hover_rule
    assert "box-shadow: var(--frosted-glass-shadow-active);" in ellipsis_hover_rule


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


def test_agent_response_pagination_ellipsis_has_a_visible_hover_affordance() -> None:
    """Keep the Agent response ellipsis visibly interactive on hover."""
    stylesheet = _stylesheet()

    for token in (
        ".browser-pagination.agent-response-pagination .local-store-page-ellipsis:hover,",
        "cursor: pointer;",
        "background: var(--frosted-glass-background-hover);",
        "color: var(--accent-text-hover);",
        ".browser-pagination.agent-response-pagination .local-store-page-ellipsis-dots {",
        "transform: scale(1.12);",
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
        "overflow-y: auto;",
        "scrollbar-width: thin;",
        ".browser-pagination-range-menu.is-scrollable {",
        "overflow-y: auto;",
        "border-radius: 10px;",
        "animation: browser-pagination-range-gel-in 300ms var(--motion-bouncy) both;",
        "@keyframes browser-pagination-range-gel-in {",
        "grid-template-columns: repeat(auto-fill, minmax(72px, 1fr));",
    ):
        assert token in stylesheet


def test_browser_pagination_range_menu_hides_the_scrollbar_track() -> None:
    """Keep the range menu scrollable without painting a scrollbar track."""
    stylesheet = _stylesheet()
    menu_start = stylesheet.index(".browser-pagination-range-menu {")
    menu_end = stylesheet.index(".browser-pagination-range-menu.is-scrollable {", menu_start)
    menu_rule = stylesheet[menu_start:menu_end]

    assert "overflow-y: auto;" in menu_rule
    assert "scrollbar-width: none;" in menu_rule
    assert "-ms-overflow-style: none;" in menu_rule
    assert "border-radius: 10px;" in menu_rule
    assert "scrollbar-gutter:" not in menu_rule
    scrollbar_start = stylesheet.index(".browser-pagination-range-menu::-webkit-scrollbar {")
    scrollbar_rule = stylesheet[scrollbar_start:stylesheet.index("\n}", scrollbar_start)]
    assert "width: 0;" in scrollbar_rule
    assert "height: 0;" in scrollbar_rule
    assert "background: transparent;" in scrollbar_rule
    track_start = stylesheet.index(".browser-pagination-range-menu::-webkit-scrollbar-track {")
    track_rule = stylesheet[track_start:stylesheet.index("\n}", track_start)]
    assert "background: transparent;" in track_rule


def test_browser_pagination_range_menu_respects_clipping_ancestors() -> None:
    """Keep the range menu inside the nearest scrollable workspace boundary."""
    script = (
        Path(__file__).resolve().parents[1] / "app/web/static/local-media-browser.js"
    ).read_text(encoding="utf-8")

    for token in (
        "function paginationRangeMenuClipBounds(picker)",
        "style.overflowX !== \"visible\" || style.overflowY !== \"visible\"",
        "const clipTop = Math.max(viewportInset, clipBounds.top);",
        "const clipBottom = Math.min(window.innerHeight - viewportInset, clipBounds.bottom);",
        "const spaceAbove = Math.max(0, pickerRect.top - clipTop - menuGap);",
        "const spaceBelow = Math.max(0, clipBottom - pickerRect.bottom - menuGap);",
    ):
        assert token in script


def test_segmented_control_uses_the_sibling_generic_pill_contract() -> None:
    """Keep Cache content modes on the sibling project's generic control contract."""
    stylesheet = _stylesheet()
    option_start = stylesheet.index(".segmented-control-option span {")
    option_rule = stylesheet[option_start:stylesheet.index("\n}", option_start)]
    selected_start = stylesheet.index(".segmented-control-option input:checked + span,")
    selected_rule = stylesheet[selected_start:stylesheet.index("\n}", selected_start)]

    for token in (
        ".segmented-control {",
        "--segmented-option-count: 2;",
        "grid-template-columns: repeat(var(--segmented-option-count), minmax(var(--segmented-option-min-width), 1fr));",
        "--mode-switch-radius: var(--radius-pill);",
        "--mode-switch-gap: 4px;",
        "border: 0;",
        ".segmented-control[data-option-count]::before {",
        "transform: translateX(calc((100% + var(--mode-switch-gap)) * var(--segmented-active-index, 0)));",
        ".segmented-control-option {",
        "text-decoration: none;",
        ".segmented-control-option input:checked + span,",
        "font-weight: var(--font-weight-regular);",
        "font-weight: var(--font-weight-bold);",
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
        ".browser-session-action-button {",
        ".browser-session-actions > .browser-session-open-original-button {",
        ".browser-session-actions > .browser-session-refresh-button {",
        ".browser-session-actions > .browser-session-full-export-button {",
        ".browser-session-drawer-refresh-icon {",
        'mask-image: url("/static/images/arrow.trianglehead.clockwise.svg");',
        ".browser-session-page-export-icon {",
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

    assert "font-weight: var(--font-weight-regular);" in option_rule
    assert "font-weight: var(--font-weight-bold);" not in option_rule
    assert "font-weight: var(--font-weight-bold);" in selected_rule


def test_browser_session_title_reuses_regular_untagged_link_contract() -> None:
    """Keep cached session titles readable without browser-default underlines."""
    stylesheet = _stylesheet()
    title_start = stylesheet.index(".browser-session-table-title,")
    title_rule = stylesheet[title_start:stylesheet.index("\n}", title_start)]

    for token in (
        "font-size: var(--font-ui-lg);",
        "font-weight: var(--font-weight-regular);",
        "text-decoration: none;",
    ):
        assert token in title_rule


def test_browser_session_updated_link_reuses_untagged_link_contract() -> None:
    """Keep updated timestamps readable without browser-default underlines."""
    stylesheet = _stylesheet()
    updated_start = stylesheet.index(".browser-session-table-updated-link {")
    updated_rule = stylesheet[updated_start:stylesheet.index("\n}", updated_start)]

    assert "text-decoration: none;" in updated_rule


def test_browser_session_counts_reuse_regular_weight_and_roomy_cell_padding() -> None:
    """Keep session message counts legible and separated from adjacent columns."""
    stylesheet = _stylesheet()
    count_start = stylesheet.index(".events-table tbody td.browser-session-table-count {")
    count_rule = stylesheet[count_start:stylesheet.index("\n}", count_start)]

    for token in (
        "font-weight: var(--font-weight-regular);",
        "padding-inline: 10px;",
    ):
        assert token in count_rule


def test_cache_overview_aligns_to_sidebar_height_on_desktop() -> None:
    """Keep the Cache overview edge aligned while the event log remains scrollable."""
    stylesheet = _stylesheet()

    for token in (
        "@media (min-width: 901px)",
        "main[data-cache-page] #workspace_panel > .workspace-header {",
        "overflow-y: auto;",
        "main[data-cache-page] #workspace_panel > .workspace-header > #overview {",
        "flex: 0 0 100%;",
        "main[data-cache-page] #workspace_panel > .workspace-header > .workspace-grid {",
        "height: auto;",
    ):
        assert token in stylesheet


def test_browser_prompt_source_header_is_centered() -> None:
    """Keep the saved-prompts Source header aligned with its centered marks."""
    stylesheet = _stylesheet()
    rule_start = stylesheet.index(".browser-prompt-table .browser-prompt-col-source {")
    rule = stylesheet[rule_start:stylesheet.index("\n}", rule_start)]

    assert "text-align: center;" in rule


def test_browser_prompts_primary_metric_uses_light_large_blue_value_type() -> None:
    """Keep ordinary browser summary metrics on the lightweight large blue style."""
    stylesheet = _stylesheet()
    metric_start = stylesheet.index(
        ".browser-metric-grid:not(.browser-session-metric-grid) > .metric-card strong {"
    )
    metric_rule = stylesheet[metric_start:stylesheet.index("\n}", metric_start)]

    assert "font-size: var(--font-metric-lg);" in metric_rule
    assert "font-weight: 300;" in metric_rule
    assert "text-align: center;" in metric_rule
    assert "background: none;" in metric_rule
    assert "-webkit-background-clip: initial;" in metric_rule
    assert "background-clip: initial;" in metric_rule
    assert "color: var(--accent-text);" in metric_rule
    assert "linear-gradient" not in metric_rule

    card_start = stylesheet.index(
        ".browser-metric-grid:not(.browser-session-metric-grid) > .metric-card {"
    )
    card_rule = stylesheet[card_start:stylesheet.index("\n}", card_start)]
    assert "width: 192px;" in card_rule
    assert "border-radius: 0;" in card_rule


def test_browser_summary_metric_contract_reuses_the_primary_card_for_siblings() -> None:
    """Apply the Saved prompts exemplar to every ordinary three-column summary card."""
    stylesheet = _stylesheet()

    selector = ".browser-metric-grid:not(.browser-session-metric-grid) > .metric-card"
    card_selector = f"{selector} {{"
    assert stylesheet.count(card_selector) == 2
    assert ".browser-prompts-primary-metric {" not in stylesheet
    assert ".browser-prompts-primary-metric strong {" not in stylesheet

    narrow_rule_start = stylesheet.rindex(card_selector)
    narrow_rule = stylesheet[narrow_rule_start:stylesheet.index("\n}", narrow_rule_start)]
    assert "width: 100%;" in narrow_rule


def test_metric_labels_use_the_shared_regular_weight_token() -> None:
    """Keep all Local resources metric labels on the 400-weight baseline."""
    stylesheet = _stylesheet()
    label_start = stylesheet.index(".metric-label {")
    label_rule = stylesheet[label_start:stylesheet.index("\n}", label_start)]

    assert "font-weight: var(--font-weight-regular);" in label_rule
    assert "font-size: var(--font-ui-md);" in label_rule
    assert "font-weight: var(--font-weight-semibold);" not in label_rule


def test_browser_prompt_table_reallocates_space_after_saved_column_removal() -> None:
    """Keep the remaining saved-prompts columns sized without a dead gap."""
    stylesheet = _stylesheet()

    assert ".browser-prompt-table .browser-prompt-col-added {" not in stylesheet
    content_start = stylesheet.index(".browser-prompt-table .browser-prompt-col-content {")
    content_rule = stylesheet[content_start:stylesheet.index("\n}", content_start)]
    source_start = stylesheet.index(".browser-prompt-table .browser-prompt-col-source {")
    source_rule = stylesheet[source_start:stylesheet.index("\n}", source_start)]
    remarks_start = stylesheet.index(".browser-prompt-table .browser-prompt-col-remarks {")
    remarks_rule = stylesheet[remarks_start:stylesheet.index("\n}", remarks_start)]

    assert "width: 50%;" in content_rule
    assert "width: 10%;" in source_rule
    assert "width: 33%;" in remarks_rule


def test_browser_prompt_copy_action_is_hidden_until_prompt_hover_or_focus() -> None:
    """Keep prompt copying discoverable without occupying the prompt content."""
    stylesheet = _stylesheet()

    copy_start = stylesheet.index(".browser-prompt-table-prompt-cell .browser-prompt-copy-button {")
    copy_rule = stylesheet[copy_start:stylesheet.index("\n}", copy_start)]
    assert "position: absolute;" in copy_rule
    assert "opacity: 0;" in copy_rule
    assert "pointer-events: none;" in copy_rule
    assert ".browser-prompt-table tbody tr:hover .browser-prompt-copy-button" in stylesheet
    assert ".browser-prompt-table-prompt-cell:focus-within .browser-prompt-copy-button" in stylesheet


def test_browser_prompt_remarks_use_pill_tags_and_stored_controls() -> None:
    """Keep saved prompt remarks compact, removable, and keyboard reachable."""
    stylesheet = _stylesheet()

    tag_start = stylesheet.index(".browser-prompt-tag {")
    tag_rule = stylesheet[tag_start:stylesheet.index("\n}", tag_start)]
    assert "border-radius: var(--radius-pill);" in tag_rule
    assert ".browser-prompt-remark-editor input {" in stylesheet
    assert ".browser-prompt-remark-add {" not in stylesheet
    assert ".browser-prompt-remark-add:focus-visible" not in stylesheet
    input_start = stylesheet.index(".browser-prompt-remark-editor input {")
    input_rule = stylesheet[input_start:stylesheet.index("\n}", input_start)]
    assert "min-height: 32px;" in input_rule
    assert "height: 32px;" in input_rule
    assert "border: 0;" in input_rule
    assert "border-radius: var(--radius-pill);" in input_rule
    assert "font-size: var(--font-size-3);" in input_rule


def test_browser_session_messages_wrap_rich_content_inside_fixed_cells() -> None:
    """Keep code blocks and nested tables inside the session message column."""
    stylesheet = _stylesheet()

    message_start = stylesheet.index(".browser-session-table-message {")
    message_rule = stylesheet[message_start:stylesheet.index("\n}", message_start)]
    pre_start = stylesheet.index(".browser-session-table-message pre {")
    pre_rule = stylesheet[pre_start:stylesheet.index("\n}", pre_start)]
    code_start = stylesheet.index(".browser-session-table-message pre code {")
    code_rule = stylesheet[code_start:stylesheet.index("\n}", code_start)]
    nested_table_start = stylesheet.index(".browser-session-table-message table {")
    nested_table_rule = stylesheet[nested_table_start:stylesheet.index("\n}", nested_table_start)]

    for token in (
        "box-sizing: border-box;",
        "width: 100%;",
        "min-width: 0;",
        "max-width: 100%;",
        "overflow-x: auto;",
        "overflow-wrap: anywhere;",
        "word-break: break-word;",
    ):
        assert token in message_rule
    assert ".browser-session-table-message > * {" in stylesheet
    assert ".browser-session-table-message img," in stylesheet
    detail_table_start = stylesheet.index(".browser-session-detail-table {")
    detail_table_rule = stylesheet[detail_table_start:stylesheet.index("\n}", detail_table_start)]
    assert "width: 100%;" in detail_table_rule
    assert "min-width: 0;" in detail_table_rule
    message_cell_start = stylesheet.index(".browser-session-detail-table tbody > tr > td:last-child {")
    message_cell_rule = stylesheet[message_cell_start:stylesheet.index("\n}", message_cell_start)]
    assert "padding-right: 18px;" in message_cell_rule
    for token in (
        "box-sizing: border-box;",
        "max-width: 100%;",
        "overflow-x: auto;",
        "white-space: pre-wrap;",
        "overflow-wrap: anywhere;",
        "word-break: break-word;",
    ):
        assert token in pre_rule
    for token in ("white-space: inherit;", "overflow-wrap: inherit;", "word-break: inherit;"):
        assert token in code_rule
    for token in ("width: 100%;", "max-width: 100%;", "table-layout: fixed;"):
        assert token in nested_table_rule


def test_browser_session_messages_default_to_compact_vertical_disclosure() -> None:
    """Keep long session messages compact until their standard control is activated."""
    stylesheet = _stylesheet()

    for token in (
        ".browser-session-table-message-shell {",
        ".browser-session-table-message-shell:not(.is-expanded) .browser-session-table-message {",
        "max-height: min(20rem, 42svh);",
        "overflow-y: hidden;",
        ".browser-session-table-message-shell.is-collapsible:not(.is-expanded) .browser-session-table-message::after {",
        ".browser-session-message-toggle {",
        "border-radius: 50%;",
        ".browser-session-message-toggle[hidden] {",
        ".browser-session-message-toggle-icon {",
        'mask: url("/static/images/rectangle.expand.vertical.svg") center/contain no-repeat;',
        ".browser-session-message-toggle[aria-expanded=\"true\"] .browser-session-message-toggle-icon {",
        'mask-image: url("/static/images/rectangle.compress.vertical.svg");',
    ):
        assert token in stylesheet


def test_browser_workspace_prefers_simplified_chinese_font_fallbacks() -> None:
    """Keep Local resources text rendered with Simplified Chinese glyph forms."""
    stylesheet = _stylesheet()
    workspace_start = stylesheet.index(".browser-workspace {")
    workspace_rule = stylesheet[workspace_start:stylesheet.index("\n}", workspace_start)]
    font_family = 'font-family: var(--font-family-brand), var(--font-family-cjk), "Helvetica Neue", Helvetica, Arial, "PingFang HK", "PingFang TC", "Microsoft JhengHei", sans-serif;'

    assert font_family in workspace_rule
    cjk_token_start = stylesheet.index('--font-family-cjk:')
    cjk_token = stylesheet[cjk_token_start:stylesheet.index("\n", cjk_token_start)]
    assert cjk_token.index('"PingFang SC"') < cjk_token.index('"Microsoft YaHei"')
    assert cjk_token.index('"Microsoft YaHei"') < cjk_token.index('"Noto Sans CJK SC"')


def test_browser_workspace_reuses_the_shared_title_rail_and_content_card() -> None:
    """Keep Local resources on the same title-rail/content-card workspace contract."""
    stylesheet = _stylesheet()
    summary_start = stylesheet.index(".browser-summary-card {")
    summary_rule = stylesheet[summary_start:stylesheet.index("\n}", summary_start)]
    content_start = stylesheet.index(".browser-content-card {")
    content_rule = stylesheet[content_start:stylesheet.index("\n}", content_start)]
    text_card_start = stylesheet.index(".browser-text-summary-card {")
    text_card_rule = stylesheet[text_card_start:stylesheet.index("\n}", text_card_start)]

    assert "display: flex;" in summary_rule
    assert "flex: 0 0 auto;" in summary_rule
    assert "min-height: calc(var(--workspace-title-rail-control-height) + var(--workspace-article-pad-block-start));" in summary_rule
    assert "padding: var(--workspace-article-pad-block-start) var(--workspace-article-pad-inline) 0;" in summary_rule
    assert "display: flex;" in content_rule
    assert "flex: 1 1 0;" in content_rule
    assert "padding: 0 var(--workspace-article-pad-inline) var(--sidebar-dock-bottom-gap);" in content_rule
    assert "overflow: visible;" in text_card_rule
    assert ".workspace > .workspace-header:first-child > .browser-summary-card {" in stylesheet
    assert "html.sidebar-memory-collapsed .app-shell .workspace > .workspace-header:first-child > .workspace-summary-card:first-child {" in stylesheet
    assert "padding-inline-start: var(--workspace-title-rail-collapsed-pad-inline-start);" in stylesheet
    assert ".browser-workspace-header {" in stylesheet
    assert "grid-template-rows: auto minmax(0, 1fr);" in stylesheet
    assert ".browser-text-summary-card .browser-session-table-shell {" in stylesheet
    assert ".browser-text-summary-card .browser-session-table-scroll {" in stylesheet


def test_global_quick_actions_reuse_the_sibling_shell_positioning_contract() -> None:
    """Keep the theme action on the same top/right contract as the sibling shell."""
    stylesheet = _stylesheet()
    token_start = stylesheet.index("--global-quick-actions-right:")
    token_line = stylesheet[token_start:stylesheet.index("\n", token_start)]
    action_start = stylesheet.index(".global-quick-actions {")
    action_rule = stylesheet[action_start:stylesheet.index("\n}", action_start)]

    assert token_line == "--global-quick-actions-right: max(calc(var(--page-edge-pad) * 2), calc(((100vw - 1560px) / 2) + (var(--page-edge-pad) * 2)));"
    assert "top: calc(var(--page-edge-pad) + var(--sidebar-toggle-top));" in action_rule
    assert "right: var(--global-quick-actions-right);" in action_rule


def test_browser_picker_arrow_matches_the_shared_select_arrow() -> None:
    """Keep custom picker arrows visually aligned with native select controls."""
    stylesheet = _stylesheet()
    arrow_start = stylesheet.index("\n.browser-picker-trigger-chevron {") + 1
    arrow_rule = stylesheet[arrow_start:stylesheet.index("\n}", arrow_start)]

    for token in (
        "width: 12px;",
        "height: 8px;",
        "font-size: 0;",
        "background-repeat: no-repeat;",
        "background-position: center;",
        "background-size: 12px 8px;",
    ):
        assert token in arrow_rule

    select_start = stylesheet.index(".browser-filter-form select.form-select {")
    select_rule = stylesheet[select_start:stylesheet.index("\n}", select_start)]
    for token in (
        "appearance: none;",
        "-webkit-appearance: none;",
        "padding-inline-end: 34px;",
        "background-image: var(--browser-picker-chevron-image);",
        "background-position: right 10px center;",
        "background-size: 12px 8px;",
    ):
        assert token in select_rule

    assert "fill='currentColor'" in stylesheet
    assert 'content: "\\25BE";' not in stylesheet


def test_browser_content_mode_reuses_the_sibling_optimistic_navigation_skeleton() -> None:
    """Keep content-mode navigation on the sibling's skeleton and motion contract."""
    stylesheet = _stylesheet()

    for token in (
        ".navigation-skeleton-root {",
        ".navigation-skeleton-card,",
        ".navigation-skeleton-line {",
        "animation: browser-navigation-skeleton-sheen 1.15s var(--motion-shimmer) infinite;",
        ".browser-navigation-skeleton-root {",
        ".browser-navigation-skeleton-heading {",
        ".browser-navigation-skeleton-metrics {",
        ".browser-navigation-skeleton-results {",
        "@keyframes browser-navigation-skeleton-sheen {",
        "@media (prefers-reduced-motion: reduce) {",
    ):
        assert token in stylesheet

def test_agent_workspace_reuses_shared_glass_and_responsive_tokens() -> None:
    """Keep the fourth dock item and Agent workspace aligned with the shared shell."""
    stylesheet = _stylesheet()

    for token in (
        "/* Code version: v2.82.17-codex.48 */",
        "transform var(--sidebar-motion-duration) var(--motion-emphasized);",
        ".dock-icon-agent",
        'mask: url("/static/images/arrow.uturn.up.circle.svg")',
        "width: 22px;",
        "height: 22px;",
        "/* Browser-mediated Computer Use Agent. */",
        ".agent-connect-fields {",
        "grid-template-columns: minmax(0, 1fr);",
        "gap: 14px;",
        ".agent-platform-combobox .browser-session-trigger-leading {",
        "flex: 1 1 auto;",
        ".agent-response-question-header {",
        ".agent-response-question {",
        "font-size: 17px;",
        ".agent-response-answer {",
        "font-size: var(--font-size-5);",
        ".agent-response-answer-content {",
        ".agent-response-pagination {",
        ".agent-platform-combobox .trade-strategy-trigger-label.browser-session-trigger-label {",
        ".agent-platform-combobox .browser-picker-selected-icon-shell {",
        ".agent-os-combobox .browser-picker-selected-icon-shell {",
        ".agent-os-combobox .browser-picker-option-icon {",
        ".agent-os-combobox .agent-combobox-option {",
        ".agent-combobox-loading-spinner {",
        ".agent-empty-response {",
        ".agent-empty-response-spinner {",
        ".agent-conversation-link.is-traditional-handoff {",
        ".agent-conversation-link-label {",
        'background-image: url("/static/images/browser.edge.png");',
        ".agent-combobox-dropdown .trade-strategy-dropdown-option,",
        "font-weight: var(--font-weight-regular);",
        ".browser-session-status-item {",
        ".browser-session-status-terminal-checkmark {",
        ".browser-session-status-card-compact .agent-terminal-execution-status {",
        ".agent-combobox.is-agent-combobox-open .agent-combobox-dropdown:not([hidden]) {",
        ".agent-port-field {",
        "grid-column: auto;",
        ".settings-category-nav-item-agent {",
        "--settings-category-active-index: 5;",
        ".agent-workspace-grid {",
        "grid-template-columns: minmax(0, 1fr);",
        "grid-template-rows: minmax(0, 1fr);",
        ".agent-task-card {",
        "display: flex;",
        ".agent-task-card > .agent-response-card,",
        "min-height: 0;",
        ".agent-composer-shell:focus-within {",
        ".agent-composer-submit-icon {",
        ".agent-composer-submit.is-stop .agent-composer-submit-icon {",
        'mask-image: url("/static/images/stop.fill.svg");',
        "border-radius: var(--radius-soft);",
        ".agent-readiness[data-ready=\"true\"] .agent-readiness-dot,",
        ".agent-activity-panel {",
        ".agent-activity-list {",
        "overflow-y: auto;",
        ".agent-activity-item[data-status=\"completed\"] .agent-activity-status {",
        ".settings-agent-runtime-status {",
        ".agent-response-output {",
        "overflow-y: auto;",
            '"PingFang SC", "PingFang TC", "PingFang HK", "Microsoft YaHei", "Microsoft JhengHei"',
        ".agent-response-output h1,",
        "font-size: var(--font-card-title);",
        ".settings-agent-system-prompt {",
        ".settings-agent-limit-grid {",
        "@media (max-width: 1100px) {",
    ):
        assert token in stylesheet


def test_agent_composer_right_aligns_model_selector_with_action_gap() -> None:
    """Keep the model selector visually grouped with the circular submit action."""
    stylesheet = _stylesheet()
    footer_start = stylesheet.rfind(".agent-composer-footer {")
    footer_rule = stylesheet[footer_start:stylesheet.index("\n}", footer_start)]

    assert "justify-content: flex-end;" in footer_rule
    assert "gap: 12px;" in footer_rule


def test_agent_combobox_trigger_labels_share_typography_contract() -> None:
    """Keep Agent model and sidebar trigger labels on one font contract."""
    stylesheet = _stylesheet()
    selector = ".agent-combobox-trigger .trade-strategy-trigger-label {"
    selector_start = stylesheet.index(selector)
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    for token in (
        "font-family: inherit;",
        "font-size: var(--font-table-body);",
        "font-weight: var(--font-weight-regular);",
        "line-height: 1.45;",
    ):
        assert token in selector_rule


def test_agent_session_lists_open_above_the_sidebar_trigger() -> None:
    """Keep long session menus inside the sidebar viewport near its bottom edge."""
    stylesheet = _stylesheet()
    selector = ".agent-session-list-combobox .agent-session-list-menu {"
    selector_start = stylesheet.index(selector)
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    assert "top: auto;" in selector_rule
    assert "bottom: calc(100% + 4px);" in selector_rule


def test_browser_session_status_labels_share_nonbold_left_typography() -> None:
    """Keep account and terminal status labels aligned without using bold emphasis."""
    stylesheet = _stylesheet()
    selector = ".browser-session-status-account,\n.agent-terminal-execution-label {"
    selector_start = stylesheet.index(selector)
    selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]

    for token in (
        "font-family: inherit;",
        "font-size: var(--font-ui-lg);",
        "font-weight: var(--font-weight-regular);",
        "line-height: 1.3;",
        "text-align: left;",
    ):
        assert token in selector_rule


def test_agent_response_pagination_keeps_spatial_effects_unclipped() -> None:
    """Keep the answer scrollable while allowing pagination motion to escape its shell."""
    stylesheet = _stylesheet()

    for selector in (".agent-workspace-grid {", ".agent-task-card {", "\n.agent-response-card {", ".agent-response-output {"):
        selector_start = stylesheet.index(selector) + (1 if selector.startswith("\n") else 0)
        selector_rule = stylesheet[selector_start:stylesheet.index("\n}", selector_start)]
        assert "overflow: visible;" in selector_rule

    pagination_start = stylesheet.index(".agent-response-pagination {")
    pagination_rule = stylesheet[pagination_start:stylesheet.index("\n}", pagination_start)]
    assert "position: relative;" in pagination_rule
    assert "z-index: var(--layer-control-affordance);" in pagination_rule
    assert "overflow: visible;" in pagination_rule

    answer_start = stylesheet.index(".agent-response-answer {")
    answer_rule = stylesheet[answer_start:stylesheet.index("\n}", answer_start)]
    assert "overflow-x: hidden;" in answer_rule
    assert "overflow-y: auto;" in answer_rule


def test_agent_response_question_and_answer_use_requested_type_sizes() -> None:
    """Keep the Agent question heading at 17px and the answer container at 15px."""
    stylesheet = _stylesheet()

    question_start = stylesheet.index(".agent-response-question {")
    question_rule = stylesheet[question_start:stylesheet.index("\n}", question_start)]
    answer_start = stylesheet.index(".agent-response-answer {")
    answer_rule = stylesheet[answer_start:stylesheet.index("\n}", answer_start)]
    heading_start = stylesheet.index(".agent-response-output h1,")
    heading_rule = stylesheet[heading_start:stylesheet.index("\n}", heading_start) + 2]
    subheading_start = stylesheet.index(".agent-response-output h4,")
    subheading_rule = stylesheet[subheading_start:stylesheet.index("\n}", subheading_start)]

    assert "font-size: 17px;" in question_rule
    assert "font-size: var(--font-card-title);" not in question_rule
    assert "font-size: var(--font-size-5);" in answer_rule
    assert ".agent-response-output h3" not in heading_rule
    assert ".agent-response-output h3" not in subheading_rule


def test_agent_response_header_and_answer_pin_the_composer() -> None:
    """Keep both response regions independently scrollable without moving the composer."""
    stylesheet = _stylesheet()

    header_start = stylesheet.index(".agent-response-question-header {")
    header_rule = stylesheet[header_start:stylesheet.index("\n}", header_start)]
    answer_start = stylesheet.index(".agent-response-answer {")
    answer_rule = stylesheet[answer_start:stylesheet.index("\n}", answer_start)]
    composer_start = stylesheet.rfind(".agent-task-card > .agent-prompt-form {")
    composer_rule = stylesheet[composer_start:stylesheet.index("\n}", composer_start)]

    for rule in (header_rule, answer_rule):
        assert "overflow-y: auto;" in rule
        assert "scrollbar-gutter: stable;" in rule
        assert "overscroll-behavior: contain;" in rule
    assert "position: sticky;" in composer_rule
    assert "bottom: 0;" in composer_rule
    assert "flex: 0 0 auto;" in composer_rule
