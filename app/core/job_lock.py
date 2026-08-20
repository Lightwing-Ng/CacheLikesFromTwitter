"""Cross-process exclusion for locally initiated cache tasks."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import TextIO

from .config import LOCAL_STORE_ROOT
from .platform_lock import lock_file, unlock_file
from .state import utc_now


class CacheTaskLock:
    """Hold a non-blocking advisory lock while one cache task is active."""

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._guard = Lock()
        self._handle: TextIO | None = None

    def acquire(self, task_name: str) -> bool:
        """Acquire the lock, returning false when another app process owns it."""
        with self._guard:
            if self._handle is not None:
                return False

            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = self._lock_path.open("a+", encoding="utf-8")
            try:
                lock_file(handle, blocking=False)
            except BlockingIOError:
                handle.close()
                return False

            try:
                handle.seek(0)
                handle.truncate()
                json.dump(
                    {
                        "pid": os.getpid(),
                        "started_at": utc_now(),
                        "task_name": task_name,
                    },
                    handle,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            except OSError:
                unlock_file(handle)
                handle.close()
                raise

            self._handle = handle
            return True

    def release(self) -> None:
        """Release the lock when its owning worker has finished."""
        with self._guard:
            if self._handle is None:
                return
            try:
                unlock_file(self._handle)
            finally:
                self._handle.close()
                self._handle = None


SHARED_CACHE_TASK_LOCK = CacheTaskLock(LOCAL_STORE_ROOT / ".cache_task.lock")
