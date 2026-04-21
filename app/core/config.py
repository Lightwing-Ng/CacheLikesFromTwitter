"""Configuration helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_STORE_ROOT = PROJECT_ROOT / "local_store"
LOGS_ROOT = PROJECT_ROOT / "logs"
SETTINGS_PATH = PROJECT_ROOT / ".cachelikes-settings.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8666
DEFAULT_CHROME_USER_DATA_DIR = Path.home() / "Library/Application Support/Google/Chrome"
DEFAULT_CHROME_PROFILE_DIRECTORY = "Default"


@dataclass(slots=True)
class CrawlConfig:
    """Runtime configuration for a single cache job."""

    headless: bool = False
    max_media_items: int = 10
    max_scroll_rounds: int = 200
    scroll_pause_seconds: float = 1.2
    stale_round_limit: int = 8
    chrome_user_data_dir: Path = DEFAULT_CHROME_USER_DATA_DIR
    chrome_profile_directory: str = DEFAULT_CHROME_PROFILE_DIRECTORY
    account_name_override: str = ""

    def sanitized_account_name(self, fallback: str) -> str:
        raw_name = self.account_name_override.strip() or fallback.strip() or "unknown_account"
        safe_name = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in raw_name)
        return safe_name.strip("._") or "unknown_account"


def load_saved_config(settings_path: Path = SETTINGS_PATH) -> CrawlConfig:
    """Load persisted crawler settings, or defaults when none exist."""
    if not settings_path.exists():
        return CrawlConfig()

    try:
        payload = json.loads(settings_path.read_text())
    except (OSError, json.JSONDecodeError):
        return CrawlConfig()

    defaults = CrawlConfig()
    return CrawlConfig(
        headless=bool(payload.get("headless", defaults.headless)),
        max_media_items=int(payload.get("max_media_items", defaults.max_media_items)),
        max_scroll_rounds=int(payload.get("max_scroll_rounds", defaults.max_scroll_rounds)),
        scroll_pause_seconds=float(payload.get("scroll_pause_seconds", defaults.scroll_pause_seconds)),
        stale_round_limit=int(payload.get("stale_round_limit", defaults.stale_round_limit)),
        chrome_user_data_dir=Path(payload.get("chrome_user_data_dir", str(defaults.chrome_user_data_dir))).expanduser(),
        chrome_profile_directory=str(
            payload.get("chrome_profile_directory", defaults.chrome_profile_directory)
        ).strip()
        or defaults.chrome_profile_directory,
        account_name_override=str(payload.get("account_name_override", defaults.account_name_override)).strip(),
    )


def save_config(config: CrawlConfig, settings_path: Path = SETTINGS_PATH) -> None:
    """Persist crawler settings for future app restarts."""
    payload = asdict(config)
    payload["chrome_user_data_dir"] = str(config.chrome_user_data_dir)
    settings_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
