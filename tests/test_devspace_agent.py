"""Focused tests for the native Agent and optional DevSpace web bridge.

Code version: v2.1.0-codex.1
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pytest

from app.core.config import CrawlConfig
from app.core.codex_agent import (
    CodexRuntimeInspector,
    _apply_codex_event,
    _build_codex_command,
    _codex_event_error,
)
from app.core.devspace_agent import (
    AgentService,
    DevSpaceRuntimeManager,
    DevSpaceSettings,
    _approve_pending_devspace_oauth,
    _is_configured_devspace_page,
    _is_web_response_complete,
    _response_reports_missing_devspace,
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


class ReadyNativeRuntime:
    """Provide deterministic native Codex readiness."""

    @staticmethod
    def snapshot(*, refresh: bool = False) -> dict[str, object]:
        del refresh
        return {
            "ready": True,
            "authenticated": True,
            "message": "Ready through the ChatGPT subscription.",
        }


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
        assert settings.workspace_path == str(workspace_root.resolve())
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


def test_devspace_oauth_approval_is_automatic_for_the_exact_configured_origin() -> None:
    class ApprovalPage:
        def __init__(self, url: str) -> None:
            self.url = url
            self.evaluated = False

        def evaluate(self, _expression: str, argument: dict[str, str]) -> bool:
            self.evaluated = argument["ownerToken"] == "test-owner-password"
            return self.evaluated

    configured_page = ApprovalPage("https://devspace.example.test/authorize")
    unrelated_page = ApprovalPage("https://chatgpt.com/")
    approved_pages: set[int] = set()
    updates: list[dict[str, str]] = []
    context = type("Context", (), {"pages": [configured_page, unrelated_page]})()

    with patch("app.core.devspace_agent.get_devspace_owner_token", return_value="test-owner-password"):
        assert _approve_pending_devspace_oauth(
            configured_page,
            context,
            "https://devspace.example.test",
            approved_pages,
            lambda **changes: updates.append(changes),
        )
        assert not _approve_pending_devspace_oauth(
            configured_page,
            context,
            "https://devspace.example.test",
            approved_pages,
            lambda **changes: updates.append(changes),
        )

    assert configured_page.evaluated
    assert not unrelated_page.evaluated
    assert updates == [
        {
            "phase": "authorizing",
            "message": "Authorizing the local DevSpace connection automatically.",
        }
    ]
    assert not _is_configured_devspace_page(
        ApprovalPage("https://devspace.example.test:invalid/authorize"),
        "https://devspace.example.test",
    )


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

        service = AgentService(
            ReadyRuntime(settings),
            runner=runner,
            native_runtime=ReadyNativeRuntime(),
        )
        service.start("Inspect the workspace", str(workspace), CrawlConfig())
        deadline = time.monotonic() + 2
        while service.snapshot()["running"] and time.monotonic() < deadline:
            time.sleep(0.01)

        snapshot = service.snapshot()
        assert snapshot["phase"] == "finished"
        assert snapshot["engine"] == "codex"
        assert snapshot["response"] == "Verified result"
        assert snapshot["conversation_url"] == "https://chatgpt.com/c/example"
        assert "token" not in snapshot


def test_web_completion_rejects_progress_labels_and_requires_stability() -> None:
    assert not _is_web_response_complete(
        "Thinking",
        is_generating=False,
        submitted_at=0.0,
        stable_since=0.0,
        now=20.0,
    )
    assert not _is_web_response_complete(
        "Verified result",
        is_generating=False,
        submitted_at=0.0,
        stable_since=18.0,
        now=20.0,
    )
    assert _is_web_response_complete(
        "Verified result",
        is_generating=False,
        submitted_at=0.0,
        stable_since=12.0,
        now=20.0,
    )
    assert _response_reports_missing_devspace(
        "The DevSpace plugin is unavailable in this environment."
    )


def test_codex_runtime_inspector_reports_chatgpt_authentication() -> None:
    completed = [
        type("Result", (), {"returncode": 0, "stdout": "codex-cli 1.2.3\n", "stderr": ""})(),
        type(
            "Result",
            (),
            {"returncode": 0, "stdout": "Logged in using ChatGPT\n", "stderr": ""},
        )(),
    ]
    with patch("app.core.codex_agent.subprocess.run", side_effect=completed):
        snapshot = CodexRuntimeInspector(Path("/tmp/codex")).snapshot(refresh=True)

    assert snapshot["ready"]
    assert snapshot["authenticated"]
    assert snapshot["version"] == "codex-cli 1.2.3"


def test_codex_runtime_rejects_api_key_authentication_as_subscription_readiness() -> None:
    completed = [
        type("Result", (), {"returncode": 0, "stdout": "codex-cli 1.2.3\n", "stderr": ""})(),
        type(
            "Result",
            (),
            {"returncode": 0, "stdout": "Logged in using API key\n", "stderr": ""},
        )(),
    ]
    with patch("app.core.codex_agent.subprocess.run", side_effect=completed):
        snapshot = CodexRuntimeInspector(Path("/tmp/codex")).snapshot(refresh=True)

    assert not snapshot["ready"]
    assert not snapshot["authenticated"]


def test_codex_command_uses_automatic_review_without_conflicting_sandbox_flags() -> None:
    command = _build_codex_command(
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
        Path("/tmp/project"),
        "Inspect the project",
    )

    assert command[:2] == [
        "/Applications/ChatGPT.app/Contents/Resources/codex",
        "exec",
    ]
    assert "--approve-for-me" in command
    assert "--sandbox" not in command
    assert command[-3:] == ["--cd", "/tmp/project", "Inspect the project"]
    assert _codex_event_error(
        {"type": "turn.failed", "error": {"message": "command rejected"}}
    ) == "command rejected"


def test_codex_json_events_expose_safe_agent_activity() -> None:
    activity: list[dict[str, str]] = []
    indexes: dict[str, int] = {}
    response, thread_id = _apply_codex_event(
        {"type": "thread.started", "thread_id": "thread-1"},
        activity,
        indexes,
        "",
        "",
    )
    response, thread_id = _apply_codex_event(
        {
            "type": "item.started",
            "item": {
                "id": "item-1",
                "type": "command_execution",
                "command": "API_KEY=sensitive pytest -q",
            },
        },
        activity,
        indexes,
        response,
        thread_id,
    )
    response, thread_id = _apply_codex_event(
        {
            "type": "item.completed",
            "item": {
                "id": "item-1",
                "type": "command_execution",
                "exit_code": 0,
            },
        },
        activity,
        indexes,
        response,
        thread_id,
    )
    response, thread_id = _apply_codex_event(
        {
            "type": "item.completed",
            "item": {"id": "item-2", "type": "agent_message", "text": "Done"},
        },
        activity,
        indexes,
        response,
        thread_id,
    )

    assert thread_id == "thread-1"
    assert response == "Done"
    assert activity[0]["detail"] == "API_KEY=[redacted] pytest -q"
    assert activity[0]["status"] == "completed"


def test_devspace_connection_requires_successful_mcp_traffic_after_marker() -> None:
    with TemporaryDirectory() as raw_root:
        log_path = Path(raw_root) / "devspace.log"
        log_path.write_text("", encoding="utf-8")
        with patch(
            "app.core.devspace_agent.load_devspace_settings",
            return_value=DevSpaceSettings(),
        ):
            runtime = DevSpaceRuntimeManager(log_path)

        marker = runtime.activity_marker()
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                '{"ts":"2026-08-13T00:00:00Z","event":"http_request",'
                '"path":"/mcp","status":401}\n'
            )
        assert not runtime.successful_mcp_activity_since(marker)

        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                '{"ts":"2026-08-13T00:00:01Z","event":"http_request",'
                '"path":"/mcp","status":200}\n'
            )
        assert runtime.successful_mcp_activity_since(marker)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "localhost"])
def test_loopback_address_detection(address: str) -> None:
    assert is_loopback_address(address)
    assert not is_loopback_address("192.0.2.1")
