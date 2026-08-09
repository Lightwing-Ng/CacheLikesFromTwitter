"""Unit tests for the Safari-backed Grok automation surface."""

# Code version: v1.1.0-codex.1

from __future__ import annotations

import base64
from pathlib import Path
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

    with patch.object(first_page, "_run_in_window"), patch.object(second_page, "_run_in_window"):
        assert context.housekeep() == 2

    assert context.pages == []
    assert first_page._closed is True
    assert second_page._closed is True
