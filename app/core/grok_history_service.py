"""Background service for Grok session history sync.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import uuid4

from .config import LOCAL_STORE_ROOT, CrawlConfig
from .grok_history import sync_grok_history
from .job_lock import CacheTaskLock, SHARED_CACHE_TASK_LOCK
from .logging_setup import reset_job_id, set_job_id
from .shadow_backup import ShadowBackupService
from .state import TaskState


logger = logging.getLogger(__name__)


def summarize_grok_history_error_for_status(error: Exception) -> str:
    """Return a concise Grok status message while logs retain full details."""

    error_text = str(error).strip()
    if "BrowserType.launch_persistent_context" in error_text:
        return (
            "Grok history could not launch the selected Edge profile. "
            "Check the local log for the complete Playwright error."
        )
    first_line = error_text.splitlines()[0] if error_text else error.__class__.__name__
    return first_line if len(first_line) <= 500 else f"{first_line[:497]}..."


class GrokHistoryService:
    """Manage one Grok text-history sync worker."""

    def __init__(
        self,
        state: TaskState,
        local_store_root: Path | str = LOCAL_STORE_ROOT,
        task_lock: CacheTaskLock | None = None,
        shadow_backup_service: ShadowBackupService | None = None,
    ) -> None:
        self._state = state
        self._local_store_root = Path(local_store_root)
        self._worker: Thread | None = None
        self._stop_requested = Event()
        self._config = CrawlConfig()
        self._lifecycle_lock = RLock()
        self._task_lock = task_lock or SHARED_CACHE_TASK_LOCK
        self._owns_task_lock = False
        self._shadow_backup_service = shadow_backup_service

    def is_running(self) -> bool:
        """Return whether a Grok history sync is active."""

        return bool(self._state.snapshot()["running"])

    def start(self, config: CrawlConfig) -> None:
        """Start one Grok text-history sync worker."""

        with self._lifecycle_lock:
            if self.is_running():
                raise RuntimeError("A Grok history sync is already running.")
            if not self._task_lock.acquire("grok-history-sync"):
                raise RuntimeError(
                    "A cache task is already running in another Cache Likes window or browser. "
                    "Stop it there before starting a Grok history sync."
                )
            self._owns_task_lock = True
            self._stop_requested.clear()
            self._config = config
            self._state.reset_for_run()
            try:
                self._worker = Thread(target=self._run, daemon=True)
                self._worker.start()
            except Exception:
                self._owns_task_lock = False
                self._task_lock.release()
                raise

    def request_stop(self) -> bool:
        """Request a cooperative stop after the active session."""

        if not self.is_running():
            return False
        self._stop_requested.set()
        self._state.update(phase="stopping")
        self._state.append_event(
            "Stop requested for Grok history sync. Waiting for the current session to finish."
        )
        return True

    def _is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def _run(self) -> None:
        """Execute the Grok text-history sync pipeline."""

        job_id = uuid4().hex[:12]
        token = set_job_id(job_id)
        try:
            logger.info(
                "Grok history sync started.",
                extra={"job_id": job_id, "grok_browser": self._config.grok_browser},
            )
            if self._is_stop_requested():
                self._state.finish_stopped("Grok history sync stopped before the browser was launched.")
                return
            result = sync_grok_history(
                self._state,
                self._config,
                self._is_stop_requested,
                local_store_root=self._local_store_root,
            )
            if result["stopped"]:
                self._state.finish_stopped(
                    f"Grok history sync stopped. Cached {result['messages']:,} messages."
                )
                return
            completion_message = (
                f"Finished Grok history sync. Inspected {result['sessions']:,} sessions, "
                f"found {result['messages']:,} messages, added or changed "
                f"{result['added_or_changed']:,}, unchanged {result['unchanged']:,}, "
                f"failed {result['failed']:,}."
            )
            if self._shadow_backup_service is not None:
                shadow_backup_message = self._shadow_backup_service.sync_after_cache_task(self._config)
                if shadow_backup_message:
                    self._state.append_event(shadow_backup_message)
                    completion_message = f"{completion_message} {shadow_backup_message}"
            self._state.finish_success(completion_message)
            logger.info("Grok history sync finished successfully.", extra={"job_id": job_id, **result})
        except Exception as exc:  # pragma: no cover - depends on live browser state
            self._state.finish_error(summarize_grok_history_error_for_status(exc))
            logger.exception("Grok history sync failed.", extra={"job_id": job_id, "error": str(exc)})
        finally:
            reset_job_id(token)
            with self._lifecycle_lock:
                if self._owns_task_lock:
                    self._owns_task_lock = False
                    self._task_lock.release()
