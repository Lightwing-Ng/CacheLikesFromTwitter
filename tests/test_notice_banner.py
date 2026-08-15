"""Regression coverage for the shared floating-banner contract. Code version: v0.1.0-codex.1."""

from pathlib import Path

from app.web.app import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = PROJECT_ROOT / "app/web/templates"
STATIC_ROOT = PROJECT_ROOT / "app/web/static"


def test_cache_status_banner_uses_the_shared_sibling_structure() -> None:
    with create_app().test_client() as client:
        response = client.get("/cache/chatgpt")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '{% call render_notice_banner(' in (TEMPLATE_ROOT / "_cache_page.html").read_text(encoding="utf-8")
    assert 'class="notice notice-floating notice-floating-banner notice-floating-banner-global cache-status-banner"' in body
    assert 'data-dismissible-notice' in body
    assert 'data-notice-storage-key="cachelikes:chatgpt-status-banner-dismissed"' in body
    assert 'class="dismiss-button notice-close"' in body
    assert 'class="icon icon-dismiss-control"' in body
    assert 'class="icon workspace-modal-icon notice-floating-banner-icon icon-modal-dialog-banner-default"' in body
    assert '<p class="notice-floating-banner-heading">Task status</p>' in body
    assert '<span id="banner_message">' in body
    assert '<span class="status-chip status-idle" id="banner_phase">idle</span>' in body


def test_browser_refresh_banner_reuses_the_shared_macro_and_controller() -> None:
    with create_app().test_client() as client:
        response = client.get("/browser")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '{% call render_notice_banner(' in (TEMPLATE_ROOT / "browser.html").read_text(encoding="utf-8")
    assert 'data-chatgpt-session-refresh-banner' in body
    assert 'data-session-refresh-dismiss' in body
    assert 'data-session-refresh-title' in body
    assert 'data-session-refresh-copy' in body
    assert 'src="/static/notice-banner.js?v=notice-banner-v0.1.0-codex.1"' in body


def test_banner_styles_follow_the_sibling_top_aligned_contract() -> None:
    stylesheet = (STATIC_ROOT / "style.css").read_text(encoding="utf-8")

    for token in (
        ".notice-floating-banner {",
        "display: grid !important;",
        "grid-template-columns: var(--workspace-modal-icon-size) minmax(0, 1fr);",
        "align-items: start !important;",
        ".notice-floating-banner-content {",
        ".notice-floating-banner-copy {",
        "list-style-position: outside;",
        ".notice-floating-banner .notice-close {",
        ".icon-dismiss-control {",
        "transform: translate3d(-50%, 0, 0);",
    ):
        assert token in stylesheet


def test_shared_notice_controller_persists_only_opt_in_notice_state() -> None:
    script = (STATIC_ROOT / "notice-banner.js").read_text(encoding="utf-8")

    assert 'document.querySelectorAll("[data-dismissible-notice]")' in script
    assert 'window.sessionStorage.getItem(storageKey)' in script
    assert 'window.sessionStorage.setItem(storageKey, String(notice.hidden))' in script
