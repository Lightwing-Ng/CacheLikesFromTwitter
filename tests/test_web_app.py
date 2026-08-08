"""Focused regression tests for the local web console."""

# Code version: v1.2.0-codex.1

from __future__ import annotations

from dataclasses import asdict
import unittest

from app.core.state import TaskSnapshot
from app.web.app import create_app, reconcile_cached_snapshot


class WebAppTests(unittest.TestCase):
    """Validate the index page renders live progress metrics."""

    def test_index_includes_progress_metric_counters(self) -> None:
        app = create_app()

        with app.test_client() as client:
            response = client.get("/")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="progress_downloaded_posts"', body)
        self.assertIn('id="progress_downloaded_images"', body)
        self.assertIn('id="progress_downloaded_videos"', body)

    def test_grok_page_and_four_slot_dock_render(self) -> None:
        app = create_app()

        with app.test_client() as client:
            grok_response = client.get("/grok")
            chatgpt_response = client.get("/chatgpt")
            index_response = client.get("/")
            settings_response = client.get("/settings")

        grok_body = grok_response.get_data(as_text=True)
        chatgpt_body = chatgpt_response.get_data(as_text=True)
        index_body = index_response.get_data(as_text=True)
        settings_body = settings_response.get_data(as_text=True)

        self.assertEqual(grok_response.status_code, 200)
        self.assertEqual(chatgpt_response.status_code, 200)
        self.assertEqual(settings_response.status_code, 200)
        self.assertIn('data-section-link="x"', grok_body)
        self.assertIn('data-section-link="grok"', grok_body)
        self.assertIn('data-section-link="settings"', grok_body)
        self.assertIn('data-section-link="chatgpt"', grok_body)
        self.assertIn('href="/chatgpt"', grok_body)
        self.assertIn('data-section-link="grok"', index_body)
        self.assertIn('data-section-link="chatgpt"', index_body)
        self.assertIn("Studio208cm project overview", chatgpt_body)
        self.assertIn('data-platform="chatgpt"', chatgpt_body)
        self.assertIn('action="/chatgpt/start"', chatgpt_body)
        for body in (grok_body, chatgpt_body, index_body, settings_body):
            with self.subTest(page=body[:40]):
                dock_positions = [
                    body.index(f'data-section-link="{label}"')
                    for label in ("x", "grok", "chatgpt", "settings")
                ]
                self.assertEqual(dock_positions, sorted(dock_positions))
        self.assertIn('id="status_progress_detail"', grok_body)
        self.assertIn("data.queued_tweets", grok_body)
        self.assertIn("data.processed_tweets", grok_body)
        self.assertNotIn('id="reset_button"', grok_body)
        self.assertIn('id="reset_button"', settings_body)
        self.assertIn('id="reset_chatgpt_button"', settings_body)
        self.assertIn("Danger zone", settings_body)

    def test_cache_reconciliation_skips_failed_snapshots(self) -> None:
        snapshot = {
            "running": False,
            "phase": "failed",
            "message": "Failure.",
            "account_name": "demo_user",
            "output_dir": "/tmp/live",
            "downloaded_posts": 0,
            "downloaded_tweets": 0,
            "downloaded_images": 0,
            "downloaded_videos": 0,
        }
        hydrated = TaskSnapshot(
            version="v-test",
            account_name="x",
            output_dir="/tmp/cache",
            downloaded_posts=542,
            downloaded_tweets=542,
            downloaded_images=0,
            downloaded_videos=542,
            message="Ready. Found existing cache: 542 posts, 0 images, 542 videos.",
        )

        reconciled = reconcile_cached_snapshot(snapshot, asdict(hydrated))

        self.assertEqual(reconciled["message"], "Failure.")
        self.assertEqual(reconciled["downloaded_posts"], 0)
        self.assertEqual(reconciled["downloaded_videos"], 0)
        self.assertEqual(reconciled["output_dir"], "/tmp/live")

    def test_cache_reconciliation_hydrates_finished_snapshots(self) -> None:
        snapshot = {
            "running": False,
            "phase": "finished",
            "message": "Finished.",
            "account_name": "",
            "output_dir": "",
            "downloaded_posts": 1,
            "downloaded_tweets": 1,
            "downloaded_images": 1,
            "downloaded_videos": 0,
        }
        hydrated = TaskSnapshot(
            version="v-test",
            account_name="x",
            output_dir="/tmp/cache",
            downloaded_posts=542,
            downloaded_tweets=542,
            downloaded_images=0,
            downloaded_videos=542,
            message="Ready. Found existing cache: 542 posts, 0 images, 542 videos.",
        )

        reconciled = reconcile_cached_snapshot(snapshot, asdict(hydrated))

        self.assertEqual(reconciled["message"], hydrated.message)
        self.assertEqual(reconciled["downloaded_posts"], 542)
        self.assertEqual(reconciled["downloaded_videos"], 542)
        self.assertEqual(reconciled["output_dir"], "/tmp/cache")


if __name__ == "__main__":
    unittest.main()
