"""Focused regression tests for the local web console."""

# Code version: v1.1.0-codex.3

from __future__ import annotations

import unittest

from app.web.app import create_app


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

    def test_grok_page_and_three_slot_dock_render(self) -> None:
        app = create_app()

        with app.test_client() as client:
            grok_response = client.get("/grok")
            index_response = client.get("/")
            settings_response = client.get("/settings")

        grok_body = grok_response.get_data(as_text=True)
        index_body = index_response.get_data(as_text=True)
        settings_body = settings_response.get_data(as_text=True)

        self.assertEqual(grok_response.status_code, 200)
        self.assertEqual(settings_response.status_code, 200)
        self.assertIn('data-section-link="x"', grok_body)
        self.assertIn('data-section-link="grok"', grok_body)
        self.assertIn('data-section-link="settings"', grok_body)
        self.assertIn('data-section-link="grok"', index_body)
        self.assertIn('id="status_progress_detail"', grok_body)
        self.assertIn("data.queued_tweets", grok_body)
        self.assertIn("data.processed_tweets", grok_body)
        self.assertNotIn('id="reset_button"', grok_body)
        self.assertIn('id="reset_button"', settings_body)
        self.assertIn("Danger zone", settings_body)


if __name__ == "__main__":
    unittest.main()
