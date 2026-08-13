"""Tests for browser-independent X parsing and session helpers.

Code version: v1.6.0-codex.1
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.browser_sessions import (
    BrowserDescriptor,
    build_chromium_launch_args,
    clone_browser_profile,
    extract_json_string_field,
    extract_x_account_from_source,
    detect_safari_x_account_handle,
    fetch_safari_page_snapshot,
    is_grok_security_verification_page,
    launch_chromium_context,
    parse_grok_account_label,
    probe_browser_session,
)
from app.core.config import CrawlConfig
from app.core.scraper import (
    build_likes_request_template,
    build_x_likes_url,
    collect_liked_tweet_urls_via_safari,
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


def test_background_chromium_launch_args_keep_the_window_offscreen() -> None:
    descriptor = BrowserDescriptor(
        browser_id="edge",
        label="Edge",
        icon_filename="images/browser.edge.png",
        engine="chromium",
        user_data_dir=Path("/tmp/edge"),
        profile_directory="Default",
        channel="msedge",
    )

    assert build_chromium_launch_args(descriptor, background_window=False) == ["--profile-directory=Default"]
    assert build_chromium_launch_args(descriptor) == [
        "--profile-directory=Default",
        "--window-position=-32000,-32000",
        "--window-size=1280,900",
        "--start-minimized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]


def test_gemini_browser_probe_routes_through_the_shared_browser_registry() -> None:
    with patch(
        "app.core.browser_sessions._probe_gemini_session",
        return_value={
            "logged_in": True,
            "can_download": True,
            "account_name": "Google account",
            "message": "Safari verified Gemini.",
        },
    ) as probe:
        result = probe_browser_session("gemini", "safari", CrawlConfig())

    assert result["logged_in"] is True
    assert result["can_download"] is True
    assert result["browser"] == "safari"
    probe.assert_called_once()


def test_chromium_context_defaults_to_an_isolated_background_profile(tmp_path: Path) -> None:
    source_user_data_dir = tmp_path / "Edge"
    source_profile_dir = source_user_data_dir / "Default"
    source_profile_dir.mkdir(parents=True)
    (source_profile_dir / "Preferences").write_text("{}", encoding="utf-8")
    descriptor = BrowserDescriptor(
        browser_id="edge",
        label="Edge",
        icon_filename="images/browser.edge.png",
        engine="chromium",
        user_data_dir=source_user_data_dir,
        profile_directory="Default",
        channel="msedge",
    )
    context = SimpleNamespace(close=lambda: None)

    class Chromium:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def launch_persistent_context(self, **kwargs):
            self.calls.append(kwargs)
            return context

    chromium = Chromium()
    playwright = SimpleNamespace(chromium=chromium)

    with launch_chromium_context(playwright, descriptor, headless=False) as launched_context:
        assert launched_context is context

    assert len(chromium.calls) == 1
    launch_kwargs = chromium.calls[0]
    assert Path(str(launch_kwargs["user_data_dir"])) != source_user_data_dir
    assert launch_kwargs["headless"] is False
    assert launch_kwargs["args"] == build_chromium_launch_args(descriptor)


def test_clone_browser_profile_continues_when_macos_blocks_local_state(tmp_path: Path) -> None:
    source_user_data_dir = tmp_path / "Edge"
    source_profile_dir = source_user_data_dir / "Default"
    source_profile_dir.mkdir(parents=True)
    (source_profile_dir / "Preferences").write_text("{}", encoding="utf-8")
    local_state = source_user_data_dir / "Local State"
    local_state.write_text("{}", encoding="utf-8")
    descriptor = BrowserDescriptor(
        browser_id="edge",
        label="Edge",
        icon_filename="images/browser.edge.png",
        engine="chromium",
        user_data_dir=source_user_data_dir,
        profile_directory="Default",
        channel="msedge",
    )

    original_read_bytes = Path.read_bytes

    def read_bytes_with_permission_error(path: Path) -> bytes:
        if path == local_state:
            raise PermissionError(1, "Operation not permitted", str(path))
        return original_read_bytes(path)

    with patch.object(Path, "read_bytes", read_bytes_with_permission_error):
        target_user_data_dir, temp_dir = clone_browser_profile(descriptor)

    try:
        assert (target_user_data_dir / "Default" / "Preferences").read_text(encoding="utf-8") == "{}"
        assert not (target_user_data_dir / "Local State").exists()
    finally:
        temp_dir.cleanup()


def test_clone_browser_profile_reports_macos_profile_permission_error(tmp_path: Path) -> None:
    source_user_data_dir = tmp_path / "Edge"
    source_profile_dir = source_user_data_dir / "Default"
    source_profile_dir.mkdir(parents=True)
    descriptor = BrowserDescriptor(
        browser_id="edge",
        label="Edge",
        icon_filename="images/browser.edge.png",
        engine="chromium",
        user_data_dir=source_user_data_dir,
        profile_directory="Default",
        channel="msedge",
    )

    with patch("shutil.copytree", side_effect=PermissionError(1, "Operation not permitted", source_profile_dir)):
        with pytest.raises(RuntimeError, match="Full Disk Access"):
            clone_browser_profile(descriptor)


def test_safari_profile_link_detection_uses_the_rendered_navigation() -> None:
    process = SimpleNamespace(returncode=0, stdout="demo_user\n")

    with patch("app.core.browser_sessions.subprocess.run", return_value=process) as run:
        assert detect_safari_x_account_handle(wait_seconds=1) == "demo_user"

    assert "AppTabBar_Profile_Link" in run.call_args.kwargs["input"]
    assert "current tab of targetWindow" in run.call_args.kwargs["input"]
    assert "set bounds of targetWindow to {-32000, -32000, -30720, -31100}" in run.call_args.kwargs["input"]
    assert "set miniaturized of targetWindow to true" in run.call_args.kwargs["input"]


def test_safari_page_snapshot_uses_an_offscreen_minimized_window() -> None:
    process = SimpleNamespace(
        returncode=0,
        stdout="https://grok.com/files\n<html>Grok</html>",
        stderr="",
    )

    with patch("app.core.browser_sessions.subprocess.run", return_value=process) as run:
        snapshot = fetch_safari_page_snapshot("https://grok.com/files", wait_seconds=1)

    script = run.call_args.kwargs["input"]
    assert snapshot == {"url": "https://grok.com/files", "source": "<html>Grok</html>"}
    assert "set previousWindowId to 0" in script
    assert "set bounds of targetWindow to {-32000, -32000, -30720, -31100}" in script
    assert "set miniaturized of targetWindow to true" in script
    assert "set index of (first window whose id is previousWindowId) to 1" in script


def test_safari_likes_collection_uses_window_id_targeting() -> None:
    process = SimpleNamespace(
        returncode=0,
        stdout=(
            "https://x.com/demo_user/likes\n"
            '["https://twitter.com/demo_user/status/123?ref=copy","https://x.com/demo_user/status/456"]'
        ),
    )
    config = CrawlConfig(x_browser="safari", max_scroll_rounds=2, scroll_pause_seconds=0.2)
    state = TaskState("test")

    with patch("app.core.scraper.subprocess.run", return_value=process) as run:
        urls = collect_liked_tweet_urls_via_safari(
            "demo_user",
            "https://x.com/demo_user/likes",
            config,
            state,
        )

    script = run.call_args.kwargs["input"]
    assert "set windowId to id of targetWindow" in script
    assert "current tab of targetWindow" in script
    assert "front document" not in script
    assert "set bounds of targetWindow to {-32000, -32000, -30720, -31100}" in script
    assert "set miniaturized of targetWindow to true" in script
    assert urls == [
        "https://x.com/demo_user/status/123",
        "https://x.com/demo_user/status/456",
    ]
    assert state.snapshot()["discovered_tweets"] == 2


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
    assert result["message"] == "Safari is ready to sync Grok."
    assert result["account_name"] not in result["message"]
