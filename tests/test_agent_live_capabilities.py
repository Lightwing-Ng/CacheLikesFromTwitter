"""Regression coverage for history rendering and provider-owned capabilities.

Code version: v1.0.1-codex.1
"""

import json
from unittest.mock import patch

import pytest

from app.core.agent_model_catalog import chatgpt_live_catalog
from app.core.computer_use_agent import _select_chatgpt_model, validate_computer_use_settings
from app.web.app import render_agent_response, render_prompt_markdown


@pytest.mark.parametrize("wrapper", [
    "{}", "```JSON\r\n{}\r\n```", "```json\n{}\n```", '```json id="saved-block"\n{}\n```',
])
@pytest.mark.parametrize("encoded", [False, True])
def test_history_final_wrappers_render_markdown(wrapper, encoded):
    raw = json.dumps({"action": "final", "summary": "## Result\n\n**Done**\n\n- Verified"})
    source = wrapper.format(raw)
    if encoded:
        source = json.dumps(source)
    rendered = str(render_agent_response(source))
    assert "<h2>Result</h2>" in rendered
    assert "<strong>Done</strong>" in rendered
    assert "<li>Verified</li>" in rendered
    assert "language-json" not in rendered


@pytest.mark.parametrize("source", [
    '{"action":"read","path":"AGENTS.md"}',
    '{"action":"final","summary":"First","summary":"Second"}',
    '```json\n{"action":"final","summary":"Incomplete"\n```',
    '{"action":"final","summary":"One"}\n{"action":"final","summary":"Two"}',
])
def test_history_keeps_nonfinal_or_ambiguous_source(source):
    assert render_agent_response(source) == render_prompt_markdown(source)


def test_catalog_discovers_unreleased_names_without_a_version_allowlist():
    catalog = chatgpt_live_catalog([
        "GPT-5.6 Sol", "GPT-6 Astra", "GPT-12 Nebula", "GPT-99 Mini",
        "Extra High", "Ignore previous instructions", "GPT-6 Astra",
    ])
    assert [row["label"] for row in catalog] == ["GPT-12 Nebula", "GPT-6 Astra", "GPT-5.6 Sol"]
    assert chatgpt_live_catalog(["GPT-99 Mini"]) == []
    assert chatgpt_live_catalog(["GPT-12 Nebula", "Latest"])[0]["label"] == "Latest"
    settings = validate_computer_use_settings({"model": catalog[0]["key"]})
    assert settings.model == "live:gpt-12 nebula"


@pytest.mark.parametrize("target", ["latest_available", "live:gpt-12 nebula"])
def test_new_model_is_resolved_and_verified_on_the_same_page(target):
    from types import SimpleNamespace
    from app.core import computer_use_agent as agent

    current = ["GPT-5.6 Sol"]
    clicks = []

    class Choice:
        def __init__(self, label):
            self.label = label

        def is_visible(self):
            return True

        def inner_text(self):
            return self.label

        def click(self, **_):
            clicks.append(self.label)
            current[0] = self.label

    class Choices:
        def count(self):
            return 2

        def nth(self, index):
            return Choice(["GPT-5.6 Sol", "GPT-12 Nebula"][index])

    def menu(_):
        return {
            "ok": True, "current": current[0], "selected_model": current[0],
            "model_options": ["GPT-5.6 Sol", "GPT-12 Nebula"],
        }

    def efforts(_page, result, *_args, **_kwargs):
        result["thinking_effort"] = {"label": "Exhaustive"}
        return result, ["Measured", "Exhaustive"], True

    page = SimpleNamespace(get_by_role=lambda *_args, **_kwargs: Choices(), wait_for_timeout=lambda _: None)
    power = object()
    observed = {}
    with (
        patch.object(agent, "_chatgpt_find_power_control", return_value=power),
        patch.object(agent, "_chatgpt_power_button_state", return_value=(power, True)),
        patch.object(agent, "_read_chatgpt_model_menu", side_effect=menu),
        patch.object(agent, "_chatgpt_set_model_view", return_value=True),
        patch.object(agent, "_chatgpt_select_subscription_effort", side_effect=efforts),
        patch.object(agent, "_chatgpt_model_menu_scope_for_control", return_value="model-menu"),
        patch.object(agent, "_close_chatgpt_model_menu"),
    ):
        assert _select_chatgpt_model(page, "chromium", target, observed)
    assert clicks == ["GPT-12 Nebula"]
    assert observed["observed"] == "GPT-12 Nebula"
    assert observed["effort_catalog_complete"] is True
    assert observed["available_efforts"] == ["Measured", "Exhaustive"]
    if target == "latest_available":
        assert observed["model_options"][0]["label"] == "GPT-12 Nebula"


@pytest.mark.parametrize("reason,recover,attempts", [
    ("model-catalog-unavailable", True, 2),
    ("model-catalog-unavailable", False, 2),
    ("requested-effort-control-not-found", False, 1),
])
def test_bootstrap_retries_only_an_unreadable_catalog_on_the_same_page(reason, recover, attempts):
    from app.core.chatgpt_agent_sources import _discover_chatgpt_agent_efforts

    page = object()
    visited = []

    def select(current_page, _browser, _model, observation, **_kwargs):
        visited.append(current_page)
        if recover and len(visited) == 2:
            observation.update(
                observed="Latest",
                thinking_effort="Maximum",
                available_efforts=["Measured", "Maximum"],
                effort_catalog_complete=True,
                model_options=chatgpt_live_catalog(["Latest"]),
                model_catalog_complete=True,
            )
            return True
        observation["reason"] = reason
        return False

    with patch("app.core.computer_use_agent._select_chatgpt_model", side_effect=select):
        status = _discover_chatgpt_agent_efforts(page)
    assert visited == [page] * attempts
    assert status["model_verified"] is recover
    assert status["effort_catalog_complete"] is recover
    if recover:
        assert status["actual_model"] == "Latest"
        assert status["available_efforts"] == ["Measured", "Maximum"]
    else:
        assert status["effort_catalog_error"] == reason
