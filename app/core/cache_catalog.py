"""Persistent local cache catalog backed by Parquet."""

# Code version: v1.3.0-codex.1

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None


CATALOG_FILENAME = ".cache_catalog.parquet"
INFO_JSON_SUFFIXES = (".info.json", ".info.json.info.json")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
CATALOG_SCHEMA_VERSION = 1


@dataclass(slots=True)
class AccountCacheSummary:
    """Capture local cache totals for one output directory."""

    account_name: str
    output_dir: Path
    downloaded_posts: int = 0
    downloaded_images: int = 0
    downloaded_videos: int = 0


def canonicalize_tweet_url(tweet_url: str) -> str:
    """Normalize X or Twitter status URLs so duplicate matches are stable."""
    text = (tweet_url or "").strip()
    if not text:
        return ""

    text = text.split("?", 1)[0].rstrip("/")
    if not text:
        return ""

    if "://" not in text:
        text = f"https://x.com/{text.lstrip('/')}"

    _, _, remainder = text.partition("://")
    host, _, path = remainder.partition("/")
    host = host.lower()
    if host in {"twitter.com", "www.twitter.com", "mobile.twitter.com", "www.x.com", "mobile.x.com"}:
        host = "x.com"

    normalized_path = "/" + path.lstrip("/") if path else ""
    return f"https://{host}{normalized_path}".rstrip("/")


def extract_status_id(tweet_url: str) -> str:
    """Extract the tweet status ID from a URL if present."""
    marker = "/status/"
    if marker not in (tweet_url or ""):
        return ""
    suffix = (tweet_url or "").split(marker, 1)[1]
    status_id = suffix.split("/", 1)[0].split("?", 1)[0].strip()
    return status_id if status_id.isdigit() else ""


def is_info_json_path(path: Path) -> bool:
    """Return whether a path is a persisted yt-dlp metadata file."""
    return path.is_file() and path.name.endswith(INFO_JSON_SUFFIXES)


def load_info_payload(tweet_dir: Path) -> dict[str, object]:
    """Load the first readable info JSON payload for a cached tweet directory."""
    for child in tweet_dir.iterdir():
        if not is_info_json_path(child):
            continue
        try:
            return json.loads(child.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def summarize_cached_tweet_dir(tweet_dir: Path) -> tuple[bool, int, int]:
    """Return whether a tweet dir is cached plus its image and video counts."""
    if not tweet_dir.exists() or not tweet_dir.is_dir():
        return False, 0, 0

    media_files = [
        child
        for child in tweet_dir.iterdir()
        if child.is_file()
        and not child.name.endswith(INFO_JSON_SUFFIXES)
        and child.suffix.lower() not in {".part", ".ytdl"}
    ]
    if not media_files:
        return False, 0, 0

    image_count = sum(child.suffix.lower() in IMAGE_SUFFIXES for child in media_files)
    video_count = sum(child.suffix.lower() in VIDEO_SUFFIXES for child in media_files)
    payload = load_info_payload(tweet_dir)
    if str(payload.get("_type") or "").lower() == "video" and video_count > 0:
        image_count = 0

    return True, image_count, video_count


def tweet_dir_has_cached_media(tweet_dir: Path) -> bool:
    """Return whether a tweet directory has reusable cached media."""
    is_cached, _image_count, _video_count = summarize_cached_tweet_dir(tweet_dir)
    return is_cached


def candidate_urls_from_payload(payload: dict[str, object]) -> list[str]:
    """Derive stable tweet URLs from stored yt-dlp metadata."""
    candidate_urls = [str(payload.get("webpage_url") or "").strip()]
    uploader_id = str(payload.get("uploader_id") or "").strip()
    display_id = str(payload.get("display_id") or "").strip()
    if uploader_id and display_id:
        candidate_urls.append(f"https://x.com/{uploader_id}/status/{display_id}")
    return [url for url in candidate_urls if url]


@dataclass(slots=True)
class LocalTweetCacheIndex:
    """Track cached tweets using a persisted Parquet catalog plus in-memory lookup maps."""

    output_dir: Path
    catalog_path: Path
    directories_by_status_id: dict[str, set[Path]] = field(default_factory=dict)
    directories_by_url: dict[str, set[Path]] = field(default_factory=dict)
    media_counts_by_directory: dict[Path, tuple[int, int]] = field(default_factory=dict)
    dirty: bool = False
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _inflight_keys: set[str] = field(default_factory=set, init=False, repr=False)

    @classmethod
    def build(cls, output_dir: Path) -> LocalTweetCacheIndex:
        """Load a persisted catalog or rebuild it from disk on demand."""
        index = cls(output_dir=output_dir, catalog_path=output_dir / CATALOG_FILENAME)
        if not output_dir.exists():
            return index

        if index._load_parquet_catalog():
            return index

        index._rebuild_from_disk()
        index.flush()
        return index

    def register(self, tweet_url: str, tweet_dir: Path | None = None) -> None:
        """Remember a tweet URL and optionally persist its cached directory."""
        with self._lock:
            canonical_url = canonicalize_tweet_url(tweet_url)
            status_id = extract_status_id(tweet_url)
            if canonical_url:
                self.directories_by_url.setdefault(canonical_url, set())
            if status_id:
                self.directories_by_status_id.setdefault(status_id, set())

            if tweet_dir is None:
                return

            is_cached, image_count, video_count = summarize_cached_tweet_dir(tweet_dir)
            if not is_cached:
                return

            self._remember_directory(tweet_dir, image_count, video_count)
            self._remember_url(tweet_url, tweet_dir)
            self.flush()

    def contains_complete_cache(self, tweet_url: str) -> bool:
        """Return whether the given tweet already has reusable local media."""
        with self._lock:
            return self._contains_complete_cache_unlocked(tweet_url)

    def claim(self, tweet_url: str) -> bool:
        """Claim one tweet URL for active processing inside the current process."""
        claim_keys = self._claim_keys(tweet_url)
        with self._lock:
            if self._contains_complete_cache_unlocked(tweet_url):
                return False
            if any(key in self._inflight_keys for key in claim_keys):
                return False
            self._inflight_keys.update(claim_keys)
            return True

    def release_claim(self, tweet_url: str) -> None:
        """Release one in-flight claim after the worker finishes."""
        claim_keys = self._claim_keys(tweet_url)
        with self._lock:
            self._inflight_keys.difference_update(claim_keys)

    def lookup_directories(self, tweet_url: str) -> set[Path]:
        """Return directories associated with a tweet URL or status ID."""
        with self._lock:
            return set(self._lookup_directories_unlocked(tweet_url))

    def summarize(self) -> tuple[int, int, int]:
        """Return cached posts, images, and videos for the indexed output directory."""
        with self._lock:
            downloaded_posts = len(self.media_counts_by_directory)
            downloaded_images = sum(image_count for image_count, _video_count in self.media_counts_by_directory.values())
            downloaded_videos = sum(video_count for _image_count, video_count in self.media_counts_by_directory.values())
            return downloaded_posts, downloaded_images, downloaded_videos

    def flush(self) -> None:
        """Persist the current catalog to Parquet when available."""
        with self._lock:
            if not self.dirty or pa is None or pq is None:
                return

            rows: list[dict[str, object]] = []
            for tweet_dir in sorted(self.media_counts_by_directory, key=lambda path: str(path)):
                image_count, video_count = self.media_counts_by_directory[tweet_dir]
                canonical_urls = sorted(
                    url for url, directories in self.directories_by_url.items() if tweet_dir in directories
                )
                status_ids = sorted(
                    status_id for status_id, directories in self.directories_by_status_id.items() if tweet_dir in directories
                )
                rows.append(
                    {
                        "schema_version": CATALOG_SCHEMA_VERSION,
                        "relative_tweet_dir": str(tweet_dir.relative_to(self.output_dir)),
                        "canonical_urls_json": json.dumps(canonical_urls, sort_keys=True),
                        "status_ids_json": json.dumps(status_ids, sort_keys=True),
                        "image_count": image_count,
                        "video_count": video_count,
                    }
                )

            self.output_dir.mkdir(parents=True, exist_ok=True)
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, self.catalog_path)
            self.dirty = False

    def _load_parquet_catalog(self) -> bool:
        """Try to load an existing Parquet catalog."""
        if pa is None or pq is None or not self.catalog_path.exists():
            return False

        try:
            rows = pq.read_table(self.catalog_path).to_pylist()
        except Exception:
            return False

        loaded_any = False
        for row in rows:
            relative_tweet_dir = str(row.get("relative_tweet_dir") or "").strip()
            if not relative_tweet_dir:
                continue
            tweet_dir = self.output_dir / relative_tweet_dir
            if not tweet_dir.exists():
                self.dirty = True
                continue

            image_count = int(row.get("image_count") or 0)
            video_count = int(row.get("video_count") or 0)
            self._remember_directory(tweet_dir, image_count, video_count)
            for url in json.loads(str(row.get("canonical_urls_json") or "[]")):
                self._remember_url(str(url), tweet_dir)
            for status_id in json.loads(str(row.get("status_ids_json") or "[]")):
                if status_id:
                    self.directories_by_status_id.setdefault(str(status_id), set()).add(tweet_dir)
            loaded_any = True

        return loaded_any

    def _rebuild_from_disk(self) -> None:
        """Scan disk once to rebuild the catalog when Parquet is missing or stale."""
        for info_json_path in self.output_dir.rglob("*.info.json*"):
            if not is_info_json_path(info_json_path):
                continue

            tweet_dir = info_json_path.parent
            is_cached, image_count, video_count = summarize_cached_tweet_dir(tweet_dir)
            if not is_cached:
                continue

            try:
                payload = json.loads(info_json_path.read_text())
            except (OSError, json.JSONDecodeError):
                payload = {}

            self._remember_directory(tweet_dir, image_count, video_count)
            for candidate_url in candidate_urls_from_payload(payload):
                self._remember_url(candidate_url, tweet_dir)
            self.dirty = True

    def _remember_directory(self, tweet_dir: Path, image_count: int, video_count: int) -> None:
        """Track one cached tweet directory and its media totals."""
        self.media_counts_by_directory[tweet_dir] = (image_count, video_count)

    def _remember_url(self, tweet_url: str, tweet_dir: Path) -> None:
        """Associate a canonical URL or status ID with one cached tweet directory."""
        canonical_url = canonicalize_tweet_url(tweet_url)
        status_id = extract_status_id(tweet_url)
        if canonical_url:
            self.directories_by_url.setdefault(canonical_url, set()).add(tweet_dir)
        if status_id:
            self.directories_by_status_id.setdefault(status_id, set()).add(tweet_dir)

    def _lookup_directories_unlocked(self, tweet_url: str) -> set[Path]:
        directories: set[Path] = set()
        canonical_url = canonicalize_tweet_url(tweet_url)
        if canonical_url:
            directories.update(self.directories_by_url.get(canonical_url, set()))

        status_id = extract_status_id(tweet_url)
        if status_id:
            directories.update(self.directories_by_status_id.get(status_id, set()))

        return directories

    def _contains_complete_cache_unlocked(self, tweet_url: str) -> bool:
        return any(tweet_dir_has_cached_media(tweet_dir) for tweet_dir in self._lookup_directories_unlocked(tweet_url))

    def _claim_keys(self, tweet_url: str) -> tuple[str, ...]:
        canonical_url = canonicalize_tweet_url(tweet_url)
        status_id = extract_status_id(tweet_url)
        keys = []
        if canonical_url:
            keys.append(f"url:{canonical_url}")
        if status_id:
            keys.append(f"status:{status_id}")
        if not keys:
            keys.append(f"raw:{tweet_url.strip()}")
        return tuple(keys)


def summarize_local_store_root(local_store_root: Path) -> list[AccountCacheSummary]:
    """Return cached media totals for each local account directory."""
    if not local_store_root.exists():
        return []

    summaries: list[AccountCacheSummary] = []
    for account_dir in sorted(child for child in local_store_root.iterdir() if child.is_dir() and not child.name.startswith(".")):
        index = LocalTweetCacheIndex.build(account_dir)
        downloaded_posts, downloaded_images, downloaded_videos = index.summarize()
        summaries.append(
            AccountCacheSummary(
                account_name=account_dir.name,
                output_dir=account_dir,
                downloaded_posts=downloaded_posts,
                downloaded_images=downloaded_images,
                downloaded_videos=downloaded_videos,
            )
        )
    return summaries
