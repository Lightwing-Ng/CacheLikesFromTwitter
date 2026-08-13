# Testing guide

Documentation version: `v1.2.0-codex.1`

## Supported commands

Install the runtime and development dependencies with the supported Python 3.13/3.14 workflow:

```bash
./scripts/setup_python.sh
```

Run the ordinary offline suite:

```bash
./scripts/test.sh
```

Run a focused test or marker selection:

```bash
./scripts/test.sh tests/test_local_media_browser.py
CACHELIKES_TEST_MARK_EXPRESSION=integration ./scripts/test.sh
```

The default marker expression is `not live`. Run an intentionally manual live check only with an
explicit override, for example `CACHELIKES_TEST_MARK_EXPRESSION=live ./scripts/test.sh`.

Run the complete quality gate:

```bash
./scripts/check.sh
```

Run the responsive contract and sidebar browser layers independently with:

```bash
./scripts/test.sh tests/test_responsive_contract.py
./scripts/test.sh tests/test_sidebar_e2e.py
```

`CACHELIKES_PYTHON` may override the interpreter only when it resolves to Python 3.13 or 3.14.
The resolver prefers the supported host `python3`, then falls back to known macOS Python
installations.

## Quality gate

`scripts/check.sh` is the single local and CI quality command. It runs, in order:

1. Ruff static checks over `main.py`, `app/`, and `tests/`.
2. `node --check` for every first-party JavaScript file in `app/web/static/`.
3. The full pytest suite with branch coverage for `app/`, including the disposable-browser
   responsive sidebar E2E flow.

The coverage report is written to `test-results/coverage.json`; all generated test artifacts are
ignored by Git. The gate currently enforces a 55% combined statement-and-branch coverage floor.
Override `CACHELIKES_COVERAGE_MINIMUM` only for an intentional local diagnostic, never to make a
regression pass.

Baseline measured on 12 Aug 2026 with a supported Python 3.13/3.14 runtime, pytest 9.0.3,
pytest-cov 7.1.0, and Ruff 0.15.21:

- 262 tests passed, with 149 unittest subtests passed.
- Combined coverage for `app/` was 64.46% using branch coverage.
- All 12 first-party JavaScript files passed syntax checks.

Raise the coverage floor only after adding behavior-level tests. Do not exclude production modules
or lower the threshold to mask a gap.

## Test organization

- Pure unit tests cover URL normalization, source parsing, media classification, state
  transitions, durable queue behavior, retries, and path validation.
- Filesystem regression tests use `tmp_path` or `TemporaryDirectory` for catalogs, manifests,
  media files, deleted previews, and settings.
- Flask integration tests use `create_app()` plus `test_client()` and assert route contracts
  without starting a web server.
- Computer Use Agent tests build context packages in temporary projects, execute the controller
  through deterministic actions, and replace the signed-in browser runner with a fake.
- Style-token, template, and responsive-contract tests protect durable UI boundaries directly.
- Sidebar E2E tests start an isolated local Flask server and a clean headless Chromium context.
  They cover touch input, backdrop dismissal, viewport transitions, and real hit testing through
  `document.elementFromPoint()`.

The current detailed module-to-behavior map is maintained in [tests/README.md](../tests/README.md).

## Isolation contract

`tests/conftest.py` runs before application test modules are imported. It redirects all default
runtime locations to process-scoped temporary directories:

- `HOME` keeps settings and browser-profile defaults away from the user account.
- `CACHELIKES_RUNTIME_ROOT` moves default local caches and logs away from the repository.
- `CACHELIKES_SETTINGS_PATH` redirects persisted settings.

Default tests must not:

- open an authenticated Chrome, Edge, Safari, or Playwright profile;
- make X, Grok, ChatGPT, yt-dlp, or general network requests;
- read, copy, delete, reset, or restore a user-owned cache, log, setting, or browser profile;
- submit a real background cache job.

Mock external boundaries at the module that invokes them. Existing patterns mock
`sync_playwright`, `launch_chromium_context`, `subprocess.run`, `urlopen`, the scraper, and
source download functions. Do not replace a lower-level implementation when the route or service
boundary is the behavior being tested.

## Markers

- `integration`: Flask tests that cross module boundaries and remain fully offline.
- `slow`: Tests materially slower than the unit-test median.
- `live`: Explicit manual checks that require a signed-in browser or a remote service. These never
  belong in CI or the default quality gate.

The sidebar E2E layer may use Playwright-managed Chromium or an installed Chrome or Edge binary,
but always launches a clean browser context without a user-data directory. Its Flask server uses
the same process-scoped temporary runtime as the rest of pytest. Browser tests must retain both
isolation properties and must never navigate to an external service.

## Writing a new test

1. Put the test beside the behavior it protects under `tests/test_<area>.py`.
2. Prefer a public behavior or invariant over assertions about incidental implementation details.
3. Use a temporary filesystem location for every test-owned file.
4. Use the `client` fixture for route contracts and preserve the injected runtime boundary.
5. Add a marker only when it accurately describes the test's cost or boundary.
6. Run the focused test, then `./scripts/check.sh` before handoff.
