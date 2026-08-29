"""Contract tests for the unified Agent capability registry.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from app.core.agent.capability_registry import (
    AGENT_ACTIONS,
    CAPABILITY_REGISTRY,
    PAGE_OBSERVATIONS,
    WEBMCP_TOOLS,
    build_agent_optimization_manifest,
    capability_registry_snapshot,
)


def test_registry_covers_agent_actions_page_observations_and_webmcp_tools() -> None:
    assert len({capability.key for capability in CAPABILITY_REGISTRY}) == len(CAPABILITY_REGISTRY)
    assert set(AGENT_ACTIONS) == {
        "list",
        "read",
        "search",
        "replace",
        "replace_base64",
        "write",
        "write_base64",
        "run",
        "bodycheck",
        "final",
    }
    assert set(PAGE_OBSERVATIONS) == {
        "provider_turn",
        "browser_interruption",
        "agent_status",
        "browser_session",
        "agent_response",
    }
    assert set(WEBMCP_TOOLS) == {
        "get_site_capabilities",
        "get_page_context",
        "navigate_to_site_target",
    }


def test_public_manifest_is_derived_from_the_registry_and_stays_bounded() -> None:
    manifest = build_agent_optimization_manifest()
    assert [item["id"] for item in manifest["capabilities"]] == [
        "cache_review",
        "local_resources",
        "agent_workspace",
        "configuration",
        "agent_actions",
        "page_observation",
        "webmcp_tools",
    ]
    assert "10 registered actions" in manifest["capabilities"][4]["description"]
    assert "5 registered observations" in manifest["capabilities"][5]["description"]
    assert "3 registered tools" in manifest["capabilities"][6]["description"]
    assert {target["path"] for target in manifest["navigation"]} == {
        "/cache/x",
        "/cache/grok",
        "/cache/chatgpt",
        "/cache/gemini",
        "/browser",
        "/agent",
        "/settings",
    }
    assert all(not target["path"].startswith("/api/") for target in manifest["navigation"])


def test_internal_snapshot_contains_transport_schemas_but_no_runtime_content() -> None:
    snapshot = capability_registry_snapshot()
    assert snapshot["version"] == "1.0.0"
    records = {record["key"]: record for record in snapshot["capabilities"]}
    assert records["agent.action.replace"]["read_only"] is False
    assert records["agent.action.run"]["read_only"] is True
    assert records["webmcp.get_page_context"]["read_only"] is True
    assert records["webmcp.get_page_context"]["input_schema"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert records["webmcp.navigate_to_site_target"]["input_schema"]["required"] == [
        "target",
    ]
    assert "prompt" not in snapshot
    assert "response" not in snapshot
    assert "page_content" not in snapshot
