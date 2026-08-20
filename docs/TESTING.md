# Testing guide

Documentation version: `v1.3.3-codex.1`

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
The resolver prefers a supported host `python3`, `python`, or Windows `py -3.13` launcher, then
falls back to known platform-specific Python
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

Baseline measured on 20 Aug 2026 with Python 3.13, pytest 9.0.3,
pytest-cov 7.1.0, and Ruff 0.15.21:

- 538 tests passed, with 301 unittest subtests passed.
- Combined coverage for `app/` was 64.37% using branch coverage.
- All 26 first-party JavaScript files passed syntax checks.

Raise the coverage floor only after adding behavior-level tests. Do not exclude production modules
or lower the threshold to mask a gap.

## CI portability contract

GitHub Actions is the canonical clean-room gate. It runs on `ubuntu-latest` with Python 3.13,
Node.js 22, UTC, and a freshly installed Playwright Chromium. A test that passes only on the
developer's macOS workstation is not evidence of a passing project contract.

Use this command to reproduce the CI timezone locally:

```bash
TZ=UTC CACHELIKES_PYTHON=/usr/local/bin/python3.13 ./scripts/check.sh
```

Tests must follow these rules:

- Do not hard-code local-time output such as `13:00`. Use UTC fixtures, the production formatter,
  or an explicit timezone in the assertion.
- Settings read/write helpers must resolve `CACHELIKES_SETTINGS_PATH` at call time. Do not use a
  module-import snapshot as a function default, because pytest and clean-room CI inject the
  process boundary before application startup.
- Do not hard-code `Finder`, `open -R`, or macOS permission messages in a host-neutral test. Test
  each platform through explicit platform arguments or monkeypatch the host predicate when the
  test is specifically for macOS or Windows.
- The yt-dlp cookie-source mapper may return the explicit `safari` backend on every CI host;
  browser automation remains host-aware and must still reject Safari where the runtime registry
  does not expose it.
- Overlay sidebars must use an explicit viewport-bounded height with internal scrolling. Do not
  rely on intrinsic fixed-position height on touch viewports, because Chromium implementations
  can report a transient bottom edge outside `window.innerHeight`.
- When `prefers-reduced-motion: reduce` is active, the sidebar shell, overlay, and toggle must
  disable their transitions entirely. The JavaScript state timer may remain short for bookkeeping,
  but the geometry used by touch hit testing must already be final when the state attribute changes.
- DOM observers must not continuously observe attributes that their callbacks write on every pass.
  Observer-backed controls must make attribute, class, and style updates idempotent, and a static
  contract test must pin the observed attribute set.
- Keep filesystem, browser-profile, and subprocess tests inside `tmp_path` or an explicit fake
  platform boundary. Never inspect the runner's real browser profile or file manager.
- Browser E2E tests must use a clean context and local Flask server only. Disable or stub unrelated
  background polling when the test injects a DOM fixture; otherwise the application may replace
  the fixture during the assertion.
- For responsive geometry and hit testing, wait for the relevant rectangle to become stable before
  asserting `document.elementFromPoint()`. Reduced motion shortens transitions but is not a promise
  that a DOM update is synchronous.
- Keep live, authenticated, and remote-service checks under `@pytest.mark.live`; they do not belong
  in the default quality gate.

When a gate fails on GitHub, reproduce the exact failing node first with `TZ=UTC`, then run the
complete `./scripts/check.sh`. Do not weaken an assertion, skip a platform branch, lower coverage,
or add a retry until the failure has been classified as a real product regression or a test
environment assumption.

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
  They cover touch input, backdrop dismissal, viewport transitions, real hit testing through
  `document.elementFromPoint()`, and the shared Chinese language boundary across startup and
  dynamic DOM mutations. The language test checks source-text preservation, `:lang(zh-CN)`
  matching, and the macOS-oriented glyph fixture without converting Unicode text.

The current detailed module-to-behavior map is maintained in [TEST_COVERAGE.md](TEST_COVERAGE.md).

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
