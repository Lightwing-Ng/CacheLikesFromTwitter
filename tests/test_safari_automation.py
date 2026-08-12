"""Unit tests for the Safari-backed browser automation surface."""

# Code version: v1.7.1-codex.1

from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from app.core.safari_automation import SafariContext, SafariPage, run_applescript


def test_safari_page_downloads_one_authenticated_range(tmp_path: Path) -> None:
    context = SafariContext("https://grok.com/files")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)
    destination = tmp_path / "asset.part"
    content = b"\xff\xd8\xff\xe0"
    metadata = {
        "state": "ready",
        "status": 206,
        "contentType": "image/jpeg",
        "contentRange": "bytes 0-3/4",
        "contentLength": "4",
        "bytes": len(content),
        "error": "",
    }

    with patch.object(
        page,
        "evaluate",
        side_effect=[
            True,
            metadata,
            base64.b64encode(content).decode(),
            True,
        ],
    ):
        content_type, resumed = page.download_to_path(
            "https://assets.grok.com/example/image.jpg",
            destination,
            lambda: False,
        )

    assert content_type == "image/jpeg"
    assert resumed is False
    assert destination.read_bytes() == content


def test_safari_page_restarts_when_a_stale_partial_gets_http_416(tmp_path: Path) -> None:
    context = SafariContext("https://grok.com/files")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)
    destination = tmp_path / "asset.part"
    destination.write_bytes(b"stale-partial")
    content = b"full-payload"
    rejected = {
        "state": "ready",
        "status": 416,
        "contentType": "",
        "contentRange": "bytes */12",
        "contentLength": "0",
        "bytes": 0,
        "error": "",
    }
    accepted = {
        "state": "ready",
        "status": 206,
        "contentType": "application/octet-stream",
        "contentRange": "bytes 0-11/12",
        "contentLength": "12",
        "bytes": len(content),
        "error": "",
    }

    with patch.object(
        page,
        "evaluate",
        side_effect=[True, rejected, True, True, accepted, base64.b64encode(content).decode(), True],
    ):
        content_type, resumed = page.download_to_path(
            "https://assets.grok.com/example/file.bin",
            destination,
            lambda: False,
        )

    assert content_type == "application/octet-stream"
    assert resumed is True
    assert destination.read_bytes() == content


def test_safari_page_evaluate_invokes_page_function_and_decodes_value() -> None:
    context = SafariContext("https://grok.com/files")
    page = SafariPage(context, window_id=123)
    encoded_result = '{"ok":true,"value":{"status":200}}'

    with patch.object(page, "_run_in_window", return_value=encoded_result) as run:
        result = page.evaluate("(request) => ({ status: request.status })", {"status": 200})

    assert result == {"status": 200}
    assert "do JavaScript" in run.call_args.args[0]


def test_safari_request_client_fetches_chunked_authenticated_text() -> None:
    context = SafariContext("https://chatgpt.com/")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)
    body_text = '{"items":[]}'

    with patch.object(
        page,
        "evaluate",
        side_effect=[
            True,
            {
                "state": "ready",
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "bodyLength": len(body_text),
                "error": "",
            },
            {"text": body_text, "end": len(body_text)},
            True,
        ],
    ) as evaluate:
        response = context.request.get(
            "https://chatgpt.com/backend-api/test",
            timeout=60_000,
            headers={
                "Authorization": "Bearer test-token",
                "Referer": "https://chatgpt.com/",
            },
        )

    assert response.ok
    assert response.status == 200
    assert response.text() == body_text
    assert response.headers == {"content-type": "application/json"}
    assert response.request.headers["Authorization"] == "Bearer test-token"
    request_argument = evaluate.call_args_list[0].args[1]
    assert request_argument["headers"] == {"Authorization": "Bearer test-token"}
    assert request_argument["referrer"] == "https://chatgpt.com/"


def test_safari_request_client_returns_small_responses_inline() -> None:
    context = SafariContext("https://chatgpt.com/")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)
    body_text = '{"accessToken":"redacted"}'

    with patch.object(
        page,
        "evaluate",
        side_effect=[
            True,
            {
                "state": "ready",
                "status": 200,
                "headers": {},
                "bodyLength": len(body_text),
                "bodyText": body_text,
                "cleanedInline": True,
                "error": "",
            },
        ],
    ) as evaluate:
        response = context.request.get(
            "https://chatgpt.com/api/auth/session",
            timeout=60_000,
        )

    assert response.text() == body_text
    assert evaluate.call_count == 2


def test_safari_request_client_can_bind_a_request_to_one_owned_page() -> None:
    context = SafariContext("https://chatgpt.com/")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)
    expected_response = object()

    with patch.object(context.request, "_get_once", return_value=expected_response) as get_once:
        response = context.request.get_from_page(
            page,
            "https://chatgpt.com/backend-api/conversation/demo",
            timeout=60_000,
            headers={"Accept": "application/json"},
        )

    assert response is expected_response
    get_once.assert_called_once_with(
        page,
        "https://chatgpt.com/backend-api/conversation/demo",
        60_000,
        {"Accept": "application/json"},
        serialize=False,
    )


def test_safari_page_exposes_shared_readiness_helpers() -> None:
    context = SafariContext("https://chatgpt.com/")
    page = SafariPage(context, window_id=123)

    with patch.object(
        page,
        "evaluate",
        side_effect=["ChatGPT", {"found": True, "text": "Ready"}],
    ):
        assert page.title() == "ChatGPT"
        assert page.locator("body").inner_text(timeout=1_000) == "Ready"

    assert page.context is context


def test_safari_page_reopens_a_window_that_was_closed_externally() -> None:
    context = SafariContext("https://grok.com/files")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)

    with patch(
        "app.core.safari_automation.run_applescript",
        side_effect=[
            RuntimeError("Safari got an error: Can't get window 1 whose id = 123. Invalid index. (-1719)"),
            "987",
            "https://grok.com/files",
        ],
    ) as run:
        assert page.url == "https://grok.com/files"

    assert page.window_id == 987
    assert run.call_count == 3


def test_run_applescript_retries_transient_safari_errors() -> None:
    failed = type("Process", (), {"returncode": 1, "stderr": "execution error (-1712)", "stdout": ""})()
    succeeded = type("Process", (), {"returncode": 0, "stderr": "", "stdout": "ok\n"})()

    with patch("app.core.safari_automation.subprocess.run", side_effect=[failed, succeeded]), patch(
        "app.core.safari_automation.time.sleep"
    ) as sleep:
        assert run_applescript("return true") == "ok"

    sleep.assert_called_once()


def test_safari_context_housekeeping_closes_all_owned_windows() -> None:
    context = SafariContext("https://grok.com/files")
    first_page = SafariPage(context, window_id=123)
    second_page = SafariPage(context, window_id=456)
    context.pages.extend([first_page, second_page])

    with patch.object(
        first_page,
        "_run_in_window",
        return_value="1|about:blank|false|true",
    ), patch.object(
        second_page,
        "_run_in_window",
        return_value="1|about:blank|false|true",
    ):
        assert context.housekeep() == 2

    assert context.pages == []
    assert first_page._closed is True
    assert second_page._closed is True


def test_safari_context_creates_owned_windows_offscreen_and_minimized() -> None:
    context = SafariContext("https://grok.com/files")

    with patch("app.core.safari_automation.run_applescript", return_value="123") as run, patch.object(
        SafariPage,
        "goto",
    ) as goto:
        page = context._create_page("https://grok.com/files")

    script = run.call_args.args[0]
    assert page.window_id == 123
    goto.assert_called_once_with(
        "https://grok.com/files",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    assert "set previousWindowId to 0" in script
    assert "set previousWindowWasVisible to visible of front window" in script
    assert "set previousWindowWasMiniaturized to miniaturized of front window" in script
    assert "existingWindowIds" in script
    assert '(URL of current tab of candidateWindow) is "about:blank"' in script
    assert "emptyWindowIds" in script
    assert "set visible of targetWindow to false" in script
    assert "set bounds of targetWindow to {-32000, -32000, -30720, -31100}" in script
    assert "set miniaturized of targetWindow to true" in script
    assert (
        "if previousWindowId is not 0 and previousWindowWasVisible and not "
        "previousWindowWasMiniaturized then"
    ) in script
    assert script.index("set URL of current tab of targetWindow") < script.index(
        "set bounds of targetWindow"
    )


def test_safari_page_navigation_retries_a_start_page_and_verifies_the_target_url() -> None:
    context = SafariContext("https://chatgpt.com/project")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)
    states = [
        {"readyState": "complete", "href": "favorites://"},
        {"readyState": "complete", "href": "favorites://"},
        {"readyState": "complete", "href": "favorites://"},
        {
            "readyState": "interactive",
            "href": "https://chatgpt.com/project",
        },
    ]

    with patch.object(page, "_read_navigation_state", side_effect=states), patch.object(
        page,
        "_run_in_window",
        return_value="",
    ) as run, patch(
        "app.core.safari_automation.SAFARI_WRONG_PAGE_GRACE_SECONDS",
        0,
    ), patch.object(page, "_keep_in_background") as keep_in_background:
        page.goto("https://chatgpt.com/project", timeout=5_000)

    assert run.call_count == 2
    keep_in_background.assert_called_once_with()


def test_safari_page_reads_navigation_state_without_json_wrapping() -> None:
    context = SafariContext("https://chatgpt.com/project")
    page = SafariPage(context, window_id=123)

    with patch.object(
        page,
        "_run_in_window",
        return_value="https://chatgpt.com/project\ninteractive",
    ) as run:
        state = page._read_navigation_state()

    assert state == {
        "href": "https://chatgpt.com/project",
        "readyState": "interactive",
    }
    assert "URL of current tab" in run.call_args.args[0]
    assert "document.readyState" in run.call_args.args[0]


def test_safari_page_close_releases_only_the_owned_tab_into_a_hidden_shell() -> None:
    context = SafariContext("https://chatgpt.com/project")
    page = SafariPage(context, window_id=123)
    context.pages.append(page)

    with patch.object(
        page,
        "_run_in_window",
        return_value="1|about:blank|false|true",
    ) as run:
        page.close()

    script = run.call_args.args[0]
    assert 'set URL of current tab of targetWindow to "about:blank"' in script
    assert 'releasedState is "complete"' in script
    assert "set visible of targetWindow to false" in script
    assert '"|" & releasedUrl' in script
    assert page._closed is True
    assert context.pages == []


def test_safari_context_serializes_concurrent_window_creation() -> None:
    contexts = [
        SafariContext("https://chatgpt.com/"),
        SafariContext("https://chatgpt.com/"),
    ]
    counter_lock = Lock()
    active_calls = 0
    maximum_active_calls = 0
    next_window_id = 100

    def create_window(_source: str) -> str:
        nonlocal active_calls, maximum_active_calls, next_window_id
        with counter_lock:
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)
            next_window_id += 1
            window_id = next_window_id
        time.sleep(0.05)
        with counter_lock:
            active_calls -= 1
        return str(window_id)

    with patch("app.core.safari_automation.run_applescript", side_effect=create_window), patch.object(
        SafariPage,
        "goto",
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            pages = list(
                executor.map(
                    lambda context: context._create_page("https://chatgpt.com/"),
                    contexts,
                )
            )

    assert maximum_active_calls == 1
    assert {page.window_id for page in pages} == {101, 102}
