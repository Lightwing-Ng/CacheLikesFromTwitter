"""Regression tests for the Settings → Style tokens registry.

Code version: v1.0.0-codex.1
"""

from app.web.token_registry import (
    build_reused_style_token_groups,
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


def test_style_tokens_route_renders_inventory_and_settings_navigation(client) -> None:
    response = client.get("/settings/style-tokens")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'aria-current="page"' in html
    assert 'data-style-token-group="surfaces-and-effects"' in html
    assert 'data-style-token-row="--frosted-glass-background"' in html
    assert 'data-style-token-copy="--frosted-glass-background"' in html
    assert 'href="/settings/style-tokens"' in html


def test_settings_page_links_to_style_tokens(client) -> None:
    response = client.get("/settings")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/settings/style-tokens"' in html
    assert html.count("Style tokens") == 1
