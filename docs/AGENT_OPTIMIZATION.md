# OpenAI Site tools and Agent Optimization

Documentation version: `v1.1.0-codex.1`

This project implements the shared Agent Optimization contract at
`/Users/lightwing/Desktop/SHARED_AGENT_OPTIMIZATION.md`. That file owns the cross-project naming,
schema, result, security, lifecycle, evaluation, and promotion rules. This document owns only the
CacheLikesFromTwitter adapter and its verification evidence.

## Runtime adapter

| Boundary | Project implementation |
| --- | --- |
| Shared runtime | `app/web/static/agent-optimization.js` |
| Project manifest | `app/web/templates/_agent_optimization.html` |
| Capability registry | `app/core/agent/capability_registry.py` |
| Agent event chain | `app/core/agent/event_chain.py` |
| Doctor routes and UI | `app/web/app.py`, `app/web/templates/agent.html`, `app/web/static/computer-use-agent.js` |
| Shared page bootstrap | `app/web/templates/_sidebar_bootstrap.html` |
| Node contract tests | `tests/test_agent_optimization.mjs` |
| Flask render tests | `tests/test_agent_optimization.py` |
| Disposable-browser tests | `tests/test_agent_optimization_browser.py` |

The runtime is byte-identical to the sibling antigravity copy and registers tools only when the
top-level document exposes `document.modelContext.registerTool`. Unsupported browsers receive the
normal interface without an error or behavioral fork.

The Agent password unlock template does not load Site tools. Normal loopback Agent pages load the
same safe v1 inventory as Cache, Local resources, and Settings pages. The manifest is generated at
render time from the capability registry; the shared runtime remains byte-identical and still
registers only three WebMCP tools.

The registry is the application-side source of truth for the Agent Action protocol, bounded page
observations, WebMCP tool metadata, and human-page navigation. It keeps the public manifest small
by publishing three aggregate groups for the internal Agent actions, page observations, and
WebMCP tools rather than exposing executable action schemas to the browser tool surface.

## v1 tools

| Tool | Result | Data boundary |
| --- | --- | --- |
| `get_site_capabilities` | Seven registry-derived capability groups and seven allowlisted destinations | Does not read cached records, settings values, or Agent context |
| `get_page_context` | Site ID, title, language, route, and matching destination | Reads zero page-content fields |
| `navigate_to_site_target` | Same-origin destination and scheduling evidence | Navigates only; does not submit Cache or Agent actions |

The allowlisted destinations are `/cache/x`, `/cache/grok`, `/cache/chatgpt`, `/cache/gemini`,
`/browser`, `/agent`, and `/settings`.

## Explicit exclusions

The v1 adapter does not expose:

- Cache start, stop, status probes, reset, refresh, or background browser launch.
- Local resource search results, saved prompts, cached messages, media paths, delete, restore,
  export, reveal, or file-manager actions.
- Agent prompt submission, source discovery, session content, recursive task execution, or terminal
  authorization.
- Settings values or writes.
- Agent event records, recovery actions, or doctor state through WebMCP. Those remain local
  human-interface diagnostics behind the existing Agent request boundary.

These exclusions prevent Site tools from widening the existing trusted-LAN, password, authenticated
browser, local storage, and user-data boundaries. Future read or write tools must follow the shared
promotion workflow and reuse existing core services and route authorization.

## Agent event chain and doctor recovery

Each new Agent run receives a `run-<hex>` identifier and appends an owner-readable JSONL chain
under the runtime root at `events/<run_id>.jsonl`. The chain starts with `run.started`, then links
each parsed Agent Action to an `action.requested` event, a bounded controller `observation`, and,
when applicable, a `verification` or `bodycheck` event before one terminal run event. Browser and
provider interruptions are page-observation events; Resume and cleanup are recovery events. Event
payloads are bounded and strip prompt, response, source, command, output, and page-content fields.
The persisted snapshot stores only the chain health summary and the last action/event identifiers.

`GET /api/agent/doctor` exposes the same lifecycle, chain, verification, bodycheck, and temporary
context-cleanup checks used by the Agent page. The Doctor panel appears only when attention is
needed and offers Resume, context cleanup, provider handoff, or a new-task affordance as
appropriate. `POST /api/agent/doctor/recover` performs only explicit local recovery actions; it
never resubmits a provider prompt.

## Automated verification

Run the focused contract, rendering, and disposable-browser layers with:

```bash
node --test tests/test_agent_optimization.mjs
/usr/local/bin/python3.13 -m pytest -q -p no:cacheprovider \
  tests/test_agent_capability_registry.py \
  tests/test_agent_event_chain.py \
  tests/test_agent_doctor.py \
  tests/test_agent_optimization.py \
  tests/test_agent_optimization_browser.py
```

Run the complete project gate with:

```bash
TZ=UTC CACHELIKES_PYTHON=/usr/local/bin/python3.13 ./scripts/check.sh
```

All tests use the pytest temporary runtime and a disposable browser context. They do not open an
authenticated profile, call a remote service, or touch the user-owned cache, logs, or settings.

Current automated evidence from 29 Aug 2026: all 9 shared Node contract cases and the focused
registry, event-chain, Doctor, rendering, Web, and controller checks passed. The complete gate
reached 1,140 passed Python cases, 399 unittest subtests, and 69.85% combined branch coverage;
the process still reported four timing-sensitive failures: two existing Computer Use subprocess
tests and two existing Sidebar integration tests. The two Computer Use failures passed in an
isolated rerun; the Sidebar assertions remain sensitive to the first asynchronous browser-status
request after `goto` and are recorded as unresolved baseline timing failures.

## OpenAI built-in Browser smoke test

This manual check depends on current OpenAI rollout and is not a CI gate:

1. Update the ChatGPT desktop app and enable Site tools under Browser permissions.
2. Open a disposable local test instance in the built-in Browser.
3. Inspect Available Site tools and confirm exactly three tools, with two read tools and one
   navigation tool.
4. Run `get_site_capabilities` and verify four capabilities plus seven destinations.
5. Run `navigate_to_site_target` with `local_resources`; verify the visible URL and page.
6. Review the invocation under Recently used.
7. Confirm the unsupported-browser path still preserves the ordinary UI.

Use GPT-5.6 Sol or GPT-5.6 Terra for the current OpenAI compatibility check. GPT-5.6 Luna currently
has WebMCP disabled. Treat this as client compatibility, not application logic.

Current evidence from 28 Aug 2026: the ChatGPT built-in Browser discovered exactly the three v1
tools on an isolated port 8677 Settings page, returned the four-capability and seven-destination
inventory, returned bounded Settings context, navigated through the Site tool to `/browser`, and
discovered a fresh three-tool set whose context matched `local_resources`. The isolated runtime was
stopped and removed after the check.

Official reference: [OpenAI Site tools](https://learn.chatgpt.com/docs/webmcp).
