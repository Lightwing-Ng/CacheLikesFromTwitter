"""Shared task state for the web UI and worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from .config import LOCAL_STORE_ROOT


DEFAULT_OUTPUT_DIR_TEMPLATE = str(LOCAL_STORE_ROOT / "{用户名}")


def utc_now() -> str:
    """Return an ISO formatted UTC timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    skipped_tweets: int = 0
    failed_tweets: int = 0
    output_dir: str = DEFAULT_OUTPUT_DIR_TEMPLATE
    last_error: str = ""
    recent_events: list[str] = field(default_factory=list)


class TaskState:
    """Thread-safe state container."""

    def __init__(self, version: str) -> None:
        self._lock = Lock()
        self._snapshot = TaskSnapshot(version=version)

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
