# OpenAI Site tools and Agent Optimization

Documentation version: `v1.0.1-codex.1`

This project implements the shared Agent Optimization contract at
`/Users/lightwing/Desktop/SHARED_AGENT_OPTIMIZATION.md`. That file owns the cross-project naming,
schema, result, security, lifecycle, evaluation, and promotion rules. This document owns only the
CacheLikesFromTwitter adapter and its verification evidence.

## Runtime adapter

| Boundary | Project implementation |
| --- | --- |
| Shared runtime | `app/web/static/agent-optimization.js` |
| Project manifest | `app/web/templates/_agent_optimization.html` |
| Shared page bootstrap | `app/web/templates/_sidebar_bootstrap.html` |
| Node contract tests | `tests/test_agent_optimization.mjs` |
| Flask render tests | `tests/test_agent_optimization.py` |
| Disposable-browser tests | `tests/test_agent_optimization_browser.py` |

The runtime is byte-identical to the sibling antigravity copy and registers tools only when the
top-level document exposes `document.modelContext.registerTool`. Unsupported browsers receive the
normal interface without an error or behavioral fork.

The Agent password unlock template does not load Site tools. Normal loopback Agent pages load the
same safe v1 inventory as Cache, Local resources, and Settings pages.

## v1 tools

| Tool | Result | Data boundary |
| --- | --- | --- |
| `get_site_capabilities` | Four static capability groups and seven allowlisted destinations | Does not read cached records, settings values, or Agent context |
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

These exclusions prevent Site tools from widening the existing trusted-LAN, password, authenticated
browser, local storage, and user-data boundaries. Future read or write tools must follow the shared
promotion workflow and reuse existing core services and route authorization.

## Automated verification

Run the focused contract, rendering, and disposable-browser layers with:

```bash
node --test tests/test_agent_optimization.mjs
/usr/local/bin/python3.13 -m pytest -q -p no:cacheprovider \
  tests/test_agent_optimization.py \
  tests/test_agent_optimization_browser.py
```

Run the complete project gate with:

```bash
TZ=UTC CACHELIKES_PYTHON=/usr/local/bin/python3.13 ./scripts/check.sh
```

All tests use the pytest temporary runtime and a disposable browser context. They do not open an
authenticated profile, call a remote service, or touch the user-owned cache, logs, or settings.

Current automated evidence from 28 Aug 2026: all 9 shared Node contract cases, all 5 focused Flask
and disposable-browser cases, all 1,119 full-suite Python cases, and all 380 unittest subtests
passed. The complete gate measured 69.31% combined branch coverage for `app/`.

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
