"""Download media from tweet URLs with yt-dlp."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

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
CONFLICT_ERROR_MARKERS = (
    "file exists",
    "already exists",
    "unable to rename",
    "cannot move file",
    "not overwriting",
)
INFO_JSON_SUFFIXES = (".info.json", ".info.json.info.json")
STATUS_URL_PATTERN = re.compile(r"/status/(\d+)")
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DownloadResult:
    """Capture the outcome for a single tweet download."""

    downloaded_media_count: int = 0
    skipped: bool = False


@dataclass(slots=True)
class LocalTweetCacheIndex:
    """Track locally cached tweets so duplicate downloads can be skipped early."""

    directories_by_status_id: dict[str, set[Path]] = field(default_factory=dict)
    directories_by_url: dict[str, set[Path]] = field(default_factory=dict)

    @classmethod
    def build(cls, output_dir: Path) -> LocalTweetCacheIndex:
        """Index cached tweet metadata that already exists on disk."""
        index = cls()
        if not output_dir.exists():
            return index

        for info_json_path in output_dir.rglob("*.info.json*"):
            if not info_json_path.is_file() or not info_json_path.name.endswith(INFO_JSON_SUFFIXES):
                continue

            try:
                payload = json.loads(info_json_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue

            tweet_dir = info_json_path.parent
            candidate_urls = [payload.get("webpage_url", "")]
            uploader_id = str(payload.get("uploader_id") or "").strip()
            display_id = str(payload.get("display_id") or "").strip()
            if uploader_id and display_id:
                candidate_urls.append(f"https://x.com/{uploader_id}/status/{display_id}")

            for candidate_url in candidate_urls:
                index.register(candidate_url, tweet_dir)

        return index

    def register(self, tweet_url: str, tweet_dir: Path | None = None) -> None:
        """Remember a tweet URL and any local directory known to contain its media."""
        canonical_url = canonicalize_tweet_url(tweet_url)
        status_id = extract_status_id(tweet_url)
        if canonical_url:
            self.directories_by_url.setdefault(canonical_url, set())
            if tweet_dir is not None:
                self.directories_by_url[canonical_url].add(tweet_dir)
        if status_id:
            self.directories_by_status_id.setdefault(status_id, set())
            if tweet_dir is not None:
                self.directories_by_status_id[status_id].add(tweet_dir)

    def contains_complete_cache(self, tweet_url: str) -> bool:
        """Return whether the given tweet already has reusable local media."""
        for tweet_dir in self.lookup_directories(tweet_url):
            if tweet_dir_has_cached_media(tweet_dir):
                return True
        return False

    def lookup_directories(self, tweet_url: str) -> set[Path]:
        """Return directories associated with a tweet URL or status ID."""
        directories: set[Path] = set()
        canonical_url = canonicalize_tweet_url(tweet_url)
        if canonical_url:
            directories.update(self.directories_by_url.get(canonical_url, set()))

        status_id = extract_status_id(tweet_url)
        if status_id:
            directories.update(self.directories_by_status_id.get(status_id, set()))

        return directories


def canonicalize_tweet_url(tweet_url: str) -> str:
    """Normalize X or Twitter status URLs so duplicate matches are stable."""
    text = (tweet_url or "").strip()
    if not text:
        return ""

    text = text.split("?", 1)[0].rstrip("/")
    if not text:
        return ""

    if "://" not in text:
        text = f"https://x.com/{text.lstrip('/')}"

    _, _, remainder = text.partition("://")
    host, _, path = remainder.partition("/")
    host = host.lower()
    if host in {"twitter.com", "www.twitter.com", "mobile.twitter.com", "www.x.com", "mobile.x.com"}:
        host = "x.com"

    normalized_path = "/" + path.lstrip("/") if path else ""
    return f"https://{host}{normalized_path}".rstrip("/")


def extract_status_id(tweet_url: str) -> str:
    """Extract the tweet status ID from a URL if present."""
    match = STATUS_URL_PATTERN.search(tweet_url or "")
    return match.group(1) if match else ""


def tweet_dir_has_cached_media(tweet_dir: Path) -> bool:
    """Return whether a tweet directory has metadata plus at least one downloaded asset."""
    if not tweet_dir.exists() or not tweet_dir.is_dir():
        return False

    has_metadata = any((tweet_dir / child.name).name.endswith(INFO_JSON_SUFFIXES) for child in tweet_dir.iterdir() if child.is_file())
    if not has_metadata:
        return False

    for child in tweet_dir.iterdir():
        if not child.is_file():
            continue
        if child.name.endswith(INFO_JSON_SUFFIXES):
            continue
        if child.suffix in {".part", ".ytdl"}:
            continue
        return True

    return False


def parse_downloaded_paths(command_output: str) -> list[Path]:
    """Extract local file paths reported by yt-dlp after successful writes."""
    downloaded_paths: list[Path] = []
    for line in command_output.splitlines():
        if line.startswith(MEDIA_MARKER_PREFIX):
            downloaded_paths.append(Path(line.removeprefix(MEDIA_MARKER_PREFIX)))
    return downloaded_paths


def is_successful_skip_output(command_output: str) -> bool:
    """Return whether yt-dlp reported a no-op success that should be counted as skipped."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in SUCCESS_SKIP_MARKERS)


def is_existing_file_conflict(command_output: str) -> bool:
    """Return whether the failure looks like a local file collision."""
    lowered = command_output.lower()
    return any(marker in lowered for marker in CONFLICT_ERROR_MARKERS)


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


def download_tweet_media(
    tweet_url: str,
    output_dir: Path,
    archive_path: Path,
    config: CrawlConfig,
    state: TaskState,
    remaining_media_items: int | None = None,
    cache_index: LocalTweetCacheIndex | None = None,
) -> DownloadResult:
    """Download media for one tweet URL."""
    output_dir.mkdir(parents=True, exist_ok=True)
    local_cache = cache_index or LocalTweetCacheIndex.build(output_dir)
    if local_cache.contains_complete_cache(tweet_url):
        state.append_event(f"Skipped cached tweet {tweet_url}")
        logger.info(
            "Skipped tweet because complete local cache already exists.",
            extra={
                "tweet_url": tweet_url,
                "output_dir": str(output_dir),
            },
        )
        return DownloadResult(skipped=True)
    yt_dlp_command = ensure_yt_dlp_available()

    command = yt_dlp_command + [
        "--cookies-from-browser",
        build_cookies_from_browser_arg(config),
        "--download-archive",
        str(archive_path),
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
            "archive_path": str(archive_path),
            "remaining_media_items": remaining_media_items,
            "yt_dlp_command": yt_dlp_command,
        },
    )
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part).strip()
    downloaded_paths = parse_downloaded_paths(stdout)

    if result.returncode == 0:
        if downloaded_paths:
            for downloaded_path in downloaded_paths:
                local_cache.register(tweet_url, downloaded_path.parent)
            state.append_event(f"Downloaded media for {tweet_url}")
            logger.info(
                "yt-dlp downloaded media successfully.",
                extra={
                    "tweet_url": tweet_url,
                    "downloaded_media_count": len(downloaded_paths),
                    "downloaded_paths": [str(path) for path in downloaded_paths],
                },
            )
            return DownloadResult(downloaded_media_count=len(downloaded_paths))

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
