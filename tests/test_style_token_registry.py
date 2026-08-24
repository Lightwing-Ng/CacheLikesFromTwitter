"""Regression tests for the Settings → Style tokens registry.

Code version: v1.1.0-codex.1
"""

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
        "status-states",
        "type-specimen",
        "glass-surface",
        "control-playground",
        "workflow-card",
        "product-summary",
    }
    assert all(row["sample_kind"] != "token-inventory" for row in rows)


def test_style_tokens_route_renders_live_demos_and_settings_navigation(client) -> None:
    response = client.get("/settings/style-tokens")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "data-style-token-reference-skin" in html
    assert 'aria-current="page"' in html
    assert 'data-style-token-card="style-token-surfaces-and-effects"' in html
    assert 'data-style-token-row="--frosted-glass-background"' in html
    assert 'data-style-token-copy="Surfaces and effects"' in html
    assert 'data-style-token-demo="metric-summary"' in html
    assert 'data-style-token-demo="control-playground"' in html
    assert 'data-style-token-demo="product-summary"' in html
    assert 'data-style-token-inventory-demo' not in html
    assert 'href="/settings/style-tokens"' in html


def test_settings_page_links_to_style_tokens(client) -> None:
    response = client.get("/settings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/settings/style-tokens"' in html
    assert html.count("Style tokens") == 1
