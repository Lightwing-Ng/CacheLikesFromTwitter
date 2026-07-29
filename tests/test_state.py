"""Focused regression tests for startup state hydration.

Code version: v1.0.1-codex.2
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import cache_catalog
from app.core import state as state_module


class TaskStateTests(unittest.TestCase):
    """Validate idle-state cache metrics are restored from disk."""

    def test_state_hydrates_existing_local_cache_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_store_root = Path(temp_dir) / "local_store"
            account_root = local_store_root / "x"

            video_dir = account_root / "uploader_a" / "111"
            video_dir.mkdir(parents=True, exist_ok=True)
            (video_dir / "111.info.json").write_text(
                json.dumps({"_type": "video", "webpage_url": "https://x.com/demo/status/111"})
            )
            (video_dir / "111.mp4").write_text("video")
            (video_dir / "111.jpg").write_text("thumbnail")

            image_dir = account_root / "uploader_b" / "222"
            image_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / "222.info.json").write_text(
                json.dumps({"_type": "playlist", "webpage_url": "https://x.com/demo/status/222"})
            )
            (image_dir / "222.jpg").write_text("image")

            legacy_dir = local_store_root / "legacy_account" / "uploader_c" / "333"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / "333.info.json").write_text(
                json.dumps({"_type": "playlist", "webpage_url": "https://x.com/legacy/status/333"})
            )
            (legacy_dir / "333.jpg").write_text("legacy-image")

            with patch.object(state_module, "LOCAL_STORE_ROOT", local_store_root):
                cache_catalog.LocalTweetCacheIndex.build(account_root).flush()
                cache_catalog.LocalTweetCacheIndex.build(local_store_root / "legacy_account").flush()
                task_state = state_module.TaskState(version="test")

            snapshot = task_state.snapshot()
            self.assertEqual(snapshot["account_name"], "x")
            self.assertEqual(snapshot["output_dir"], str(account_root))
            self.assertEqual(snapshot["downloaded_posts"], 2)
            self.assertEqual(snapshot["downloaded_images"], 1)
            self.assertEqual(snapshot["downloaded_videos"], 1)
            self.assertEqual(snapshot["downloaded_tweets"], 2)
            self.assertIn("Found existing cache", snapshot["message"])


if __name__ == "__main__":
    unittest.main()
