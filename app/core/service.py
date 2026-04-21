"""Orchestration service for the cache job."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, Thread
from uuid import uuid4

from .config import CrawlConfig, LOCAL_STORE_ROOT
from .downloader import LocalTweetCacheIndex, download_tweet_media
from .logging_setup import reset_job_id, set_job_id
from .scraper import collect_liked_tweet_urls
from .state import TaskState

logger = logging.getLogger(__name__)


class CacheLikesService:
    """Manage a single background cache job."""

    def __init__(self, state: TaskState) -> None:
        self._state = state
        self._worker: Thread | None = None
        self._stop_requested = Event()

    def is_running(self) -> bool:
        """Return whether a job is active."""
        snapshot = self._state.snapshot()
        return bool(snapshot["running"])

    def start(self, config: CrawlConfig) -> None:
        """Start a new background job."""
        if self.is_running():
            raise RuntimeError("A cache job is already running.")

        self._stop_requested.clear()
        self._state.reset_for_run()
        self._worker = Thread(target=self._run, args=(config,), daemon=True)
        self._worker.start()

    def request_stop(self) -> bool:
        """Request cooperative stop for the active job."""
        if not self.is_running():
            return False
        self._stop_requested.set()
        self._state.update(phase="stopping")
        self._state.append_event("Emergency stop requested. Waiting for current task to stop.")
        return True

    def _is_stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    def _run(self, config: CrawlConfig) -> None:
        """Execute the full job pipeline."""
        job_id = uuid4().hex[:12]
        token = set_job_id(job_id)
        try:
            logger.info(
                "Cache job started.",
                extra={
                    "job_id": job_id,
                    "chrome_profile_directory": config.chrome_profile_directory,
                    "chrome_user_data_dir": str(config.chrome_user_data_dir),
                    "headless": config.headless,
                    "max_media_items": config.max_media_items,
                    "max_scroll_rounds": config.max_scroll_rounds,
                    "scroll_pause_seconds": config.scroll_pause_seconds,
                    "stale_round_limit": config.stale_round_limit,
                },
            )
            if self._is_stop_requested():
                self._state.finish_stopped("Job stopped before collection started.")
                return

            account_handle, tweet_urls = collect_liked_tweet_urls(config, self._state)
            account_name = config.sanitized_account_name(account_handle)
            output_dir = LOCAL_STORE_ROOT / account_name
            archive_path = output_dir / ".downloaded_archive.txt"
            cache_index = LocalTweetCacheIndex.build(output_dir)
            logger.info(
                "Likes collection completed.",
                extra={
                    "job_id": job_id,
                    "account_handle": account_handle,
                    "account_name": account_name,
                    "discovered_tweets": len(tweet_urls),
                    "output_dir": str(output_dir),
                    "archive_path": str(archive_path),
                },
            )

            self._state.update(output_dir=str(output_dir), phase="downloading", discovered_tweets=len(tweet_urls))
            self._state.append_event(
                f"Starting media download for up to {config.max_media_items} files from "
                f"{len(tweet_urls)} liked tweets into {output_dir}."
            )

            downloaded_media = 0
            downloaded_posts = 0
            downloaded_images = 0
            downloaded_videos = 0
            skipped = 0
            failed = 0

            for index, tweet_url in enumerate(tweet_urls, start=1):
                if self._is_stop_requested():
                    self._state.finish_stopped(
                        f"Emergency stop completed. Downloaded {downloaded_posts} posts, {downloaded_images} images, "
                        f"{downloaded_videos} videos ({downloaded_media} media files), "
                        f"skipped {skipped}, failed {failed}."
                    )
                    logger.info(
                        "Cache job stopped by operator.",
                        extra={
                            "job_id": job_id,
                            "downloaded_media_total": downloaded_media,
                            "downloaded_posts_total": downloaded_posts,
                            "downloaded_images_total": downloaded_images,
                            "downloaded_videos_total": downloaded_videos,
                            "skipped_tweets": skipped,
                            "failed_tweets": failed,
                        },
                    )
                    return

                remaining_media_items = config.max_media_items - downloaded_media
                if remaining_media_items <= 0:
                    self._state.append_event(
                        f"Reached the temporary test cap of {config.max_media_items} media files."
                    )
                    logger.info(
                        "Download cap reached before processing next tweet.",
                        extra={
                            "job_id": job_id,
                            "processed_tweets": index - 1,
                            "downloaded_media_count": downloaded_media,
                            "download_cap": config.max_media_items,
                        },
                    )
                    break

                self._state.append_event(f"Processing liked tweet {index}/{len(tweet_urls)}")
                try:
                    logger.info(
                        "Processing liked tweet.",
                        extra={
                            "job_id": job_id,
                            "tweet_url": tweet_url,
                            "tweet_index": index,
                            "tweet_total": len(tweet_urls),
                            "remaining_media_items": remaining_media_items,
                        },
                    )
                    result = download_tweet_media(
                        tweet_url,
                        output_dir,
                        archive_path,
                        config,
                        self._state,
                        remaining_media_items=remaining_media_items,
                        cache_index=cache_index,
                    )
                    if result.skipped:
                        skipped += 1
                        logger.info(
                            "Tweet skipped.",
                            extra={
                                "job_id": job_id,
                                "tweet_url": tweet_url,
                                "tweet_index": index,
                                "skipped_tweets": skipped,
                            },
                        )
                    else:
                        downloaded_post_increment = (
                            result.downloaded_post_count
                            if result.downloaded_post_count > 0
                            else (1 if result.downloaded_media_count > 0 else 0)
                        )
                        downloaded_media += result.downloaded_media_count
                        downloaded_posts += downloaded_post_increment
                        downloaded_images += result.downloaded_image_count
                        downloaded_videos += result.downloaded_video_count
                        logger.info(
                            "Tweet download completed.",
                            extra={
                                "job_id": job_id,
                                "tweet_url": tweet_url,
                                "tweet_index": index,
                                "downloaded_media_count": result.downloaded_media_count,
                                "downloaded_media_total": downloaded_media,
                                "downloaded_post_increment": downloaded_post_increment,
                                "downloaded_posts_total": downloaded_posts,
                                "downloaded_images_total": downloaded_images,
                                "downloaded_videos_total": downloaded_videos,
                            },
                        )
                except Exception as exc:  # pragma: no cover
                    failed += 1
                    self._state.append_event(str(exc))
                    logger.exception(
                        "Tweet download failed.",
                        extra={
                            "job_id": job_id,
                            "tweet_url": tweet_url,
                            "tweet_index": index,
                            "failed_tweets": failed,
                        },
                    )

                self._state.update(
                    downloaded_tweets=downloaded_media,
                    downloaded_posts=downloaded_posts,
                    downloaded_images=downloaded_images,
                    downloaded_videos=downloaded_videos,
                    skipped_tweets=skipped,
                    failed_tweets=failed,
                )

            self._state.finish_success(
                f"Finished. Discovered {len(tweet_urls)} posts, downloaded {downloaded_media} media files "
                f"across {downloaded_posts} posts ({downloaded_images} images, {downloaded_videos} videos), "
                f"skipped {skipped}, failed {failed}."
            )
            logger.info(
                "Cache job finished successfully.",
                extra={
                    "job_id": job_id,
                    "discovered_tweets": len(tweet_urls),
                    "downloaded_media_total": downloaded_media,
                    "downloaded_posts_total": downloaded_posts,
                    "downloaded_images_total": downloaded_images,
                    "downloaded_videos_total": downloaded_videos,
                    "skipped_tweets": skipped,
                    "failed_tweets": failed,
                    "output_dir": str(output_dir),
                },
            )
        except Exception as exc:  # pragma: no cover
            self._state.finish_error(str(exc))
            logger.exception(
                "Cache job failed.",
                extra={
                    "job_id": job_id,
                    "error": str(exc),
                },
            )
        finally:
            reset_job_id(token)
