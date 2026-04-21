"""Background service for Grok media sync."""

# Code version: v1.0.1-codex.1

from __future__ import annotations

import logging
from threading import Event, Thread
from uuid import uuid4

from .grok_downloader import sync_grok_media
from .logging_setup import reset_job_id, set_job_id
from .state import TaskState


logger = logging.getLogger(__name__)


class GrokDownloadService:
    """Manage a single Grok sync worker."""

    def __init__(self, state: TaskState) -> None:
        self._state = state
        self._worker: Thread | None = None
        self._stop_requested = Event()

    def is_running(self) -> bool:
        """Return whether a Grok sync is active."""
        snapshot = self._state.snapshot()
        return bool(snapshot["running"])

    def start(self) -> None:
        """Start a new Grok sync worker."""
        if self.is_running():
            raise RuntimeError("A Grok sync is already running.")

        self._stop_requested.clear()
        self._state.reset_for_run()
        self._worker = Thread(target=self._run, daemon=True)
        self._worker.start()

    def request_stop(self) -> bool:
        """Request cooperative stop for the active Grok sync."""
        if not self.is_running():
            return False
        self._stop_requested.set()
        self._state.update(phase="stopping")
        self._state.append_event("Emergency stop requested for Grok sync. Waiting for the current task to stop.")
        return True

    def _is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def _run(self) -> None:
        """Execute the Grok sync pipeline."""
        job_id = uuid4().hex[:12]
        token = set_job_id(job_id)
        try:
            logger.info("Grok sync started.", extra={"job_id": job_id})
            if self._is_stop_requested():
                self._state.finish_stopped("Grok sync stopped before the browser was launched.")
                return

            result = sync_grok_media(self._state, should_stop=self._is_stop_requested)
            if result.stopped:
                self._state.finish_stopped(
                    f"Grok sync stopped. Cached {result.cached_count} assets "
                    f"({result.cached_images} images, {result.cached_videos} videos)."
                )
                logger.info(
                    "Grok sync stopped by operator.",
                    extra={
                        "job_id": job_id,
                        "cached_count": result.cached_count,
                        "cached_images": result.cached_images,
                        "cached_videos": result.cached_videos,
                    },
                )
                return

            self._state.finish_success(
                f"Finished Grok sync. Discovered {result.discovered_count} assets, "
                f"added {result.downloaded_count} new files ({result.downloaded_images} images, "
                f"{result.downloaded_videos} videos), deduped {result.deduped_by_hash}, "
                f"failed {result.failed_count}, "
                f"cached total {result.cached_count} assets."
            )
            logger.info(
                "Grok sync finished successfully.",
                extra={
                    "job_id": job_id,
                    "discovered_count": result.discovered_count,
                    "downloaded_count": result.downloaded_count,
                    "downloaded_images": result.downloaded_images,
                    "downloaded_videos": result.downloaded_videos,
                    "deduped_by_hash": result.deduped_by_hash,
                    "failed_count": result.failed_count,
                    "cached_count": result.cached_count,
                },
            )
        except Exception as exc:  # pragma: no cover
            self._state.finish_error(str(exc))
            logger.exception(
                "Grok sync failed.",
                extra={
                    "job_id": job_id,
                    "error": str(exc),
                },
            )
        finally:
            reset_job_id(token)
