"""Tests for yt-dlp output classification and retry boundaries.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from app.core.config import CrawlConfig
from app.core.downloader import (
    MEDIA_MARKER_PREFIX,
    build_cookies_from_browser_arg,
    count_downloaded_media_types,
    is_existing_file_conflict,
    is_missing_media_skip_output,
    is_not_found_skip_output,
    is_successful_skip_output,
    is_suspended_skip_output,
    is_transient_retryable_output,
    is_unsupported_external_url_skip_output,
    parse_downloaded_paths,
    run_yt_dlp_with_retries,
)


def test_output_parsing_counts_media_and_classifies_skips() -> None:
    output = "\n".join(
        [
            "ordinary output",
            f"{MEDIA_MARKER_PREFIX}/tmp/photo.JPG",
            f"{MEDIA_MARKER_PREFIX}/tmp/video.mp4",
            f"{MEDIA_MARKER_PREFIX}/tmp/unknown.txt",
        ]
    )

    paths = parse_downloaded_paths(output)

    assert [str(path) for path in paths] == ["/tmp/photo.JPG", "/tmp/video.mp4", "/tmp/unknown.txt"]
    assert count_downloaded_media_types(paths) == (1, 1)
    assert is_successful_skip_output("[download] file already exists")
    assert is_missing_media_skip_output("No video could be found in this tweet")
    assert is_not_found_skip_output("HTTP Error 404")
    assert is_suspended_skip_output("account: suspended")
    assert is_existing_file_conflict("unable to rename because the file exists")


def test_external_url_classifier_does_not_skip_native_x_urls() -> None:
    assert is_unsupported_external_url_skip_output("Unsupported URL: https://example.com/video")
    assert not is_unsupported_external_url_skip_output("Unsupported URL: https://x.com/user/status/1")


def test_browser_cookie_arguments_follow_selected_browser() -> None:
    chrome_argument = build_cookies_from_browser_arg(CrawlConfig(x_browser="chrome"))
    assert chrome_argument.startswith("chrome:")
    assert build_cookies_from_browser_arg(CrawlConfig(x_browser="safari")) == "safari"
    with pytest.raises(RuntimeError, match="Unsupported X browser"):
        build_cookies_from_browser_arg(CrawlConfig(x_browser="firefox"))


def test_transient_yt_dlp_failure_retries_then_returns_success() -> None:
    transient = subprocess.CompletedProcess(["yt-dlp"], 1, stdout="", stderr="timed out")
    success = subprocess.CompletedProcess(["yt-dlp"], 0, stdout="done", stderr="")

    with patch("app.core.downloader.subprocess.run", side_effect=[transient, success]) as runner, patch(
        "app.core.downloader.time.sleep"
    ) as sleep:
        result = run_yt_dlp_with_retries(["yt-dlp"], "https://x.com/demo/status/1")

    assert result is success
    assert runner.call_count == 2
    sleep.assert_called_once()


def test_non_transient_yt_dlp_failure_does_not_retry() -> None:
    failure = subprocess.CompletedProcess(["yt-dlp"], 1, stdout="", stderr="HTTP Error 404")

    with patch("app.core.downloader.subprocess.run", return_value=failure) as runner:
        result = run_yt_dlp_with_retries(["yt-dlp"], "https://x.com/demo/status/1")

    assert result is failure
    assert runner.call_count == 1
    assert not is_transient_retryable_output(failure.stderr)
