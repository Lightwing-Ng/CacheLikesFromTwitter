"""Activity disclosure and status glyph regressions. Code version: v1.0.0-codex.1."""

import pytest
from playwright.sync_api import expect

from tests import test_sidebar_e2e as fixtures

disposable_browser = fixtures.disposable_browser
sidebar_server_url = fixtures.sidebar_server_url


@pytest.mark.parametrize("width", [1138, 390])
@pytest.mark.parametrize("motion", ["no-preference", "reduce"])
def test_activity_preserves_collapse_and_tracks_current(disposable_browser, sidebar_server_url, width, motion):
    context = disposable_browser.new_context(viewport={"width": width, "height": 959}, reduced_motion=motion)
    page = context.new_page()
    payload = fixtures._finished_chatgpt_agent_payload()
    payload["agent"].update(running=True, phase="running", finished_at="", run_id="activity-test", run_revision=100)
    payload["agent"]["activity"] = [
        {"status": "completed", "label": "Read", "detail": "app/example.py", "meta": "Turn 1"},
        {"status": "running", "label": "Search", "detail": "tests", "meta": "Turn 2"},
    ]
    page.route("**/api/agent/status", lambda route: route.fulfill(json=payload))
    page.route("**/api/browser-session**", lambda route: route.fulfill(json={
        "can_download": True, "logged_in": True, "browser": "edge", "platform": "chatgpt",
        "agent_sources": fixtures._chatgpt_catalog_sessions(),
    }))
    page.route("**/api/agent/sources**", lambda route: route.fulfill(json=fixtures._chatgpt_catalog_sessions()))
    try:
        page.goto(f"{sidebar_server_url}/agent/edge/chatgpt")
        panel = page.locator("#agent_activity_panel")
        summary = panel.locator("summary")
        expect(panel).to_have_js_property("open", True)
        done = panel.locator('[data-status="completed"] .agent-activity-status')
        expect(done).to_have_css("mask-image", f'url("{sidebar_server_url}/static/images/checkmark.circle.svg")')
        geometry = done.evaluate("""e => {
            const label = e.parentElement.querySelector('.agent-activity-label').getBoundingClientRect();
            const icon = e.getBoundingClientRect();
            const heading = document.querySelector('.agent-activity-heading').getBoundingClientRect();
            const working = document.querySelector('[data-agent-response-status-leading]').getBoundingClientRect();
            return {center: Math.abs((label.top + label.bottom - icon.top - icon.bottom) / 2),
                left: Math.abs(heading.left - working.left),
                green: getComputedStyle(e).backgroundColor === getComputedStyle(document.documentElement).getPropertyValue('--theme-success-strong').trim()};
        }""")
        assert geometry["center"] <= 1
        assert geometry["left"] <= 1
        # Resolve the color through a computed property, independent of hex/rgb spelling.
        expect(done).to_have_css("background-color", "rgb(22, 163, 74)")
        running = panel.locator('[data-status="running"] .cache-phase-live-marker')
        expect(running).to_be_visible()
        assert running.evaluate("e => getComputedStyle(e, '::before').animationName") == "cachePhaseLiveBreath"
        summary.click()
        if motion == "no-preference":
            assert page.locator('#agent_activity_list').evaluate("e => e.getAnimations().some(a => a.playState === 'running')")
        expect(panel).to_have_js_property("open", False)
        current = page.locator("#agent_activity_current")
        expect(current).to_be_visible()
        expect(current.locator('li')).to_have_count(1)
        expect(summary.locator('.agent-activity-live')).to_be_visible()
        payload["agent"]["activity"].append({"status": "running", "label": "Run", "detail": "next", "meta": "Turn 3"})
        expect(current).to_contain_text("Run")
        expect(panel).to_have_js_property("open", False)
        summary.focus()
        summary.press("Enter")
        expect(panel).to_have_js_property("open", True)
        expect(current).to_be_hidden()
        expect(panel.locator('li')).to_have_count(3)
        summary.press("Space")
        expect(panel).to_have_js_property("open", False)
        payload["agent"].update(running=False, phase="finished")
        expect(current).to_be_hidden()
        expect(summary.locator('.agent-activity-live')).to_be_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    finally:
        context.close()
