"""Focused tests for ChatGPT project image caching."""

# Code version: v1.13.0-codex.1

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest
from PIL import Image

from app.core.browser_sessions import probe_browser_session
from app.core.chatgpt_downloader import (
    ChatGPTImageSizeLimitError,
    ChatGPTImageCandidate,
    ChatGPTImageCatalog,
    ChatGPTCatalogEntry,
    chatgpt_target_dir,
    collect_chatgpt_project_index_images,
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
from app.core.chatgpt_downloader import (
    ChatGPTConversationWorkResult,
    ChatGPTImageDownloadWorkResult,
    PlaywrightError,
    _chatgpt_file_download_url,
    _chatgpt_project_id,
    _extract_chatgpt_conversation_image_payloads,
    _get_chatgpt_api_json,
    _is_unavailable_chatgpt_image_error,
    _is_retryable_chatgpt_image_error,
    _is_recoverable_chatgpt_page_error,
    _iter_chatgpt_index_image_results,
    _iter_chatgpt_conversation_results,
    _merge_current_conversation_images,
    _wait_for_project_conversation_links,
)
from app.core.config import CrawlConfig, DEFAULT_CHATGPT_PROJECT_NAME, DEFAULT_CHATGPT_PROJECT_URL
from app.core.state import TaskState


PNG_PAYLOAD = b"\x89PNG\r\n\x1a\n" + (b"cachelikes" * 8)


def _visual_test_image_payload(image_format: str, *, quality: int | None = None) -> bytes:
    """Create one deterministic image payload for visual-deduplication coverage."""
    image = Image.new("RGB", (128, 96))
    image.putdata(
        [
            ((column * 37 + row * 11) % 256, (column * 7 + row * 29) % 256, (column * 19 + row * 5) % 256)
            for row in range(image.height)
            for column in range(image.width)
        ]
    )
    output = BytesIO()
    save_options = {"quality": quality} if quality is not None else {}
    image.save(output, format=image_format, **save_options)
    return output.getvalue()


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
    assert _chatgpt_project_id(DEFAULT_CHATGPT_PROJECT_URL) == "g-p-69522aca2f788191b337866d5c03c59e"


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


def test_chatgpt_extracts_every_image_asset_from_the_current_conversation_branch() -> None:
    payload = {
        "current_node": "assistant-message",
        "mapping": {
            "user-message": {
                "parent": None,
                "message": {
                    "author": {"role": "user"},
                    "content": {
                        "parts": [
                            "**Keep the subject centered.**\n\n- Use soft studio light\n- Preserve the blue backdrop",
                            {
                                "asset_pointer": "file-service://file_user_original",
                                "content_type": "image/png",
                                "width": 1_024,
                                "height": 1_536,
                                "file_name": "user-reference.png",
                            },
                            {
                                "asset_pointer": "file-service://file_document",
                                "content_type": "application/pdf",
                            },
                        ]
                    },
                }
            },
            "assistant-message": {
                "parent": "user-message",
                "message": {
                    "author": {"role": "assistant"},
                    "content": {
                        "parts": [
                            {
                                "image_asset_pointer": "file-service://file_assistant_original",
                                "content_type": "image_asset_pointer",
                                "width": 1_536,
                                "height": 1_024,
                            },
                            {
                                "image_asset_pointer": "sediment://file_historical_missing",
                                "content_type": "image_asset_pointer",
                            }
                        ]
                    },
                }
            },
            "stale-branch-message": {
                "parent": "user-message",
                "message": {
                    "author": {"role": "assistant"},
                    "content": {
                        "parts": [
                            {
                                "asset_pointer": "sediment://file_stale_branch",
                                "content_type": "image_asset_pointer",
                            }
                        ]
                    },
                },
            },
        }
    }

    candidates = _extract_chatgpt_conversation_image_payloads(payload)

    assert {candidate["fileId"] for candidate in candidates} == {
        "file_user_original",
        "file_assistant_original",
    }
    by_file_id = {candidate["fileId"]: candidate for candidate in candidates}
    assert by_file_id["file_user_original"]["messageRole"] == "user"
    assert by_file_id["file_user_original"]["width"] == 1_024
    assert by_file_id["file_assistant_original"]["messageRole"] == "assistant"
    expected_prompt = "**Keep the subject centered.**\n\n- Use soft studio light\n- Preserve the blue backdrop"
    assert by_file_id["file_user_original"]["promptMarkdown"] == expected_prompt
    assert by_file_id["file_assistant_original"]["promptMarkdown"] == expected_prompt


def test_chatgpt_project_index_keeps_only_current_project_images() -> None:
    class _JsonResponse:
        ok = True
        status = 200

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def text(self) -> str:
            return json.dumps(self.payload)

    class _IndexRequest:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **_kwargs) -> _JsonResponse:
            self.urls.append(url)
            if "after=next-page" in url:
                return _JsonResponse(
                    {
                        "items": [
                            {
                                "conversation_id": "project-second",
                                "asset_pointer": "file-service://file_project_second",
                                "url": "https://chatgpt.com/backend-api/estuary/content?id=file_project_second&sig=two",
                                "width": 1_536,
                                "height": 1_024,
                                "created_at": 1_786_362_721.382649,
                            }
                        ]
                    }
                )
            return _JsonResponse(
                {
                    "items": [
                        {
                            "conversation_id": "different-project",
                            "asset_pointer": "file-service://file_other_project",
                            "url": "https://chatgpt.com/backend-api/estuary/content?id=file_other_project&sig=other",
                        },
                        {
                            "conversation_id": "project-first",
                            "asset_pointer": "file-service://file_project_first",
                            "url": "https://chatgpt.com/backend-api/estuary/content?id=file_project_first&sig=one",
                            "width": 1_024,
                            "height": 1_536,
                            "created_at": 1_786_362_700.25,
                        },
                    ],
                    "cursor": "next-page",
                }
            )

    class _IndexContext:
        def __init__(self) -> None:
            self.request = _IndexRequest()

    context = _IndexContext()
    request_headers = {"authorization": "Bearer test-token", "oai-device-id": "device-id"}
    candidates = collect_chatgpt_project_index_images(
        context,
        DEFAULT_CHATGPT_PROJECT_URL,
        [
            "https://chatgpt.com/g/g-p-69522aca2f788191b337866d5c03c59e-studio208cm/c/project-first",
            "https://chatgpt.com/g/g-p-69522aca2f788191b337866d5c03c59e-studio208cm/c/project-second",
        ],
        request_headers,
        TaskState("test"),
        should_stop=lambda: False,
    )

    assert {candidate.file_id for candidate in candidates} == {
        "file_project_first",
        "file_project_second",
    }
    assert all(candidate.request_headers == request_headers for candidate in candidates)
    assert {candidate.file_id: candidate.created_at for candidate in candidates} == {
        "file_project_first": "1786362700.25",
        "file_project_second": "1786362721.382649",
    }
    assert any("after=next-page" in url for url in context.request.urls)


def test_chatgpt_api_retries_transient_playwright_connection_errors() -> None:
    class _JsonResponse:
        ok = True
        status = 200

        @staticmethod
        def text() -> str:
            return '{"items": []}'

    class _RetryingRequest:
        def __init__(self) -> None:
            self.attempts = 0

        def get(self, _url: str, **_kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise PlaywrightError("socket hang up")
            return _JsonResponse()

    class _RetryingContext:
        def __init__(self) -> None:
            self.request = _RetryingRequest()

    context = _RetryingContext()
    with patch("app.core.chatgpt_downloader.time.sleep") as sleep:
        payload = _get_chatgpt_api_json(context, "https://chatgpt.com/backend-api/test", {})

    assert payload == {"items": []}
    assert context.request.attempts == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]


@pytest.mark.parametrize(
    "message",
    (
        "APIRequestContext.get: Client network socket disconnected before secure TLS connection was established",
        "APIRequestContext.get: socket hang up",
        "APIRequestContext.get: read ECONNRESET",
        "APIRequestContext.get: connect ETIMEDOUT",
    ),
)
def test_chatgpt_image_retries_platform_network_error_messages(message: str) -> None:
    assert _is_retryable_chatgpt_image_error(PlaywrightError(message))


def test_chatgpt_missing_image_assets_are_skipped_without_repeat_attempts(tmp_path: Path) -> None:
    catalog = ChatGPTImageCatalog.build(tmp_path / "chatgpt" / "Studio208cm")
    candidate = ChatGPTImageCandidate(
        source_url=_chatgpt_file_download_url("file_historical_missing"),
        file_id="file_historical_missing",
        conversation_url="https://chatgpt.com/c/project-conversation",
    )

    assert _is_unavailable_chatgpt_image_error(
        candidate,
        RuntimeError("ChatGPT file metadata request returned HTTP 404."),
    )
    direct_candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_historical_direct",
        file_id="file_historical_direct",
        conversation_url="https://chatgpt.com/c/project-conversation",
    )
    assert _is_unavailable_chatgpt_image_error(
        direct_candidate,
        RuntimeError("ChatGPT image request returned HTTP 404."),
    )
    catalog.mark_unavailable(candidate.file_id)
    assert not catalog.claim_download(candidate.file_id)


def test_chatgpt_resolves_api_assets_to_their_original_download_url(tmp_path: Path) -> None:
    file_id = "file_api_image"
    download_url = f"https://chatgpt.com/backend-api/estuary/content?id={file_id}&sig=temporary"

    class _DownloadMetadataResponse:
        ok = True
        status = 200

        def text(self) -> str:
            return json.dumps({"download_url": download_url})

    class _ResolvedImageResponse:
        ok = True
        status = 200
        headers = {"content-type": "image/png"}

        def body(self) -> bytes:
            return PNG_PAYLOAD

    class _ResolvingRequest:
        def __init__(self) -> None:
            self.requests: list[tuple[str, dict[str, object]]] = []

        def get(self, url: str, **kwargs):
            self.requests.append((url, kwargs))
            if url == _chatgpt_file_download_url(file_id):
                return _DownloadMetadataResponse()
            assert url == download_url
            return _ResolvedImageResponse()

    class _ResolvingContext:
        def __init__(self) -> None:
            self.request = _ResolvingRequest()

    candidate = ChatGPTImageCandidate(
        source_url=_chatgpt_file_download_url(file_id),
        file_id=file_id,
        conversation_url="https://chatgpt.com/c/conversation-api-image",
        request_headers={"authorization": "Bearer test-token", "oai-device-id": "device-id"},
    )
    context = _ResolvingContext()
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    catalog = ChatGPTImageCatalog.build(target_dir)

    assert download_chatgpt_image(context, catalog, target_dir, candidate)
    assert [request[0] for request in context.request.requests] == [
        _chatgpt_file_download_url(file_id),
        download_url,
    ]
    assert context.request.requests[0][1]["headers"]["authorization"] == "Bearer test-token"
    assert catalog.entries_by_file_id[file_id].source_url == download_url


def test_chatgpt_refreshes_an_expired_project_index_image_url(tmp_path: Path) -> None:
    file_id = "file_expired_index_image"
    direct_url = f"https://chatgpt.com/backend-api/estuary/content?id={file_id}&sig=expired"
    refreshed_url = f"https://chatgpt.com/backend-api/estuary/content?id={file_id}&sig=refreshed"
    conversation_url = "https://chatgpt.com/c/project-index-conversation"

    class _NotFoundResponse:
        ok = False
        status = 404

    class _DownloadMetadataResponse:
        ok = True
        status = 200

        def text(self) -> str:
            return json.dumps({"download_url": refreshed_url})

    class _ResolvedImageResponse:
        ok = True
        status = 200
        headers = {"content-type": "image/png"}

        def body(self) -> bytes:
            return PNG_PAYLOAD

    class _RefreshingRequest:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str, **_kwargs):
            self.urls.append(url)
            if url == direct_url:
                return _NotFoundResponse()
            if url == _chatgpt_file_download_url(file_id, conversation_url):
                return _DownloadMetadataResponse()
            assert url == refreshed_url
            return _ResolvedImageResponse()

    class _RefreshingContext:
        def __init__(self) -> None:
            self.request = _RefreshingRequest()

    candidate = ChatGPTImageCandidate(
        source_url=direct_url,
        file_id=file_id,
        conversation_url=conversation_url,
        request_headers={"authorization": "Bearer test-token", "oai-device-id": "device-id"},
    )
    context = _RefreshingContext()
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    catalog = ChatGPTImageCatalog.build(target_dir)

    assert download_chatgpt_image(context, catalog, target_dir, candidate)
    assert context.request.urls == [
        direct_url,
        _chatgpt_file_download_url(file_id, conversation_url),
        refreshed_url,
    ]
    assert catalog.entries_by_file_id[file_id].source_url == refreshed_url


def test_chatgpt_prefers_a_rendered_original_url_over_an_unresolved_api_asset() -> None:
    conversation_url = "https://chatgpt.com/c/conversation-direct-url"
    file_id = "file_direct_url"
    candidates_by_file_id = {
        file_id: ChatGPTImageCandidate(
            source_url=_chatgpt_file_download_url(file_id, conversation_url),
            file_id=file_id,
            conversation_url=conversation_url,
            width=2_048,
            height=2_048,
            request_headers={"authorization": "Bearer test-token"},
        )
    }
    raw_candidate = {
        "sourceUrl": f"https://chatgpt.com/backend-api/estuary/content?id={file_id}&sig=temporary",
        "fileId": file_id,
        "width": 1_024,
        "height": 1_024,
    }

    with patch("app.core.chatgpt_downloader._extract_original_image_payloads", return_value=[raw_candidate]):
        _merge_current_conversation_images(
            object(),
            conversation_url,
            candidates_by_file_id,
            "Conversation title",
        )

    assert candidates_by_file_id[file_id].source_url == raw_candidate["sourceUrl"]


def test_chatgpt_catalog_registers_downloads_and_skips_complete_files(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_demo",
        file_id="file_demo",
        conversation_url=DEFAULT_CHATGPT_PROJECT_URL.replace("/project", "/c/demo"),
        alt_text="A generated image",
        prompt_markdown="**Initial** prompt",
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
    refreshed_candidate = replace(
        candidate,
        conversation_title="A refreshed session",
        created_at="1786362721.382649",
        prompt_markdown="**Updated** prompt\n\n- Keep the pose",
    )
    assert catalog.update_metadata_batch((refreshed_candidate,)) == 1
    assert catalog.update_metadata_batch((refreshed_candidate,)) == 0

    reloaded = ChatGPTImageCatalog.build(target_dir)
    entry = reloaded.entries_by_file_id["file_demo"]
    assert reloaded.complete_entry("file_demo") == entry
    assert entry.conversation_title == "A refreshed session"
    assert entry.created_at == "1786362721.382649"
    assert entry.prompt_markdown == "**Updated** prompt\n\n- Keep the pose"
    assert (target_dir / entry.relative_path).read_bytes() == PNG_PAYLOAD


def test_chatgpt_skips_images_above_the_universal_cache_size_limit(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_oversized",
        file_id="file_oversized",
        conversation_url="https://chatgpt.com/c/oversized",
    )
    catalog = ChatGPTImageCatalog.build(target_dir)

    with pytest.raises(ChatGPTImageSizeLimitError, match="cache limit"):
        download_chatgpt_image(
            _FakeContext(),
            catalog,
            target_dir,
            candidate,
            max_file_size_bytes=len(PNG_PAYLOAD) - 1,
        )

    assert catalog.summarize() == 0
    assert not list(target_dir.glob("img_*"))


def test_chatgpt_catalog_removes_lower_quality_visual_duplicates(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    target_dir.mkdir(parents=True)
    high_content = _visual_test_image_payload("JPEG", quality=90)
    low_content = _visual_test_image_payload("JPEG", quality=20)
    assert len(high_content) > len(low_content)
    high_path = target_dir / "img_high.jpg"
    low_path = target_dir / "img_low.jpg"
    high_path.write_bytes(high_content)
    low_path.write_bytes(low_content)
    conversation_url = "https://chatgpt.com/g/project/c/visual-duplicate"
    catalog = ChatGPTImageCatalog(
        target_dir,
        {
            "file-high": ChatGPTCatalogEntry(
                file_id="file-high",
                relative_path=high_path.name,
                content_sha256="high",
                content_bytes=len(high_content),
                source_url="https://chatgpt.com/backend-api/estuary/content?id=file-high",
                conversation_url=conversation_url,
                alt_text="High quality copy",
                width=0,
                height=0,
                first_seen_at="2026-08-10T00:00:00Z",
                last_seen_at="2026-08-10T00:00:00Z",
            ),
            "file-low": ChatGPTCatalogEntry(
                file_id="file-low",
                relative_path=low_path.name,
                content_sha256="low",
                content_bytes=len(low_content),
                source_url="https://chatgpt.com/backend-api/estuary/content?id=file-low",
                conversation_url=conversation_url,
                alt_text="Citation thumbnail",
                width=0,
                height=0,
                first_seen_at="2026-08-10T00:00:00Z",
                last_seen_at="2026-08-10T00:00:00Z",
            ),
        },
    )

    result = catalog.deduplicate_visual_duplicates()

    assert result.removed_file_ids == ("file-low",)
    assert result.reclaimed_bytes == len(low_content)
    assert high_path.exists()
    assert not low_path.exists()
    assert set(catalog.entries_by_file_id) == {"file-high"}


def test_chatgpt_catalog_does_not_keep_an_incoming_lower_quality_duplicate(tmp_path: Path) -> None:
    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    target_dir.mkdir(parents=True)
    high_content = _visual_test_image_payload("JPEG", quality=90)
    low_content = _visual_test_image_payload("JPEG", quality=20)
    assert len(high_content) > len(low_content)
    high_path = target_dir / "img_high.jpg"
    low_path = target_dir / "img_low.jpg"
    high_path.write_bytes(high_content)
    low_path.write_bytes(low_content)
    conversation_url = "https://chatgpt.com/g/project/c/visual-duplicate"
    catalog = ChatGPTImageCatalog.build(target_dir)
    high_candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file-high",
        file_id="file-high",
        conversation_url=conversation_url,
    )
    low_candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file-low",
        file_id="file-low",
        conversation_url=conversation_url,
    )

    assert catalog.register_download(
        high_candidate,
        high_path.name,
        "high",
        len(high_content),
        "2026-08-10T00:00:00Z",
    )
    assert not catalog.register_download(
        low_candidate,
        low_path.name,
        "low",
        len(low_content),
        "2026-08-10T00:00:01Z",
    )
    assert high_path.exists()
    assert not low_path.exists()
    assert set(catalog.entries_by_file_id) == {"file-high"}


def test_chatgpt_retries_a_transient_direct_image_failure(tmp_path: Path) -> None:
    class _TransientResponse:
        ok = False
        status = 503
        headers: dict[str, str] = {}

    class _RetryRequest:
        def __init__(self) -> None:
            self.urls: list[str] = []
            self.responses = [_TransientResponse(), _FakeResponse()]

        def get(self, url: str, **_kwargs):
            self.urls.append(url)
            return self.responses.pop(0)

    class _RetryContext:
        def __init__(self) -> None:
            self.request = _RetryRequest()

    target_dir = tmp_path / "chatgpt" / "Studio208cm"
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_retry",
        file_id="file_retry",
        conversation_url="https://chatgpt.com/g/project/c/retry",
    )
    context = _RetryContext()
    catalog = ChatGPTImageCatalog.build(target_dir)

    with patch("app.core.chatgpt_downloader.time.sleep") as sleep:
        assert download_chatgpt_image(context, catalog, target_dir, candidate)

    assert len(context.request.urls) == 2
    sleep.assert_called_once_with(0.5)
    assert catalog.summarize() == 1


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


def test_chatgpt_sync_uses_the_project_image_index_without_legacy_page_scans(tmp_path: Path) -> None:
    state = TaskState("test")
    browser_context = _ClosableBrowserContext()
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_index_only",
        file_id="file_index_only",
        conversation_url="https://chatgpt.com/c/project-index-only",
    )

    with patch(
        "app.core.chatgpt_downloader.sync_playwright",
        return_value=nullcontext(object()),
    ), patch(
        "app.core.chatgpt_downloader.launch_chromium_context",
        return_value=nullcontext(browser_context),
    ), patch(
        "app.core.chatgpt_downloader.collect_project_conversation_urls",
        return_value=[candidate.conversation_url],
    ), patch(
        "app.core.chatgpt_downloader.collect_chatgpt_project_index_images",
        return_value=[candidate],
    ), patch(
        "app.core.chatgpt_downloader._iter_chatgpt_index_image_results",
        return_value=iter([ChatGPTImageDownloadWorkResult(candidate.file_id, skipped=True)]),
    ), patch("app.core.chatgpt_downloader._iter_chatgpt_conversation_results") as conversation_results:
        result = sync_chatgpt_images(
            state,
            config=CrawlConfig(),
            target_dir=tmp_path / "chatgpt" / DEFAULT_CHATGPT_PROJECT_NAME,
        )

    assert result.discovered_conversations == 1
    assert result.discovered_images == 1
    snapshot = state.snapshot()
    assert snapshot["queued_tweets"] == 1
    assert snapshot["processed_tweets"] == 1
    assert snapshot["progress_unit"] == "images"
    conversation_results.assert_not_called()


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
            scan_wait_seconds=0.2,
        )

    assert [candidate.file_id for candidate in candidates] == ["file_user_image"]
    assert set(directions) == {"top", "bottom"}
    assert page.waits
    assert set(page.waits) == {200}


def test_chatgpt_recycles_tabs_after_recoverable_page_failures() -> None:
    assert _is_recoverable_chatgpt_page_error(RuntimeError("Page crashed"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("frame was detached"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("ERR_ABORTED"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("net::ERR_SSL_BAD_RECORD_MAC_ALERT"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("net::ERR_SSL_VERSION_OR_CIPHER_MISMATCH"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("net::ERR_CONNECTION_RESET"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("chrome-error://chromewebdata/"))
    assert _is_recoverable_chatgpt_page_error(RuntimeError("ChatGPT startup timed out after 60 seconds"))
    assert not _is_recoverable_chatgpt_page_error(RuntimeError("HTTP 403"))


def test_chatgpt_parallel_iterator_partitions_conversations_across_bounded_workers(tmp_path: Path) -> None:
    assignments_seen: list[list[int]] = []

    def fake_worker(
        assignments,
        _descriptor,
        _catalog,
        _target_dir,
        _startup_timeout_seconds,
        _scan_wait_seconds,
        _should_stop,
        result_queue,
    ) -> None:
        assignments_seen.append([index for index, _url in assignments])
        for index, url in assignments:
            result_queue.put(ChatGPTConversationWorkResult(index, url))

    urls = [f"https://chatgpt.com/c/conversation-{index}" for index in range(5)]
    with patch("app.core.chatgpt_downloader._chatgpt_conversation_worker", side_effect=fake_worker):
        results = list(
            _iter_chatgpt_conversation_results(
                urls,
                object(),
                ChatGPTImageCatalog.build(tmp_path / "Studio208cm"),
                tmp_path / "Studio208cm",
                60,
                0.5,
                lambda: False,
                worker_count=3,
            )
        )

    assert sorted(result.conversation_index for result in results) == [1, 2, 3, 4, 5]
    assert len(assignments_seen) == 3
    assert sorted(index for assignment in assignments_seen for index in assignment) == [1, 2, 3, 4, 5]


def test_chatgpt_project_index_iterator_partitions_direct_image_downloads(tmp_path: Path) -> None:
    assignments_seen: list[list[str]] = []

    def fake_worker(candidates, _descriptor, _catalog, _target_dir, _should_stop, result_queue) -> None:
        assignments_seen.append([candidate.file_id for candidate in candidates])
        for candidate in candidates:
            result_queue.put(ChatGPTImageDownloadWorkResult(candidate.file_id, downloaded=True))

    candidates = [
        ChatGPTImageCandidate(
            source_url=f"https://chatgpt.com/backend-api/estuary/content?id=file_index_{index}",
            file_id=f"file_index_{index}",
            conversation_url="https://chatgpt.com/c/project-conversation",
        )
        for index in range(5)
    ]
    with patch("app.core.chatgpt_downloader._chatgpt_index_image_worker", side_effect=fake_worker):
        results = list(
            _iter_chatgpt_index_image_results(
                candidates,
                object(),
                ChatGPTImageCatalog.build(tmp_path / "Studio208cm"),
                tmp_path / "Studio208cm",
                lambda: False,
                worker_count=3,
            )
        )

    assert {result.candidate_file_id for result in results} == {candidate.file_id for candidate in candidates}
    assert len(assignments_seen) == 3
    assert {file_id for assignment in assignments_seen for file_id in assignment} == {
        candidate.file_id for candidate in candidates
    }


def test_chatgpt_project_index_iterator_bounds_worker_cleanup_wait(tmp_path: Path) -> None:
    release_worker = Event()
    candidate = ChatGPTImageCandidate(
        source_url="https://chatgpt.com/backend-api/estuary/content?id=file_index_cleanup",
        file_id="file_index_cleanup",
        conversation_url="https://chatgpt.com/c/project-conversation",
    )

    def lingering_worker(candidates, _descriptor, _catalog, _target_dir, _should_stop, result_queue) -> None:
        result_queue.put(ChatGPTImageDownloadWorkResult(candidates[0].file_id, downloaded=True))
        release_worker.wait(timeout=1)

    try:
        with patch(
            "app.core.chatgpt_downloader._chatgpt_index_image_worker",
            side_effect=lingering_worker,
        ), patch(
            "app.core.chatgpt_downloader.CHATGPT_WORKER_JOIN_TIMEOUT_SECONDS",
            0.01,
        ):
            results = list(
                _iter_chatgpt_index_image_results(
                    [candidate],
                    object(),
                    ChatGPTImageCatalog.build(tmp_path / "Studio208cm"),
                    tmp_path / "Studio208cm",
                    lambda: False,
                    worker_count=1,
                )
            )
    finally:
        release_worker.set()

    assert [result.candidate_file_id for result in results] == [candidate.file_id]


def test_chatgpt_project_startup_timeout_is_explicit() -> None:
    class _ProjectPage:
        def wait_for_timeout(self, _milliseconds: int) -> None:
            pass

    with patch(
        "app.core.chatgpt_downloader._extract_project_links",
        return_value=[],
    ), patch(
        "app.core.chatgpt_downloader._has_load_more_conversations",
        return_value=False,
    ):
        with pytest.raises(RuntimeError, match="after 1 seconds"):
            _wait_for_project_conversation_links(
                _ProjectPage(),
                DEFAULT_CHATGPT_PROJECT_URL,
                should_stop=lambda: False,
                startup_timeout_seconds=1,
                scan_wait_seconds=0.1,
            )
