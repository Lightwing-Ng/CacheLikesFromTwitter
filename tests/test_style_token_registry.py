"""Regression tests for the Settings → Style tokens registry.

Code version: v1.1.0-codex.5
"""

from pathlib import Path

from app.web.token_registry import (
    build_reused_style_token_groups,
    build_reused_style_token_rows,
    load_css_token_registry,
)


def test_registry_reads_shared_tokens_from_all_root_layers() -> None:
    registry = load_css_token_registry()

    assert registry["--frosted-glass-background"].reference_count >= 2
    assert registry["--frosted-glass-background"].line > 0
    assert registry["--style-token-card-gap"].value == "12px"


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
        "type-specimen",
        "glass-surface",
    }
    assert all(row["sample_kind"] != "token-inventory" for row in rows)
    assert [row["name"] for row in rows] == [
        "Foundation",
        "Typography",
        "Surfaces and effects",
        "Controls",
    ]
    assert rows[-1]["sample_kind"] == "range-mode"


def test_style_tokens_route_renders_live_demos_and_settings_navigation(client) -> None:
    response = client.get("/settings/style-tokens")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "data-style-token-reference-skin" in html
    assert 'aria-current="page"' in html
    assert 'data-style-token-card="style-token-surfaces-and-effects"' in html
    assert 'data-style-token-row="--frosted-glass-background"' in html
    assert 'data-style-token-copy="Surfaces and effects"' in html
    assert 'class="metric-card metric-card-accent"' in html
    assert ">Messages</span>" in html
    assert 'data-style-token-demo="control-playground"' not in html
    assert 'class="range-mode-shell"' in html
    assert 'class="range-mode-option"' in html
    assert 'data-style-token-card="style-token-color-and-status"' not in html
    assert 'data-style-token-card="style-token-layout-and-motion"' not in html
    assert 'data-style-token-card="style-token-product-components"' not in html
    assert 'data-style-token-card="style-token-controls"' in html
    assert 'data-style-token-copy="Controls"' in html
    assert 'data-style-token-inventory-demo' not in html
    assert 'href="/settings/style-tokens"' in html


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
