# Web Computer Use Agent

Documentation version: `v3.23.1-codex.1`

## Purpose

The Agent workspace is a browser-mediated fallback for times when the local coding-agent token
pool is constrained. It uses an already signed-in Web session for ChatGPT, Gemini, Grok, or Claude, with
Edge or Chrome as the supported background Chromium browsers. ChatGPT also remains available in
Safari for the existing session flows. Edge is the default because its Chromium controller does
not depend on desktop clicks; Chrome uses the same isolated controller.

The default is a new root-level session. Every provider can also join one of the 20 most recent
sessions, start a session in one of the 20 most recent Projects, or join one of that Project's 20
most recent sessions. The adapter maps ChatGPT Projects, Gemini Notebooks, Grok Projects, and Claude
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

On `/agent`, ChatGPT uses an agent-scoped bootstrap request: the selected Edge/Chrome/Safari
context verifies the account and collects Recent sessions and Projects in one launch. The status
payload carries that catalog directly to the selector, and the same payload seeds the shared L1 and
Parquet L2 cache. The page therefore does not open a second browser for the Recent sessions step.
Loading sessions inside a selected Project remains a later, separately keyed operation.

This route uses no API, command-line coding-agent runtime, MCP connection, or third-party agent bridge.
ChatGPT plan limits, file-upload limits, data controls, storage, and retention still apply.

## Canonical navigation

The Agent entrypoint is scoped by the selected browser and Web provider. The canonical form is
`/agent/<browser>/<platform>`, such as `/agent/edge/chatgpt` or `/agent/edge/claude`; `/agent/<browser>/`
is a browser-scoped compatibility alias, and the legacy `/agent` path redirects to
the persisted selection. Changing either selector updates the canonical path without reloading the
page, so a copied URL preserves the intended Edge/ChatGPT selection.

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
4. Before attaching project data or submitting a prompt, ChatGPT must expose its visible Model
   submenu and read back `GPT-5.6 Sol` or `5.6 Sol`. If that verification fails, the run stops
   without attaching the context or sending the prompt. Gemini, Grok, and Claude retain their
   best-effort boundary: when their compatible model control is not exposed, the controller keeps
   the selected session's current remote model and reports that limitation.
   Chromium composer readiness is polled in 250 ms slices so Stop can terminate the initial page
   verification before model selection, context attachment, or prompt submission. Its single
   recovery reload waits only for navigation commit and is capped at five seconds. Stop is checked
   again before and throughout context attachment, after attachment state publication, and before
   prompt submission; Chromium submitters also return before reading or filling a composer when a
   stop is already pending.
5. The service builds one owner-readable Markdown context package containing the request,
   repository instruction files, a bounded file index, dirty-worktree status, and project entry
   files. Credential locations, environment files, cookie stores, and private-key formats are
   excluded from the file index and controller access.
6. Chromium browsers attach the package directly when the selected provider exposes a file input.
   The controller treats the upload as accepted only after the composer visibly reads back the
   exact context filename; a populated hidden file input alone is insufficient. If the filename
   never becomes visible or the page reports an upload failure, the run continues without claiming
   an attachment and requests only the bounded files needed for subsequent actions. After a
   confirmed attachment or that on-demand fallback, the controller clicks the semantic send
   control and confirms that the provider accepted the prompt. Grok uses its live `textarea` and
   `chat-submit`/`Submit` contract; if that control is briefly absent after a follow-up observation,
   the controller falls back to pressing Enter and still verifies prompt acceptance.
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
  the temporary context, then releases the macOS idle-sleep assertion and clears context metadata;
  only after those cleanup steps does it persist `running=false` as the completion barrier. A context
  deletion failure instead publishes a failed phase, persists the context path and size as bounded
  recovery metadata, and logs the cleanup error. The next production run retries only that exact
  runtime-local cleanup and remains blocked if the file still exists. Sleep-assertion release
  failures cannot prevent the final barrier.
  Initial synchronous browser navigation and local context-package construction are not fully
  preemptible; Stop can wait for those bounded operations, but later gates still prevent context
  attachment or prompt submission.
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
  runtime directory is owner-only, and the snapshot file uses mode `0600`. If a persisted run was
  still marked active when the service exited, the next process restores it as `interrupted`
  instead of claiming that it is still running or completed.
- The generated context package is task-scoped and is normally deleted after success, stop, or
  failure, including a task that opened a new Web session. A deletion failure is visible as a failed
  run and blocks the next task until the exact runtime-local file can be removed. Structured log
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

The selected provider's file-upload limit remains authoritative. ChatGPT documents a 512 MB hard
file limit and a 2 million-token limit for text and document files; the application uses the lower
applicable boundary and keeps the local byte ceiling configurable. Gemini, Grok, and Claude may impose
different limits or attachment behavior, so the controller requires a visible exact-filename
readback before claiming an attachment and otherwise falls back to bounded controller observations.

Windows uses the same file-action boundary with native Windows paths, a new process group, an
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

The model selector is provider-specific: ChatGPT exposes `5.6 Sol`, Gemini exposes `3.1 Pro`, and
Grok and Claude expose `Auto`. ChatGPT is fail-closed: the controller must select or observe and
then visibly read back GPT-5.6 Sol before any attachment or send. A localized or changed ChatGPT
menu that cannot prove that selection stops the run without transferring project context. Gemini,
Grok, and Claude remain best-effort: if their remote UI does not expose a matching model option,
the controller leaves that selected session's current remote model unchanged and reports the
limitation rather than claiming model-selection success.

While an Agent task is running on macOS, the service holds an idle-sleep assertion until it has
attempted task-scoped context removal during success, stop, or failure cleanup. A failed removal is
published as a recoverable failed state rather than keeping an orphan worker marked active. On
Windows, the controller isolates the active process in a new process group and uses a cooperative
stop before terminating it. Closing a MacBook lid,
choosing Sleep, restarting, losing network access, or ending the local service can still suspend or
interrupt a task.

## Verification

Default tests use temporary projects, fake browser runners, and isolated settings paths. Live
read-only capability probes verified signed-in sessions, composers, send controls, and model-menu
behavior for ChatGPT, Gemini, and Grok in both Edge and Chrome on 14 Aug 2026. Claude's provider
contract is covered by mocked readiness, URL, source, and route checks in this change; a live Claude
probe was not possible because the selected account is currently restricted. The probes did not
send project content. Any live signed-in browser run must be treated as an external data transfer;
confirm the target and data scope before sending a real project task.

On 26 Aug 2026, 280 focused controller/hardening tests passed with the bundled ripgrep available.
The same suite passed 279 tests with only its real-ripgrep integration test skipped under an explicit
no-`rg` PATH; all mocked ripgrep JSON, Stop, timeout, post-filter, and diagnostic-isolation cases still
executed through a workspace-external trusted fixture. The production-hardening suite covered
recursive search parity, Stop propagation, completion cleanup, explicit session reuse,
verification-gate ordering, canonical executable and argument confinement, hard-link rejection,
strict direct `tsc --noEmit` parsing, bounded content fingerprints, and real POSIX leader-exited
descendant processes. The complete project gate passed 825 tests and 357 subtests with 67.26%
overall coverage and branch measurement enabled. This verification did not restart the user-owned
service or send a new Web-provider task; Windows received static and mock validation only.

On 19 Aug 2026, the named `08.19 Agentic` Edge tasks completed a 38-turn ChatGPT audit and a
9-turn Gemini audit with `bodycheck`. Grok completed its first read action and the live Submit/Enter
fallback was verified, but Grok Auto remained in a long second-turn thinking state during two
bounded audits; this provider-specific runtime limitation remains observable and is not reported
as a completed full audit.
