"""Background service for ChatGPT project image sync."""

# Code version: v1.2.0-codex.1

from __future__ import annotations

import logging
from threading import Event, RLock, Thread
from uuid import uuid4

from .chatgpt_downloader import sync_chatgpt_images
from .config import CrawlConfig
from .job_lock import CacheTaskLock, SHARED_CACHE_TASK_LOCK
from .logging_setup import reset_job_id, set_job_id
from .shadow_backup import ShadowBackupService
from .state import TaskState


logger = logging.getLogger(__name__)


def summarize_chatgpt_error_for_status(error: Exception) -> str:
    """Return a concise ChatGPT status message while retaining full logs."""
    error_text = str(error).strip()
    if "BrowserType.launch_persistent_context" in error_text:
        return (
            "ChatGPT browser automation failed while launching the selected Edge profile. "
            "Close any duplicate cache window and check the local log for the full Playwright output."
        )

    first_line = error_text.splitlines()[0] if error_text else error.__class__.__name__
    if len(first_line) <= 500:
        return first_line
    return f"{first_line[:497]}..."


class ChatGPTDownloadService:
    """Manage one ChatGPT project image sync worker."""

    def __init__(
        self,
        state: TaskState,
        task_lock: CacheTaskLock | None = None,
        shadow_backup_service: ShadowBackupService | None = None,
    ) -> None:
        self._state = state
        self._worker: Thread | None = None
        self._stop_requested = Event()
        self._config = CrawlConfig()
        self._lifecycle_lock = RLock()
        self._task_lock = task_lock or SHARED_CACHE_TASK_LOCK
        self._owns_task_lock = False
        self._shadow_backup_service = shadow_backup_service

    def is_running(self) -> bool:
        """Return whether a ChatGPT image sync is active."""
        snapshot = self._state.snapshot()
        return bool(snapshot["running"])

    def start(self, config: CrawlConfig) -> None:
        """Start a new ChatGPT project image sync worker."""
        with self._lifecycle_lock:
            if self.is_running():
                raise RuntimeError("A ChatGPT sync is already running.")
            if not self._task_lock.acquire("chatgpt-sync"):
                raise RuntimeError(
                    "A cache task is already running in another Cache Likes window or browser. "
                    "Stop it there before starting a ChatGPT sync."
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
        """Request a cooperative stop for the active ChatGPT sync."""
        if not self.is_running():
            return False
        self._stop_requested.set()
        self._state.update(phase="stopping")
        self._state.append_event("Emergency stop requested for ChatGPT sync. Waiting for the current task to stop.")
        return True

    def _is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def _run(self) -> None:
        """Execute the ChatGPT image sync pipeline."""
        job_id = uuid4().hex[:12]
        token = set_job_id(job_id)
        try:
            logger.info(
                "ChatGPT sync started.",
                extra={
                    "job_id": job_id,
                    "chatgpt_browser": self._config.chatgpt_browser,
                    "chatgpt_project_name": self._config.chatgpt_project_name,
                },
            )
            if self._is_stop_requested():
                self._state.finish_stopped("ChatGPT sync stopped before the browser was launched.")
                return

            result = sync_chatgpt_images(
                self._state,
                config=self._config,
                should_stop=self._is_stop_requested,
            )
            if result.stopped:
                self._state.finish_stopped(
                    f"ChatGPT sync stopped. Cached {result.cached_count:,} original images."
                )
                logger.info(
                    "ChatGPT sync stopped by operator.",
                    extra={
                        "job_id": job_id,
                        "discovered_conversations": result.discovered_conversations,
                        "discovered_images": result.discovered_images,
                        "downloaded_count": result.downloaded_count,
                        "cached_count": result.cached_count,
                    },
                )
                return

            completion_message = (
                f"Finished ChatGPT sync. Inspected {result.discovered_conversations:,} conversations, "
                f"found {result.discovered_images:,} original images, added {result.downloaded_count:,} new files, "
                f"skipped over size limit {result.skipped_size:,}, "
                f"failed {result.failed_count:,}; cached total {result.cached_count:,} images."
            )
            if self._shadow_backup_service is not None:
                shadow_backup_message = self._shadow_backup_service.sync_after_cache_task(self._config)
                if shadow_backup_message:
                    self._state.append_event(shadow_backup_message)
                    completion_message = f"{completion_message} {shadow_backup_message}"
            self._state.finish_success(completion_message)
            logger.info(
                "ChatGPT sync finished successfully.",
                extra={
                    "job_id": job_id,
                    "discovered_conversations": result.discovered_conversations,
                    "discovered_images": result.discovered_images,
                    "downloaded_count": result.downloaded_count,
                    "skipped_known": result.skipped_known,
                    "failed_count": result.failed_count,
                    "cached_count": result.cached_count,
                },
            )
        except Exception as exc:  # pragma: no cover - depends on live browser state
            self._state.finish_error(summarize_chatgpt_error_for_status(exc))
            logger.exception(
                "ChatGPT sync failed.",
                extra={
                    "job_id": job_id,
                    "error": str(exc),
                },
            )
        finally:
            reset_job_id(token)
            with self._lifecycle_lock:
                if self._owns_task_lock:
                    self._owns_task_lock = False
                    self._task_lock.release()
