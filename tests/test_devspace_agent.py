"""Focused tests for the local DevSpace and subscription web-agent bridge.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pytest

from app.core.config import CrawlConfig
from app.core.devspace_agent import (
    ChatGPTWebAgentService,
    DevSpaceSettings,
    _approve_pending_devspace_oauth,
    get_devspace_owner_token,
    is_loopback_address,
    resolve_workspace_path,
    save_devspace_settings,
    validate_devspace_settings,
)


class ReadyRuntime:
    """Provide the narrow runtime contract needed by the Agent service."""

    def __init__(self, settings: DevSpaceSettings) -> None:
        self.settings = settings

    @staticmethod
    def snapshot() -> dict[str, bool]:
        return {"ready": True}


def test_devspace_settings_validate_origins_roots_and_browser() -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        source = root / "devspace"
        workspace_root = root / "workspaces"
        source.mkdir()
        workspace_root.mkdir()
        (source / "package.json").write_text("{}\n", encoding="utf-8")

        settings = validate_devspace_settings(
            {
                "source_dir": str(source),
                "allowed_root": str(workspace_root),
                "public_base_url": "https://devspace.example.test",
                "chatgpt_url": "https://chatgpt.com/",
                "browser": "edge",
                "port": "7676",
            }
        )

        assert settings.source_dir == str(source.resolve())
        assert settings.allowed_root == str(workspace_root.resolve())
        assert settings.public_base_url == "https://devspace.example.test"
        assert settings.platform == "chatgpt"
        assert settings.browser == "edge"
        assert settings.port == 7676

        default_settings = DevSpaceSettings()
        assert default_settings.browser == "safari"

        with pytest.raises(ValueError, match="without /mcp"):
            validate_devspace_settings(
                {
                    **asdict(settings),
                    "public_base_url": "https://devspace.example.test/mcp",
                }
            )

        with pytest.raises(ValueError, match="ChatGPT, Gemini, or Grok"):
            validate_devspace_settings(
                {
                    **asdict(settings),
                    "platform": "claude",
                }
            )


def test_workspace_resolution_stays_under_the_allowed_root() -> None:
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        allowed = root / "allowed"
        workspace = allowed / "project"
        outside = root / "outside"
        workspace.mkdir(parents=True)
        outside.mkdir()

        assert resolve_workspace_path(str(workspace), str(allowed)) == workspace.resolve()
        with pytest.raises(ValueError, match="inside the allowed root"):
            resolve_workspace_path(str(outside), str(allowed))


def test_saved_settings_are_owner_readable_only() -> None:
    with TemporaryDirectory() as raw_root:
        settings_path = Path(raw_root) / "devspace-agent.json"
        save_devspace_settings(DevSpaceSettings(), settings_path)

        assert settings_path.stat().st_mode & 0o777 == 0o600
        assert "owner_token" not in settings_path.read_text(encoding="utf-8")


def test_owner_password_is_stable_and_owner_readable_only() -> None:
    with TemporaryDirectory() as raw_root:
        secret_path = Path(raw_root) / "devspace-owner.json"

        first = get_devspace_owner_token(secret_path)
        second = get_devspace_owner_token(secret_path)

        assert first == second
        assert len(first) >= 16
        assert secret_path.stat().st_mode & 0o777 == 0o600


def test_devspace_oauth_approval_is_automatic_and_local_only() -> None:
    class ApprovalPage:
        def __init__(self, url: str) -> None:
            self.url = url
            self.evaluated = False

        def evaluate(self, _expression: str, argument: dict[str, str]) -> bool:
            self.evaluated = argument["ownerToken"] == "test-owner-password"
            return self.evaluated

    local_page = ApprovalPage("http://127.0.0.1:7676/authorize")
    remote_page = ApprovalPage("https://chatgpt.com/")
    approved_pages: set[int] = set()
    updates: list[dict[str, str]] = []
    context = type("Context", (), {"pages": [local_page, remote_page]})()

    with patch("app.core.devspace_agent.get_devspace_owner_token", return_value="test-owner-password"):
        assert _approve_pending_devspace_oauth(
            local_page,
            context,
            7676,
            approved_pages,
            lambda **changes: updates.append(changes),
        )
        assert not _approve_pending_devspace_oauth(
            local_page,
            context,
            7676,
            approved_pages,
            lambda **changes: updates.append(changes),
        )

    assert local_page.evaluated
    assert not remote_page.evaluated
    assert updates == [
        {
            "phase": "authorizing",
            "message": "Authorizing the local DevSpace connection automatically.",
        }
    ]


def test_agent_service_reports_runner_result_without_api_credentials() -> None:
    with TemporaryDirectory() as raw_root:
        workspace = Path(raw_root) / "project"
        workspace.mkdir()
        settings = DevSpaceSettings(allowed_root=raw_root)

        def runner(**kwargs):
            assert kwargs["prompt"] == "Inspect the workspace"
            assert kwargs["workspace_path"] == str(workspace.resolve())
            kwargs["update"](phase="running", message="Using DevSpace tools.")
            return "Verified result", "https://chatgpt.com/c/example"

        service = ChatGPTWebAgentService(ReadyRuntime(settings), runner=runner)
        service.start("Inspect the workspace", str(workspace), CrawlConfig())
        deadline = time.monotonic() + 2
        while service.snapshot()["running"] and time.monotonic() < deadline:
            time.sleep(0.01)

        snapshot = service.snapshot()
        assert snapshot["phase"] == "finished"
        assert snapshot["response"] == "Verified result"
        assert snapshot["conversation_url"] == "https://chatgpt.com/c/example"
        assert "token" not in snapshot


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "localhost"])
def test_loopback_address_detection(address: str) -> None:
    assert is_loopback_address(address)
    assert not is_loopback_address("192.0.2.1")
