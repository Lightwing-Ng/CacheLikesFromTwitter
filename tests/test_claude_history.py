"""Focused tests for browser-rendered Claude history caching.

Code version: v1.0.0-codex.1
"""

from pathlib import Path

import pytest

from app.core.claude_history import (
    ClaudeConversationLink,
    ClaudeHistoryStore,
    ClaudeNoCacheableMessagesError,
    build_claude_initial_snapshot,
    claude_conversation_id,
    extract_claude_conversation_messages,
)


class _RenderedClaudePage:
    """Return one deterministic browser-rendered message payload."""

    def evaluate(self, script, *_args):
        assert "user-message" in script
        return {
            "title": "Rendered Claude chat",
            "modelLabel": "Sonnet 5 Medium",
            "messages": [
                {
                    "conversation_title": "Rendered Claude chat",
                    "turn_index": 1,
                    "message_index": 0,
                    "role": "user",
                    "author_label": "You",
                    "content_text": "Please summarize this.",
                    "content_html": "<p>Please summarize this.</p>",
                    "source_links": [],
                    "model_label": "",
                    "message_timestamp": "2026-09-03T01:00:00Z",
                },
                {
                    "conversation_title": "Rendered Claude chat",
                    "turn_index": 1,
                    "message_index": 1,
                    "role": "assistant",
                    "author_label": "Claude",
                    "content_text": "Here is the summary.",
                    "content_html": "<p>Here is the summary.</p>",
                    "source_links": ["https://example.com/source", "javascript:alert(1)"],
                    "model_label": "Sonnet 5 Medium",
                    "message_timestamp": "2026-09-03T01:00:05Z",
                },
            ],
        }


def test_claude_rendered_messages_are_normalized_before_storage() -> None:
    conversation = ClaudeConversationLink(
        "chat-1",
        "https://claude.ai/chat/chat-1",
        "Fallback title",
    )

    messages = extract_claude_conversation_messages(_RenderedClaudePage(), conversation)

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content_text"] == "Please summarize this."
    assert messages[1]["model_label"] == "Sonnet 5 Medium"


def test_claude_store_round_trip_preserves_first_seen_metadata(tmp_path: Path) -> None:
    conversation = ClaudeConversationLink(
        "chat-1",
        "https://claude.ai/chat/chat-1",
        "Rendered Claude chat",
    )
    messages = extract_claude_conversation_messages(_RenderedClaudePage(), conversation)
    store = ClaudeHistoryStore(tmp_path / "llm" / "claude" / "history.parquet")

    first = store.replace_conversation(conversation, messages, "2026-09-03T01:01:00Z")
    store.save()
    first_seen = store.rows[0]["first_seen_at"]
    second = store.replace_conversation(conversation, messages, "2026-09-03T02:01:00Z")

    assert first.added_or_changed == 2
    assert first.unchanged_messages == 0
    assert first.unchanged_sessions == 0
    assert second.added_or_changed == 0
    assert second.unchanged_messages == 2
    assert second.unchanged_sessions == 1
    assert store.rows[0]["first_seen_at"] == first_seen
    assert store.cached_conversations == 1
    assert store.cached_messages == 2

    snapshot = build_claude_initial_snapshot("v-test", tmp_path)
    assert snapshot.downloaded_posts == 1
    assert snapshot.downloaded_tweets == 2
    assert "Found existing Claude history" in snapshot.message


def test_claude_urls_use_the_shared_conversation_contract() -> None:
    assert claude_conversation_id("https://claude.ai/chat/chat-1?ignored=1") == "chat-1"
    assert claude_conversation_id("https://claude.ai/project/project-1/chat/chat-1") == "chat-1"
    assert claude_conversation_id("https://example.com/chat/chat-1") == ""


def test_claude_store_rejects_sessions_without_rendered_messages(tmp_path: Path) -> None:
    store = ClaudeHistoryStore(tmp_path / "history.parquet")
    conversation = ClaudeConversationLink("chat-1", "https://claude.ai/chat/chat-1", "Empty")

    with pytest.raises(ClaudeNoCacheableMessagesError):
        store.replace_conversation(conversation, [], "2026-09-03T01:01:00Z")
