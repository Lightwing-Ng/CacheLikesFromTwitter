"""Route and service tests for Agent doctor recovery UX.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import json
import time

from app.core.computer_use_agent import (
    ComputerUseAgentService,
    ComputerUseSettingsStore,
)
from app.core.config import CrawlConfig


def _wait_for_completion(service: ComputerUseAgentService) -> dict[str, object]:
    deadline = time.monotonic() + 3
    while service.snapshot()["running"] and time.monotonic() < deadline:
        time.sleep(0.01)
    return service.snapshot()


def test_idle_doctor_is_healthy_and_marks_run_only_checks_not_applicable(tmp_path) -> None:
    service = ComputerUseAgentService(
        ComputerUseSettingsStore(tmp_path / "settings.json"),
        runtime_root=tmp_path / "runtime",
    )

    doctor = service.doctor()
    checks = {check["id"]: check for check in doctor["checks"]}
    assert doctor["status"] == "healthy"
    assert checks["event_chain"]["status"] == "pass"
    assert checks["verification"]["status"] == "info"
    assert checks["bodycheck"]["status"] == "info"
    assert doctor["actions"][0]["enabled"] is False


def test_doctor_does_not_call_active_context_a_cleanup_failure(tmp_path) -> None:
    service = ComputerUseAgentService(
        ComputerUseSettingsStore(tmp_path / "settings.json"),
        runtime_root=tmp_path / "runtime",
    )
    service._snapshot.running = True
    service._snapshot.run_id = "run-0123456789abcdef"
    service._snapshot.context_file = str(tmp_path / "runtime" / "context.md")

    checks = {check["id"]: check for check in service.doctor()["checks"]}

    assert checks["context_cleanup"]["status"] == "pass"
    assert "active Agent run" in checks["context_cleanup"]["detail"]


def test_completed_run_persists_event_chain_and_doctor_can_report_healthy(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    monkeypatch.setattr(
        "app.core.computer_use_agent._start_macos_idle_sleep_assertion",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.core.computer_use_agent._stop_macos_idle_sleep_assertion",
        lambda _process: None,
    )

    def runner(**kwargs):
        update = kwargs["update"]
        update(
            phase="running",
            message="Controller active.",
            verification_passed=True,
            bodycheck_passed=True,
        )
        return "Verified result", "https://chatgpt.com/c/example", 1, True

    runtime_root = tmp_path / "runtime"
    service = ComputerUseAgentService(
        ComputerUseSettingsStore(tmp_path / "settings.json"),
        runner=runner,
        runtime_root=runtime_root,
    )
    service.start("Inspect the project", str(workspace), CrawlConfig())
    snapshot = _wait_for_completion(service)

    assert snapshot["running"] is False
    assert snapshot["run_id"].startswith("run-")
    assert snapshot["event_chain_state"] == "ready"
    assert snapshot["event_count"] == 2
    assert snapshot["last_event_kind"] == "run.completed"
    event_path = runtime_root / "events" / f"{snapshot['run_id']}.jsonl"
    records = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert [record["kind"] for record in records] == ["run.started", "run.completed"]

    doctor = service.doctor()
    assert doctor["status"] == "healthy"
    assert doctor["run_id"] == snapshot["run_id"]
    assert doctor["events"][-1]["kind"] == "run.completed"


def test_capability_and_doctor_routes_are_local_and_bounded(client) -> None:
    capabilities_response = client.get("/api/agent/capabilities")
    doctor_response = client.get("/api/agent/doctor")
    recovery_response = client.post(
        "/api/agent/doctor/recover",
        json={"action": "cleanup_context"},
    )
    invalid_recovery_response = client.post(
        "/api/agent/doctor/recover",
        json={"action": "unsupported"},
    )
    remote_response = client.get(
        "/api/agent/doctor",
        environ_base={"REMOTE_ADDR": "192.0.2.10"},
    )

    assert capabilities_response.status_code == 200
    assert doctor_response.status_code == 200
    assert recovery_response.status_code == 200
    assert recovery_response.get_json()["recovery"]["ok"] is True
    assert invalid_recovery_response.status_code == 409
    assert remote_response.status_code == 403
    capabilities = capabilities_response.get_json()
    doctor = doctor_response.get_json()
    assert capabilities["version"] == "1.0.0"
    assert len(capabilities["capabilities"]) == 24
    assert doctor["capability_registry_version"] == "1.0.0"
    assert "prompt" not in doctor
    assert "response" not in doctor


def test_agent_page_exposes_doctor_panel_and_recovery_script(client) -> None:
    body = client.get("/agent", follow_redirects=True).get_data(as_text=True)
    script = client.get("/static/computer-use-agent.js").get_data(as_text=True)

    assert 'id="agent_doctor_panel"' in body
    assert 'id="agent_doctor_checks"' in body
    assert 'id="agent_doctor_actions"' in body
    assert 'requestJson("/api/agent/doctor")' in script
    assert 'mutate("/api/agent/doctor/recover", {action})' in script
    assert "agentNeedsDoctor" in script
