# Known operating constraints and behavior-change history

Documentation version: `v1.3.3-codex.1`

## Agent Web execution safety contract established on 24 Aug 2026

- ChatGPT now fails closed before project-data transfer: its visible Model submenu must read back
  `GPT-5.6 Sol` or `5.6 Sol` before the controller attaches context or sends a prompt. Gemini, Grok,
  and Claude retain their best-effort model-selection behavior; a missing compatible selector keeps
  the selected session's current remote model and reports the limitation.
- A Chromium attachment is accepted only when the composer visibly exposes the exact context
  filename. A missing filename or reported upload failure falls back to bounded on-demand reads
  instead of claiming that the package was attached.
- Controller discovery now excludes recognized credential, environment, cookie, and private-key
  paths. `search` is literal-only in both the bounded fixed-string `rg` path and its project-confined
  Python fallback. `run` rejects direct `rg`, network or out-of-project targets,
  and mutating or unbounded flags; a bounded project fingerprint also detects command-side writes,
  fails that verification, and makes the prior bodycheck stale.
- Agent-scoped `/api/browser-session` requests now pass through the same network, Host, Origin, and
  password gate as the rest of the control plane. Admitted responses carry `no-store`, `Pragma`,
  and expired `Expires` headers.
- The service atomically persists only bounded run metadata through a same-directory unique temporary
  file. POSIX runtime directories and snapshots use `0700` and `0600`; Windows additionally depends
  on the configured application-data directory's inherited ACL. Prompt bodies, responses,
  conversation history, source text, and error stacks are not stored in that snapshot. Task context
  removal, including new-session contexts, is attempted on every exit path. Startup also removes
  unreferenced app-owned timestamp contexts, rejects linked or junction-backed runtime ancestors,
  metadata, run directories, hard-linked context files, and FIFO/device/socket persistence inputs,
  and blocks the next task on any cleanup-boundary failure rather than following or reading them.
- A synchronous worker-thread launch failure is committed as `failed` with `running=false` before
  the start error returns. Stop therefore remains unavailable for a worker that never existed, and
  the next valid task is not blocked by a stale `starting` or `stopping` snapshot.
- macOS and Windows prompts share the same complete 10-action JSON schema. Prompt migrations preserve
  custom guidance and use an owner-only, `fsync`-backed atomic settings replacement so a failed write
  cannot truncate the previous configuration.
- Stop is checked during Safari composer/send polling and Chromium navigation retries. The exception
  completion barrier reads Stop under the lifecycle lock, so an accepted Stop remains `stopped` and
  clears stale error or handoff state even when a synchronous browser error returns afterward.
- Structured console and JSON-line logging redact recognized browser credentials across messages,
  fields, exceptions, and stack traces. Active and rotated log files use mode `0600`. Chromium
  context cleanup ignores only known already-closed or driver-disconnected second-close errors,
  still removes the cloned profile, and propagates unexpected close failures.

## Agentic failure handoff to traditional Edge on 20 Aug 2026

- A normal ChatGPT browser window cannot perform project-confined local file actions, so it is not
  treated as a successful Agent replacement. When an Edge and ChatGPT controller run fails after the
  exact conversation URL is known, the service now opens that same conversation through normal Edge
  with macOS background activation, keeps the Agent phase failed, and marks local edits and bodycheck
  unfinished.
- The response toolbar expands to `Continue in Edge`, and explicit conversation opening targets the
  browser selected for the task instead of the system default. The automatic Edge path creates a
  normal window through Edge's AppleScript model without calling `activate`, leaving the current
  foreground application unchanged while macOS controls Stage Manager grouping.

## ChatGPT Agent rendered-action and history retry recovery on 19 Aug 2026

- The latest failed ChatGPT Agent run returned action strings containing quotes, backslashes, and CSS comment
  delimiters. Reading the bare JSON through rendered Markdown removed significant characters, after which four
  format attempts failed. Agent actions now use fenced `json` transport and prefer the literal code-block text.
- The selected-session history route also observed a transient TLS disconnect while reading `/api/auth/session`.
  Session authorization now reuses the bounded ChatGPT API retry path instead of surfacing that first disconnect
  as an HTTP 500 response.

## Agent action recovery and response typography on 19 Aug 2026

- A prompt that asks the Agent response node to use the sibling `--font-size-5` token now applies
  `font-size: var(--font-size-5)` to `.agent-response-answer-content`, updates the CSS cache-buster,
  and has a focused style contract. If a provider repeats multiple complete candidates with the same
  controller action, the local loop keeps the final candidate instead of exhausting format retries.
- Candidates with different action names remain rejected so an ambiguous provider response cannot perform
  an unintended operation.

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
