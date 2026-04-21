"""Focused regression tests for the cache orchestration service."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import CrawlConfig, LOCAL_STORE_ROOT
from app.core.downloader import DownloadResult
from app.core.service import CacheLikesService
from app.core.state import TaskState


class CacheLikesServiceTests(unittest.TestCase):
    """Validate the worker handoff and temporary download cap."""

    def test_run_passes_config_to_downloader(self) -> None:
        state = TaskState(version="test")
        service = CacheLikesService(state)
        config = CrawlConfig(max_media_items=10)

        with patch(
            "app.core.service.collect_liked_tweet_urls",
            return_value=("demo_account", ["https://x.com/demo/status/1"]),
        ), patch("app.core.service.download_tweet_media", return_value=DownloadResult(downloaded_media_count=1)) as mock_download:
            service._run(config)

        self.assertEqual(mock_download.call_count, 1)
        call = mock_download.call_args
        self.assertEqual(call.args[0], "https://x.com/demo/status/1")
        self.assertEqual(call.args[1], LOCAL_STORE_ROOT / "demo_account")
        self.assertEqual(call.args[2], LOCAL_STORE_ROOT / "demo_account" / ".downloaded_archive.txt")
        self.assertIs(call.args[3], config)
        self.assertIs(call.args[4], state)
        self.assertEqual(call.kwargs["remaining_media_items"], 10)

    def test_run_stops_after_media_cap_is_reached(self) -> None:
        state = TaskState(version="test")
        service = CacheLikesService(state)
        config = CrawlConfig(max_media_items=10)
        tweet_urls = [f"https://x.com/demo/status/{index}" for index in range(1, 5)]

        with patch(
            "app.core.service.collect_liked_tweet_urls",
            return_value=("demo_account", tweet_urls),
        ), patch(
            "app.core.service.download_tweet_media",
            side_effect=[
                DownloadResult(downloaded_media_count=4),
                DownloadResult(downloaded_media_count=4),
                DownloadResult(downloaded_media_count=2),
                DownloadResult(downloaded_media_count=1),
            ],
        ) as mock_download:
            service._run(config)

        self.assertEqual(mock_download.call_count, 3)
        snapshot = state.snapshot()
        self.assertEqual(snapshot["phase"], "finished")
        self.assertEqual(snapshot["downloaded_tweets"], 10)
        self.assertIn("downloaded 10 media files", snapshot["message"])

    def test_request_stop_returns_false_when_idle(self) -> None:
        state = TaskState(version="test")
        service = CacheLikesService(state)

        self.assertFalse(service.request_stop())

    def test_run_stops_when_emergency_stop_is_requested(self) -> None:
        state = TaskState(version="test")
        service = CacheLikesService(state)
        config = CrawlConfig(max_media_items=10)
        tweet_urls = [f"https://x.com/demo/status/{index}" for index in range(1, 4)]

        def fake_download(*_args, **_kwargs):
            service._stop_requested.set()
            return DownloadResult(downloaded_media_count=1)

        with patch(
            "app.core.service.collect_liked_tweet_urls",
            return_value=("demo_account", tweet_urls),
        ), patch("app.core.service.download_tweet_media", side_effect=fake_download) as mock_download:
            service._run(config)

        self.assertEqual(mock_download.call_count, 1)
        snapshot = state.snapshot()
        self.assertEqual(snapshot["phase"], "stopped")
        self.assertEqual(snapshot["downloaded_tweets"], 1)
        self.assertIn("Emergency stop completed", snapshot["message"])


if __name__ == "__main__":
    unittest.main()
