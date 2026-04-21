"""Shared task state for the web UI and worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from .cache_catalog import summarize_local_store_root
from .config import LOCAL_STORE_ROOT


DEFAULT_OUTPUT_DIR_TEMPLATE = str(LOCAL_STORE_ROOT / "{用户名}")


def utc_now() -> str:
    """Return an ISO formatted UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_initial_snapshot(version: str) -> TaskSnapshot:
    """Hydrate the initial idle snapshot from any existing local cache."""
    snapshot = TaskSnapshot(version=version)
    summaries = summarize_local_store_root(LOCAL_STORE_ROOT)
    if not summaries:
        return snapshot

    downloaded_posts = sum(summary.downloaded_posts for summary in summaries)
    downloaded_images = sum(summary.downloaded_images for summary in summaries)
    downloaded_videos = sum(summary.downloaded_videos for summary in summaries)

    if downloaded_posts == 0 and downloaded_images == 0 and downloaded_videos == 0:
        return snapshot

    if len(summaries) == 1:
        account_name = summaries[0].account_name
        output_dir = str(summaries[0].output_dir)
    else:
        account_name = f"{len(summaries)} accounts"
        output_dir = str(LOCAL_STORE_ROOT)

    snapshot.account_name = account_name
    snapshot.output_dir = output_dir
    snapshot.downloaded_posts = downloaded_posts
    snapshot.downloaded_images = downloaded_images
    snapshot.downloaded_videos = downloaded_videos
    snapshot.downloaded_tweets = downloaded_images + downloaded_videos
    snapshot.message = (
        f"Ready. Found existing cache: {downloaded_posts} posts, "
        f"{downloaded_images} images, {downloaded_videos} videos."
    )
    return snapshot


@dataclass(slots=True)
class TaskSnapshot:
    """Serializable task state."""

    version: str
    running: bool = False
    phase: str = "idle"
    message: str = "Ready."
    account_name: str = ""
    started_at: str = ""
    finished_at: str = ""
    discovered_tweets: int = 0
    downloaded_tweets: int = 0
    downloaded_posts: int = 0
    downloaded_images: int = 0
    downloaded_videos: int = 0
    skipped_tweets: int = 0
    failed_tweets: int = 0
    output_dir: str = DEFAULT_OUTPUT_DIR_TEMPLATE
    last_error: str = ""
    recent_events: list[str] = field(default_factory=list)


class TaskState:
    """Thread-safe state container."""

    def __init__(self, version: str) -> None:
        self._lock = Lock()
        self._snapshot = build_initial_snapshot(version)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._snapshot)

    def reset_for_run(self) -> None:
        with self._lock:
            version = self._snapshot.version
            self._snapshot = TaskSnapshot(
                version=version,
                running=True,
                phase="starting",
                message="Initializing job.",
                started_at=utc_now(),
            )

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self._snapshot, key, value)

    def append_event(self, message: str) -> None:
        with self._lock:
            self._snapshot.recent_events.append(f"[{utc_now()}] {message}")
            self._snapshot.recent_events = self._snapshot.recent_events[-50:]
            self._snapshot.message = message

    def finish_success(self, message: str) -> None:
        with self._lock:
            self._snapshot.running = False
            self._snapshot.phase = "finished"
            self._snapshot.message = message
            self._snapshot.finished_at = utc_now()

    def finish_error(self, message: str) -> None:
        with self._lock:
            self._snapshot.running = False
            self._snapshot.phase = "failed"
            self._snapshot.message = message
            self._snapshot.last_error = message
            self._snapshot.finished_at = utc_now()

    def finish_stopped(self, message: str) -> None:
        with self._lock:
            self._snapshot.running = False
            self._snapshot.phase = "stopped"
            self._snapshot.message = message
            self._snapshot.finished_at = utc_now()
