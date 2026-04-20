"""Download media from tweet URLs with yt-dlp."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .config import CrawlConfig
from .state import TaskState


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
) -> bool:
    """Download media for one tweet URL."""
    yt_dlp_command = ensure_yt_dlp_available()
    output_dir.mkdir(parents=True, exist_ok=True)

    command = yt_dlp_command + [
        "--cookies-from-browser",
        build_cookies_from_browser_arg(config),
        "--download-archive",
        str(archive_path),
        "--output",
        str(output_dir / "%(uploader_id|unknown_uploader)s" / "%(id)s" / "%(id)s.%(ext)s"),
        "--output",
        "infojson:" + str(output_dir / "%(uploader_id|unknown_uploader)s" / "%(id)s" / "%(id)s.info.json"),
        "--write-info-json",
        "--write-thumbnail",
        "--no-progress",
        "--restrict-filenames",
        "--no-overwrites",
        tweet_url,
    ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        state.append_event(f"Downloaded media for {tweet_url}")
        return True

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    combined = stderr or stdout or "Unknown yt-dlp error."

    if "has already been recorded in the archive" in combined:
        state.append_event(f"Skipped already archived tweet {tweet_url}")
        return False

    raise RuntimeError(f"yt-dlp failed for {tweet_url}: {combined}")
