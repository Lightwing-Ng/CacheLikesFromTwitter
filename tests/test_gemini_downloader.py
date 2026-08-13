"""Focused tests for Gemini session history Parquet persistence."""

# Code version: v1.3.2-codex.1

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq
import pytest

from app.core.gemini_downloader import (
    GeminiConversationLink,
    GeminiHistoryStore,
    _open_gemini_sidebar,
    _prepare_gemini_page_for_rendering,
    _read_gemini_conversation_links,
    _scroll_gemini_conversation_navigation,
    build_gemini_initial_snapshot,
    gemini_conversation_id,
    gemini_history_path,
    inspect_gemini_bot_check,
    is_gemini_conversation_url,
    normalize_gemini_conversation_url,
    wait_for_gemini_bot_check_clear,
    collect_gemini_conversation_links,
)
from app.core.config import CrawlConfig
from app.core.state import TaskSnapshot, TaskState
from app.core.resource_persistence import GEMINI_HISTORY_SCHEMA


def _messages(user_text: str = "Hello", assistant_text: str = "Hi there") -> list[dict[str, object]]:
    return [
        {
            "conversation_title": "Demo chat",
            "turn_index": 0,
            "message_index": 0,
            "role": "user",
            "author_label": "You",
            "content_text": user_text,
            "content_html": f"<p>{user_text}</p>",
            "source_links": [],
            "model_label": "",
        },
        {
            "conversation_title": "Demo chat",
            "turn_index": 0,
            "message_index": 1,
            "role": "assistant",
            "author_label": "Gemini",
            "content_text": assistant_text,
            "content_html": f"<p>{assistant_text}</p>",
            "source_links": ["https://example.com/source", "https://example.com/source"],
            "model_label": "Gemini Flash",
        },
    ]


def test_open_gemini_sidebar_expands_the_independent_recents_list() -> None:
    class Page:
        def __init__(self) -> None:
            self.scripts: list[str] = []
            self.waits: list[int] = []
            self.responses = [
                True,
                {"buttonFound": True, "expanded": False, "links": 0},
                {"buttonFound": True, "expanded": True, "links": 30},
            ]

        def evaluate(self, script):
            self.scripts.append(script)
            return self.responses.pop(0)

        def wait_for_timeout(self, milliseconds):
            self.waits.append(milliseconds)

    page = Page()

    _open_gemini_sidebar(page)

    assert len(page.scripts) == 3
    assert "open sidebar" in page.scripts[0]
    assert "chats-expandable-section" in page.scripts[1]
    assert "recentsButton" in page.scripts[2]
    assert page.waits == [1_000, 500]


def test_gemini_conversation_urls_are_canonical_and_host_scoped() -> None:
    source = "https://gemini.google.com/app/abc_123?utm_source=test#fragment"

    assert normalize_gemini_conversation_url(source) == "https://gemini.google.com/app/abc_123"
    assert gemini_conversation_id(source) == "abc_123"
    assert is_gemini_conversation_url(source)
    assert not is_gemini_conversation_url("https://example.com/app/abc_123")
    assert not is_gemini_conversation_url("https://gemini.google.com/app")


def test_gemini_history_store_atomically_merges_and_replaces_conversations(tmp_path: Path) -> None:
    path = gemini_history_path(tmp_path)
    first = GeminiConversationLink("conversation-a", "https://gemini.google.com/app/conversation-a", "Demo chat")
    second = GeminiConversationLink("conversation-b", "https://gemini.google.com/app/conversation-b", "Second chat")
    store = GeminiHistoryStore(path)

    added, unchanged = store.replace_conversation(first, _messages(), "2026-08-12T05:00:00Z")
    assert added == 2
    assert not unchanged
    store.save()

    table = pq.read_table(path)
    assert table.schema.names == GEMINI_HISTORY_SCHEMA.names
    assert table.num_rows == 2
    assert table.to_pylist()[1]["source_links"] == ["https://example.com/source"]

    reloaded = GeminiHistoryStore(path)
    added, unchanged = reloaded.replace_conversation(first, _messages(), "2026-08-12T06:00:00Z")
    assert added == 0
    assert unchanged
    reloaded.replace_conversation(second, _messages("Question", "Answer"), "2026-08-12T06:00:00Z")
    reloaded.save()

    final_store = GeminiHistoryStore(path)
    assert final_store.cached_conversations == 2
    assert final_store.cached_messages == 4
    first_rows = [row for row in final_store.rows if row["conversation_id"] == "conversation-a"]
    assert {row["first_seen_at"] for row in first_rows} == {"2026-08-12T05:00:00Z"}
    assert {row["last_seen_at"] for row in first_rows} == {"2026-08-12T06:00:00Z"}

    added, unchanged = final_store.replace_conversation(
        first,
        [_messages("Edited question", "unused")[0]],
        "2026-08-12T07:00:00Z",
    )
    final_store.save()
    assert added == 1
    assert not unchanged
    assert final_store.cached_conversations == 2
    assert final_store.cached_messages == 3


def test_gemini_initial_snapshot_counts_cached_rows(tmp_path: Path) -> None:
    path = gemini_history_path(tmp_path)
    store = GeminiHistoryStore(path)
    store.replace_conversation(
        GeminiConversationLink("conversation-a", "https://gemini.google.com/app/conversation-a", "Demo"),
        _messages(),
        "2026-08-12T05:00:00Z",
    )
    store.save()

    snapshot = build_gemini_initial_snapshot("v-test", tmp_path)

    assert snapshot.downloaded_posts == 1
    assert snapshot.downloaded_tweets == 2
    assert snapshot.output_dir == str(path.parent)
    assert "1 session, 2 messages" in snapshot.message


def test_gemini_history_store_rejects_an_unreadable_existing_parquet(tmp_path: Path) -> None:
    path = gemini_history_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("not parquet", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Parquet is unreadable"):
        GeminiHistoryStore(path)


def test_rendered_gemini_links_are_deduplicated_and_normalized() -> None:
    class Page:
        def evaluate(self, _script):
            return [
                {
                    "conversationId": "abc",
                    "url": "https://gemini.google.com/app/abc?query=1",
                    "title": "First",
                },
                {
                    "conversationId": "abc",
                    "url": "https://gemini.google.com/app/abc",
                    "title": "Duplicate",
                },
                {
                    "conversationId": "foreign",
                    "url": "https://example.com/app/foreign",
                    "title": "Foreign",
                },
            ]

    assert _read_gemini_conversation_links(Page()) == [
        GeminiConversationLink("abc", "https://gemini.google.com/app/abc", "First")
    ]


def test_gemini_scroll_dispatches_for_a_virtualized_conversation_list() -> None:
    class Page:
        def evaluate(self, script):
            self.script = script
            return {
                "moved": False,
                "eventDispatched": True,
                "top": 0,
                "height": 0,
                "viewport": 0,
            }

    page = Page()
    state = _scroll_gemini_conversation_navigation(page)

    assert state["eventDispatched"] is True
    assert "closest('infinite-scroller')" in page.script
    assert "dispatchEvent(new Event('scroll'" in page.script


def test_gemini_keeps_safari_render_active_in_background() -> None:
    class Page:
        def __init__(self) -> None:
            self.background_render_calls = 0
            self.background_calls = 0
            self.waits: list[int] = []

        def keep_rendering_in_background(self) -> None:
            self.background_render_calls += 1

        def keep_background(self) -> None:
            self.background_calls += 1

        def wait_for_timeout(self, milliseconds: int) -> None:
            self.waits.append(milliseconds)

    page = Page()
    _prepare_gemini_page_for_rendering(page)

    assert page.background_render_calls == 1
    assert page.background_calls == 0
    assert page.waits == [1_000]


def test_gemini_bot_check_pauses_until_user_clears_google_verification() -> None:
    class Page:
        def __init__(self) -> None:
            self.checks = [
                {"detected": True, "reason": "captcha"},
                {"detected": False},
            ]
            self.front_calls = 0
            self.waits = 0

        def evaluate(self, _script, _markers):
            return self.checks.pop(0)

        def bring_to_front(self):
            self.front_calls += 1

        def wait_for_timeout(self, milliseconds):
            assert milliseconds == 1_000
            self.waits += 1

    page = Page()
    state = TaskState("v-test", snapshot_factory=lambda version: TaskSnapshot(version=version))

    assert wait_for_gemini_bot_check_clear(page, state, lambda: False, "collecting")

    snapshot = state.snapshot()
    assert page.front_calls == 1
    assert page.waits == 1
    assert snapshot["phase"] == "collecting"
    assert any("human verification" in event for event in snapshot["recent_events"])
    assert any("verification cleared" in event for event in snapshot["recent_events"])


def test_gemini_bot_check_inspection_uses_page_markers_and_challenge_selectors() -> None:
    class Page:
        def evaluate(self, script, markers):
            assert "challengeElement" in script
            assert "unusual traffic" in markers
            assert "[data-sitekey], [id*=" in script
            assert " + '[class*=\"captcha\"]" in script
            return {"detected": True, "reason": "challenge element"}

    assert inspect_gemini_bot_check(Page())["detected"]


def test_gemini_collection_keeps_virtualized_loading_after_a_scroll_without_pixel_motion() -> None:
    class Page:
        def __init__(self) -> None:
            self.scroll_round = 0

        def goto(self, *_args, **_kwargs):
            return None

        def evaluate(self, script, *_args):
            if "dispatchEvent(new Event('scroll'" in script:
                self.scroll_round += 1
                return {"moved": False, "eventDispatched": True}
            if "document.querySelectorAll('a[href]')" in script:
                count = min(2 + max(0, self.scroll_round - 1) * 2, 6)
                return [
                    {
                        "conversationId": f"conversation-{index}",
                        "url": f"https://gemini.google.com/app/conversation-{index}",
                        "title": f"Conversation {index}",
                    }
                    for index in range(count)
                ]
            raise AssertionError(f"Unexpected page script: {script[:80]}")

        def wait_for_timeout(self, _milliseconds):
            return None

    page = Page()
    config = CrawlConfig(
        gemini_max_conversations=6,
        max_scroll_rounds=5,
        gemini_stale_round_limit=1,
        gemini_scroll_pause_seconds=0.1,
    )
    with patch("app.core.gemini_downloader.inspect_gemini_bot_check", return_value={"detected": False}), patch(
        "app.core.gemini_downloader._wait_for_gemini_ready"
    ), patch("app.core.gemini_downloader._open_gemini_sidebar"), patch(
        "app.core.gemini_downloader._prepare_gemini_page_for_rendering"
    ):
        links = collect_gemini_conversation_links(page, config, lambda: False)

    assert len(links) == 6
