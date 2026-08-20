# Test Suite

Test-suite version: `v1.2.2-codex.1`

The authoritative test workflow, coverage baseline, isolation contract, and CI behavior are
documented in [TESTING.md](TESTING.md). Use `./scripts/test.sh` for the normal
offline suite and `./scripts/check.sh` for the full quality gate.

## Coverage Map

- `test_config*.py` and `test_state.py`: persisted settings, account-name safety, startup
  hydration, task state transitions, and event retention.
- `test_cache_catalog.py`: canonical X URLs, local-media classification, Parquet catalog
  recovery, cache claims, and per-account summaries.
- `test_downloader.py`: yt-dlp output classification, browser cookie arguments, and retry
  behavior.
- `test_scraper*.py` and `test_scraper_and_browser_sessions.py`: X handle discovery,
  timeline payload parsing, GraphQL request templates, and browser-session parsers.
- `test_grok_downloader*.py` and `test_grok_storage.py`: media signature validation,
  catalog deduplication, timestamp recovery, manifest recovery, and durable Grok queue
  transitions.
- `test_service.py` and `test_services_and_web.py`: concurrent download orchestration,
  emergency-stop semantics, status summaries, Flask pages, APIs, settings, and reset routes.
- `test_logging_setup.py`: structured logging setup and JSON line output.
- `test_runtime_isolation.py`: process-wide pytest runtime redirection and the Grok
  snapshot default-path regression.
- `test_responsive_contract.py`: shared CSS and JavaScript breakpoints, independent compact-content
  and sidebar-overlay boundaries, global hidden behavior, and bootstrap load order.
- `test_sidebar_e2e.py`: disposable Chromium coverage for target iPhone, iPad, and desktop
  viewports, touch dismissal, viewport transitions, horizontal overflow, toggle hit testing,
  and the runtime Chinese language-boundary contract that preserves source text.

## Isolation Rules

`conftest.py` changes `HOME`, `CACHELIKES_RUNTIME_ROOT`, and `CACHELIKES_SETTINGS_PATH` before
application modules load. Filesystem tests use pytest temporary paths. The sidebar E2E suite uses
a clean disposable browser context against a local isolated Flask server. Authenticated browser
profiles, yt-dlp, X, Grok, remote network transport, and user-owned local media remain outside the
test boundary.

Run the full suite with `./scripts/test.sh`.
