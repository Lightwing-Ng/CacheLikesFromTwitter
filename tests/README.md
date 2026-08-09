# Test Suite

Test-suite version: `v1.1.0-codex.1`

The authoritative test workflow, coverage baseline, isolation contract, and CI behavior are
documented in [docs/TESTING.md](../docs/TESTING.md). Use `./scripts/test.sh` for the normal
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

## Isolation Rules

`conftest.py` changes `HOME`, `CACHELIKES_RUNTIME_ROOT`, and `CACHELIKES_SETTINGS_PATH` before
application modules load. Filesystem tests use pytest temporary paths. Browser, Playwright,
yt-dlp, X, Grok, and network transport are replaced by fakes or mocks; no authenticated session
or user-owned local media cache is touched.

Run the full suite with `./scripts/test.sh`.
