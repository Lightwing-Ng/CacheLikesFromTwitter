"""Focused tests for the provider-neutral Agent session source adapter.

Code version: v1.2.0-codex.1
"""

from __future__ import annotations

from unittest.mock import patch

from app.core.agent_session_sources import (
    _claude_page_status,
    _read_grok_project_links,
    _read_grok_project_session_links,
    list_agent_project_sessions,
    list_agent_sources,
    normalize_agent_conversation_url,
    normalize_agent_project_url,
)
from app.core.config import CrawlConfig
from app.core.gemini_downloader import GeminiConversationLink
from app.core.grok_history import GrokConversation


def test_agent_conversation_url_normalization_is_provider_specific() -> None:
    assert normalize_agent_conversation_url(
        "gemini",
        "https://gemini.google.com/app/session-1/?hl=en",
    ) == "https://gemini.google.com/app/session-1"
    assert normalize_agent_conversation_url(
        "grok",
        "https://www.grok.com/c/session-2/",
    ) == "https://grok.com/c/session-2"
    assert normalize_agent_conversation_url(
        "chatgpt",
        "https://www.chatgpt.com/c/session-3?messageId=ignored",
    ) == "https://chatgpt.com/c/session-3"
    assert normalize_agent_conversation_url("grok", "https://example.com/c/session") == ""
    assert normalize_agent_conversation_url(
        "grok",
        "https://grok.com/project/project-1?chat=session-1",
    ) == "https://grok.com/project/project-1?chat=session-1"
    assert normalize_agent_conversation_url(
        "claude",
        "https://www.claude.ai/chat/session-4/?utm_source=agent",
    ) == "https://claude.ai/chat/session-4"
    assert normalize_agent_conversation_url(
        "claude",
        "https://claude.ai/project/project-1/chat/session-4",
    ) == "https://claude.ai/project/project-1/chat/session-4"
    assert normalize_agent_conversation_url(
        "claude",
        "https://claude.ai/project/project-1?chat=session-4",
    ) == "https://claude.ai/project/project-1/chat/session-4"


def test_agent_project_url_normalization_hides_provider_specific_routes() -> None:
    assert normalize_agent_project_url(
        "chatgpt",
        "https://chatgpt.com/g/g-p-demo/project?tab=chat",
    ) == "https://chatgpt.com/g/g-p-demo/project"
    assert normalize_agent_project_url(
        "gemini",
        "https://gemini.google.com/notebook/notebook-1/?hl=en",
    ) == "https://gemini.google.com/notebook/notebook-1"
    assert normalize_agent_project_url(
        "grok",
        "https://www.grok.com/project/project-1?tab=conversations",
    ) == "https://grok.com/project/project-1?tab=conversations"
    assert normalize_agent_project_url(
        "claude",
        "https://www.claude.ai/project/project-1/?tab=chats",
    ) == "https://claude.ai/project/project-1"
    assert normalize_agent_project_url("grok", "https://example.com/project/project-1") == ""


def test_claude_sources_use_the_shared_chromium_source_collection() -> None:
    with patch(
        "app.core.agent_session_sources._run_chromium_source_collection",
        return_value={
            "recent_sessions": [
                {
                    "id": "claude-1",
                    "title": "Claude session",
                    "url": "https://claude.ai/chat/claude-1",
                }
            ],
            "projects": [
                {
                    "id": "project-1",
                    "title": "Claude project",
                    "url": "https://claude.ai/project/project-1",
                }
            ],
        },
    ) as collector:
        payload = list_agent_sources("claude", "edge", CrawlConfig())

    assert payload["platform"] == "claude"
    assert payload["recent_sessions"][0]["url"] == "https://claude.ai/chat/claude-1"
    assert payload["projects"][0]["url"] == "https://claude.ai/project/project-1"
    assert collector.call_args.args[:3] == ("edge", CrawlConfig(), "https://claude.ai/new")


def test_claude_status_exposes_account_restriction_without_attempting_login_bypass() -> None:
    class _Body:
        def inner_text(self, **_kwargs: object) -> str:
            return "Your account has been disabled for violating the usage policy."

    class _Page:
        def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

        def locator(self, selector: str) -> _Body:
            assert selector == "body"
            return _Body()

    status = _claude_page_status(_Page(), "Edge")

    assert status["can_download"] is False
    assert status["account_name"] == "Claude account restricted"
    assert "restricted or unavailable" in status["message"]


def test_gemini_sources_reuse_the_existing_history_link_collector() -> None:
    links = [
        GeminiConversationLink(
            conversation_id="gemini-1",
            url="https://gemini.google.com/app/gemini-1",
            title="Gemini session",
        )
    ]
    with patch(
        "app.core.agent_session_sources._run_chromium_source_collection",
        return_value=links,
    ) as collector:
        payload = list_agent_sources("gemini", "edge", CrawlConfig())

    assert payload["platform"] == "gemini"
    assert payload["projects"] == []
    assert payload["recent_sessions"] == [
        {
            "id": "gemini-1",
            "title": "Gemini session",
            "url": "https://gemini.google.com/app/gemini-1",
            "updated_at": "",
        }
    ]
    assert collector.call_args.args[0] == "edge"
    assert collector.call_args.args[1].gemini_max_conversations == 20
    assert collector.call_args.args[2] == "https://gemini.google.com/app"


def test_grok_sources_reuse_the_existing_authenticated_conversations_api() -> None:
    conversations = [
        GrokConversation(
            conversation_id="grok-1",
            title="Grok session",
            created_at="2026-08-14T01:00:00Z",
            updated_at="2026-08-14T02:00:00Z",
            url="https://grok.com/c/grok-1",
        )
    ]
    with patch(
        "app.core.agent_session_sources._run_chromium_source_collection",
        return_value=conversations,
    ) as collector:
        payload = list_agent_sources("grok", "chrome", CrawlConfig())

    assert payload["platform"] == "grok"
    assert payload["recent_sessions"][0] == {
        "id": "grok-1",
        "title": "Grok session",
        "url": "https://grok.com/c/grok-1",
        "updated_at": "2026-08-14T02:00:00Z",
    }
    assert collector.call_args.args[:3] == ("chrome", CrawlConfig(), "https://grok.com/")


def test_chatgpt_sources_still_use_the_existing_project_capable_adapter() -> None:
    existing_payload = {"recent_sessions": [], "projects": [{"url": "project"}]}
    with patch(
        "app.core.agent_session_sources.list_chatgpt_agent_sources",
        return_value=existing_payload,
    ) as sources:
        payload = list_agent_sources("chatgpt", "edge", CrawlConfig())

    assert payload == {**existing_payload, "platform": "chatgpt"}
    sources.assert_called_once()


def test_gemini_sources_expose_notebooks_as_shared_projects() -> None:
    with patch(
        "app.core.agent_session_sources._run_chromium_source_collection",
        return_value={
            "recent_sessions": [
                {
                    "conversation_id": "gemini-1",
                    "title": "Gemini session",
                    "url": "https://gemini.google.com/app/gemini-1",
                }
            ],
            "projects": [
                {
                    "id": "notebook-1",
                    "title": "Research notebook",
                    "url": "https://gemini.google.com/notebook/notebook-1",
                    "updated_at": "",
                }
            ],
        },
    ):
        payload = list_agent_sources("gemini", "edge", CrawlConfig())

    assert payload["projects"] == [
        {
            "id": "notebook-1",
            "title": "Research notebook",
            "url": "https://gemini.google.com/notebook/notebook-1",
            "updated_at": "",
        }
    ]


def test_grok_sources_expose_projects_as_shared_projects() -> None:
    with patch(
        "app.core.agent_session_sources._run_chromium_source_collection",
        return_value={
            "recent_sessions": [],
            "projects": [
                {
                    "id": "project-1",
                    "title": "Research project",
                    "url": "https://grok.com/project/project-1?tab=conversations",
                    "updated_at": "",
                }
            ],
        },
    ):
        payload = list_agent_sources("grok", "edge", CrawlConfig())

    assert payload["projects"][0]["url"] == "https://grok.com/project/project-1?tab=conversations"


def test_grok_project_reader_uses_playwright_controls_for_button_rows() -> None:
    class _Toggle:
        def count(self) -> int:
            return 1

        def is_visible(self) -> bool:
            return True

        def get_attribute(self, _name: str) -> str:
            return "false"

        def click(self, **_kwargs: object) -> None:
            return None

    class _Locator:
        def evaluate_all(self, _script: str) -> list[dict[str, object]]:
            return [{"index": 3, "label": "Research project New chat Options"}]

        def nth(self, _index: int) -> "_Locator":
            return self

        def click(self, **_kwargs: object) -> None:
            return None

    class _Page:
        def get_by_role(self, _role: str, *, name: str, exact: bool) -> _Toggle:
            assert name == "Projects"
            assert exact is True
            return _Toggle()

        def wait_for_timeout(self, _milliseconds: int) -> None:
            return None

        def locator(self, selector: str) -> _Locator:
            if selector == 'a[href*="/project/"]':
                return _LocatorWithRows()
            return _Locator()

    class _LocatorWithRows(_Locator):
        def evaluate_all(self, _script: str) -> list[dict[str, str]]:
            return [{
                "href": "https://grok.com/project/project-1?chat=session-1",
                "title": "Research project",
            }]

    assert _read_grok_project_links(_Page()) == [{
        "id": "project-1",
        "title": "Research project",
        "url": "https://grok.com/project/project-1?tab=conversations",
        "updated_at": "",
    }]


def test_grok_project_reader_prefers_workspace_repository_api() -> None:
    class _Page:
        def evaluate(self, _script: str, request: dict[str, object]) -> dict[str, object]:
            assert "/rest/workspaces?" in str(request["url"])
            return {
                "status": 200,
                "body": {
                    "workspaces": [
                        {
                            "workspaceId": "project-1",
                            "name": "Research project",
                            "lastUseTime": "2026-08-14T12:00:00Z",
                            "kind": "WORKSPACE_KIND_ALL",
                        },
                        {
                            "workspaceId": "imagine-1",
                            "name": "Generated images",
                            "kind": "WORKSPACE_KIND_IMAGINE",
                        },
                    ]
                },
            }

    assert _read_grok_project_links(_Page()) == [{
        "id": "project-1",
        "title": "Research project",
        "url": "https://grok.com/project/project-1?tab=conversations",
        "updated_at": "2026-08-14T12:00:00Z",
    }]


def test_grok_project_session_reader_uses_workspace_conversations_api() -> None:
    class _Page:
        def evaluate(self, _script: str, request: dict[str, object]) -> dict[str, object]:
            assert "workspaceId=project-1" in str(request["url"])
            return {
                "status": 200,
                "body": {
                    "conversations": [{
                        "conversationId": "session-1",
                        "title": "Research session",
                        "modifyTime": "2026-08-14T12:30:00Z",
                    }]
                },
            }

    assert _read_grok_project_session_links(
        _Page(),
        "https://grok.com/project/project-1?tab=conversations",
    ) == [{
        "id": "session-1",
        "title": "Research session",
        "url": "https://grok.com/project/project-1?chat=session-1",
        "updated_at": "2026-08-14T12:30:00Z",
    }]


def test_project_session_listing_uses_one_contract_for_gemini_and_grok() -> None:
    project_cases = (
        (
            "gemini",
            "https://gemini.google.com/notebook/notebook-1",
            "https://gemini.google.com/app/gemini-session",
        ),
        (
            "grok",
            "https://grok.com/project/project-1?tab=conversations",
            "https://grok.com/c/grok-session",
        ),
    )
    for platform, project_url, session_url in project_cases:
        with patch(
            "app.core.agent_session_sources._run_chromium_source_collection",
            return_value=[
                {
                    "id": "selected-session",
                    "title": "Selected session",
                    "url": session_url,
                    "updated_at": "",
                }
            ],
        ) as collector:
            payload = list_agent_project_sessions(platform, "edge", project_url, CrawlConfig())

        assert payload["platform"] == platform
        assert payload["project_url"] == project_url
        assert payload["sessions"][0]["url"] == session_url
        assert collector.call_args.args[2] == project_url


def test_chatgpt_project_session_listing_keeps_existing_adapter() -> None:
    with patch(
        "app.core.agent_session_sources.list_chatgpt_project_sessions",
        return_value={"project_url": "https://chatgpt.com/g/g-p-demo/project", "sessions": []},
    ) as sessions:
        payload = list_agent_project_sessions(
            "chatgpt",
            "edge",
            "https://chatgpt.com/g/g-p-demo/project",
            CrawlConfig(),
        )

    assert payload["platform"] == "chatgpt"
    sessions.assert_called_once()
