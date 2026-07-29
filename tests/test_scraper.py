"""Focused regression tests for likes timeline URL extraction.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import unittest

from app.core.scraper import normalize_status_url, parse_likes_timeline_page


class ScraperNormalizationTests(unittest.TestCase):
    """Validate canonical tweet URL extraction from likes page links."""

    def test_normalize_status_url_strips_photo_and_analytics_suffixes(self) -> None:
        cases = {
            "https://x.com/demo/status/1234567890": "https://x.com/demo/status/1234567890",
            "https://x.com/demo/status/1234567890/photo/1": "https://x.com/demo/status/1234567890",
            "https://x.com/demo/status/1234567890/analytics": "https://x.com/demo/status/1234567890",
            "https://x.com/demo/status/1234567890/photo/4?lang=en": "https://x.com/demo/status/1234567890",
            "https://twitter.com/demo/status/1234567890/photo/2": "https://x.com/demo/status/1234567890",
            "https://mobile.twitter.com/demo/status/1234567890": "https://x.com/demo/status/1234567890",
            "https://x.com/i/web/status/1234567890": "https://x.com/i/status/1234567890",
            "https://x.com/i/status/1234567890?lang=en": "https://x.com/i/status/1234567890",
        }

        for raw_url, expected_url in cases.items():
            with self.subTest(raw_url=raw_url):
                self.assertEqual(normalize_status_url(raw_url), expected_url)

    def test_normalize_status_url_rejects_non_status_links(self) -> None:
        self.assertEqual(normalize_status_url("https://x.com/home"), "")
        self.assertEqual(normalize_status_url(""), "")

    def test_parse_likes_timeline_page_extracts_urls_and_bottom_cursor(self) -> None:
        payload = {
            "data": {
                "user": {
                    "result": {
                        "timeline": {
                            "timeline": {
                                "instructions": [
                                    {
                                        "entries": [
                                            {
                                                "entryId": "tweet-123",
                                                "content": {
                                                    "__typename": "TimelineTimelineItem",
                                                    "itemContent": {
                                                        "__typename": "TimelineTweet",
                                                        "tweet_results": {
                                                            "result": {
                                                                "__typename": "TweetWithVisibilityResults",
                                                                "tweet": {
                                                                    "rest_id": "123",
                                                                    "legacy": {
                                                                        "id_str": "123",
                                                                    },
                                                                    "core": {
                                                                        "user_results": {
                                                                            "result": {
                                                                                "legacy": {
                                                                                    "screen_name": "demo_account",
                                                                                }
                                                                            }
                                                                        }
                                                                    },
                                                                },
                                                            }
                                                        },
                                                    },
                                                },
                                            },
                                            {
                                                "entryId": "cursor-bottom-1",
                                                "content": {
                                                    "__typename": "TimelineTimelineCursor",
                                                    "cursorType": "Bottom",
                                                    "value": "bottom-cursor-token",
                                                },
                                            },
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }

        urls, cursor = parse_likes_timeline_page(payload)

        self.assertEqual(urls, ["https://x.com/demo_account/status/123"])
        self.assertEqual(cursor, "bottom-cursor-token")


if __name__ == "__main__":
    unittest.main()
