"""Regression tests for cross-window cache task exclusion.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import CrawlConfig
from app.core.grok_service import GrokDownloadService
from app.core.job_lock import CacheTaskLock
from app.core.service import CacheLikesService
from app.core.state import TaskState


def test_cache_task_lock_excludes_another_owner_until_release(tmp_path: Path) -> None:
    lock_path = tmp_path / "cache-task.lock"
    first_owner = CacheTaskLock(lock_path)
    second_owner = CacheTaskLock(lock_path)

    assert first_owner.acquire("x-cache")
    assert not second_owner.acquire("grok-sync")

    first_owner.release()

    assert second_owner.acquire("grok-sync")
    second_owner.release()


class _IdleThread:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass


def test_x_cache_and_grok_sync_share_one_process_lock(tmp_path: Path) -> None:
    task_lock = CacheTaskLock(tmp_path / "cache-task.lock")
    x_service = CacheLikesService(TaskState("test"), task_lock=task_lock)
    grok_service = GrokDownloadService(TaskState("test"), task_lock=task_lock)

    with patch("app.core.service.Thread", _IdleThread):
        x_service.start(CrawlConfig())

    try:
        with pytest.raises(RuntimeError, match="already running"):
            grok_service.start(CrawlConfig())
    finally:
        x_service._owns_task_lock = False
        task_lock.release()
