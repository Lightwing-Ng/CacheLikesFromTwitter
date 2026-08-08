"""Focused tests for ChatGPT project image caching."""

# Code version: v1.0.1-codex.1

from __future__ import annotations

from pathlib import Path

from app.core.browser_sessions import probe_browser_session
from app.core.chatgpt_downloader import (
    ChatGPTImageCandidate,
    ChatGPTImageCatalog,
    chatgpt_target_dir,
    download_chatgpt_image,
    extract_chatgpt_file_id,
    infer_image_extension,
    looks_like_image,
    reset_chatgpt_state,
    should_cache_chatgpt_candidate,
)
from app.core.config import CrawlConfig, DEFAULT_CHATGPT_PROJECT_NAME, DEFAULT_CHATGPT_PROJECT_URL


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


def test_chatgpt_skips_user_uploaded_images_but_keeps_assistant_images() -> None:
    base = {
        "source_url": "https://chatgpt.com/backend-api/estuary/content?id=file_role",
        "file_id": "file_role",
        "conversation_url": "https://chatgpt.com/g/project/c/role",
    }

    assert not should_cache_chatgpt_candidate(ChatGPTImageCandidate(**base, message_role="user"))
    assert should_cache_chatgpt_candidate(ChatGPTImageCandidate(**base, message_role="assistant"))
    assert should_cache_chatgpt_candidate(ChatGPTImageCandidate(**base))


def test_chatgpt_catalog_registers_downloads_and_skips_complete_files(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_demo",
        file_id="file_demo",
        conversation_url=DEFAULT_CHATGPT_PROJECT_URL.replace("/project", "/c/demo"),
        alt_text="A generated image",
        width=1_024,
        height=1_536,
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
    assert "interactive Edge" in ready["message"]

    invalid = probe_browser_session(
        "chatgpt",
        "edge",
        CrawlConfig(chatgpt_project_url="https://example.com/project"),
    )
    assert invalid["can_download"] is False
    assert "https://chatgpt.com/" in invalid["message"]
