# Known operating constraints and behavior-change history

Documentation version: `v1.13.0-codex.1`

## Four-provider Agent pre-transfer hardening on 27 Aug 2026

- ChatGPT, Gemini, Grok, and Claude now all fail closed when the configured remote model cannot be
  read back. The failure occurs before context attachment and prompt submission, and the diagnostic
  explicitly states that no project data was sent. Regression coverage proves zero attachment and
  zero submission for ChatGPT `GPT-5.6 Sol`, Gemini `Gemini 3.1 Pro`, Grok `Auto`, and Claude
  `Auto` failures. Claude accepts only the literal `Auto` label; `Default` and the brand name
  `Claude` are not model readbacks.
- An `Auto` model readback now requires both popup behavior and explicit model, mode, or
  provider-model metadata. An unrelated popup button whose visible text is merely `Auto` cannot
  satisfy Grok or Claude model verification; English metadata uses token boundaries so strings such
  as `modern`, `breakfast`, and `octopus` cannot impersonate `mode`, `fast`, and `opus`. The real
  Grok `Model select` trigger remains accepted.
- Gemini readiness distinguishes account authentication from provider availability. If the signed-in
  page reports that Gemini is unavailable in the selected browser's current region, both the direct
  readiness helper and the shared browser-status API fail closed, Ask remains disabled, and no
  project context is transferred. English, Simplified Chinese, and Traditional Chinese landing-page
  copy are recognized. The Agent rechecks this terminal state while waiting for the composer and after
  a missing-model-control wait, closing the skeleton-composer race without treating conversation text
  as a region failure.
- Gemini's current menu renders `3.1 Pro` with an `Advanced reasoning` subtitle and shortens the
  closed trigger to `Pro`. Selection therefore resolves only the exact controlled menu, matches the
  visible primary `.label` to the sole UI value `3.1 Pro` rather than a brand-prefixed alias, observes
  the menu close, and then supports the provider's normal
  unmount/remount cycle by resolving the same controlled ID again. The trigger itself may also be
  replaced; before each click or readback, exactly one live trigger must retain the original
  `aria-controls` value. Readback requires both the `selected` class and a visible `Selected` marker
  before the menu is closed and confirmed hidden. A bare `Pro` trigger, duplicate trigger, subtitle
  or wrapper match, hidden proof, nested popup, unselected option, or unconfirmed close remains
  fail-closed.
- Gemini may render a usable composer several seconds before its model control finishes hydrating.
  The Chromium controller now selects the matching provider tab first and retries only a missing
  model control for about 15 seconds in Stop-aware 250 ms slices. A fully loaded page with unrelated
  visible buttons no longer causes a premature failure. All ambiguous or invalid control states,
  readback mismatches, and closure failures still fail immediately before data transfer. Persisted
  missing-control diagnostics contain only bounded state and element counts plus fixed menu-role
  values; remote page titles and arbitrary visible button text are excluded.
- Gemini Notebook discovery rejects the provider's `create` and `new` route aliases while reading
  the live DOM and at the source-catalog API boundary. Even a fresh in-memory or Parquet cache hit is
  revalidated before response, so those actions cannot be relabeled as Projects or normalized to
  invalid `/app/create` and `/app/new` targets.
- Non-ChatGPT model selection runs through the same linearized Stop gate as other browser side
  effects. A Stop already accepted prevents DOM inspection or clicks; a concurrent Stop is ordered
  against the bounded selector operation before it is published. Failed readback diagnostics retain
  the observed trigger text and no longer imply that an unverified remote model will be used.
- The browser-status cache is terminal only for a fresh positive authenticated result. A fresh
  negative result is displayed while a new probe runs, and an explicit refresh always bypasses the
  cache. Chromium coverage starts with a fresh signed-out Gemini cache row, proves an immediate
  authenticated retry enables Ask, and proves a subsequent forced refresh starts another request.
- The 27 Aug 2026 host Edge validation first reproduced `ERR_CONNECTION_TIMED_OUT`, then reached
  Gemini's Simplified Chinese current-region-unavailable landing page after refresh. The exact
  connection-timeout marker is now included in the shared bounded navigation retry contract. The
  provider-region state remains an external operating constraint: the controller must keep Ask
  disabled and must not attach project context or submit a prompt until that same Edge session can
  access Gemini normally.

## Grok Agent session binding and readiness hardening on 26 Aug 2026

- Fresh Grok runs treat only the normal home-to-`/c/<id>` transition as a candidate new session. The
  latest visible user message must also echo that run's high-entropy transfer ID, and the receipt URL
  must survive an immediate canonical recheck before the controller binds it. Project sessions
  preserve both Project ID and `chat` identity; root chats, cross-Project chats, same-Project old-chat
  switches, composer-only markers, and receipt URL drift fail closed before any local action.
- Before a fresh root or Project submit, Grok's complete same-scope conversation catalog is captured
  as a denylist. Invalid rows, incomplete schemas, repeated cursors, and pagination overflow fail
  closed; a pre-existing conversation cannot become the run's new session even if it later echoes
  the current transfer ID. Fresh runs do not upload context before this binding completes.
- Grok Agent readiness uses the signed-in home-page message composer and collects the initial source
  catalog in the same Edge or Chrome context. It additionally requires an authenticated Grok
  conversations request, and visible login or account-creation actions fail even when an anonymous
  composer is present. The cache-oriented `/files` probe remains separate.
- Grok `Auto` matching rejects compound controls such as `Auto-play`, requires a semantic model
  trigger, and limits choices to its opened menu, listbox, or dialog. Finding or clicking a menu item
  is not a successful readback; the selector trigger must expose the chosen label after the click.
- A fresh signed bootstrap supersedes stale cached source data or errors before loaded/loading guards
  execute and invalidates the older request. Grok Project fallback rows must use the selected
  Project's own `?chat=<id>` URL. Gemini Notebook aliases converge on one typed `/app/<id>` identity
  and remain receipt-gated for a Project-new run. Existing Gemini Notebook session ownership cannot
  be proven, so the Project-session catalog is empty and execution accepts only New session in project.
- The browser-status controller ignores both success and failure from a request whose browser or
  provider is no longer selected. A delayed ChatGPT failure therefore cannot overwrite a newer Grok
  ready state in the same Edge selector.
- Completed Agent snapshots are displayed only when both their provider and browser match the
  canonical route. A mismatch is rendered as an idle, empty task on the server's first frame and in
  later polling updates; provider or browser changes also clear the composer. This prevents an old
  ChatGPT prompt, activity log, or response from being relabeled or resubmitted as a Grok task.
- Send checks the official host and exact selected target in the same page evaluation that clicks
  the button. Fresh unbound Grok runs disable the non-atomic Enter fallback; reused or bound Grok
  sessions check Stop immediately after the DOM send-button scan. A Stop
  accepted during that scan therefore returns without sending the next observation.
- After the final 8666 restart, both the isolated Edge production probe and a fresh host Edge tab
  remained at Grok's Cloudflare `Verify you are human` security page. The controller correctly kept
  Ask disabled and transferred no project context. The operator must complete the provider-required
  browser verification; this project does not automate or bypass that external security boundary.

## Agent Web execution safety contract established on 24 Aug 2026

- Every provider now fails closed before project-data transfer: the visible compatible model
  control must read back the configured model before the controller attaches context or sends a
  prompt. A missing or ambiguous selector stops the run instead of retaining an unverified remote
  model.
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
- The macOS idle-sleep assertion is bound to the service PID through `caffeinate -w`. Worker
  completion and service shutdown atomically claim one shared assertion, the shutdown hook releases
  an unclaimed assertion after its bounded worker wait, and a registration arriving after shutdown
  immediately attempts to release it. Assertion startup and registration exceptions now enter the
  same completion path instead of leaving a stale `running=true` snapshot. Closing the lid, choosing
  Sleep, or ending the service can still interrupt the Web task, but the assertion cannot outlive the
  service PID.
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
