"""Focused tests for ChatGPT project image caching."""

# Code version: v1.0.3-codex.1

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from app.core.browser_sessions import probe_browser_session
from app.core.chatgpt_downloader import (
    ChatGPTImageCandidate,
    ChatGPTImageCatalog,
    chatgpt_target_dir,
    collect_conversation_images,
    collect_project_conversation_urls,
    download_chatgpt_image,
    extract_chatgpt_file_id,
    infer_image_extension,
    is_chatgpt_conversation_url,
    looks_like_image,
    reset_chatgpt_state,
    should_cache_chatgpt_candidate,
    sync_chatgpt_images,
)
from app.core.config import CrawlConfig, DEFAULT_CHATGPT_PROJECT_NAME, DEFAULT_CHATGPT_PROJECT_URL
from app.core.state import TaskState


PNG_PAYLOAD = b"\x89PNG\r\n\x1a\n" + (b"cachelikes" * 8)


class _FakeResponse:
    ok = True
    status = 200
    headers = {"content-type": "image/png"}

    def body(self) -> bytes:
        return PNG_PAYLOAD


class _FakeRequest:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs) -> _FakeResponse:
        self.urls.append(url)
        return _FakeResponse()


class _FakeContext:
    def __init__(self) -> None:
        self.request = _FakeRequest()


def test_chatgpt_url_helpers_accept_original_estuary_assets() -> None:
    source_url = (
        "https://chatgpt.com/backend-api/estuary/content?"
        "id=file_0000000090648211ba8e0181b729f6b1&ts=496144&p=fs"
    )

    assert extract_chatgpt_file_id(source_url) == "file_0000000090648211ba8e0181b729f6b1"
    assert infer_image_extension(source_url, "image/png; charset=binary") == ".png"
    assert infer_image_extension(source_url, "image/png", b"\xff\xd8\xfflegacy-jpeg") == ".jpg"
    assert looks_like_image(PNG_PAYLOAD)
    assert not looks_like_image(b"<html>not an image</html>")
    assert chatgpt_target_dir(DEFAULT_CHATGPT_PROJECT_NAME).name == DEFAULT_CHATGPT_PROJECT_NAME


def test_chatgpt_keeps_original_images_from_every_message_role() -> None:
    base = {
        "source_url": "https://chatgpt.com/backend-api/estuary/content?id=file_role",
        "file_id": "file_role",
        "conversation_url": "https://chatgpt.com/g/project/c/role",
    }

    assert should_cache_chatgpt_candidate(ChatGPTImageCandidate(**base, message_role="user"))
    assert should_cache_chatgpt_candidate(ChatGPTImageCandidate(**base, message_role="assistant"))
    assert should_cache_chatgpt_candidate(ChatGPTImageCandidate(**base))

    known_upload = dict(base, file_id="file_000000000e6471fd89cf0af9b5bd16e5")
    assert should_cache_chatgpt_candidate(ChatGPTImageCandidate(**known_upload, message_role="user"))
    assert not should_cache_chatgpt_candidate(ChatGPTImageCandidate(**dict(base, source_url="")))


def test_chatgpt_catalog_registers_downloads_and_skips_complete_files(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_demo",
        file_id="file_demo",
        conversation_url=DEFAULT_CHATGPT_PROJECT_URL.replace("/project", "/c/demo"),
        alt_text="A generated image",
        width=1_024,
        height=1_536,
        message_role="assistant",
    )
    context = _FakeContext()
    catalog = ChatGPTImageCatalog.build(target_dir)

    assert download_chatgpt_image(context, catalog, target_dir, candidate)
    assert not download_chatgpt_image(context, catalog, target_dir, candidate)
    assert len(context.request.urls) == 1
    assert catalog.summarize() == 1

    reloaded = ChatGPTImageCatalog.build(target_dir)
    entry = reloaded.entries_by_file_id["file_demo"]
    assert reloaded.complete_entry("file_demo") == entry
    assert (target_dir / entry.relative_path).read_bytes() == PNG_PAYLOAD


def test_chatgpt_reset_removes_only_the_dedicated_cache(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_reset",
        file_id="file_reset",
        conversation_url="https://chatgpt.com/g/project/c/reset",
        message_role="assistant",
    )
    catalog = ChatGPTImageCatalog.build(target_dir)
    download_chatgpt_image(_FakeContext(), catalog, target_dir, candidate)
    partial_dir = target_dir / ".chatgpt-partial"
    partial_dir.mkdir(exist_ok=True)
    (partial_dir / "orphan.part").write_bytes(b"partial")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    result = reset_chatgpt_state(target_dir=target_dir)

    assert result.removed_media_files == 1
    assert result.removed_state_files == 1
    assert result.removed_partial_files == 1
    assert not target_dir.exists() or not any(target_dir.iterdir())
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_chatgpt_browser_probe_requires_a_chatgpt_project_url() -> None:
    ready = probe_browser_session("chatgpt", "edge", CrawlConfig())
    assert ready["can_download"] is True
    assert ready["account_name"] == DEFAULT_CHATGPT_PROJECT_NAME
    assert "background browser session" in ready["message"]

    invalid = probe_browser_session(
        "chatgpt",
        "edge",
        CrawlConfig(chatgpt_project_url="https://example.com/project"),
    )
    assert invalid["can_download"] is False
    assert "https://chatgpt.com/" in invalid["message"]


def test_chatgpt_accepts_a_single_chat_session_url() -> None:
    session_url = "https://chatgpt.com/g/g-p-demo-project/c/conversation-123"

    assert is_chatgpt_conversation_url(session_url)
    assert is_chatgpt_conversation_url("https://chatgpt.com/c/conversation-123?oai-dm=1")
    assert not is_chatgpt_conversation_url(DEFAULT_CHATGPT_PROJECT_URL)
    assert not is_chatgpt_conversation_url("https://example.com/c/conversation-123")


def test_chatgpt_uses_a_single_chat_session_without_scanning_a_project() -> None:
    session_url = "https://chatgpt.com/c/conversation-123"
    state = TaskState("test")

    with patch("app.core.chatgpt_downloader.open_chatgpt_page") as open_page:
        conversation_urls = collect_project_conversation_urls(
            object(),
            session_url,
            state,
            should_stop=lambda: False,
        )

    assert conversation_urls == [session_url]
    open_page.assert_not_called()


class _ClosableBrowserContext:
    def new_page(self) -> object:
        return object()

    def close(self) -> None:
        pass


def test_chatgpt_sync_launches_edge_offscreen_with_a_rendered_window(tmp_path: Path) -> None:
    state = TaskState("test")
    browser_context = _ClosableBrowserContext()

    with patch(
        "app.core.chatgpt_downloader.sync_playwright",
        return_value=nullcontext(object()),
    ), patch(
        "app.core.chatgpt_downloader.launch_chromium_context",
        return_value=nullcontext(browser_context),
    ) as launch_context, patch(
        "app.core.chatgpt_downloader.collect_project_conversation_urls",
        return_value=[],
    ):
        result = sync_chatgpt_images(
            state,
            config=CrawlConfig(),
            target_dir=tmp_path / "chatgpt" / DEFAULT_CHATGPT_PROJECT_NAME,
        )

    assert result.discovered_conversations == 0
    assert launch_context.call_args.kwargs["headless"] is False
    assert launch_context.call_args.kwargs["background_window"] is True


class _ConversationPage:
    def __init__(self) -> None:
        self.waits: list[int] = []

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


def test_chatgpt_scans_the_nested_message_view_in_both_directions() -> None:
    page = _ConversationPage()
    directions: list[str] = []
    raw_candidate = {
        "sourceUrl": "https://chatgpt.com/backend-api/estuary/content?id=file_user_image",
        "fileId": "file_user_image",
        "messageRole": "user",
    }

    def scroll_message_view(_page, direction: str) -> dict[str, object]:
        directions.append(direction)
        return {"height": 1_200, "atBoundary": True, "moved": False}

    with patch("app.core.chatgpt_downloader.open_chatgpt_page"), patch(
        "app.core.chatgpt_downloader._extract_original_image_payloads",
        return_value=[raw_candidate],
    ), patch(
        "app.core.chatgpt_downloader._scroll_chatgpt_message_view",
        side_effect=scroll_message_view,
    ):
        candidates = collect_conversation_images(
            page,
            "https://chatgpt.com/c/conversation-123",
            should_stop=lambda: False,
        )

    assert [candidate.file_id for candidate in candidates] == ["file_user_image"]
    assert set(directions) == {"top", "bottom"}
    assert page.waits
