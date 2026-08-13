"""Focused tests for Grok text-history persistence and API pagination."""

# Code version: v1.0.0-codex.1

from pathlib import Path

from app.core.chat_history_browser import query_chat_history
from app.core.grok_history import (
    GrokConversation,
    GrokHistoryStore,
    GrokTextMessage,
    list_grok_conversations,
)


def _message(key: str, role: str, index: int, content: str) -> GrokTextMessage:
    return GrokTextMessage(
        message_key=key,
        platform="grok",
        conversation_id="conversation-1",
        conversation_title="Test session",
        conversation_url="https://grok.com/c/conversation-1",
        role=role,
        author_label="You" if role == "user" else "Grok",
        content_text=content,
        content_html="",
        timestamp=f"2026-08-13T00:0{index}:00Z",
        turn_index=index + 1 if role == "user" else index,
        message_index=index,
        model_label="grok-4" if role == "assistant" else "",
        source_links=(),
        content_sha256=f"sha-{key}",
    )


def test_grok_history_store_round_trips_and_preserves_first_seen(tmp_path: Path) -> None:
    """Keep stable rows and update only their latest observation timestamp."""
    path = tmp_path / "llm" / "grok" / "history.parquet"
    conversation = GrokConversation(
        "conversation-1",
        "Test session",
        "2026-08-13T00:00:00Z",
        "2026-08-13T00:01:00Z",
        "https://grok.com/c/conversation-1",
    )
    store = GrokHistoryStore(path)
    first = store.replace_conversation(
        conversation,
        [_message("conversation-1:r1", "user", 0, "hello")],
        "2026-08-13T00:02:00Z",
    )
    second = store.replace_conversation(
        conversation,
        [_message("conversation-1:r1", "user", 0, "hello")],
        "2026-08-13T00:03:00Z",
    )

    assert first.added_or_changed == 1
    assert second.added_or_changed == 0
    assert second.unchanged == 1
    page = query_chat_history(tmp_path, source="grok", session_view=True)
    assert page.total_count == 1
    assert page.sessions[0].conversation_title == "Test session"
    assert page.items[0].content_text == "hello"


def test_grok_history_is_included_in_all_source_queries(tmp_path: Path) -> None:
    """Make the Local resources all-sources view include Grok rows."""
    path = tmp_path / "llm" / "grok" / "history.parquet"
    conversation = GrokConversation(
        "conversation-1",
        "Test session",
        "",
        "",
        "https://grok.com/c/conversation-1",
    )
    GrokHistoryStore(path).replace_conversation(
        conversation,
        [_message("conversation-1:r1", "assistant", 0, "answer")],
        "2026-08-13T00:02:00Z",
    )

    page = query_chat_history(tmp_path, source="all")
    assert page.total_count == 1
    assert page.items[0].source == "grok"


def test_grok_conversation_pagination_uses_page_token(monkeypatch) -> None:
    """Follow Grok's nextPageToken with the pageToken request parameter."""
    calls: list[str] = []

    def fake_api(_page, path: str, **_kwargs):
        calls.append(path)
        if "pageToken=next-token" in path:
            return {
                "conversations": [
                    {
                        "conversationId": "conversation-2",
                        "title": "Second",
                    }
                ]
            }
        return {
            "conversations": [
                {
                    "conversationId": "conversation-1",
                    "title": "First",
                }
            ],
            "nextPageToken": "next-token",
        }

    monkeypatch.setattr("app.core.grok_history._grok_api_json", fake_api)
    conversations = list_grok_conversations(object())

    assert [item.conversation_id for item in conversations] == [
        "conversation-1",
        "conversation-2",
    ]
    assert "pageToken=next-token" in calls[1]
