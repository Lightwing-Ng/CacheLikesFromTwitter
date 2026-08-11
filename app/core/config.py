"""Configuration helpers."""

# Code version: v1.9.0-codex.1

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT_ENV = "CACHELIKES_RUNTIME_ROOT"
SETTINGS_PATH_ENV = "CACHELIKES_SETTINGS_PATH"


def resolve_runtime_root() -> Path:
    """Return the optional runtime root used by isolated test processes."""
    configured_root = os.environ.get(RUNTIME_ROOT_ENV, "").strip()
    if not configured_root:
        return PROJECT_ROOT
    return Path(configured_root).expanduser().resolve(strict=False)


RUNTIME_ROOT = resolve_runtime_root()
LOCAL_STORE_ROOT = RUNTIME_ROOT / "local_store"
X_LOCAL_STORE_DIRNAME = "x"
LOGS_ROOT = RUNTIME_ROOT / "logs"
LEGACY_SETTINGS_PATH = RUNTIME_ROOT / ".cachelikes-settings.json"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8666
DEFAULT_CHROME_USER_DATA_DIR = Path.home() / "Library/Application Support/Google/Chrome"
DEFAULT_CHROME_PROFILE_DIRECTORY = "Default"
DEFAULT_SHADOW_BACKUP_DESTINATION = Path(
    "/Users/lightwing/Library/CloudStorage/OneDrive-Personal/AICaches"
)
DEFAULT_DOWNLOAD_WORKERS = 4
DEFAULT_MAX_MEDIA_FILE_SIZE_MIB = 50
MIN_MAX_MEDIA_FILE_SIZE_MIB = 1
MAX_MAX_MEDIA_FILE_SIZE_MIB = 10_240
DEFAULT_CHATGPT_PROJECT_URL = (
    "https://chatgpt.com/g/g-p-69522aca2f788191b337866d5c03c59e-studio208cm/project"
)
DEFAULT_CHATGPT_PROJECT_NAME = "Studio208cm"
DEFAULT_CHATGPT_STARTUP_TIMEOUT_SECONDS = 30.0
DEFAULT_CHATGPT_SCAN_WAIT_SECONDS = 0.5
MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS = 1.0
MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS = 600.0
MIN_CHATGPT_SCAN_WAIT_SECONDS = 0.1
MAX_CHATGPT_SCAN_WAIT_SECONDS = 5.0


def default_settings_path() -> Path:
    """Store local settings outside the Git worktree to avoid accidental commits."""
    configured_path = os.environ.get(SETTINGS_PATH_ENV, "").strip()
    if configured_path:
        return Path(configured_path).expanduser().resolve(strict=False)
    return Path.home() / "Library/Application Support/CacheLikesFromTwitter/settings.json"


SETTINGS_PATH = default_settings_path()


@dataclass(slots=True)
class CrawlConfig:
    """Runtime configuration for a single cache job."""

    headless: bool = False
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS
    max_media_items: int = 10
    max_scroll_rounds: int = 200
    scroll_pause_seconds: float = 1.2
    stale_round_limit: int = 8
    x_browser: str = "chrome"
    grok_browser: str = "edge"
    chatgpt_browser: str = "edge"
    chatgpt_project_url: str = DEFAULT_CHATGPT_PROJECT_URL
    chatgpt_project_name: str = DEFAULT_CHATGPT_PROJECT_NAME
    chatgpt_startup_timeout_seconds: float = DEFAULT_CHATGPT_STARTUP_TIMEOUT_SECONDS
    chatgpt_scan_wait_seconds: float = DEFAULT_CHATGPT_SCAN_WAIT_SECONDS
    chrome_user_data_dir: Path = DEFAULT_CHROME_USER_DATA_DIR
    chrome_profile_directory: str = DEFAULT_CHROME_PROFILE_DIRECTORY
    account_name_override: str = ""
    shadow_backup_enabled: bool = True
    shadow_backup_auto_sync: bool = True
    shadow_backup_mirror_deletions: bool = False
    shadow_backup_destination: Path = DEFAULT_SHADOW_BACKUP_DESTINATION
    max_media_file_size_mib: int = DEFAULT_MAX_MEDIA_FILE_SIZE_MIB

    @property
    def max_media_file_size_bytes(self) -> int:
        """Return the universal media-file limit in bytes."""
        return self.max_media_file_size_mib * 1024 * 1024

    def sanitized_account_name(self, fallback: str) -> str:
        raw_name = self.account_name_override.strip() or fallback.strip() or "unknown_account"
        safe_name = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in raw_name)
        return safe_name.strip("._") or "unknown_account"


def load_saved_config(settings_path: Path = SETTINGS_PATH) -> CrawlConfig:
    """Load persisted crawler settings, or defaults when none exist."""
    candidate_paths = [settings_path]
    if settings_path == SETTINGS_PATH and LEGACY_SETTINGS_PATH not in candidate_paths:
        candidate_paths.append(LEGACY_SETTINGS_PATH)

    payload: dict[str, object] | None = None
    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue

        try:
            payload = json.loads(candidate_path.read_text())
            break
        except (OSError, json.JSONDecodeError):
            continue

    if payload is None:
        return CrawlConfig()

    defaults = CrawlConfig()
    return CrawlConfig(
        headless=bool(payload.get("headless", defaults.headless)),
        download_workers=max(1, int(payload.get("download_workers", defaults.download_workers))),
        max_media_file_size_mib=_clamp_int_setting(
            payload.get("max_media_file_size_mib", defaults.max_media_file_size_mib),
            defaults.max_media_file_size_mib,
            MIN_MAX_MEDIA_FILE_SIZE_MIB,
            MAX_MAX_MEDIA_FILE_SIZE_MIB,
        ),
        max_media_items=int(payload.get("max_media_items", defaults.max_media_items)),
        max_scroll_rounds=int(payload.get("max_scroll_rounds", defaults.max_scroll_rounds)),
        scroll_pause_seconds=float(payload.get("scroll_pause_seconds", defaults.scroll_pause_seconds)),
        stale_round_limit=int(payload.get("stale_round_limit", defaults.stale_round_limit)),
        x_browser=str(payload.get("x_browser", defaults.x_browser)).strip().lower() or defaults.x_browser,
        grok_browser=str(payload.get("grok_browser", defaults.grok_browser)).strip().lower() or defaults.grok_browser,
        chatgpt_browser=str(payload.get("chatgpt_browser", defaults.chatgpt_browser)).strip().lower()
        or defaults.chatgpt_browser,
        chatgpt_project_url=str(payload.get("chatgpt_project_url", defaults.chatgpt_project_url)).strip()
        or defaults.chatgpt_project_url,
        chatgpt_project_name=str(payload.get("chatgpt_project_name", defaults.chatgpt_project_name)).strip()
        or defaults.chatgpt_project_name,
        chatgpt_startup_timeout_seconds=_clamp_float_setting(
            payload.get("chatgpt_startup_timeout_seconds", defaults.chatgpt_startup_timeout_seconds),
            defaults.chatgpt_startup_timeout_seconds,
            MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
            MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
        ),
        chatgpt_scan_wait_seconds=_clamp_float_setting(
            payload.get("chatgpt_scan_wait_seconds", defaults.chatgpt_scan_wait_seconds),
            defaults.chatgpt_scan_wait_seconds,
            MIN_CHATGPT_SCAN_WAIT_SECONDS,
            MAX_CHATGPT_SCAN_WAIT_SECONDS,
        ),
        chrome_user_data_dir=Path(payload.get("chrome_user_data_dir", str(defaults.chrome_user_data_dir))).expanduser(),
        chrome_profile_directory=str(
            payload.get("chrome_profile_directory", defaults.chrome_profile_directory)
        ).strip()
        or defaults.chrome_profile_directory,
        account_name_override=str(payload.get("account_name_override", defaults.account_name_override)).strip(),
        shadow_backup_enabled=bool(payload.get("shadow_backup_enabled", defaults.shadow_backup_enabled)),
        shadow_backup_auto_sync=bool(payload.get("shadow_backup_auto_sync", defaults.shadow_backup_auto_sync)),
        shadow_backup_mirror_deletions=bool(
            payload.get("shadow_backup_mirror_deletions", defaults.shadow_backup_mirror_deletions)
        ),
        shadow_backup_destination=Path(
            str(payload.get("shadow_backup_destination", defaults.shadow_backup_destination)).strip()
            or str(defaults.shadow_backup_destination)
        ).expanduser(),
    )


def _clamp_float_setting(value: object, fallback: float, minimum: float, maximum: float) -> float:
    """Parse one persisted float setting and keep it within its supported range."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, minimum), maximum)


def _clamp_int_setting(value: object, fallback: int, minimum: int, maximum: int) -> int:
    """Parse one persisted integer setting and keep it within its supported range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, minimum), maximum)


def save_config(config: CrawlConfig, settings_path: Path = SETTINGS_PATH) -> None:
    """Persist crawler settings for future app restarts."""
    payload = asdict(config)
    payload["x_browser"] = config.x_browser
    payload["grok_browser"] = config.grok_browser
    payload["chatgpt_browser"] = config.chatgpt_browser
    payload["chatgpt_project_url"] = config.chatgpt_project_url
    payload["chatgpt_project_name"] = config.chatgpt_project_name
    payload["chrome_user_data_dir"] = str(config.chrome_user_data_dir)
    payload["shadow_backup_destination"] = str(config.shadow_backup_destination)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
