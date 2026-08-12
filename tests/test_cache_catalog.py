"""Regression tests for the persistent local tweet cache catalog.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.cache_catalog import (
    CATALOG_FILENAME,
    LocalTweetCacheIndex,
    canonicalize_tweet_url,
    extract_status_id,
    summarize_cached_tweet_dir,
    summarize_local_store_root,
)
from app.core.resource_persistence import read_parquet_rows


def _write_cached_tweet(directory: Path, url: str, media_name: str) -> None:
    directory.mkdir(parents=True)
    (directory / media_name).write_bytes(b"media")
    (directory / "metadata.info.json").write_text(json.dumps({"webpage_url": url}), encoding="utf-8")


def test_url_canonicalization_and_status_id_cover_x_and_twitter_variants() -> None:
    assert canonicalize_tweet_url("https://twitter.com/User/status/123/?foo=1") == "https://x.com/User/status/123"
    assert canonicalize_tweet_url("https://mobile.x.com/user/status/456") == "https://x.com/user/status/456"
    assert canonicalize_tweet_url("") == ""
    assert extract_status_id("https://x.com/user/status/456?source=share") == "456"
    assert extract_status_id("https://x.com/user/status/not-a-number") == ""


def test_cached_tweet_summary_counts_media_and_respects_video_metadata(tmp_path: Path) -> None:
    image_dir = tmp_path / "image-post"
    _write_cached_tweet(image_dir, "https://x.com/demo/status/1", "image.jpg")
    (image_dir / "clip.mp4").write_bytes(b"video")
    assert summarize_cached_tweet_dir(image_dir) == (True, 1, 1)

    video_dir = tmp_path / "video-post"
    _write_cached_tweet(video_dir, "https://x.com/demo/status/2", "poster.jpg")
    (video_dir / "clip.mp4").write_bytes(b"video")
    (video_dir / "metadata.info.json").write_text('{"_type": "video"}', encoding="utf-8")
    assert summarize_cached_tweet_dir(video_dir) == (True, 0, 1)


def test_catalog_survives_rebuild_and_prevents_duplicate_claims(tmp_path: Path) -> None:
    account_dir = tmp_path / "demo"
    tweet_dir = account_dir / "tweet-123"
    url = "https://twitter.com/demo/status/123?ref=copy"
    _write_cached_tweet(tweet_dir, url, "image.png")

    index = LocalTweetCacheIndex.build(account_dir)
    assert index.contains_complete_cache("https://x.com/demo/status/123")
    assert index.summarize() == (1, 1, 0)
    assert index.claim("https://x.com/demo/status/123") is False
    assert not (tweet_dir / "metadata.info.json").exists()
    rows = read_parquet_rows(account_dir / CATALOG_FILENAME)
    assert rows is not None
    assert rows[0]["canonical_urls"] == ["https://x.com/demo/status/123"]
    assert rows[0]["status_ids"] == ["123"]
    assert rows[0]["webpage_url"] == url
    assert index.metadata_for_directory(tweet_dir)["webpage_url"] == url

    uncached_url = "https://x.com/demo/status/999"
    assert index.claim(uncached_url) is True
    assert index.claim(uncached_url) is False
    index.release_claim(uncached_url)
    assert index.claim(uncached_url) is True

    reloaded = LocalTweetCacheIndex.build(account_dir)
    assert reloaded.contains_complete_cache("https://x.com/demo/status/123")
    assert reloaded.summarize() == (1, 1, 0)


def test_local_store_summary_ignores_hidden_directories(tmp_path: Path) -> None:
    _write_cached_tweet(tmp_path / "alice" / "tweet-1", "https://x.com/alice/status/1", "image.webp")
    _write_cached_tweet(tmp_path / ".ignored" / "tweet-2", "https://x.com/ignored/status/2", "clip.mp4")

    summaries = summarize_local_store_root(tmp_path)

    assert [(item.account_name, item.downloaded_posts, item.downloaded_images, item.downloaded_videos) for item in summaries] == [
        ("alice", 1, 1, 0)
    ]
