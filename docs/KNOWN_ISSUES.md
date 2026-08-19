# Known operating constraints and behavior-change history

Documentation version: `v1.1.2-codex.1`

## Agentic provider audit and Grok Auto follow-up limitation on 19 Aug 2026

- The canonical Agent URL now preserves the selected browser and Web provider, such as
  `/agent/edge/chatgpt`; Edge tasks use an isolated offscreen, minimized clone and restore the
  persisted default to Edge + ChatGPT after provider-specific audits.
- Switching the Agent provider now resets a stale previous-provider target URL before official-host
  validation. Grok's live textarea and Submit control also have a bounded Enter fallback for a
  briefly absent follow-up button.
- Real named `08.19 Agentic` Edge tasks completed ChatGPT and Gemini read-only audits with
  `bodycheck`. Grok opened the signed-in conversation and completed its first read action, but
  Grok Auto stayed in a long second-turn thinking state in two bounded audits; the task was
  stopped safely and must not be presented as a complete Grok audit.

## Touch-safe iPad sidebar contract established on 12 Aug 2026

- Sidebar overlay behavior now extends through `900 px`, while compact content remains limited to
  `600 px`. iPad portrait layouts therefore use the overlay interaction without inheriting the
  phone content layout.
- CSS and JavaScript consume one semantic breakpoint registry. A new overlay session starts with
  the sidebar closed, while an explicit `sessionStorage` choice remains stable across viewport
  transitions.
- The overlay sidebar and 44 × 44 CSS px toggle use safe-area-aware fixed geometry. The toggle is
  above the transparent backdrop, fixed notices, sidebar title, and dock; closed sidebar and
  backdrop states cannot receive pointer input.
- `[hidden] { display: none !important; }` is now a global contract. A hidden backdrop cannot be
  reactivated by a later responsive `display` declaration and therefore leaves layout, paint, and
  hit testing together.
- The toggle is rendered as a direct child of the page rather than inside the app shell. This
  keeps its touch layer independent from Safari's fixed-position stacking behavior while the
  backdrop remains inside the shell beside the sidebar.
- The quality gate now runs a seeded local Chromium E2E suite in a disposable browser context. It
  validates target phone, iPad, and desktop viewports without reading an authenticated profile.

## Current operating constraints

- X, Grok, and ChatGPT acquisition depends on already authenticated host browser sessions. Their
  remote pages, APIs, and anti-automation behavior can change independently of this project.
- The application deliberately binds to the LAN. Cache and Local resources routes do not have a
  login layer, while the Agent control plane requires its six-digit password for private-network
  requests. The application remains suitable only for trusted local networks and must not be
  publicly exposed.
- X media acquisition relies on yt-dlp's browser-cookie integration. A browser, cookie-store, or
  yt-dlp compatibility change can block downloads even when the local web console remains healthy.
- Grok and ChatGPT caches retain local catalog and recovery state. A source-specific reset removes
  that state and cached media, so it is intentionally an explicit operator action.
- Browser deletion is recoverable only while its retained preview exists in `.browser-trash/`.
  Removing that preview outside the application prevents restoration.
- The default quality gate remains local-only and does not use authenticated browser state. Its
  sidebar E2E layer requires Playwright-managed Chromium, Chrome, or Edge to be installed.

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
