"""Regression tests for the Settings → Style tokens registry.

Code version: v1.1.0-codex.15
"""

from pathlib import Path

from app.web.token_registry import (
    build_reused_style_token_groups,
    build_reused_style_token_rows,
    build_style_token_component_rows,
    load_css_token_registry,
)


def test_registry_reads_shared_tokens_from_all_root_layers() -> None:
    registry = load_css_token_registry()

    assert registry["--frosted-glass-background"].reference_count >= 2
    assert registry["--frosted-glass-background"].line > 0
    assert registry["--style-token-column-gap"].value == "24px"


def test_style_token_groups_only_expose_reused_tokens() -> None:
    groups = build_reused_style_token_groups(minimum_references=2)
    token_names = [token["name"] for group in groups for token in group["tokens"]]

    assert token_names
    assert len(token_names) == len(set(token_names))
    assert all(
        token["reference_count"] >= 2
        for group in groups
        for token in group["tokens"]
    )


def test_style_token_rows_pair_every_category_with_a_live_component_demo() -> None:
    rows = build_reused_style_token_rows(minimum_references=2)

    assert {row["sample_kind"] for row in rows} == {
        "metric-summary",
        "range-mode",
    }
    assert all(row["sample_kind"] != "token-inventory" for row in rows)
    assert [row["name"] for row in rows] == [
        "Foundation",
        "Controls",
    ]
    assert rows[-1]["sample_kind"] == "range-mode"


def test_style_token_component_rows_include_browser_sources_and_scrollable_table() -> None:
    rows = build_style_token_component_rows()

    assert [row["id"] for row in rows] == [
        "secondary-button",
        "primary-button",
        "global-theme-toggle",
        "shared-cache-settings-link",
        "prompt-tag",
        "local-store-pagination",
        "shared-select-filter",
        "agent-browser-selector",
        "scrollable-data-table",
    ]
    assert [row["sample_kind"] for row in rows] == [
        "secondary-button",
        "primary-button",
        "global-theme-toggle",
        "shared-cache-settings-link",
        "prompt-tag",
        "local-store-pagination",
        "shared-select-filter",
        "agent-browser-selector",
        "scrollable-data-table",
    ]
    assert all(row["tokens"] for row in rows)
    assert {
        token["name"] for token in rows[4]["tokens"]
    } == {
        "--accent-border-strong",
        "--accent-surface-soft",
        "--accent-text",
        "--radius-pill",
        "--font-ui-xs",
    }
    assert "--scrollable-data-table-min-width" in {
        token["name"] for token in rows[-1]["tokens"]
    }


def test_style_tokens_route_renders_live_demos_and_settings_navigation(client) -> None:
    response = client.get("/settings/style-tokens")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "data-style-token-reference-skin" in html
    assert 'aria-current="page"' in html
    assert 'data-style-token-card="style-token-surfaces-and-effects"' not in html
    assert 'data-style-token-card="style-token-typography"' not in html
    assert 'data-style-token-copy="Typography"' not in html
    assert 'data-style-token-copy="Surfaces and effects"' not in html
    assert 'class="style-token-card style-token-card--demo-only"' not in html
    assert 'data-style-token-demo="type-specimen"' not in html
    assert 'data-style-token-demo="glass-surface"' not in html
    assert 'class="metric-card metric-card-accent foundation-metric-card"' in html
    assert ">Messages</span>" in html
    for dead_demo in (
        "status-states",
        "control-playground",
        "workflow-card",
        "product-summary",
    ):
        assert f'data-style-token-demo="{dead_demo}"' not in html
    assert 'class="range-mode-shell"' in html
    assert 'data-segmented-pill="measured"' in html
    assert 'class="range-mode-option"' in html
    assert 'data-style-token-card="style-token-color-and-status"' not in html
    assert 'data-style-token-card="style-token-layout-and-motion"' not in html
    assert 'data-style-token-card="style-token-product-components"' not in html
    assert 'data-style-token-card="style-token-controls"' in html
    assert 'data-style-token-copy="Controls"' in html
    assert 'data-style-token-inventory-demo' not in html
    assert 'href="/settings/style-tokens"' in html
    assert 'sidebar.js?v=sidebar-v1.19.0-codex.1' in html
    assert 'segmented-control.js?v=segmented-control-v1.0.3-codex.1' in html


def test_cache_summary_metrics_reuse_the_foundation_metric_contract(client) -> None:
    response = client.get("/cache/chatgpt")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'class="metric-grid foundation-metric-grid"' in html
    assert 'class="progress-metric-grid foundation-metric-grid"' in html
    assert html.count("foundation-metric-card") == 10
    assert 'class="progress-metric-card foundation-metric-card"' in html


def test_style_tokens_route_renders_requested_browser_components_and_table(client) -> None:
    response = client.get("/settings/style-tokens")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    for card_id in (
        "secondary-button",
        "primary-button",
        "global-theme-toggle",
        "shared-cache-settings-link",
        "prompt-tag",
        "local-store-pagination",
        "shared-select-filter",
        "agent-browser-selector",
        "scrollable-data-table",
    ):
        assert f'data-style-token-card="{card_id}"' in html
    assert 'data-source-xpath="/html/body/main/div[3]/aside/section[2]/form/div[2]/button"' in html
    assert 'data-source-xpath="/html/body/main/div[3]/section/div/div[2]/nav"' in html
    assert 'data-source-xpath="/html/body/main/div[3]/aside/section[2]/form/label[2]/div/button"' in html
    assert 'data-source-route="/agent/edge/claude"' in html
    assert 'data-source-selector="label.field:nth-of-type(2) > div.agent-browser-session-field.is-browser-status-loading > div.trade-strategy-combobox.agent-combobox:nth-of-type(1) > button.trade-strategy-select.form-select"' in html
    assert 'aria-label="Browser: Edge"' in html
    assert 'data-style-token-agent-browser-option="edge"' in html
    assert 'data-style-token-demo="global-theme-toggle"' in html
    assert 'data-style-token-theme-toggle' in html
    assert 'aria-label="Switch to Dark mode"' in html
    assert 'data-style-token-demo="primary-button"' in html
    assert 'data-style-token-primary-button' in html
    assert 'data-source-selector="button#start_button"' in html
    assert 'data-style-token-demo="shared-cache-settings-link"' in html
    assert 'data-style-token-shared-cache-settings-link' in html
    assert 'data-source-route="/cache/chatgpt"' in html
    assert 'data-source-selector="aside#app_sidebar > section.sidebar-section:nth-of-type(3) > a.ghost-link.ghost-link--compact"' in html
    assert 'href="/settings#settings-downloads"' in html
    assert 'data-style-token-demo="prompt-tag"' in html
    assert 'data-style-token-prompt-tag' in html
    assert 'data-source-route="/browser"' in html
    assert 'aria-label="Remove remark PS"' in html
    assert 'data-style-token-table-demo' in html
    assert 'data-style-token-table-filter-option="buy"' in html
    assert 'data-style-token-table-pagination' in html
    assert html.count('data-style-token-table-row') == 12

    script = (Path(__file__).parents[1] / "app/web/static/settings-style-tokens.js").read_text()
    for fragment in (
        "bindStyleTokenTableDemos",
        "bindStyleTokenFilterMenus",
        "bindStyleTokenAgentBrowserDemo",
        "bindStyleTokenPagination",
        "bindStyleTokenThemeToggleDemo",
        "bindStyleTokenPrimaryButtonDemo",
        "__styleTokenOnSelect",
    ):
        assert fragment in script
    for fragment in (
        "bindSegmentedDemos",
        "bindToggleDemos",
        "bindWorkflowDemos",
        "bindProductDemos",
        "data-style-token-workflow-action",
        "data-style-token-product-action",
    ):
        assert fragment not in script

    segmented_script = (Path(__file__).parents[1] / "app/web/static/segmented-control.js").read_text()
    for fragment in (
        '.range-mode-shell[data-option-count]',
        'segmentedPill !== "measured"',
        'ResizeObserver',
        '--segmented-pill-left',
        '--segmented-pill-width',
    ):
        assert fragment in segmented_script


def test_style_token_reference_skin_respects_light_theme_override() -> None:
    stylesheet = (Path(__file__).parents[1] / "app/web/static/style.css").read_text()

    assert (
        ':root[data-style-token-reference-skin]:not([data-theme-override="light"])'
        in stylesheet
    )
    assert '.style-token-page .global-theme-toggle[data-effective-theme="light"] .icon' in stylesheet


def test_settings_page_links_to_style_tokens(client) -> None:
    response = client.get("/settings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/settings/style-tokens"' in html
    assert html.count("Style tokens") == 1
