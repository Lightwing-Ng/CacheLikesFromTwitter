"""Read-only local media browser tests.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest

from app.core.local_media_browser import (
    BrowserDeletionCatalog,
    LocalMediaCatalog,
    LocalMediaItem,
    build_local_store_pagination,
    format_captured_at_label,
    paginate_media_items,
    resolve_local_media_path,
    sort_media_items,
)


def _write_media(path: Path, content: bytes = b"media") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _item(name: str, captured_at: str = "2026-08-08T00:00:00Z", media_kind: str = "image") -> LocalMediaItem:
    return LocalMediaItem(
        stable_id=f"id-{name}",
        source="x",
        media_kind=media_kind,
        relative_path=f"x/{name}",
        filename=name,
        title=name,
        description="",
        creator="demo",
        source_url="",
        captured_at=captured_at,
        captured_at_label="8 Aug 2026",
        content_bytes=5,
        project_name="",
    )


def test_scans_x_image_and_reads_info_json(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "x" / "uploader" / "123" / "123.jpg"
    _write_media(media_path, b"jpeg-bytes")
    (media_path.parent / "123.info.json").write_text(
        json.dumps(
            {
                "title": "A cached X image",
                "description": "A useful description",
                "uploader": "Uploader Name",
                "uploader_id": "uploader",
                "timestamp": 1786147200,
                "webpage_url": "https://x.com/uploader/status/123",
                "display_id": "123",
            }
        ),
        encoding="utf-8",
    )

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert len(items) == 1
    item = items[0]
    assert item.source == "x"
    assert item.media_kind == "image"
    assert item.relative_path == "x/uploader/123/123.jpg"
    assert item.title == "A cached X image"
    assert item.description == "A useful description"
    assert item.creator == "Uploader Name"
    assert item.source_url == "https://x.com/uploader/status/123"
    assert item.content_bytes == len(b"jpeg-bytes")


def test_scans_x_metadata_once_per_media_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "local_store"
    media_directory = root / "x" / "uploader" / "123"
    _write_media(media_directory / "first.jpg")
    _write_media(media_directory / "second.jpg")
    catalog = LocalMediaCatalog(root)
    metadata_loads: list[Path] = []

    def load_metadata(directory: Path) -> dict[str, str]:
        metadata_loads.append(directory)
        return {"title": "Shared X metadata"}

    monkeypatch.setattr(catalog, "_load_x_metadata", load_metadata)

    items = catalog.snapshot(force_refresh=True)

    assert [item.title for item in items] == ["Shared X metadata", "Shared X metadata"]
    assert metadata_loads == [media_directory]


def test_query_returns_stale_snapshot_while_refresh_is_in_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "local_store"
    _write_media(root / "x" / "demo" / "cached.jpg")
    catalog = LocalMediaCatalog(root, ttl_seconds=0)
    catalog.snapshot(force_refresh=True)

    refresh_started = Event()
    release_refresh = Event()
    query_finished = Event()
    original_scan_x = catalog._scan_x
    pages = []
    failures = []

    def blocked_scan_x():
        refresh_started.set()
        if not release_refresh.wait(timeout=2):
            raise TimeoutError("The test refresh was not released.")
        return original_scan_x()

    def run_query() -> None:
        try:
            pages.append(catalog.query())
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            query_finished.set()

    monkeypatch.setattr(catalog, "_scan_x", blocked_scan_x)
    refresh_thread = Thread(target=lambda: catalog.snapshot(force_refresh=True))
    query_thread = Thread(target=run_query)
    refresh_thread.start()

    try:
        assert refresh_started.wait(timeout=1)
        query_thread.start()
        assert query_finished.wait(timeout=1)
        assert not failures
        assert [item.filename for item in pages[0].items] == ["cached.jpg"]
    finally:
        release_refresh.set()
        refresh_thread.join(timeout=2)
        query_thread.join(timeout=2)

    assert not refresh_thread.is_alive()
    assert not query_thread.is_alive()


def test_browser_deletion_keeps_preview_and_blocks_future_source_downloads(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "x" / "uploader" / "123" / "123.jpg"
    _write_media(media_path, b"jpeg-bytes")
    (media_path.parent / "123.info.json").write_text(
        json.dumps(
            {
                "title": "A removable X image",
                "webpage_url": "https://x.com/uploader/status/123",
                "uploader_id": "uploader",
                "display_id": "123",
            }
        ),
        encoding="utf-8",
    )

    catalog = LocalMediaCatalog(root)
    item = catalog.snapshot(force_refresh=True)[0]
    deleted = catalog.delete(item.stable_id)

    assert deleted.is_deleted
    assert not media_path.exists()
    assert catalog.deleted_preview_path(item.stable_id).read_bytes() == b"jpeg-bytes"
    assert catalog.is_excluded("x", "https://twitter.com/uploader/status/123")
    assert catalog.snapshot(force_refresh=True)[0].is_deleted

    restored = catalog.restore(item.stable_id)

    assert not restored.is_deleted
    assert media_path.read_bytes() == b"jpeg-bytes"
    assert not catalog.is_excluded("x", item.source_url)
    assert catalog.deleted_preview_path(item.stable_id) is None


def test_browser_deletion_catalog_normalizes_source_keys(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    deletion_catalog = BrowserDeletionCatalog(root)
    item = _item("asset.jpg")
    media_path = root / item.relative_path
    _write_media(media_path)
    item = replace(
        item,
        source_url="https://x.com/demo/status/asset",
        resource_key="https://x.com/demo/status/asset",
    )

    deletion_catalog.delete(item)

    assert deletion_catalog.is_excluded("x", "https://twitter.com/demo/status/asset/")


def test_scans_x_video_and_supports_double_info_suffix(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "x" / "uploader" / "456" / "456.mp4"
    _write_media(media_path, b"video-bytes")
    (media_path.parent / "456.info.json.info.json").write_text(
        '{"title": "Cached X video", "upload_date": "20260808"}',
        encoding="utf-8",
    )

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert len(items) == 1
    assert items[0].media_kind == "video"
    assert items[0].title == "Cached X video"
    assert items[0].captured_at_label == "8 Aug 2026"


def test_scans_grok_catalog_metadata(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "grok" / "img_asset.jpg"
    _write_media(media_path, b"grok-image")
    (root / "grok" / ".grok_catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "identity": "asset-123/portrait",
                        "relative_path": "img_asset.jpg",
                        "media_kind": "image",
                        "source_url": "https://grok.com/files/asset-123",
                        "first_seen_at": "2026-08-01T00:00:00Z",
                        "last_seen_at": "2026-08-07T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert len(items) == 1
    assert items[0].source == "grok"
    assert items[0].title == "portrait"
    assert items[0].creator == "Grok"
    assert items[0].source_url == "https://grok.com/files/asset-123"
    assert items[0].captured_at_label == "7 Aug 2026"


def test_grok_catalog_damage_falls_back_to_filename_and_mtime(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "grok" / "fallback.webp"
    _write_media(media_path, b"fallback")
    os.utime(media_path, (1786147200, 1786147200))
    (root / "grok" / ".grok_catalog.json").write_text("{not valid", encoding="utf-8")

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert len(items) == 1
    assert items[0].filename == "fallback.webp"
    assert items[0].title == "fallback.webp"
    assert items[0].captured_at_label == "8 Aug 2026"


def test_scans_chatgpt_catalog_and_project_name(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "chatgpt" / "Demo Project" / "img_file.png"
    _write_media(media_path, b"chatgpt-image")
    (media_path.parent / ".chatgpt_catalog.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "file-123": {
                        "file_id": "file-123",
                        "relative_path": "img_file.png",
                        "conversation_url": "https://chatgpt.com/c/demo",
                        "alt_text": "A project illustration",
                        "width": 1200,
                        "height": 800,
                        "first_seen_at": "2026-08-02T00:00:00Z",
                        "last_seen_at": "2026-08-08T00:00:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert len(items) == 1
    assert items[0].source == "chatgpt"
    assert items[0].project_name == "Demo Project"
    assert items[0].title == "A project illustration"
    assert items[0].description == "A project illustration"
    assert items[0].source_url == "https://chatgpt.com/c/demo"
    assert items[0].width == 1200
    assert items[0].height == 800


def test_chatgpt_catalog_missing_falls_back_to_filename(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    media_path = root / "chatgpt" / "Fallback" / "img_file.avif"
    _write_media(media_path, b"avif-bytes")

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert len(items) == 1
    assert items[0].project_name == "Fallback"
    assert items[0].title == "img_file.avif"
    assert items[0].media_kind == "image"


def test_chatgpt_for_prompts_is_exempt_from_regular_inventory(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    _write_media(root / "chatgpt" / "forPrompts" / "temporary.png")
    _write_media(root / "chatgpt" / "RegularProject" / "inventory.png")

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert [item.relative_path for item in items] == ["chatgpt/RegularProject/inventory.png"]


def test_ignores_hidden_partial_state_and_unknown_files(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    visible = root / "x" / "demo" / "visible.png"
    _write_media(visible)
    _write_media(root / "x" / ".hidden" / "hidden.jpg")
    _write_media(root / "x" / "partial.jpg.part")
    _write_media(root / "x" / "download.ytdl")
    _write_media(root / "x" / "state.json")
    _write_media(root / "x" / "unknown.txt")
    _write_media(root / "x" / ".hidden.jpg")

    items = LocalMediaCatalog(root).snapshot(force_refresh=True)

    assert [item.relative_path for item in items] == ["x/demo/visible.png"]


def test_search_is_case_insensitive_and_source_kind_filters_apply(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    _write_media(root / "x" / "demo" / "Summer-Trip.jpg")
    _write_media(root / "grok" / "winter-video.mp4")
    catalog = LocalMediaCatalog(root)

    search_page = catalog.query(query="SUMMER", force_refresh=True)
    source_page = catalog.query(source="grok")
    kind_page = catalog.query(media_kind="video")

    assert [item.filename for item in search_page.items] == ["Summer-Trip.jpg"]
    assert [item.filename for item in source_page.items] == ["winter-video.mp4"]
    assert source_page.image_count == 0
    assert source_page.video_count == 1
    assert [item.filename for item in kind_page.items] == ["winter-video.mp4"]


def test_sorting_is_stable_for_equal_timestamps(tmp_path: Path) -> None:
    items = (
        _item("b.jpg"),
        _item("a.jpg"),
    )

    assert [item.filename for item in sort_media_items(items, "newest")] == ["a.jpg", "b.jpg"]
    assert [item.filename for item in sort_media_items(items, "oldest")] == ["a.jpg", "b.jpg"]
    assert [item.filename for item in sort_media_items(items, "name")] == ["a.jpg", "b.jpg"]


def test_page_invalid_and_out_of_range_values_are_normalized() -> None:
    items = tuple(_item(f"{index:02d}.jpg") for index in range(25))

    negative = paginate_media_items(items, page="-3")
    too_large = paginate_media_items(items, page="999")
    malformed = paginate_media_items(items, page="not-a-page")

    assert negative.current_page == 1
    assert malformed.current_page == 1
    assert too_large.current_page == 2
    assert too_large.total_pages == 2
    assert len(too_large.items) == 1


def test_pagination_matches_investment_table_five_page_chunks() -> None:
    first_chunk = build_local_store_pagination(total_pages=12, current_page=1)
    middle_chunk = build_local_store_pagination(total_pages=12, current_page=6)

    assert [(item.kind, item.page, item.is_active) for item in first_chunk] == [
        ("page", 1, True),
        ("page", 2, False),
        ("page", 3, False),
        ("page", 4, False),
        ("page", 5, False),
        ("ellipsis", 0, False),
        ("page", 12, False),
        ("next", 6, False),
    ]
    assert [(item.kind, item.page, item.is_active) for item in middle_chunk] == [
        ("previous", 5, False),
        ("page", 1, False),
        ("ellipsis", 0, False),
        ("page", 6, True),
        ("page", 7, False),
        ("page", 8, False),
        ("page", 9, False),
        ("page", 10, False),
        ("ellipsis", 0, False),
        ("page", 12, False),
        ("next", 11, False),
    ]


def test_date_format_uses_fixed_english_months() -> None:
    assert format_captured_at_label("20260808") == "8 Aug 2026"


def test_stable_id_is_unchanged_across_two_scans(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    _write_media(root / "x" / "demo" / "same.jpg")
    catalog = LocalMediaCatalog(root, ttl_seconds=0)

    first = catalog.snapshot(force_refresh=True)[0]
    second = catalog.snapshot(force_refresh=True)[0]

    assert first.stable_id == second.stable_id
    assert first.stable_id.startswith("media-")


def test_external_symlink_is_rejected_and_not_scanned(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    outside = tmp_path / "outside.jpg"
    _write_media(outside, b"outside")
    link = root / "x" / "outside.jpg"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    catalog = LocalMediaCatalog(root)

    assert resolve_local_media_path(root, "x/outside.jpg") is None
    assert catalog.snapshot(force_refresh=True) == ()


def test_parent_path_traversal_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "local_store"
    _write_media(root / "x" / "safe.jpg")

    assert resolve_local_media_path(root, "../x/safe.jpg") is None
    assert resolve_local_media_path(root, "%2e%2e/x/safe.jpg") is None
    assert resolve_local_media_path(root, "%252e%252e/x/safe.jpg") is None
