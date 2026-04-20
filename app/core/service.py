"""Orchestration service for the cache job."""

from __future__ import annotations

from pathlib import Path
from threading import Thread

from .config import CrawlConfig, LOCAL_STORE_ROOT
from .downloader import download_tweet_media
from .scraper import collect_liked_tweet_urls
from .state import TaskState


class CacheLikesService:
    """Manage a single background cache job."""

    def __init__(self, state: TaskState) -> None:
        self._state = state
        self._worker: Thread | None = None

    def is_running(self) -> bool:
        """Return whether a job is active."""
        snapshot = self._state.snapshot()
        return bool(snapshot["running"])

    def start(self, config: CrawlConfig) -> None:
        """Start a new background job."""
        if self.is_running():
            raise RuntimeError("A cache job is already running.")

        self._state.reset_for_run()
        self._worker = Thread(target=self._run, args=(config,), daemon=True)
        self._worker.start()

    def _run(self, config: CrawlConfig) -> None:
        """Execute the full job pipeline."""
        try:
            account_handle, tweet_urls = collect_liked_tweet_urls(config, self._state)
            account_name = config.sanitized_account_name(account_handle)
            output_dir = LOCAL_STORE_ROOT / account_name
            archive_path = output_dir / ".downloaded_archive.txt"

            self._state.update(output_dir=str(output_dir), phase="downloading", discovered_tweets=len(tweet_urls))
            self._state.append_event(
                f"Starting media download for up to {config.max_media_items} files from "
                f"{len(tweet_urls)} liked tweets into {output_dir}."
            )

            downloaded_media = 0
            skipped = 0
            failed = 0

            for index, tweet_url in enumerate(tweet_urls, start=1):
                remaining_media_items = config.max_media_items - downloaded_media
                if remaining_media_items <= 0:
                    self._state.append_event(
                        f"Reached the temporary test cap of {config.max_media_items} media files."
                    )
                    break

                self._state.append_event(f"Processing liked tweet {index}/{len(tweet_urls)}")
                try:
                    result = download_tweet_media(
                        tweet_url,
                        output_dir,
                        archive_path,
                        config,
                        self._state,
                        remaining_media_items=remaining_media_items,
                    )
                    if result.skipped:
                        skipped += 1
                    else:
                        downloaded_media += result.downloaded_media_count
                except Exception as exc:  # pragma: no cover
                    failed += 1
                    self._state.append_event(str(exc))

                self._state.update(
                    downloaded_tweets=downloaded_media,
                    skipped_tweets=skipped,
                    failed_tweets=failed,
                )

            self._state.finish_success(
                f"Finished. Discovered {len(tweet_urls)} liked tweets, downloaded {downloaded_media} media files, "
                f"skipped {skipped}, failed {failed}."
            )
        except Exception as exc:  # pragma: no cover
            self._state.finish_error(str(exc))
