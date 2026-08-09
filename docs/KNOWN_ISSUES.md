# Known operating constraints and behavior-change history

Documentation version: `v1.0.0-codex.1`

## Current operating constraints

- X, Grok, and ChatGPT acquisition depends on already authenticated host browser sessions. Their
  remote pages, APIs, and anti-automation behavior can change independently of this project.
- The application deliberately binds to the LAN and has no authentication layer. It is suitable
  only for trusted local networks and must not be publicly exposed.
- X media acquisition relies on yt-dlp's browser-cookie integration. A browser, cookie-store, or
  yt-dlp compatibility change can block downloads even when the local web console remains healthy.
- Grok and ChatGPT caches retain local catalog and recovery state. A source-specific reset removes
  that state and cached media, so it is intentionally an explicit operator action.
- Browser deletion is recoverable only while its retained preview exists in `.browser-trash/`.
  Removing that preview outside the application prevents restoration.
- The default quality gate is fully offline and does not run an authenticated browser E2E test.
  Flask integration tests and JavaScript syntax checks protect the current baseline; a future E2E
  layer must use a seeded disposable runtime before it can enter CI.

## Quality and isolation foundation established on 9 Aug 2026

- Added a project documentation set covering architecture, testing, operations, and active
  constraints.
- Added one supported setup, launch, test, and quality-gate workflow under `scripts/`.
- Added GitHub Actions that calls the same quality gate used locally and preserves coverage output.
- Redirected pytest's default cache, log, settings, and browser-home paths into a temporary runtime
  before application modules load.
- Replaced the Grok snapshot helper's import-time path default with call-time resolution so test
  redirection cannot be bypassed by a frozen default argument.

Future behavior changes should add a concise dated entry here when they alter an operating
constraint, data-safety guarantee, or externally visible recovery contract.
