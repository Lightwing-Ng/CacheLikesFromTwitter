# CacheLikesFromTwitter

Documentation version: `v1.11.0-codex.1`

CacheLikesFromTwitter is a local Flask web console that caches media from the
currently signed-in X account's Likes timeline, Grok's Files library, and a
configured ChatGPT project or session. It stores media locally and provides
a browser for reviewing, deleting, and restoring cached files.

Its Agent workspace uses the selected authenticated Web session for ChatGPT, Gemini, or Grok.
The sidebar exposes one provider-neutral Project concept: ChatGPT Projects, Gemini Notebooks, and
Grok Projects are adapted behind the same Project selector and execution contract. It defaults to
a new root-level session, while the sidebar can join one of the 20 most recent sessions, start a
session in one of the 20 most recent Projects, or join one of a Project's 20 most recent sessions.
The selected Web provider supplies reasoning while a bounded local macOS Computer Use controller
reads, changes, runs, and verifies only the selected project. This fallback uses no API,
command-line coding-agent runtime, MCP connection, or third-party agent bridge.

## Visual Style Reference

This is a sibling project of `../antigravity/app`. Its visual
language is the source of truth for shared application-shell, typography, surface,
control, and motion decisions. Read [STYLE_REFERENCE.md](STYLE_REFERENCE.md) before
making any UI change.

This project starts a web console on `http://localhost:8666` and listens on all network
interfaces so devices on the same LAN can use `http://<computer-ip>:8666`. Treat that LAN
endpoint as trusted-only; do not expose it through port forwarding or a public reverse proxy.

## Requirements

- macOS with a supported Python 3.13 or 3.14 interpreter; the resolver prefers the host
  `python3` when it is supported
- A signed-in Chrome, Edge, or Safari session for the source you want to cache
- Playwright Chromium for Chromium-backed X, Grok, and ChatGPT automation
- `yt-dlp` for X media downloads
- An authenticated ChatGPT Web account for the optional Computer Use Agent workspace

ChatGPT project caching uses up to three isolated Edge workers in parallel. The worker count is
bounded deliberately because each worker owns a separate authenticated browser context.

## Quick Start

```bash
./scripts/setup_python.sh
```

Then open the project in PyCharm and run the shared `main` configuration with a supported
Python 3.13 or 3.14 interpreter, or launch it from a shell:

```bash
./scripts/run_app.sh
```

Set `CACHELIKES_SKIP_PLAYWRIGHT_INSTALL=1` only for an offline test-only dependency setup.
`CACHELIKES_PYTHON` is an explicit Python 3.13 or 3.14 override intended primarily for CI or
local runtime compatibility.

## Quality Checks

Run the fast offline Python suite with:

```bash
./scripts/test.sh
```

Run the complete local quality gate with:

```bash
./scripts/check.sh
```

The quality gate runs Ruff, JavaScript syntax checks, the Python suite with branch coverage,
and a disposable Chromium sidebar E2E flow. It is the same command executed by GitHub Actions.
The browser flow uses a clean context against an isolated local server; the suite never opens
an authenticated profile, downloads media, or writes to user-owned caches, logs, or settings.

## Documentation

- [Cache handoff and operating runbook](docs/CACHE_HANDOFF.md)
- [Architecture guide](docs/ARCHITECTURE.md)
- [Testing guide](docs/TESTING.md)
- [Operations guide](docs/OPERATIONS.md)
- [Known operating constraints](docs/KNOWN_ISSUES.md)
- [ChatGPT Web Computer Use Agent](docs/COMPUTER_USE_AGENT.md)
- [Third-party notices](docs/THIRD_PARTY_NOTICES.md)
- [Engineering and test contract](docs/AGENTS.md)
- [Test coverage map](tests/README.md)

## Project Layout

- `main.py`: supported Python 3.13/3.14 entrypoint
- `app/core/`: cache services, browser automation, downloaders, state, storage, and logging
- `app/web/`: Flask routes, templates, static assets, and the local-media browser
- `tests/`: deterministic unit and Flask integration coverage
- `scripts/`: supported setup, launch, test, and quality-gate commands
- `local_store/`: ignored user-owned media cache
- `logs/`: ignored structured local logs

## Notes

- The first run works best when normal Chrome windows are closed.
- The default Chrome profile path is macOS `~/Library/Application Support/Google/Chrome`.
- Media download relies on `yt-dlp --cookies-from-browser chrome`.
