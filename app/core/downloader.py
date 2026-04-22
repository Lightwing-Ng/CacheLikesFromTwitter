"""Download media from tweet URLs with yt-dlp."""

# Code version: v1.3.0-codex.1

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .cache_catalog import LocalTweetCacheIndex
from .config import CrawlConfig
from .state import TaskState


MEDIA_MARKER_PREFIX = "__CACHELIKES_MEDIA__:"
SUCCESS_SKIP_MARKERS = (
    "has already been recorded in the archive",
    "has already been downloaded",
    "already exists",
    "file already exists",
    "not overwriting",
    "has been downloaded",
)
MISSING_MEDIA_SKIP_MARKERS = (
    "no video could be found in this tweet",
)
UNSUPPORTED_EXTERNAL_URL_MARKERS = (
    "unsupported url:",
)
NOT_FOUND_SKIP_MARKERS = (
    "http error 404",
    "404: not found",
    "unable to download webpage: http error 404",
)
SUSPENDED_SKIP_MARKERS = (
    ": suspended",
)
TRANSIENT_ERROR_MARKERS = (
    "timed out",
    "remote end closed connection without response",
    "transporterror(",
    "proxyerror(",
    "tunnel connection failed",
    "service unavailable",
)
CONFLICT_ERROR_MARKERS = (
    "file exists",
    "already exists",
    "unable to rename",
    "cannot move file",
    "not overwriting",
)
DOWNLOAD_RETRY_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAY_SECONDS = 1.5
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadResult:
    """Capture the outcome for a single tweet download."""

    downloaded_media_count: int = 0
    downloaded_post_count: int = 0
    downloaded_image_count: int = 0
    downloaded_video_count: int = 0
    skipped: bool = False


IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
}
VIDEO_SUFFIXES = {
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
}


def parse_downloaded_paths(command_output: str) -> list[Path]:
    """Extract local file paths reported by yt-dlp after successful writes."""
    downloaded_paths: list[Path] = []
    for line in command_output.splitlines():
        if line.startswith(MEDIA_MARKER_PREFIX):
            downloaded_paths.append(Path(line.removeprefix(MEDIA_MARKER_PREFIX)))
    return downloaded_paths


def count_downloaded_media_types(downloaded_paths: list[Path]) -> tuple[int, int]:
    """Return image and video counts from downloaded output paths."""
    image_count = 0
    video_count = 0
    for path in downloaded_paths:
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            image_count += 1
        elif suffix in VIDEO_SUFFIXES:
            video_count += 1
    return image_count, video_count


def is_successful_skip_output(command_output: str) -> bool:
    """Return whether yt-dlp reported a no-op success that should be counted as skipped."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in SUCCESS_SKIP_MARKERS)


def is_existing_file_conflict(command_output: str) -> bool:
    """Return whether the failure looks like a local file collision."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in CONFLICT_ERROR_MARKERS)


def is_missing_media_skip_output(command_output: str) -> bool:
    """Return whether yt-dlp reported no downloadable media for the tweet."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in MISSING_MEDIA_SKIP_MARKERS)


def is_unsupported_external_url_skip_output(command_output: str) -> bool:
    """Return whether yt-dlp followed a tweet external link that we do not support."""
    lowered = command_output.lower()
    if not any(marker in lowered for marker in UNSUPPORTED_EXTERNAL_URL_MARKERS):
        return False

    return "unsupported url: https://x.com/" not in lowered and "unsupported url: https://twitter.com/" not in lowered


def is_not_found_skip_output(command_output: str) -> bool:
    """Return whether the tweet target is no longer available."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in NOT_FOUND_SKIP_MARKERS)


def is_suspended_skip_output(command_output: str) -> bool:
    """Return whether the tweet or account is suspended and cannot be downloaded."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in SUSPENDED_SKIP_MARKERS)


def is_transient_retryable_output(command_output: str) -> bool:
    """Return whether the error looks transient enough to retry briefly."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in TRANSIENT_ERROR_MARKERS)


def resolve_yt_dlp_command() -> list[str]:
    """Return the preferred yt-dlp invocation for the current environment."""
    module_command = [sys.executable, "-m", "yt_dlp"]
    probe = subprocess.run(module_command + ["--version"], capture_output=True, text=True, check=False)
    if probe.returncode == 0:
        return module_command

    binary = shutil.which("yt-dlp")
    if binary:
        return [binary]

    raise RuntimeError(
        "yt-dlp is not installed. Run `python3 -m pip install -r requirements.txt` "
        "or `brew install yt-dlp`."
    )


def ensure_yt_dlp_available() -> list[str]:
    """Raise a clear error when yt-dlp is unavailable."""
    try:
        return resolve_yt_dlp_command()
    except RuntimeError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Run `python3 -m pip install -r requirements.txt` "
            "or `brew install yt-dlp`."
        ) from exc


def build_cookies_from_browser_arg(config: CrawlConfig) -> str:
    """Match yt-dlp's browser cookies source to the selected Chrome profile."""
    profile_path = Path(config.chrome_user_data_dir).expanduser() / config.chrome_profile_directory
    return f"chrome:{profile_path}"


def run_yt_dlp_with_retries(command: list[str], tweet_url: str) -> subprocess.CompletedProcess[str]:
    """Run yt-dlp with a small retry budget for transient network failures."""
    attempt = 0
    last_result: subprocess.CompletedProcess[str] | None = None

    while attempt < DOWNLOAD_RETRY_ATTEMPTS:
        attempt += 1
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        last_result = result
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part).strip()

        if result.returncode == 0 or not is_transient_retryable_output(combined) or attempt >= DOWNLOAD_RETRY_ATTEMPTS:
            return result

        logger.warning(
            "Retrying yt-dlp after transient failure.",
            extra={
                "tweet_url": tweet_url,
                "attempt": attempt,
                "max_attempts": DOWNLOAD_RETRY_ATTEMPTS,
                "command_output_excerpt": combined[:2_000],
            },
        )
        time.sleep(DOWNLOAD_RETRY_DELAY_SECONDS)

    if last_result is None:
        raise RuntimeError(f"yt-dlp did not execute for {tweet_url}")
    return last_result


def download_tweet_media(
    tweet_url: str,
    output_dir: Path,
    config: CrawlConfig,
    state: TaskState,
    remaining_media_items: int | None = None,
    cache_index: LocalTweetCacheIndex | None = None,
) -> DownloadResult:
    """Download media for one tweet URL."""
    output_dir.mkdir(parents=True, exist_ok=True)
    local_cache = cache_index or LocalTweetCacheIndex.build(output_dir)
    if not local_cache.claim(tweet_url):
        state.append_event(f"Skipped cached or in-flight tweet {tweet_url}")
        logger.info(
            "Skipped tweet because a complete local cache exists or another worker already claimed it.",
            extra={
                "tweet_url": tweet_url,
                "output_dir": str(output_dir),
            },
        )
        return DownloadResult(skipped=True)

    try:
        yt_dlp_command = ensure_yt_dlp_available()

        command = yt_dlp_command + [
            "--cookies-from-browser",
            build_cookies_from_browser_arg(config),
            "--output",
            str(output_dir / "%(uploader_id|unknown_uploader)s" / "%(id)s" / "%(id)s.%(ext)s"),
            "--output",
            "infojson:" + str(output_dir / "%(uploader_id|unknown_uploader)s" / "%(id)s" / "%(id)s"),
            "--write-info-json",
            "--write-thumbnail",
            "--no-progress",
            "--restrict-filenames",
            "--no-overwrites",
            "--print",
            f"after_move:{MEDIA_MARKER_PREFIX}%(filepath)s",
        ]
        if remaining_media_items is not None:
            command.extend(["--max-downloads", str(max(1, remaining_media_items))])
        command.append(tweet_url)

        logger.info(
            "Invoking yt-dlp for tweet media download.",
            extra={
                "tweet_url": tweet_url,
                "output_dir": str(output_dir),
                "remaining_media_items": remaining_media_items,
                "yt_dlp_command": yt_dlp_command,
            },
        )
        result = run_yt_dlp_with_retries(command, tweet_url)
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part).strip()
        downloaded_paths = parse_downloaded_paths(stdout)

        if result.returncode == 0:
            if downloaded_paths:
                image_count, video_count = count_downloaded_media_types(downloaded_paths)
                for downloaded_path in downloaded_paths:
                    local_cache.register(tweet_url, downloaded_path.parent)
                state.append_event(f"Downloaded media for {tweet_url}")
                logger.info(
                    "yt-dlp downloaded media successfully.",
                    extra={
                        "tweet_url": tweet_url,
                        "downloaded_media_count": len(downloaded_paths),
                        "downloaded_image_count": image_count,
                        "downloaded_video_count": video_count,
                        "downloaded_paths": [str(path) for path in downloaded_paths],
                    },
                )
                return DownloadResult(
                    downloaded_media_count=len(downloaded_paths),
                    downloaded_post_count=1,
                    downloaded_image_count=image_count,
                    downloaded_video_count=video_count,
                )

            if is_successful_skip_output(combined) or local_cache.contains_complete_cache(tweet_url):
                local_cache.register(tweet_url)
                state.append_event(f"Skipped already cached tweet {tweet_url}")
                logger.info(
                    "yt-dlp reported a cache hit or no-op success.",
                    extra={
                        "tweet_url": tweet_url,
                        "returncode": result.returncode,
                        "command_output_excerpt": combined[:2_000],
                    },
                )
                return DownloadResult(skipped=True)

            state.append_event(f"No new media files were produced for {tweet_url}")
            logger.warning(
                "yt-dlp succeeded but produced no new media files.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                },
            )
            return DownloadResult(skipped=True)

        if is_existing_file_conflict(combined) and local_cache.contains_complete_cache(tweet_url):
            local_cache.register(tweet_url)
            state.append_event(f"Skipped existing local conflict for {tweet_url}")
            logger.warning(
                "Downgraded local file conflict to skip because cache is already complete.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                },
            )
            return DownloadResult(skipped=True)

        if is_missing_media_skip_output(combined):
            local_cache.register(tweet_url)
            state.append_event(f"Skipped tweet with no downloadable media {tweet_url}")
            logger.info(
                "Downgraded missing media response to skip.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                },
            )
            return DownloadResult(skipped=True)

        if is_unsupported_external_url_skip_output(combined):
            local_cache.register(tweet_url)
            state.append_event(f"Skipped unsupported external media target for {tweet_url}")
            logger.info(
                "Downgraded unsupported external URL response to skip.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                },
            )
            return DownloadResult(skipped=True)

        if is_not_found_skip_output(combined):
            local_cache.register(tweet_url)
            state.append_event(f"Skipped unavailable tweet target for {tweet_url}")
            logger.info(
                "Downgraded missing remote tweet target to skip.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                },
            )
            return DownloadResult(skipped=True)

        if is_suspended_skip_output(combined):
            local_cache.register(tweet_url)
            state.append_event(f"Skipped suspended tweet target for {tweet_url}")
            logger.info(
                "Downgraded suspended tweet target to skip.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                },
            )
            return DownloadResult(skipped=True)

        if is_transient_retryable_output(combined):
            local_cache.register(tweet_url)
            state.append_event(f"Skipped transient network failure after retries for {tweet_url}")
            logger.warning(
                "Downgraded transient yt-dlp failure to skip after retry budget was exhausted.",
                extra={
                    "tweet_url": tweet_url,
                    "returncode": result.returncode,
                    "command_output_excerpt": combined[:2_000],
                    "retry_attempts": DOWNLOAD_RETRY_ATTEMPTS,
                },
            )
            return DownloadResult(skipped=True)

        logger.error(
            "yt-dlp failed for tweet media download.",
            extra={
                "tweet_url": tweet_url,
                "returncode": result.returncode,
                "stdout_excerpt": stdout[:2_000],
                "stderr_excerpt": stderr[:2_000],
            },
        )
        raise RuntimeError(f"yt-dlp failed for {tweet_url}: {combined}")
    finally:
        local_cache.release_claim(tweet_url)
