"""Unit tests for the Safari-backed Grok automation surface."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

from app.core.safari_automation import SafariContext, SafariPage


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


def test_safari_page_evaluate_invokes_page_function_and_decodes_value() -> None:
    context = SafariContext("https://grok.com/files")
    page = SafariPage(context, window_id=123)
    encoded_result = '{"ok":true,"value":{"status":200}}'

    with patch.object(page, "_run_in_window", return_value=encoded_result) as run:
        result = page.evaluate("(request) => ({ status: request.status })", {"status": 200})

    assert result == {"status": 200}
    assert "do JavaScript" in run.call_args.args[0]
