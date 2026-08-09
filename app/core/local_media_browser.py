"""Local media discovery, deletion tombstones, and pagination."""

# Code version: v1.4.1-codex.1

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import Condition, RLock
from time import monotonic
from typing import Any, Iterable, Iterator, Mapping
from urllib.parse import unquote, urlsplit

from . import config


IMAGE_SUFFIXES = frozenset({".avif", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".webp"})
VIDEO_SUFFIXES = frozenset({".m4v", ".mkv", ".mov", ".mp4", ".webm"})
MEDIA_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES
SOURCE_VALUES = frozenset({"all", "x", "grok", "chatgpt"})
MEDIA_KIND_VALUES = frozenset({"all", "image", "video"})
SORT_VALUES = frozenset({"newest", "oldest", "name"})
PAGE_SIZE = 24
DEFAULT_TTL_SECONDS = 5.0
CHATGPT_TEMPORARY_PROJECT_NAMES = frozenset({"forprompts"})
_DATE_RE = re.compile(r"^\d{8}$")
_NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?$")
_ENGLISH_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True, slots=True)
class LocalMediaItem:
    """Describe one readable media file without exposing its absolute path."""

    stable_id: str
    source: str
    media_kind: str
    relative_path: str
    filename: str
    title: str
    description: str
    creator: str
    source_url: str
    captured_at: str
    captured_at_label: str
    content_bytes: int
    project_name: str
    alt_text: str = ""
    width: int = 0
    height: int = 0
    resource_key: str = ""
    is_deleted: bool = False
    preview_relative_path: str = ""


@dataclass(frozen=True, slots=True)
class LocalMediaPaginationItem:
    """Describe one server-backed control in the shared local-store pagination UI."""

    kind: str
    page: int = 0
    is_active: bool = False


@dataclass(frozen=True, slots=True)
class LocalMediaPage:
    """Contain a filtered, sorted, and paginated media result."""

    items: tuple[LocalMediaItem, ...]
    total_count: int
    image_count: int
    video_count: int
    current_page: int
    total_pages: int
    page_size: int = PAGE_SIZE

    @property
    def pagination_items(self) -> tuple[LocalMediaPaginationItem, ...]:
        """Return the same five-page pagination sequence used by the investment table."""
        return build_local_store_pagination(self.total_pages, self.current_page)

    @property
    def pagination_active_index(self) -> int:
        """Return the zero-based control index used to place the active indicator."""
        for index, item in enumerate(self.pagination_items):
            if item.is_active:
                return index
        return 0


def stable_media_id(relative_path: str) -> str:
    """Return a deterministic identifier derived from a POSIX relative path."""
    normalized_path = str(relative_path or "").replace("\\", "/")
    digest = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()
    return f"media-{digest[:24]}"


def format_captured_at_label(value: str | datetime | None) -> str:
    """Format a timestamp with fixed English month names for the UI."""
    parsed = _parse_datetime(value)
    if parsed is None:
        return "Unknown date"
    return f"{parsed.day} {_ENGLISH_MONTHS[parsed.month - 1]} {parsed.year}"


def resolve_local_media_path(local_store_root: Path | str, relative_path: str) -> Path | None:
    """Resolve a media path only when it remains a readable file inside the cache."""
    root = Path(local_store_root).expanduser().resolve(strict=False)
    decoded_path = _decode_relative_path(relative_path)
    if decoded_path is None:
        return None

    relative = PurePosixPath(decoded_path)
    if relative.is_absolute() or not relative.parts:
        return None
    if any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts):
        return None

    candidate = root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved_relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None

    if any(part.startswith(".") for part in resolved_relative.parts):
        return None
    if resolved.suffix.lower() not in MEDIA_SUFFIXES:
        return None
    try:
        stat_result = resolved.stat()
    except OSError:
        return None
    if not resolved.is_file() or stat_result.st_size <= 0 or not os.access(resolved, os.R_OK):
        return None
    return resolved


DELETED_MEDIA_FILENAME = ".browser_deleted.json"
DELETED_MEDIA_DIRNAME = ".browser-trash"


def normalize_resource_key(source: str, value: str) -> str:
    """Normalize a downloader identity before persisting or comparing exclusions."""
    normalized_source = str(source or "").strip().lower()
    text = str(value or "").strip()
    if normalized_source == "x":
        parsed = urlsplit(text)
        hostname = (parsed.hostname or "").lower()
        if hostname in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and parsed.path:
            return f"https://x.com{parsed.path.rstrip('/')}".lower()
    return text.casefold() if normalized_source in {"grok", "chatgpt"} else text


def is_exempt_media_path(relative_path: str) -> bool:
    """Return whether a path belongs to the ChatGPT temporary work directory."""
    parts = PurePosixPath(str(relative_path or "").replace("\\", "/")).parts
    return len(parts) >= 2 and parts[0].casefold() == "chatgpt" and parts[1].casefold() in CHATGPT_TEMPORARY_PROJECT_NAMES


class BrowserDeletionCatalog:
    """Persist removed media as recoverable tombstones with local previews."""

    def __init__(self, local_store_root: Path | str) -> None:
        self.local_store_root = Path(local_store_root).expanduser().resolve(strict=False)
        self.catalog_path = self.local_store_root / DELETED_MEDIA_FILENAME
        self.trash_root = self.local_store_root / DELETED_MEDIA_DIRNAME
        self._lock = RLock()
        self._entries = self._load_entries()

    def is_excluded(self, source: str, resource_key: str) -> bool:
        """Return whether a source resource has been removed by the operator."""
        normalized_source = str(source or "").strip().lower()
        normalized_key = normalize_resource_key(normalized_source, resource_key)
        if not normalized_source or not normalized_key:
            return False
        with self._lock:
            return any(
                entry.get("source") == normalized_source
                and normalize_resource_key(normalized_source, str(entry.get("resource_key") or ""))
                == normalized_key
                for entry in self._entries.values()
            )

    def delete(self, item: LocalMediaItem) -> LocalMediaItem:
        """Move one active file to recoverable storage and record its exclusion."""
        if item.is_deleted:
            return item
        if is_exempt_media_path(item.relative_path):
            raise PermissionError("ChatGPT temporary media is exempt from browser deletion.")

        with self._lock:
            existing = self._entries.get(item.stable_id)
            if existing is not None:
                return self._item_from_entry(existing)

            media_path = resolve_local_media_path(self.local_store_root, item.relative_path)
            if media_path is None:
                raise FileNotFoundError("Cached media is no longer available.")

            trash_relative_path = f"{DELETED_MEDIA_DIRNAME}/{item.stable_id}{media_path.suffix.lower()}"
            trash_path = self._resolve_storage_path(trash_relative_path, allow_hidden=True)
            if trash_path is None:
                raise ValueError("Invalid deleted-media path.")
            trash_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(media_path), str(trash_path))

            payload = asdict(item)
            payload["resource_key"] = item.resource_key or item.source_url or item.relative_path
            entry = {
                "stable_id": item.stable_id,
                "source": item.source,
                "resource_key": payload["resource_key"],
                "original_relative_path": item.relative_path,
                "preview_relative_path": trash_relative_path,
                "item": payload,
                "deleted_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
            self._entries[item.stable_id] = entry
            self._save_entries()
            return self._item_from_entry(entry)

    def restore(self, stable_id: str) -> LocalMediaItem:
        """Restore one removed file to its original path and clear its exclusion."""
        with self._lock:
            entry = self._entries.get(str(stable_id or ""))
            if entry is None:
                raise KeyError("Removed media was not found.")

            original_relative_path = str(entry.get("original_relative_path") or "")
            original_path = self._resolve_storage_path(original_relative_path, allow_hidden=False)
            preview_relative_path = str(entry.get("preview_relative_path") or "")
            preview_path = self._resolve_storage_path(preview_relative_path, allow_hidden=True)
            if original_path is None or preview_path is None:
                raise ValueError("Removed media has an invalid restore path.")
            if original_path.exists():
                raise FileExistsError("The original cache path is occupied.")
            if not preview_path.is_file():
                raise FileNotFoundError("The retained preview is no longer available.")

            original_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(preview_path), str(original_path))
            del self._entries[str(stable_id)]
            self._save_entries()
            payload = dict(entry.get("item") or {})
            payload["is_deleted"] = False
            payload["preview_relative_path"] = ""
            return self._item_from_payload(payload)

    def preview_path(self, stable_id: str) -> Path | None:
        """Return a retained preview path without exposing arbitrary hidden files."""
        with self._lock:
            entry = self._entries.get(str(stable_id or ""))
            if entry is None:
                return None
            candidate = self._resolve_storage_path(str(entry.get("preview_relative_path") or ""), allow_hidden=True)
            if candidate is None or not candidate.is_file() or candidate.suffix.lower() not in MEDIA_SUFFIXES:
                return None
            return candidate

    def deleted_items(self) -> list[LocalMediaItem]:
        """Return tombstones whose retained media is still available for preview."""
        with self._lock:
            items: list[LocalMediaItem] = []
            for entry in self._entries.values():
                item = self._item_from_entry(entry)
                if is_exempt_media_path(item.relative_path):
                    continue
                if self.preview_path(str(entry.get("stable_id") or "")) is not None:
                    items.append(item)
            return items

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {}
        raw_entries = payload.get("entries", {}) if isinstance(payload, dict) else {}
        if not isinstance(raw_entries, dict):
            return {}
        return {
            str(stable_id): entry
            for stable_id, entry in raw_entries.items()
            if isinstance(entry, dict) and str(stable_id).strip()
        }

    def _save_entries(self) -> None:
        self.local_store_root.mkdir(parents=True, exist_ok=True)
        temporary_path = self.catalog_path.with_name(f"{self.catalog_path.name}.tmp")
        temporary_path.write_text(
            json.dumps({"version": 1, "entries": self._entries}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.catalog_path)

    def _resolve_storage_path(self, relative_path: str, *, allow_hidden: bool) -> Path | None:
        decoded_path = _decode_relative_path(relative_path)
        if decoded_path is None:
            return None
        relative = PurePosixPath(decoded_path)
        if relative.is_absolute() or not relative.parts:
            return None
        if any(part in {"", ".", ".."} or (part.startswith(".") and not allow_hidden) for part in relative.parts):
            return None
        candidate = self.local_store_root.joinpath(*relative.parts)
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.local_store_root)
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved

    @staticmethod
    def _item_from_payload(payload: Mapping[str, Any]) -> LocalMediaItem:
        fields = {field.name for field in LocalMediaItem.__dataclass_fields__.values()}
        return LocalMediaItem(**{key: payload.get(key) for key in fields if key in payload})

    def _item_from_entry(self, entry: Mapping[str, Any]) -> LocalMediaItem:
        payload = dict(entry.get("item") or {})
        payload["stable_id"] = str(entry.get("stable_id") or payload.get("stable_id") or "")
        payload["relative_path"] = str(entry.get("original_relative_path") or payload.get("relative_path") or "")
        payload["resource_key"] = str(entry.get("resource_key") or payload.get("resource_key") or "")
        payload["is_deleted"] = True
        payload["preview_relative_path"] = str(entry.get("preview_relative_path") or "")
        return self._item_from_payload(payload)


def normalize_browser_filters(
    source: str | None = None,
    media_kind: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    page: object = 1,
) -> dict[str, Any]:
    """Normalize user-controlled browser filters to safe allowlisted values."""
    normalized_source = str(source or "").strip().lower()
    normalized_kind = str(media_kind or "").strip().lower()
    normalized_sort = str(sort or "").strip().lower()
    normalized_query = str(query or "").strip()[:120]
    return {
        "source": normalized_source if normalized_source in SOURCE_VALUES else "all",
        "kind": normalized_kind if normalized_kind in MEDIA_KIND_VALUES else "all",
        "q": normalized_query,
        "sort": normalized_sort if normalized_sort in SORT_VALUES else "newest",
        "page": _coerce_positive_page(page),
    }


def filter_media_items(
    items: Iterable[LocalMediaItem],
    *,
    source: str = "all",
    media_kind: str = "all",
    query: str = "",
) -> tuple[LocalMediaItem, ...]:
    """Filter media items by source, kind, and case-insensitive text search."""
    normalized = normalize_browser_filters(source, media_kind, query, "newest", 1)
    search = normalized["q"].casefold()
    filtered: list[LocalMediaItem] = []
    for item in items:
        if normalized["source"] != "all" and item.source != normalized["source"]:
            continue
        if normalized["kind"] != "all" and item.media_kind != normalized["kind"]:
            continue
        if search:
            searchable = " ".join(
                (
                    item.filename,
                    item.title,
                    item.description,
                    item.creator,
                    item.project_name,
                )
            ).casefold()
            if search not in searchable:
                continue
        filtered.append(item)
    return tuple(filtered)


def sort_media_items(items: Iterable[LocalMediaItem], sort: str = "newest") -> tuple[LocalMediaItem, ...]:
    """Sort media deterministically, using relative paths as stable tie breakers."""
    normalized_sort = str(sort or "").strip().lower()
    if normalized_sort not in SORT_VALUES:
        normalized_sort = "newest"

    if normalized_sort == "name":
        def key(item: LocalMediaItem) -> tuple[str, str]:
            return (item.filename.casefold(), item.relative_path)
    else:
        direction = -1 if normalized_sort == "newest" else 1

        def key(item: LocalMediaItem) -> tuple[float, str]:
            timestamp = _parse_datetime(item.captured_at)
            timestamp_value = timestamp.timestamp() if timestamp is not None else 0.0
            return (direction * timestamp_value, item.relative_path)

    return tuple(sorted(items, key=key))


def paginate_media_items(
    items: Iterable[LocalMediaItem],
    page: object = 1,
    page_size: int = PAGE_SIZE,
) -> LocalMediaPage:
    """Return one bounded page and normalized page metadata."""
    materialized = tuple(items)
    safe_page_size = max(1, int(page_size))
    total_count = len(materialized)
    total_pages = max(1, (total_count + safe_page_size - 1) // safe_page_size)
    current_page = min(total_pages, _coerce_positive_page(page))
    start = (current_page - 1) * safe_page_size
    page_items = materialized[start : start + safe_page_size]
    return LocalMediaPage(
        items=page_items,
        total_count=total_count,
        image_count=sum(1 for item in materialized if item.media_kind == "image"),
        video_count=sum(1 for item in materialized if item.media_kind == "video"),
        current_page=current_page,
        total_pages=total_pages,
        page_size=safe_page_size,
    )


def build_local_store_pagination(
    total_pages: int,
    current_page: int,
) -> tuple[LocalMediaPaginationItem, ...]:
    """Build the investment table's five-page chunk and boundary controls."""
    normalized_total_pages = max(1, int(total_pages))
    normalized_current_page = min(normalized_total_pages, max(1, int(current_page)))
    if normalized_total_pages <= 1:
        return ()

    chunk_size = 5
    start_page = ((normalized_current_page - 1) // chunk_size) * chunk_size + 1
    end_page = min(start_page + chunk_size - 1, normalized_total_pages)
    items: list[LocalMediaPaginationItem] = []

    if start_page > 1:
        items.append(LocalMediaPaginationItem(kind="previous", page=start_page - 1))
        items.append(LocalMediaPaginationItem(kind="page", page=1))
        items.append(LocalMediaPaginationItem(kind="ellipsis"))

    for page in range(start_page, end_page + 1):
        items.append(
            LocalMediaPaginationItem(
                kind="page",
                page=page,
                is_active=page == normalized_current_page,
            )
        )

    if end_page < normalized_total_pages:
        items.append(LocalMediaPaginationItem(kind="ellipsis"))
        items.append(LocalMediaPaginationItem(kind="page", page=normalized_total_pages))
        items.append(LocalMediaPaginationItem(kind="next", page=end_page + 1))

    return tuple(items)


class LocalMediaCatalog:
    """Scan local media and manage recoverable browser deletions."""

    def __init__(
        self,
        local_store_root: Path | str | None = None,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.local_store_root = Path(local_store_root or config.LOCAL_STORE_ROOT).expanduser().resolve(strict=False)
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = RLock()
        self._refresh_condition = Condition(self._lock)
        self._deletion_catalog = BrowserDeletionCatalog(self.local_store_root)
        self._cached_snapshot: tuple[LocalMediaItem, ...] = ()
        self._cached_at = 0.0
        self._has_snapshot = False
        self._refreshing = False
        self._generation = 0

    def snapshot(self, force_refresh: bool = False) -> tuple[LocalMediaItem, ...]:
        """Return a short-lived, thread-safe snapshot of readable local media."""
        while True:
            with self._refresh_condition:
                now = monotonic()
                if not force_refresh and self._has_snapshot and now - self._cached_at < self.ttl_seconds:
                    return self._cached_snapshot

                if self._refreshing:
                    if self._has_snapshot and not force_refresh:
                        return self._cached_snapshot
                    while self._refreshing:
                        self._refresh_condition.wait()
                    if self._has_snapshot:
                        return self._cached_snapshot
                    continue

                refresh_generation = self._generation
                self._refreshing = True

            try:
                refreshed_snapshot = self._build_snapshot()
            except Exception:
                with self._refresh_condition:
                    self._refreshing = False
                    self._refresh_condition.notify_all()
                raise

            with self._refresh_condition:
                self._refreshing = False
                if refresh_generation == self._generation:
                    self._cached_snapshot = refreshed_snapshot
                    self._cached_at = monotonic()
                    self._has_snapshot = True
                    self._refresh_condition.notify_all()
                    return self._cached_snapshot
                self._refresh_condition.notify_all()

    def _build_snapshot(self) -> tuple[LocalMediaItem, ...]:
        """Scan the cache outside the snapshot-state lock."""
        items: list[LocalMediaItem] = []
        for scanner in (self._scan_x, self._scan_grok, self._scan_chatgpt):
            try:
                items.extend(scanner())
            except Exception:
                continue

        items.extend(self._deletion_catalog.deleted_items())
        return tuple(sorted(items, key=lambda item: (item.relative_path.casefold(), item.relative_path)))

    def invalidate(self) -> None:
        """Discard the in-memory snapshot without touching the local cache."""
        with self._refresh_condition:
            self._invalidate_locked()

    def delete(self, stable_id: str) -> LocalMediaItem:
        """Remove one cached file from active storage while retaining an undo preview."""
        item = next(
            (candidate for candidate in self.snapshot(force_refresh=True) if candidate.stable_id == stable_id),
            None,
        )
        if item is None:
            raise KeyError("Cached media was not found.")

        with self._refresh_condition:
            deleted_item = self._deletion_catalog.delete(item)
            self._invalidate_locked()
            return deleted_item

    def restore(self, stable_id: str) -> LocalMediaItem:
        """Restore one removed media file and make it eligible for future downloads."""
        with self._refresh_condition:
            restored_item = self._deletion_catalog.restore(stable_id)
            self._invalidate_locked()
            return restored_item

    def _invalidate_locked(self) -> None:
        """Discard cache state while preventing an older scan from publishing."""
        self._generation += 1
        self._cached_snapshot = ()
        self._cached_at = 0.0
        self._has_snapshot = False

    def deleted_preview_path(self, stable_id: str) -> Path | None:
        """Return the retained preview path for one deleted media item."""
        return self._deletion_catalog.preview_path(stable_id)

    def is_excluded(self, source: str, resource_key: str) -> bool:
        """Return whether a source resource is persistently excluded from downloads."""
        return self._deletion_catalog.is_excluded(source, resource_key)

    def query(
        self,
        *,
        source: str = "all",
        media_kind: str = "all",
        query: str = "",
        sort: str = "newest",
        page: object = 1,
        force_refresh: bool = False,
    ) -> LocalMediaPage:
        """Return a safe filtered, sorted, and paginated view of the snapshot."""
        filters = normalize_browser_filters(source, media_kind, query, sort, page)
        filtered = filter_media_items(
            self.snapshot(force_refresh=force_refresh),
            source=filters["source"],
            media_kind=filters["kind"],
            query=filters["q"],
        )
        return paginate_media_items(sort_media_items(filtered, filters["sort"]), filters["page"])

    def _scan_x(self) -> list[LocalMediaItem]:
        root = self.local_store_root / "x"
        items: list[LocalMediaItem] = []
        metadata_by_directory: dict[Path, Mapping[str, Any]] = {}
        for media_path in self._iter_media_files(root):
            file_info = _stat_media_file(media_path)
            if file_info is None:
                continue
            directory = media_path.parent
            if directory not in metadata_by_directory:
                metadata_by_directory[directory] = self._load_x_metadata(directory)
            metadata = metadata_by_directory[directory]
            uploader = _display_text(metadata.get("uploader") or metadata.get("uploader_id"))
            uploader_id = _display_text(metadata.get("uploader_id"))
            display_id = _display_text(metadata.get("display_id"))
            source_url = _safe_source_url(metadata.get("webpage_url"))
            if not source_url and uploader_id and display_id:
                source_url = f"https://x.com/{uploader_id}/status/{display_id}"
            items.append(
                self._build_item(
                    media_path,
                    source="x",
                    title=metadata.get("title"),
                    description=metadata.get("description"),
                    creator=uploader or "X",
                    source_url=source_url,
                    resource_key=source_url,
                    captured_value=metadata.get("timestamp") or metadata.get("upload_date"),
                    stat_result=file_info,
                )
            )
        return items

    def _scan_grok(self) -> list[LocalMediaItem]:
        root = self.local_store_root / "grok"
        files = self._media_files_by_relative_path(root)
        catalog_entries = self._load_grok_catalog(root)
        items: list[LocalMediaItem] = []
        for relative_path, media_path in files.items():
            file_info = _stat_media_file(media_path)
            if file_info is None:
                continue
            entry = catalog_entries.get(relative_path, {})
            identity = _display_text(entry.get("identity"))
            title = identity.rsplit("/", 1)[-1] if identity else media_path.name
            resource_key = identity.split("/", 1)[0] if identity else ""
            items.append(
                self._build_item(
                    media_path,
                    source="grok",
                    title=title,
                    description=identity,
                    creator="Grok",
                    source_url=_safe_source_url(entry.get("source_url")),
                    resource_key=resource_key,
                    captured_value=entry.get("last_seen_at") or entry.get("first_seen_at"),
                    stat_result=file_info,
                )
            )
        return items

    def _scan_chatgpt(self) -> list[LocalMediaItem]:
        root = self.local_store_root / "chatgpt"
        items: list[LocalMediaItem] = []
        for project_dir in self._iter_visible_directories(root):
            if project_dir.name.casefold() in CHATGPT_TEMPORARY_PROJECT_NAMES:
                continue
            project_name = project_dir.name
            files = self._media_files_by_relative_path(project_dir)
            catalog_entries = self._load_chatgpt_catalog(project_dir)
            for relative_path, media_path in files.items():
                file_info = _stat_media_file(media_path)
                if file_info is None:
                    continue
                entry = catalog_entries.get(relative_path, {})
                alt_text = _display_text(entry.get("alt_text"))
                try:
                    width = max(0, int(entry.get("width") or 0))
                    height = max(0, int(entry.get("height") or 0))
                except (TypeError, ValueError):
                    width = 0
                    height = 0
                items.append(
                    self._build_item(
                        media_path,
                        source="chatgpt",
                        title=alt_text or media_path.name,
                        description=alt_text,
                        creator=project_name,
                        source_url=_safe_source_url(entry.get("conversation_url")),
                        resource_key=_display_text(entry.get("file_id")) or media_path.stem.removeprefix("img_"),
                        captured_value=entry.get("last_seen_at") or entry.get("first_seen_at"),
                        project_name=project_name,
                        alt_text=alt_text,
                        width=width,
                        height=height,
                        stat_result=file_info,
                    )
                )
        return items

    def _build_item(
        self,
        media_path: Path,
        *,
        source: str,
        title: Any,
        description: Any,
        creator: Any,
        source_url: str,
        captured_value: Any,
        stat_result: os.stat_result,
        resource_key: str = "",
        project_name: str = "",
        alt_text: str = "",
        width: int = 0,
        height: int = 0,
    ) -> LocalMediaItem:
        relative_path = media_path.relative_to(self.local_store_root).as_posix()
        captured_at_dt = _parse_datetime(captured_value) or datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
        captured_at = _isoformat(captured_at_dt)
        safe_title = _redact_local_root(_display_text(title) or media_path.name, self.local_store_root)
        safe_description = _redact_local_root(_display_text(description), self.local_store_root)
        safe_creator = _redact_local_root(_display_text(creator) or source.title(), self.local_store_root)
        return LocalMediaItem(
            stable_id=stable_media_id(relative_path),
            source=source,
            media_kind="video" if media_path.suffix.lower() in VIDEO_SUFFIXES else "image",
            relative_path=relative_path,
            filename=media_path.name,
            title=safe_title,
            description=safe_description,
            creator=safe_creator,
            source_url=source_url,
            captured_at=captured_at,
            captured_at_label=format_captured_at_label(captured_at_dt),
            content_bytes=int(stat_result.st_size),
            project_name=_redact_local_root(_display_text(project_name), self.local_store_root),
            alt_text=_redact_local_root(_display_text(alt_text), self.local_store_root),
            width=width,
            height=height,
            resource_key=_redact_local_root(_display_text(resource_key), self.local_store_root),
        )

    def _media_files_by_relative_path(self, root: Path) -> dict[str, Path]:
        files: dict[str, Path] = {}
        for media_path in self._iter_media_files(root):
            try:
                relative_path = media_path.relative_to(root).as_posix()
            except ValueError:
                continue
            files.setdefault(relative_path, media_path)
        return files

    def _iter_media_files(self, root: Path) -> Iterator[Path]:
        if not root.exists() or not root.is_dir():
            return
        pending = [root]
        visited_directories: set[Path] = set()
        while pending:
            directory = pending.pop()
            safe_directory = self._resolve_inside(directory, require_directory=True)
            if safe_directory is None:
                continue
            if safe_directory in visited_directories:
                continue
            visited_directories.add(safe_directory)
            try:
                children = sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name))
            except OSError:
                continue
            for child in children:
                if child.name.startswith("."):
                    continue
                if child.is_symlink():
                    resolved_child = self._resolve_inside(child)
                    if resolved_child is None or resolved_child.is_dir():
                        continue
                    if resolved_child.is_file() and child.suffix.lower() in MEDIA_SUFFIXES:
                        yield child
                    continue
                try:
                    if child.is_dir():
                        pending.append(child)
                    elif child.is_file() and child.suffix.lower() in MEDIA_SUFFIXES:
                        if self._resolve_inside(child) is not None:
                            yield child
                except OSError:
                    continue

    def _iter_visible_directories(self, root: Path) -> Iterator[Path]:
        if not root.exists() or not root.is_dir():
            return
        try:
            children = sorted(root.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.is_symlink():
                continue
            try:
                if child.is_dir() and self._resolve_inside(child, require_directory=True) is not None:
                    yield child
            except OSError:
                continue

    def _resolve_inside(self, path: Path, require_directory: bool = False) -> Path | None:
        try:
            lexical_relative = path.relative_to(self.local_store_root)
            if any(part.startswith(".") for part in lexical_relative.parts):
                return None
            resolved = path.resolve(strict=True)
            resolved_relative = resolved.relative_to(self.local_store_root)
        except (OSError, RuntimeError, ValueError):
            return None
        if any(part.startswith(".") for part in resolved_relative.parts):
            return None
        if require_directory and not resolved.is_dir():
            return None
        if not require_directory and not resolved.exists():
            return None
        return resolved

    def _load_x_metadata(self, directory: Path) -> Mapping[str, Any]:
        candidates: list[Path] = []
        try:
            children = sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        except OSError:
            return {}
        for child in children:
            if child.name.startswith(".") or not child.name.endswith(".info.json") and not child.name.endswith(
                ".info.json.info.json"
            ):
                continue
            if self._resolve_inside(child) is not None:
                candidates.append(child)
        for candidate in candidates:
            payload = _read_json_object(candidate, self.local_store_root)
            if payload:
                return payload
        return {}

    def _load_grok_catalog(self, root: Path) -> dict[str, Mapping[str, Any]]:
        payload = _read_json_object(root / ".grok_catalog.json", self.local_store_root, allow_hidden=True)
        if not payload:
            return {}
        raw_entries = payload.get("entries")
        if isinstance(raw_entries, Mapping):
            raw_entries = list(raw_entries.values())
        if not isinstance(raw_entries, list):
            return {}
        entries: dict[str, Mapping[str, Any]] = {}
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                continue
            relative_path = _safe_catalog_relative_path(raw_entry.get("relative_path"))
            if not relative_path:
                continue
            candidate = root / relative_path
            if self._resolve_inside(candidate) is None:
                continue
            try:
                local_relative = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            entries.setdefault(local_relative, raw_entry)
        return entries

    def _load_chatgpt_catalog(self, project_dir: Path) -> dict[str, Mapping[str, Any]]:
        payload = _read_json_object(project_dir / ".chatgpt_catalog.json", self.local_store_root, allow_hidden=True)
        if not payload:
            return {}
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, Mapping):
            return {}
        entries: dict[str, Mapping[str, Any]] = {}
        for raw_entry in raw_entries.values():
            if not isinstance(raw_entry, Mapping):
                continue
            relative_path = _safe_catalog_relative_path(raw_entry.get("relative_path"))
            if not relative_path:
                continue
            candidate = project_dir / relative_path
            if self._resolve_inside(candidate) is None:
                continue
            try:
                local_relative = candidate.relative_to(project_dir).as_posix()
            except ValueError:
                continue
            entries.setdefault(local_relative, raw_entry)
        return entries


def _decode_relative_path(value: str | None) -> str | None:
    """Decode URL path escapes enough times to reject encoded traversal."""
    if value is None:
        return None
    decoded = str(value)
    for _ in range(4):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if not decoded or "\x00" in decoded or "\\" in decoded:
        return None
    return decoded


def _safe_catalog_relative_path(value: Any) -> str | None:
    text = _decode_relative_path(str(value or ""))
    if text is None:
        return None
    relative = PurePosixPath(text)
    if relative.is_absolute() or not relative.parts:
        return None
    if any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts):
        return None
    return relative.as_posix()


def _read_json_object(
    path: Path,
    local_store_root: Path,
    *,
    allow_hidden: bool = False,
) -> dict[str, Any]:
    """Read one local JSON object without following links outside the cache."""
    try:
        resolved = path.resolve(strict=True)
        resolved_relative = resolved.relative_to(local_store_root)
        if not allow_hidden and any(part.startswith(".") for part in resolved_relative.parts):
            return {}
        if not resolved.is_file() or not os.access(resolved, os.R_OK):
            return {}
        with resolved.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, RuntimeError, ValueError, TypeError, UnicodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _stat_media_file(path: Path) -> os.stat_result | None:
    """Return stat data for a non-empty, readable regular file."""
    try:
        stat_result = path.stat()
    except OSError:
        return None
    if not path.is_file() or stat_result.st_size <= 0 or not os.access(path, os.R_OK):
        return None
    return stat_result


def _display_text(value: Any) -> str:
    """Convert metadata to bounded, safe display text."""
    if value is None:
        return ""
    return str(value).replace("\x00", "").strip()


def _redact_local_root(value: str, local_store_root: Path) -> str:
    """Prevent the configured absolute cache path from entering page data."""
    text = str(value or "")
    root_text = str(local_store_root)
    alternate_root_text = root_text.replace("/private/var/", "/var/")
    for candidate in {root_text, alternate_root_text}:
        if candidate:
            text = text.replace(candidate, "[local cache]")
    return text


def _safe_source_url(value: Any) -> str:
    """Keep only source URLs that can be safely rendered as external links."""
    text = _display_text(value)
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def _parse_datetime(value: str | datetime | Any) -> datetime | None:
    """Parse epoch, yyyymmdd, ISO, and date-only metadata as UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool) or value is None:
        return None
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        if _DATE_RE.fullmatch(text):
            try:
                parsed = datetime.strptime(text, "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                return None
        elif _NUMERIC_RE.fullmatch(text):
            try:
                parsed = datetime.fromtimestamp(float(text), tz=UTC)
            except (OverflowError, OSError, ValueError):
                return None
        else:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat(value: datetime) -> str:
    """Normalize one datetime to a stable UTC ISO representation."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_positive_page(value: object) -> int:
    try:
        numeric = int(str(value).strip())
    except (TypeError, ValueError):
        return 1
    return max(1, numeric)
