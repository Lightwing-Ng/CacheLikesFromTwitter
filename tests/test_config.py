"""Focused regression tests for persisted crawler settings.

Code version: v1.3.1-codex.1
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config import CrawlConfig, load_saved_config, save_config


class ConfigPersistenceTests(unittest.TestCase):
    """Validate saved settings survive app restarts."""

    def test_new_configuration_uses_non_disruptive_gemini_default(self) -> None:
        self.assertEqual(CrawlConfig().gemini_browser, "edge")

    def test_save_and_load_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_path = Path(temp_dir) / "settings.json"
            config = CrawlConfig(
                headless=True,
                max_media_file_size_mib=128,
                max_media_items=50_000,
                max_scroll_rounds=5_000,
                scroll_pause_seconds=1.0,
                stale_round_limit=12,
                gemini_browser="safari",
                gemini_max_conversations=2_000,
                gemini_scroll_pause_seconds=0.35,
                gemini_stale_round_limit=7,
                chrome_user_data_dir=Path("/tmp/chrome-profile"),
                chrome_profile_directory="Profile 2",
                account_name_override="demo_override",
                shadow_backup_enabled=True,
                shadow_backup_auto_sync=True,
                shadow_backup_mirror_deletions=True,
                shadow_backup_destination=Path("/tmp/OneDrive/AICaches"),
            )

            save_config(config, settings_path)
            loaded = load_saved_config(settings_path)

        self.assertTrue(loaded.headless)
        self.assertEqual(loaded.max_media_file_size_mib, 128)
        self.assertEqual(loaded.max_media_file_size_bytes, 128 * 1024 * 1024)
        self.assertEqual(loaded.max_media_items, 50_000)
        self.assertEqual(loaded.max_scroll_rounds, 5_000)
        self.assertEqual(loaded.scroll_pause_seconds, 1.0)
        self.assertEqual(loaded.stale_round_limit, 12)
        self.assertEqual(loaded.gemini_browser, "safari")
        self.assertEqual(loaded.gemini_max_conversations, 2_000)
        self.assertEqual(loaded.gemini_scroll_pause_seconds, 0.35)
        self.assertEqual(loaded.gemini_stale_round_limit, 7)
        self.assertEqual(loaded.chrome_user_data_dir, Path("/tmp/chrome-profile"))
        self.assertEqual(loaded.chrome_profile_directory, "Profile 2")
        self.assertEqual(loaded.account_name_override, "demo_override")
        self.assertTrue(loaded.shadow_backup_enabled)
        self.assertTrue(loaded.shadow_backup_auto_sync)
        self.assertTrue(loaded.shadow_backup_mirror_deletions)
        self.assertEqual(loaded.shadow_backup_destination, Path("/tmp/OneDrive/AICaches"))


if __name__ == "__main__":
    unittest.main()
