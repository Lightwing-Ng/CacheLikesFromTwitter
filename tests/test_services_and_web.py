"""Service orchestration and Flask contract tests.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import CrawlConfig
from app.core.downloader import DownloadResult
from app.core.grok_downloader import GrokResetResult
from app.core.grok_service import summarize_error_for_status
from app.core.service import CacheLikesService
from app.core.state import TaskSnapshot, TaskState


def test_cache_service_run_aggregates_download_results_without_browser_access(tmp_path: Path) -> None:
    state = TaskState("v-test", snapshot_factory=lambda version: TaskSnapshot(version=version))
    service = CacheLikesService(state)
    config = CrawlConfig(download_workers=1, max_media_items=10, account_name_override="saved")
    results = [
        DownloadResult(downloaded_media_count=2, downloaded_post_count=1, downloaded_image_count=1, downloaded_video_count=1),
        DownloadResult(skipped=True),
    ]

    with patch("app.core.service.LOCAL_STORE_ROOT", tmp_path), patch(
        "app.core.service.collect_liked_tweet_urls",
        return_value=("detected", ["https://x.com/demo/status/1", "https://x.com/demo/status/2"]),
    ), patch("app.core.service.LocalTweetCacheIndex.build"), patch(
        "app.core.service.download_tweet_media",
        side_effect=results,
    ):
        state.reset_for_run()
        service._run(config)

    snapshot = state.snapshot()
    assert snapshot["phase"] == "finished"
    assert snapshot["downloaded_posts"] == 1
    assert snapshot["downloaded_images"] == 1
    assert snapshot["downloaded_videos"] == 1
    assert snapshot["skipped_tweets"] == 1
    assert snapshot["output_dir"] == str(tmp_path / "x")


def test_grok_status_error_summary_is_actionable_and_bounded() -> None:
    launch_error = RuntimeError("BrowserType.launch_persistent_context: profile locked")
    assert "browser profile" in summarize_error_for_status(launch_error)
    assert summarize_error_for_status(RuntimeError("first line\nsecond line")) == "first line"
    assert summarize_error_for_status(RuntimeError("x" * 600)).endswith("...")


@pytest.mark.integration
def test_web_pages_and_status_apis_are_available(client) -> None:
    for path, expected_text in (("/", b"Execution overview"), ("/grok", b"Grok library overview"), ("/settings", b"Configuration center")):
        response = client.get(path)
        assert response.status_code == 200
        assert expected_text in response.data

    status = client.get("/api/status")
    grok_status = client.get("/api/grok/status")
    assert status.status_code == 200
    assert grok_status.status_code == 200
    assert status.get_json()["phase"] in {"idle", "starting", "downloading", "finished", "failed", "stopped", "stopping"}


@pytest.mark.integration
def test_browser_session_api_validates_inputs_and_returns_probe_payload(client) -> None:
    invalid = client.get("/api/browser-session?platform=unknown&browser=chrome")
    assert invalid.status_code == 400
    assert "Unsupported platform" in invalid.get_json()["error"]

    with patch("app.web.app.probe_browser_session", return_value={"ready": True, "account_name": "demo"}) as probe:
        valid = client.get("/api/browser-session?platform=x&browser=chrome")

    assert valid.status_code == 200
    assert valid.get_json() == {"ready": True, "account_name": "demo"}
    probe.assert_called_once()


@pytest.mark.integration
def test_settings_and_grok_reset_routes_redirect_without_external_work(client, tmp_path: Path) -> None:
    with patch("app.web.app.save_config") as save_config:
        settings_response = client.post("/settings", data={"download_workers": "1,234", "scroll_pause_seconds": "2.5"})
    assert settings_response.status_code == 302
    save_config.assert_called_once()

    with patch("app.web.app.reset_grok_state", return_value=GrokResetResult(removed_media_files=2, removed_state_files=1)):
        reset_response = client.post("/grok/reset")
    assert reset_response.status_code == 302
    assert client.get("/api/grok/status").status_code == 200


@pytest.mark.integration
def test_grok_start_route_accepts_safari(client) -> None:
    with patch("app.core.grok_service.GrokDownloadService.start") as start:
        response = client.post("/grok/start", data={"grok_browser": "safari"})

    assert response.status_code == 302
    assert start.call_args.args[0].grok_browser == "safari"
