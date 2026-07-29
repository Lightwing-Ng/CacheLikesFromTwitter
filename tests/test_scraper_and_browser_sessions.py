"""Tests for browser-independent X parsing and session helpers.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.browser_sessions import (
    extract_json_string_field,
    extract_x_account_from_source,
    detect_safari_x_account_handle,
    is_grok_security_verification_page,
    parse_grok_account_label,
    probe_browser_session,
)
from app.core.config import CrawlConfig
from app.core.scraper import (
    build_likes_request_template,
    build_x_likes_url,
    extract_account_handle_from_urlish,
    normalize_status_url,
    parse_likes_timeline_page,
    collect_liked_tweet_urls,
)
from app.core.state import TaskState


def _tweet_entry(status_id: str, handle: str) -> dict[str, object]:
    return {
        "content": {
            "__typename": "TimelineTimelineItem",
            "itemContent": {
                "__typename": "TimelineTweet",
                "tweet_results": {
                    "result": {
                        "rest_id": status_id,
                        "legacy": {"id_str": status_id},
                        "core": {"user_results": {"result": {"legacy": {"screen_name": handle}}}},
                    }
                },
            },
        }
    }


def test_x_url_and_handle_parsing_rejects_reserved_and_foreign_values() -> None:
    assert build_x_likes_url("@demo") == "https://x.com/demo/likes"
    assert extract_account_handle_from_urlish("https://x.com/demo/likes") == "demo"
    assert extract_account_handle_from_urlish("/demo/media") == "demo"
    assert extract_account_handle_from_urlish("https://x.com/settings") == ""
    assert extract_account_handle_from_urlish("https://example.com/demo") == ""
    assert normalize_status_url("http://twitter.com/demo/status/123/?x=1") == "https://x.com/demo/status/123"
    assert normalize_status_url("https://x.com/i/web/status/456") == "https://x.com/i/status/456"
    with pytest.raises(RuntimeError, match="without a detected account handle"):
        build_x_likes_url("")


def test_likes_timeline_parser_extracts_tweets_and_bottom_cursor() -> None:
    payload = {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        _tweet_entry("101", "alice"),
                                        {"content": {"__typename": "TimelineTimelineCursor", "cursorType": "Bottom", "value": "cursor-2"}},
                                        _tweet_entry("102", "bob"),
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }

    urls, cursor = parse_likes_timeline_page(payload)

    assert urls == ["https://x.com/alice/status/101", "https://x.com/bob/status/102"]
    assert cursor == "cursor-2"


def test_authenticated_request_template_keeps_only_required_headers() -> None:
    response = SimpleNamespace(
        url="https://x.com/i/api/graphql/query/Likes?variables=%7B%22userId%22%3A%221%22%7D&features=%7B%22a%22%3Atrue%7D",
        request=SimpleNamespace(headers={"Authorization": "Bearer test", "X-Csrf-Token": "csrf", "Cookie": "private"}),
    )

    template = build_likes_request_template(response, "https://x.com/demo/likes")

    assert template.api_url_base == "https://x.com/i/api/graphql/query/Likes"
    assert template.variables == {"userId": "1"}
    assert template.headers == {"Authorization": "Bearer test", "X-Csrf-Token": "csrf", "referer": "https://x.com/demo/likes"}


def test_browser_session_parsers_do_not_require_live_browser_access() -> None:
    assert extract_json_string_field('{"givenName":"Demo User"}', "givenName") == "Demo User"
    assert extract_x_account_from_source('{"screen_name":"demo_user"}') == "demo_user"
    assert parse_grok_account_label('{"givenName":"Demo","xUsername":"demo_x"}') == "Demo (@demo_x)"
    assert is_grok_security_verification_page(
        "Just a moment...",
        (
            "Performing security verification\n"
            "This website uses a security service to protect against malicious bots.\n"
            "Performance and Security by Cloudflare"
        ),
    )
    assert not is_grok_security_verification_page(
        "Grok",
        "Ready. Found existing Grok cache: 475 assets, 429 images, 46 videos.",
    )
    with pytest.raises(ValueError, match="Unsupported platform"):
        probe_browser_session("unknown", "chrome", CrawlConfig())
    with pytest.raises(ValueError, match="Unsupported browser"):
        probe_browser_session("x", "firefox", CrawlConfig())


def test_safari_profile_link_detection_uses_the_rendered_navigation() -> None:
    process = SimpleNamespace(returncode=0, stdout="demo_user\n")

    with patch("app.core.browser_sessions.subprocess.run", return_value=process) as run:
        assert detect_safari_x_account_handle(wait_seconds=1) == "demo_user"

    assert "AppTabBar_Profile_Link" in run.call_args.kwargs["input"]


def test_safari_collection_prefers_navigation_handle_before_page_source() -> None:
    config = CrawlConfig(x_browser="safari")
    state = TaskState("test")
    collected_urls = ["https://x.com/demo_user/status/123"]

    with patch("app.core.scraper.detect_safari_x_account_handle", return_value="demo_user"), patch(
        "app.core.scraper.fetch_safari_page_snapshot"
    ) as snapshot, patch(
        "app.core.scraper.collect_liked_tweet_urls_via_safari",
        return_value=collected_urls,
    ):
        handle, urls = collect_liked_tweet_urls(config, state)

    assert handle == "demo_user"
    assert urls == collected_urls
    snapshot.assert_not_called()


def test_safari_grok_probe_marks_verified_session_ready_to_download() -> None:
    source = '{"givenName":"Demo","xUsername":"demo_x"}'

    with patch(
        "app.core.browser_sessions.fetch_safari_page_snapshot",
        return_value={"url": "https://grok.com/files", "source": source},
    ):
        result = probe_browser_session("grok", "safari", CrawlConfig())

    assert result["logged_in"] is True
    assert result["can_download"] is True
    assert result["account_name"] == "Demo (@demo_x)"
    assert "ready to sync" in result["message"]
