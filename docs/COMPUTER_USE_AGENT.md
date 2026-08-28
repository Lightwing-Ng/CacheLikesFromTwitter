# Web Computer Use Agent

Documentation version: `v3.43.0-codex.1`

## Purpose

The Agent workspace is a browser-mediated fallback for times when the local coding-agent token
pool is constrained. It uses an already signed-in Web session for ChatGPT, Gemini, Grok, or Claude, with
Edge or Chrome as the supported background Chromium browsers. ChatGPT also remains available in
Safari for the existing session flows. Edge is the default because its Chromium controller does
not depend on desktop clicks; Chrome uses the same isolated controller.

The default is a new root-level session. Every provider can also join one of the 20 most recent
sessions or start a session in one of the 20 most recent Projects. ChatGPT, Grok, and Claude can
also join one of that Project's 20 most recent sessions. Gemini Notebook session ownership cannot
be proved from its current Web routes, so Gemini Projects fail closed to `New session in project`.
For Gemini, that mode starts a receipt-isolated controller task on the selected Notebook surface;
it does not prove that Gemini created a distinct provider-side subconversation.
The adapter maps ChatGPT Projects, Gemini Notebooks, Grok Projects, and Claude
Projects to the same Project contract, so the Agent UI and execution loop do not expose
provider-specific container names. Claude source discovery reads rendered links only and does not
call a Claude API or extract credentials. A run-scoped `session_title` is preserved as the local session label and included
in the first provider message; the provider may still choose its own remote conversation title. The
selected Web provider supplies reasoning; a bounded local controller
performs project actions and returns compact observations to the same conversation.

The recent-session, Project, and Project-session catalogs use one shared read-through Parquet cache
under `local_store/agent/agent_source_catalog.parquet`. The cache key isolates provider, browser,
catalog kind, and Project URL. Fresh entries are reused from process memory for 15 minutes; the
first process read hydrates that memory from Parquet. After expiry, passive requests immediately
serve the last catalog while one background refresh runs per key. Add `refresh=1` to the relevant
`/api/agent/sources` or `/api/agent/project-sessions` request when a synchronous browser re-check
is required. If that refresh fails and an older entry exists, the API returns the older catalog
with `cache.status: "stale"` so the selector remains usable and the condition stays observable.

On `/agent`, ChatGPT, Grok, and Claude use an agent-scoped bootstrap request: the selected browser
context verifies the actual Web composer and collects Recent sessions and Projects in one launch.
Grok readiness is verified on `https://grok.com/`; it does not depend on the separate `/files`
download surface or account-label scraping. A visible composer is necessary but not sufficient:
the same browser context must also complete one authenticated Grok conversations request, and any
visible login, signup, or account-creation action fails closed. The status payload carries the
catalog directly to the selector and seeds the shared L1 and Parquet L2 cache. A fresh bootstrap
supersedes older in-memory or session-storage catalog state before loaded/loading guards run,
aborting and invalidating any older request. The page therefore does not open a second browser for
the Recent sessions step. Loading sessions inside a selected Project remains a later, separately
keyed operation. Grok's DOM fallback exposes only same-Project `?chat=<id>` sessions.

This route uses no provider developer API, command-line coding-agent runtime, MCP connection, or
third-party agent bridge. Readiness and catalog discovery may call the provider's own authenticated
Web endpoints inside the cloned browser context.
ChatGPT plan limits, file-upload limits, data controls, storage, and retention still apply.

## Canonical navigation

The Agent entrypoint is scoped by the selected browser and Web provider. The canonical form is
`/agent/<browser>/<platform>`, such as `/agent/edge/chatgpt` or `/agent/edge/claude`; `/agent/<browser>/`
is a browser-scoped compatibility alias, and the legacy `/agent` path redirects to
the persisted selection. Changing either selector updates the canonical path without reloading the
page, so a copied URL preserves the intended Edge/ChatGPT selection.

Completed UI state is bound to both the provider and browser recorded by the run. Opening or
switching to another canonical route renders an idle phase with an empty activity list, response,
and composer instead of relabeling an older provider's result. The API keeps the global persisted
snapshot for recovery, but the server-rendered first frame and subsequent client polling both apply
the same provenance check. Changing the provider or browser also clears the current composer so an
older task cannot be submitted accidentally through a different Web session.

## Execution loop

1. Select one local project, a Web provider/model, and an authenticated browser on the canonical
   Agent route.
   Configure the operating system in Settings → Agent; the setting detects the host and selects
   macOS or Windows automatically. If local permissions are needed, explicitly use `Open terminal
   permissions` in Settings → Agent. macOS opens Full Disk Access for the Terminal that starts
   the service; Windows requests PowerShell administrator authorization through UAC. Automatic
   detection never opens an authorization surface.
   The browser status card also reports whether the host Terminal or PowerShell executable is
   available and the selected project currently grants read, write, and directory-entry access.
2. Keep `New session` or choose a recent session/Project and, for a Project, either
   `New session in project` or one of its recent sessions. A completed run refreshes the
   session catalog and keeps the Open conversation link, but it does not switch the page
   off `New session` or write a conversation URL into the next submit. Reuse requires an
   explicit user selection that is present in the latest catalog.
3. Enter a task. The service validates the selected provider's official URL and opens it in the
   selected browser profile. When a request switches away from the persisted provider, the service
   resets a stale previous-provider target URL to the new provider's official home before
   validation.
4. Before attaching project data or submitting a prompt, every provider must expose a compatible
   model control and visibly read back the configured model. ChatGPT must prove `GPT-5.6 Sol` or
   `5.6 Sol`, Gemini must prove `Gemini 3.1 Pro`, Grok must prove `Build`, and Claude must prove
   `Auto`. A missing,
   changed, localized, or ambiguous selector fails closed without attaching context or sending a
   prompt. Only exact model labels and explicit model or mode selector wrappers are accepted;
   compound controls such as `Auto-play`, subscription labels such as `SuperGrok Build plan`, and
   unrelated popup buttons whose text happens to match a model label are rejected. An `Auto`
   trigger must expose popup semantics plus model, mode, or
   provider-model metadata. English metadata is matched as complete tokens, so unrelated identifiers
   such as `modern-theme`, `breakfast-options`, or `octopus-picker` cannot satisfy `mode`, `fast`,
   or `opus`. The current Grok `Model select` trigger is an accepted explicit model
   wrapper. After a click, the selector itself must read back the chosen model before the run can
   publish `model_verified=true`. Gemini is the narrow exception because its current trigger shortens
   `3.1 Pro` to `Pro`: the controller resolves only the exact `aria-controls` menu, requires a
   visible primary `.label` equal only to the UI label `3.1 Pro` rather than a brand-prefixed alias,
   observes that selection closed the menu, reopens a
   freshly resolved node with the same ID, and requires both the provider's `selected` class and its
   visible `Selected` marker. Both the controlled menu and its trigger may be replaced during normal
   open and close transitions; the controller therefore resolves exactly one live trigger with the
   original `aria-controls` value before every click and readback. Nested popups, duplicate triggers,
   subtitles, wrappers, hidden labels or markers, and the shortened trigger alone never prove the
   configured model. Every exit either confirms that the controlled menu is closed or fails the run.
   Chromium first reuses the matching official provider tab, without focusing it, before navigation.
   Some provider shells expose a composer before their model picker has hydrated. A missing
   non-ChatGPT model control is therefore rechecked up to 61 times in 250 ms Stop-aware slices, for a
   maximum wait of about 15 seconds. Only `model-control-not-found` is eligible for this outer wait;
   an ambiguous control, invalid surface, unavailable option, failed readback, or unproved menu close
   still fails immediately. The wait changes only when proof is attempted, not what counts as proof.
   Gemini's account and region state is rechecked throughout composer readiness and after a missing
   model-control wait, so a late English, Simplified Chinese, or Traditional Chinese region-unavailable
   landing page is reported as a provider availability failure rather than a model mismatch. Gemini's
   anonymous shell can expose both a composer and conversation-shaped links; a visible exact sign-in
   action without a visible Google Account control therefore remains signed out. Its model menu's
   exact `Sign in for all models` barrier is a second pre-transfer check and is never clicked as if it
   were a model option. Grok uses only the exact visible `#model-select-trigger` whose accessible
   name is `Model select` and whose popup type is `menu`. Trusted Playwright clicks open its exact
   `aria-controls` surface; the selected candidate must be one exact `Build` or `Build Beta`
   `menuitemradio` owned directly by that menu. The controller then reopens the menu and requires
   both `aria-checked="true"` and `data-state="checked"`, closes it, and requires the trigger to
   read back `Build Beta`. Nested menus, upgrade dialogs, duplicate controls or options, disabled
   choices, and unknown overlays fail closed. Only the exact `Meet Grok Bot` and `Introducing Build
   Mode` onboarding dialogs may be dismissed, through one visible enabled exact `Dismiss` button;
   no forced click is used.
   Missing-control hydration diagnostics retain enumerated readiness and element counts, but never
   persist the remote page title or arbitrary visible DOM text.
   Chromium composer readiness is polled in 250 ms slices so Stop can terminate the initial page
   verification before model selection, context attachment, or prompt submission. Its single
   recovery reload waits only for navigation commit and is capped at five seconds. Stop is checked
   again before and throughout eligible reused-session context attachment, after attachment state publication, and before
   prompt submission; Chromium submitters also return before reading or filling a composer when a
   stop is already pending. Grok's bounded Enter fallback is unavailable for an unbound fresh run;
   a reused or already bound session rechecks Stop after its last DOM send-button scan and before
   pressing Enter, so a Stop accepted during that scan cannot submit another controller observation.
   Gemini CAPTCHA and Grok Cloudflare or human-verification interstitials are detected separately
   from conversation text. A visible challenge control always pauses; marker-only detection also
   requires the normal composer to be unavailable, so a prompt or response that mentions a CAPTCHA
   cannot self-trigger the pause. The controller surfaces the same isolated Chromium clone once,
   preserves the outstanding submit, and waits for both the challenge to clear and an explicit
   Resume. Stop remains effective, provider deadlines exclude the paused interval, and the clone's
   prior off-screen or minimized bounds are restored after the pause ends.
5. The service builds one owner-readable Markdown context package containing the request,
   repository instruction files, a bounded file index, dirty-worktree status, and project entry
   files. Credential locations, environment files, cookie stores, and private-key formats are
   excluded from the file index and controller access.
6. Fresh root and Project runs do not attach the package before the new provider conversation is
   bound; they stream bounded context through controller reads on demand. Reused sessions may attach
   the package directly when the selected provider exposes a file input.
   The controller treats the upload as accepted only after the composer visibly reads back the
   exact context filename; a populated hidden file input alone is insufficient. If the filename
   never becomes visible or the page reports an upload failure, the run continues without claiming
   an attachment and requests only the bounded files needed for subsequent actions. After a
   confirmed attachment or that on-demand fallback, the controller identifies exactly one visible,
   enabled provider composer outside dialogs, menus, navigation, headers, and feedback surfaces.
   It fills that exact element, reads back the complete prompt, and then clicks only a semantic Send
   control in the same bounded chat scope. Every Gemini, Grok, or Claude turn carries a high-entropy
   receipt that must remain in the latest visible user turn through response attribution. A challenge
   or remount before Send can safely refill the still-uncommitted prompt; once a click or Enter may
   have committed, recovery verifies the receipt and never sends that turn again. In the same browser
   evaluation that clicks Send, the controller first checks the official host and exact selected
   landing or bound conversation identity; a tab switch to an old conversation therefore cannot race
   the final click. Grok accepts its known `chat-submit` control or a semantic chat composer and
   bounded Send pair; if that control is briefly absent after a follow-up observation, the controller
   falls back to pressing Enter and still verifies the per-turn receipt.
   For every fresh root or Project run, the first prompt also contains a high-entropy transfer ID. The
   controller binds the new conversation only when the latest visible user message outside the
   composer echoes that ID and the URL atomically observed with the receipt still matches a second
   canonical URL read. This proves where the transfer landed; before a fresh Grok submit, the
   controller additionally enumerates the complete root or selected-Project
   conversation catalog. Pagination loops, malformed rows, repeated cursors, and incomplete schemas
   fail closed, and a conversation present in that pre-submit baseline cannot be bound even if it
   later displays the current transfer ID. Gemini does not expose an equivalent complete pre-submit
   conversation catalog, so its transfer receipt does not independently prove that the destination
   was absent from the account beforehand. The binding wait is bounded and Stop-aware; no local
   controller action executes before it succeeds. Gemini
   Notebook routes converge on their typed `/app/<id>` identity and use the same receipt gate even
   when the provider remains on that URL.
7. The selected Web provider returns exactly one JSON action at a time inside a fenced `json` code block so
   rendered Markdown cannot consume action quotes, backslashes, asterisks, or source-code delimiters. The
   controller prefers that code block's literal text and supports `list`, `read`, `search`, `replace`, `write`,
   `run`, `bodycheck`, and `final`. If a provider emits multiple complete
   candidates with the same action name in one response, the controller uses the final candidate in textual
   response order; mixed action types remain rejected as ambiguous.
   `search` uses project-confined `rg` when available, with structured UTF-8 JSON output, a 2 MiB
   file-size cap, an 8,000-character single-line literal-query cap, and case-insensitive root and
   recursive command-layer exclusions for ignored,
   runtime-internal, and sensitive paths. Ripgrep's external config and symlink following are
   explicitly disabled, an end-of-options marker keeps option-shaped queries literal, and raw
   diagnostics are never returned to the Web provider. A second output filter applies the same
   ignored, sensitive, path, and glob rules as the Python fallback. Structured path fields avoid
   delimiter ambiguity in legal filenames containing colons. Ripgrep searches hidden and normally
   ignored safe project files while symlinks remain unfollowed.
   Native paths, including ripgrep's leading `./`, are normalized to the fallback's workspace-relative
   output form without rewriting legal POSIX backslashes. Explicit file globs match basename,
   workspace-relative paths, and search-root-relative paths, so `path=app` plus `glob=core/*.py`
   stays consistent across engines. The controller accepts the common literal, separator, `*`, `?`,
   and `**` glob subset and rejects negated, brace-expansion, and character-class patterns whose
   ripgrep and Python meanings can diverge. Windows glob matching normalizes separators and case;
   POSIX keeps a literal backslash literal. Ripgrep output is consumed through a bounded queue and the
   process is stopped on Stop, after the global result or raw-event limit, or after 30 seconds;
   individual returned lines are also bounded. If the service cannot launch `rg`, a bounded Python
   literal-text fallback skips ignored, symlinked, sensitive, and oversized files and still
   enforces the requested path, glob, result, file-count, and time limits.
8. A malformed non-JSON reply receives up to three strict-format corrections that repeat the fenced JSON and
   escaping contract without spending the
   configured controller-action budget. This keeps a recoverable web-model formatting lapse from
   prematurely ending a valid task, while still bounding retries.
9. After an edit, the controller rejects a final answer until at least one approved verification
   command and `bodycheck` both succeed for the current edit generation. If an
   Edge and ChatGPT run still fails after an exact conversation URL exists, the service preserves the
   failed state and opens that same conversation in the user's traditional Edge browser with macOS
   background activation. The local page exposes a `Continue in Edge` handoff instead of claiming
   completion. A traditional ChatGPT window can continue the conversation, but it cannot perform or
   verify local file actions through this controller; local edits and bodycheck therefore remain
   unfinished.
10. The local page renders the final Markdown and links to the selected Web conversation in the
   browser encoded by the task, rather than the system default browser. When a
   ChatGPT recent session or project session is selected, the page fetches that conversation's
   read-only mapping through the selected signed-in browser and loads its user/assistant history
   into the same response article. The response card keeps one question-and-answer pair per page,
   opens on the newest page, and uses the shared paginator to revisit earlier exchanges. Its
   ellipsis controls open the shared grouped page-range menu, including keyboard navigation and
   Escape-to-close behavior. The question header and Markdown answer each have an independent
   vertical scroll region and reuse the standard expand/collapse control. The composer remains a
   non-shrinking bottom flex item so long responses cannot push it out of view. The sidebar session
   trigger stays on `New session` after a completed run unless the user explicitly
   chooses a catalog session; the Open conversation link still targets the finished
   conversation.

## Safety boundary

- Every file action and returned observation resolves below the selected project. `.git` and Agent runtime internals are
  inaccessible. Environment files, credential stores, cookies, and private keys are excluded from
  context indexes and from `list`, `read`, and `search` observations.
- Existing files change only through an exact, single-match replacement. New files use an
  explicit write action.
- Shell commands are restricted to bounded inspection, build, lint, and test work. Approved PATH
  tools are resolved once to an absolute executable outside the workspace before launch; Python
  verification is pinned to the service's own Python runtime. A workspace script must be a real,
  platform-compatible executable below `scripts/`, with no symbolic link, junction, or hard-linked
  regular file in its path.
  `git status` is filtered inspection only and never satisfies the post-edit verification gate. The
  command layer rejects direct `rg` execution in favor of `search`, paths or network targets outside
  the selected project, linked or sensitive path arguments, pytest configuration/package/plugin
  overrides, non-check Ruff modes, TypeScript invocations other than the exact `tsc --noEmit`
  inspection command, mutating or unbounded flags, file-writing redirection, deletion, moving,
  installation, downloads, publishing, environment enumeration, and Git-history mutation.
  A bounded before-and-after content fingerprint covers up to 12,000 files, 12,000 directories,
  512 MiB, and 15 seconds per scan while excluding the documented ignored/runtime directories.
  An incomplete initial fingerprint prevents launch; a changed or incomplete final fingerprint
  fails the run, advances the edit generation, and invalidates both verification and bodycheck.
  Verification output is decoded with replacement for invalid UTF-8, retained to 48,000 characters,
  and drained through a bounded queue. Stop, timeout, stream failure, and normal completion all
  perform a process-group cleanup before the final fingerprint on POSIX.
- This controller is not an operating-system sandbox. Pytest, package scripts, Make targets, and
  approved workspace scripts execute code from the selected repository and can have side effects
  that a path parser or after-the-fact fingerprint cannot prevent outside that repository. Production
  use therefore assumes a trusted local repository and a cooperative Web model. Use an OS sandbox
  when the repository or generated test code is untrusted.
- Stop is honored during the initial Chromium composer gate, ends Web-provider generation, and
  terminates the current local process group. Completion first clears the active process and removes
  the temporary context, then atomically claims the macOS idle-sleep assertion and attempts to
  release it. Only after those cleanup steps does it clear context metadata and persist
  `running=false` as the completion barrier. Worker completion and process shutdown cannot both
  claim the same assertion.
  During service exit, the shutdown hook requests Stop, waits up to eight seconds, and then claims
  any assertion that the worker has not already claimed. A late worker registration after shutdown
  immediately attempts to release its assertion instead of repopulating the shared slot. The
  assertion also runs as `caffeinate -i -w <service PID>`, so termination of the service PID releases
  it even when Python cleanup or the daemon worker cannot finish. A context deletion failure instead
  publishes a failed phase, persists the context path and size as bounded
  recovery metadata, and logs the cleanup error. The next production run retries that exact
  runtime-local cleanup, sweeps every other unreferenced app-owned timestamp context, and remains
  blocked if any cleanup fails. Sleep-assertion release failures cannot prevent the final barrier.
  Unexpected assertion startup or registration failures also pass through the failed completion
  path, persist `running=false`, and do not prevent a later task from starting.
  Local context-package construction, Chromium profile cloning, and browser-context launch are
  synchronous and not fully preemptible; initial navigation can also remain in flight until its
  configured timeout. Stop can wait for those phases. Gates before browser startup, immediately
  after context launch, after navigation, during Chromium navigation retries, and throughout
  Safari composer/send polling avoid later work where possible and still prevent context attachment
  or prompt submission. A synchronous browser error observed after an accepted Stop is published as
  `stopped`, not as a task failure.
- The Flask control routes accept host-loopback traffic directly. Private-network requests must
  first unlock `/agent` with the six-digit password gate; the successful signed session also
  authorizes same-origin `/api/agent/*` requests. Public and host-rebinding requests are rejected.
  The default password is `195135`, and `CACHELIKES_AGENT_PASSWORD` overrides it before launch.
- `/api/browser-session?...&scope=agent` uses that same network, Host, Origin, and password gate.
  Responses produced after admission carry `Cache-Control: no-store`, `Pragma: no-cache`, and an
  expired `Expires` value so Agent account-readiness data is not retained by browser caches.
- Project context and requested source files are transmitted to the selected Web account only
  when a task is sent. Selecting a ChatGPT session reads its existing conversation history for
  display and does not write those remote messages to the local cache.
- The service atomically persists only bounded run metadata, including phase, provider, model
  verification, attachment confirmation, timestamps, conversation target, bodycheck state, and a
  temporary context cleanup path and byte count while a run is active or cleanup recovery is pending. It does not persist prompt
  bodies, responses, conversation history, source text, or error stacks in that snapshot. The
  runtime directory and each task directory are owner-only, and context and snapshot files use mode
  `0600`. If a persisted run was
  still marked active when the service exited, the next process restores it as `interrupted`
  instead of claiming that it is still running or completed.
- The generated context package is task-scoped and is normally deleted after success, stop, or
  failure, including a task that opened a new Web session. Service startup and the next task also
  delete unreferenced `context.md` files only from app-owned timestamp directories while preserving
  the exact recovery pointer. A deletion failure is visible or logged and blocks the next task until
  the runtime-local file can be removed. Structured log
  formatters redact recognized
  browser credentials from messages, structured fields, exceptions, and stack traces. Active and
  rotated JSON-line logs use owner-only mode `0600`.

The question-and-answer pages are bounded to the latest 100 completed Agent exchanges per Web
conversation and live only for the current local service process. Selected ChatGPT history is
also bounded to the latest 100 paired exchanges for the page view; remote history is never
persisted by this feature.

## Settings

Settings → Agent stores:

- the default target operating system;
- the context Markdown byte limit;
- the maximum controller-turn count;
- the local command timeout;
- separate macOS and Windows system prompts.

Both operating-system defaults use one shared, complete 10-action JSON schema. At load time, prompts
missing the fenced-JSON or base64 transport contract are replaced with the current safe defaults.
Marker-complete prompts with an incomplete action schema receive the canonical schema; former
`text or regex` query fields are normalized even when their JSON whitespace differs, and the
authoritative literal-only instruction is added when absent. All other user-authored guidance and
unrelated settings remain intact. Settings are written through an owner-only, same-directory
temporary file, flushed with `fsync`, and atomically replaced. A failed write preserves the complete
previous file. Successful migrations are immediate and idempotent across later service starts.

The selected provider's file-upload limit remains authoritative. ChatGPT documents a 512 MB hard
file limit and a 2 million-token limit for text and document files; the application uses the lower
applicable boundary and keeps the local byte ceiling configurable. Gemini, Grok, and Claude may impose
different limits or attachment behavior, so the controller requires a visible exact-filename
readback before claiming an attachment and otherwise falls back to bounded controller observations.

Windows uses the same complete action schema and file-action boundary with native Windows paths, a new process group, an
absolute System32 `taskkill /T /F` fallback, and Edge or Chrome Chromium sessions. This round's
Windows process-tree contract is covered statically and by mocks, not by a real Windows end-to-end
run. If a Windows group leader exits before its descendants, `taskkill` is best effort rather than
the strict Job Object completion barrier required for hostile child processes. Safari remains
macOS-only. The selected operating system must match the host running the local service.

Edge and Chrome run through an isolated clone of the selected signed-in profile and operate the
selected provider's DOM directly. Agent Edge and Chrome tasks use offscreen, minimized temporary
contexts, with first-run, crash, notification, and repost prompts disabled, so they do not create a
visible Stage Manager window, take focus, or interrupt normal macOS use. The user's original profile
is never opened for writing. A normal task exit closes the isolated context and removes its
temporary profile; the next Chromium launch removes only abandoned `cachelikes-edge-*` or
`cachelikes-chrome-*` directories older than 24 hours. Safari uses one shared Apple Events context,
restores the previous frontmost application after window operations, and closes every task-owned
window on success, stop, failure, or exception. Safari remains available only for ChatGPT's existing
session flows. Claude requires Edge or Chrome. If Claude renders an
account suspension, ban, deactivation, or other restricted-state message, the readiness card reports
that state and does not attempt a login bypass.

Chromium cleanup treats only the known Playwright already-closed and driver-disconnected close
errors as an idempotent second close, while still removing the temporary profile. Unexpected
context-close failures continue to propagate instead of being hidden.

The traditional Edge handoff is intentionally separate from the isolated Agent context. On a failed
Edge and ChatGPT run with a verified conversation URL, macOS asks the normal `Microsoft Edge`
application to create a new window and set its active tab URL through Edge's AppleScript window model.
The handoff never calls `activate`, so the current foreground application remains unchanged while
Stage Manager places the Edge window in the background. Clicking the handoff pill later opens the same
URL in Edge normally.

The model selector is provider-specific: ChatGPT exposes `5.6 Sol`, Gemini exposes `3.1 Pro`, Grok
exposes `Build Beta`, and Claude exposes `Auto`. Each provider is fail-closed: the controller must select or observe
and then visibly read back the exact configured model before any attachment or send. A localized
or changed menu that cannot prove the selection stops the run without transferring project data.
For an `Auto` readback, a generic popup wrapper is insufficient: the trigger must also identify
itself as a model or mode control, or expose provider-specific model metadata.

Browser readiness uses a short session cache only for a positive authenticated result. A fresh
negative result is rendered immediately but also re-probed, so completing login or a provider
security check does not leave Ask blocked for five minutes. An explicit controller refresh always
bypasses the cache. A signed-in Gemini page that states the service is unavailable in the browser's
current region is not an authenticated-ready result: the probe reports the provider condition,
keeps Ask disabled, and transfers no project data. Gemini Notebook discovery rejects provider-owned creation aliases such as
`/notebook/create` and `/notebooks/new`. Every source-catalog API response revalidates cached Project
URLs through the current provider contract, so those aliases cannot appear as selectable Projects
even when an older in-memory or Parquet catalog contains them.

While an Agent task is running on macOS, the service holds an idle-sleep assertion bound to the
service PID until it has attempted task-scoped context removal during success, stop, or failure
cleanup. Worker completion and service shutdown use an atomic ownership transfer before attempting
to terminate that assertion, while `caffeinate -w` is the final safeguard if the service exits
before cleanup. A failed context removal is published as a recoverable failed state rather than
keeping an orphan worker marked active. On Windows, the controller isolates the active process in a
new process group and uses a cooperative stop before terminating it. Closing a MacBook lid, choosing
Sleep, restarting, losing network access, or ending the local service can still suspend or interrupt
a task.

## Verification

Default tests use temporary projects, fake browser runners, and isolated settings paths. Live
read-only capability probes verified signed-in sessions, composers, send controls, and model-menu
behavior for ChatGPT, Gemini, and Grok in both Edge and Chrome on 14 Aug 2026. Claude's provider
contract is covered by mocked readiness, URL, source, and route checks in this change; a live Claude
probe was not possible because the selected account is currently restricted. The probes did not
send project content. Any live signed-in browser run must be treated as an external data transfer;
confirm the target and data scope before sending a real project task.

On 27 Aug 2026, delayed Gemini hydration, Stop interruption, strict model proof, bounded diagnostic
privacy, localized region gating, and transient navigation retry coverage passed 307 controller
tests, 89 complete Chromium E2E tests, 20 Gemini tests, and 70 hardening tests. The complete project
gate passed 994 tests and 370 subtests with 68.56% branch coverage. A live Edge check reproduced
`ERR_CONNECTION_TIMED_OUT`; the shared transient marker now retries that exact error. The refreshed
host tab then returned Gemini's Simplified Chinese current-region-unavailable landing page. The
controller treated that as a terminal provider condition before context attachment or prompt
submission, so the interrupted external task was not represented as completed.

On 26 Aug 2026, 315 focused controller/hardening tests passed with the bundled ripgrep available.
The same suite passed 314 tests with only its real-ripgrep integration test skipped under an explicit
no-`rg` PATH; all mocked ripgrep JSON, Stop, timeout, post-filter, and diagnostic-isolation cases still
executed through a workspace-external trusted fixture. The production-hardening suite covered
recursive search parity, Stop propagation, completion cleanup, explicit session reuse,
verification-gate ordering, canonical executable and argument confinement, hard-link rejection,
strict direct `tsc --noEmit` parsing, shared cross-platform action-schema migration, atomic settings
replacement, unique atomic run-snapshot replacement, Safari submission Stop gates, Chromium retry
Stop gates, linked-path-confined orphaned-context housekeeping, bounded content fingerprints, and
real POSIX leader-exited descendant processes. Sleep lifecycle regressions cover service-PID-bound
`caffeinate`, shutdown-first and worker-first ownership races, join timeout takeover, late
registration after shutdown, and assertion startup or registration exceptions followed by a clean
second run. Runtime regressions reject linked or junction-backed
runtime ancestors, timestamp directories, snapshot metadata, hard-linked context files, and
non-regular persisted inputs without changing external content or permissions or blocking startup.
A worker-thread launch failure is also published and persisted as `failed` with `running=false`, so
Stop is not falsely accepted and a later task can start. The complete project gate passed 936 tests
and 366 subtests with 68.40%
overall coverage and branch measurement enabled. A protected runtime inventory also found and then
removed 45 historical orphaned context bundles totaling 1,481,451 bytes; no timestamp context remained.
This verification did not restart the user-owned service or send a new Web-provider task; Windows
received static and mock validation only.

On 19 Aug 2026, the named `08.19 Agentic` Edge tasks completed a 38-turn ChatGPT audit and a
9-turn Gemini audit with `bodycheck`. Grok completed its first read action and the live Submit/Enter
fallback was verified, but Grok Auto remained in a long second-turn thinking state during two
bounded audits; this provider-specific runtime limitation remains observable and is not reported
as a completed full audit.

On 26 Aug 2026, production preparation for a new Grok task added receipt-correlated session binding.
A fresh root run may bind only the `/c/<id>` conversation whose latest user message contains that
run's transfer ID. Project-new runs add the same proof and may bind only inside the selected Project,
while Project-session runs compare the Project ID and `chat` query exactly. Grok freshness now also
requires a complete pre-submit conversation baseline, and Send performs its target check atomically
with the click. Fresh runs transfer no attachment before binding. The pass also added positive
authenticated-API readiness, semantic-menu-scoped and re-read model selection, same-Project catalog
fallback filtering, Gemini Notebook Project-session fail-closed behavior, fresh-bootstrap
reconciliation over stale catalog state, provider-aware stale-request suppression, and strict
provider/browser provenance isolation for completed UI state and composer content. Focused
controller/source/Web regressions passed 399 tests and 342 subtests; all 55 Chromium UI/E2E tests
then passed. The full gate passed as recorded above. After the final 8666 restart, the live Edge
Grok route loaded `computer-use-agent-v3.22.0-codex.1` and rendered `idle` with an empty response
and composer even though the persisted global snapshot belonged to a completed ChatGPT run. Both the
controller's isolated Edge probe and a fresh host Edge tab still showed Grok's Cloudflare
`Verify you are human` security page. The local Agent kept Ask disabled. No CAPTCHA or security
barrier was bypassed, and no project context or prompt was sent; the operator must complete that
verification in Edge before the real project run can begin.
