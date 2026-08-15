"""Focused tests for the Agent's ChatGPT Web source catalog.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

from contextlib import nullcontext
import json
from unittest.mock import patch

from app.core.chatgpt_agent_sources import (
    _collect_projects,
    _collect_projects_from_api,
    _collect_root_sessions,
    _conversation_history_items,
    _conversation_item,
    _fetch_conversation_history,
    normalize_chatgpt_conversation_url,
    normalize_chatgpt_project_url,
    probe_and_collect_chatgpt_sources,
)
from app.core.config import CrawlConfig


class _Response:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.ok = status < 400
        self.status = status
        self._payload = payload

    def text(self) -> str:
        import json

        return json.dumps(self._payload)


class _Request:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses

    def get(self, url: str, **_kwargs) -> _Response:
        for marker, payload in self.responses.items():
            if marker in url:
                return _Response(payload)
        return _Response({}, status=404)


class _Context:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.request = _Request(responses)


class _Page:
    def evaluate(self, _script: str):
        return []


class _BootstrapPage:
    def __init__(self) -> None:
        self.waits: list[int] = []

    def goto(self, *_args, **_kwargs) -> None:
        return None

    def evaluate(self, _script: str) -> dict[str, object]:
        return {
            "ok": True,
            "status": 200,
            "bodyText": json.dumps({"accessToken": "fixture-token"}),
            "error": "",
        }

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


class _BootstrapContext:
    def __init__(self, page: _BootstrapPage) -> None:
        self.pages = [page]


def test_chatgpt_source_urls_are_canonical_and_scoped() -> None:
    assert normalize_chatgpt_project_url(
        "https://www.chatgpt.com/g/g-p-demo/project/?utm_source=agent"
    ) == "https://chatgpt.com/g/g-p-demo/project"
    assert normalize_chatgpt_conversation_url(
        "https://www.chatgpt.com/g/g-p-demo/c/session-1?oai-dm=1"
    ) == "https://chatgpt.com/g/g-p-demo/c/session-1"
    assert normalize_chatgpt_project_url("https://chatgpt.com/c/not-a-project") == ""
    assert normalize_chatgpt_conversation_url("https://example.com/c/session-1") == ""


def test_chatgpt_status_and_sources_share_one_chromium_context() -> None:
    page = _BootstrapPage()
    context = _BootstrapContext(page)
    source_payload = {
        "browser_label": "Edge",
        "recent_sessions": [{"id": "recent-1"}],
        "projects": [],
        "limit": 20,
    }
    with patch(
        "app.core.chatgpt_agent_sources.sync_playwright_or_error",
        return_value=nullcontext(object()),
    ) as playwright_factory, patch(
        "app.core.chatgpt_agent_sources.launch_chromium_context",
        return_value=nullcontext(context),
    ) as launch_context, patch(
        "app.core.chatgpt_agent_sources._collect_sources",
        return_value=source_payload,
    ) as collect_sources:
        status, sources = probe_and_collect_chatgpt_sources("edge", CrawlConfig())

    assert status["can_download"] is True
    assert sources == {**source_payload, "platform": "chatgpt"}
    playwright_factory.assert_called_once()
    launch_context.assert_called_once()
    collect_sources.assert_called_once_with(context, page, "Edge")


def test_root_sessions_filter_project_sessions_and_limit_to_twenty() -> None:
    items = [
        {"id": "root-1", "title": "Root session", "update_time": "2026-08-13T10:00:00Z"},
        {"id": "project-1", "title": "Project session", "gizmo_id": "g-p-demo"},
    ]
    context = _Context({"/backend-api/conversations": {"items": items}})

    sessions = _collect_root_sessions(context, {"authorization": "Bearer test"})

    assert sessions == [
        {
            "id": "root-1",
            "title": "Root session",
            "url": "https://chatgpt.com/c/root-1",
            "updated_at": "2026-08-13T10:00:00Z",
        }
    ]


def test_project_api_parser_supports_nested_gizmo_items() -> None:
    context = _Context(
        {
            "/backend-api/gizmos": {
                "items": [
                    {
                        "gizmo": {
                            "id": "g-p-demo-project",
                            "name": "Demo project",
                            "updated_at": "2026-08-13T09:00:00Z",
                        }
                    }
                ]
            }
        }
    )

    projects = _collect_projects_from_api(context, {"authorization": "Bearer test"})

    assert projects == [
        {
            "id": "g-p-demo-project",
            "title": "Demo project",
            "url": "https://chatgpt.com/g/g-p-demo-project/project",
            "updated_at": "2026-08-13T09:00:00Z",
        }
    ]


def test_project_api_parser_supports_sidebar_resource_records() -> None:
    context = _Context(
        {
            "/backend-api/gizmos/snorlax/sidebar": {
                "items": [
                    {
                        "gizmo": {
                            "gizmo": {
                            "id": "g-p-11111111111111111111111111111111",
                            "short_url": "g-p-11111111111111111111111111111111-sidebar-project",
                                "display": {"name": "Sidebar project"},
                                "last_interacted_at": "2026-08-13T11:00:00Z",
                            },
                            "conversations": {"items": []},
                        }
                    }
                ]
            }
        }
    )

    projects = _collect_projects(context, _Page(), {"authorization": "Bearer test"})

    assert projects == [
        {
            "id": "g-p-11111111111111111111111111111111",
            "title": "Sidebar project",
            "url": "https://chatgpt.com/g/g-p-11111111111111111111111111111111-sidebar-project/project",
            "updated_at": "2026-08-13T11:00:00Z",
        }
    ]


def test_conversation_item_can_build_project_session_url() -> None:
    assert _conversation_item(
        {"id": "session-1", "title": "Project chat"},
        "https://chatgpt.com/g/g-p-demo-project/c/",
    )["url"] == "https://chatgpt.com/g/g-p-demo-project/c/session-1"


def test_conversation_history_pairs_ordered_user_and_assistant_messages() -> None:
    history = _conversation_history_items(
        [
            {
                "message_index": 2,
                "role": "assistant",
                "content_text": "The first answer.",
                "last_seen_at": "2026-08-14T01:02:00Z",
            },
            {
                "message_index": 1,
                "role": "user",
                "content_text": "The first question.",
                "last_seen_at": "2026-08-14T01:01:00Z",
            },
            {
                "message_index": 4,
                "role": "assistant",
                "content_text": "The second answer.",
                "last_seen_at": "2026-08-14T01:04:00Z",
            },
            {
                "message_index": 3,
                "role": "user",
                "content_text": "The second question.",
                "last_seen_at": "2026-08-14T01:03:00Z",
            },
        ]
    )

    assert history == [
        {
            "prompt": "The first question.",
            "response": "The first answer.",
            "started_at": "2026-08-14T01:01:00Z",
            "finished_at": "2026-08-14T01:02:00Z",
        },
        {
            "prompt": "The second question.",
            "response": "The second answer.",
            "started_at": "2026-08-14T01:03:00Z",
            "finished_at": "2026-08-14T01:04:00Z",
        },
    ]


def test_fetch_conversation_history_reads_authenticated_mapping_without_persistence() -> None:
    context = _Context(
        {
            "/api/auth/session": {"accessToken": "fixture-token"},
            "/backend-api/conversation/fixture-session": {
                "title": "Fixture session",
                "current_node": "assistant-node",
                "mapping": {
                    "root": {"message": None, "parent": None},
                    "user-node": {
                        "parent": "root",
                        "message": {
                            "author": {"role": "user"},
                            "content": {"parts": ["Check the fonts"]},
                            "create_time": "2026-08-14T01:01:00Z",
                        }
                    },
                    "assistant-node": {
                        "parent": "user-node",
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {"parts": ["The font stack is configured"]},
                            "create_time": "2026-08-14T01:02:00Z",
                        }
                    },
                    "alternate-assistant-node": {
                        "parent": "user-node",
                        "message": {
                            "author": {"role": "assistant"},
                            "content": {"parts": ["An alternate answer"]},
                            "create_time": "2026-08-14T01:03:00Z",
                        }
                    },
                },
            },
        }
    )

    payload = _fetch_conversation_history(context, "https://chatgpt.com/c/fixture-session")

    assert payload["title"] == "Fixture session"
    assert payload["history"] == [
        {
            "prompt": "Check the fonts",
            "response": "The font stack is configured",
            "started_at": "2026-08-14T01:01:00Z",
            "finished_at": "2026-08-14T01:02:00Z",
        }
    ]
