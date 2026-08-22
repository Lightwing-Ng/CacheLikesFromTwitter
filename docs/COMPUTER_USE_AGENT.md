# Web Computer Use Agent

Documentation version: `v3.18.1-codex.1`

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
   `New session in project` or one of its recent sessions.
3. Enter a task. The service validates the selected provider's official URL and opens it in the
   selected browser profile. When a request switches away from the persisted provider, the service
   resets a stale previous-provider target URL to the new provider's official home before
   validation.
4. The service builds one owner-readable Markdown context package containing the request,
   repository instruction files, a bounded file index, dirty-worktree status, and project entry
   files.
5. Chromium browsers attach the package directly when the selected provider exposes a file input,
   wait for the attachment to enable Send, click the semantic send control, and confirm that the
   provider accepted the prompt. Grok uses its live `textarea` and `chat-submit`/`Submit` contract;
   if that control is briefly absent after a follow-up observation, the controller falls back to
   pressing Enter and still verifies prompt acceptance. If direct attachment is unavailable, the
   controller requests only the bounded files needed for the next action.
6. The selected Web provider returns exactly one JSON action at a time inside a fenced `json` code block so
   rendered Markdown cannot consume action quotes, backslashes, asterisks, or source-code delimiters. The
   controller prefers that code block's literal text and supports `list`, `read`, `search`, `replace`, `write`,
   `run`, `bodycheck`, and `final`. If a provider emits multiple complete
   candidates with the same action name in one response, the controller uses the final candidate in textual
   response order; mixed action types remain rejected as ambiguous.
7. A malformed non-JSON reply receives up to three strict-format corrections that repeat the fenced JSON and
   escaping contract without spending the
   configured controller-action budget. This keeps a recoverable web-model formatting lapse from
   prematurely ending a valid task, while still bounding retries.
8. The controller rejects a final answer until `bodycheck` succeeds after the latest edit. If an
   Edge and ChatGPT run still fails after an exact conversation URL exists, the service preserves the
   failed state and opens that same conversation in the user's traditional Edge browser with macOS
   background activation. The local page exposes a `Continue in Edge` handoff instead of claiming
   completion. A traditional ChatGPT window can continue the conversation, but it cannot perform or
   verify local file actions through this controller; local edits and bodycheck therefore remain
   unfinished.
9. The local page renders the final Markdown and links to the selected Web conversation in the
   browser encoded by the task, rather than the system default browser. When a
   ChatGPT recent session or project session is selected, the page fetches that conversation's
   read-only mapping through the selected signed-in browser and loads its user/assistant history
   into the same response article. The response card keeps one question-and-answer pair per page,
   opens on the newest page, and uses the shared paginator to revisit earlier exchanges. Its
   ellipsis controls open the shared grouped page-range menu, including keyboard navigation and
   Escape-to-close behavior. The question header and Markdown answer each have an independent
   vertical scroll region and reuse the standard expand/collapse control. The composer remains a
   non-shrinking bottom flex item so long responses cannot push it out of view. The sidebar session
   trigger follows the selected or newly completed conversation title.

## Safety boundary

- Every controller path resolves below the selected project. `.git` internals are inaccessible.
- Existing files change only through an exact, single-match replacement. New files use an
  explicit write action.
- Shell commands are restricted to bounded inspection, build, lint, and test work. The command
  layer rejects file-writing redirection, deletion, moving, installation, downloads, publishing,
  environment enumeration, and Git-history mutation.
- Stop ends Web-provider generation and terminates the current local process group.
- The Flask control routes accept host-loopback traffic directly. Private-network requests must
  first unlock `/agent` with the six-digit password gate; the successful signed session also
  authorizes same-origin `/api/agent/*` requests. Public and host-rebinding requests are rejected.
  The default password is `195135`, and `CACHELIKES_AGENT_PASSWORD` overrides it before launch.
- Project context and requested source files are transmitted to the selected Web account only
  when a task is sent. Selecting a ChatGPT session reads its existing conversation history for
  display and does not write those remote messages to the local cache.

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
different limits or attachment behavior, so the controller treats a missing attachment control
as a signal to fall back to bounded controller observations.

Windows uses the same project-confined controller with native Windows paths, PowerShell process
groups, and Edge or Chrome Chromium sessions. Safari remains macOS-only. The selected operating
system must match the host running the local service.

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

The traditional Edge handoff is intentionally separate from the isolated Agent context. On a failed
Edge and ChatGPT run with a verified conversation URL, macOS asks the normal `Microsoft Edge`
application to create a new window and set its active tab URL through Edge's AppleScript window model.
The handoff never calls `activate`, so the current foreground application remains unchanged while
Stage Manager places the Edge window in the background. Clicking the handoff pill later opens the same
URL in Edge normally.

The model selector is provider-specific: ChatGPT exposes `5.6 Sol`, Gemini exposes `3.1 Pro`, and
Grok and Claude expose `Auto`. The controller selects the requested model only when the provider exposes a
matching visible menu option. If the remote UI is localized or exposes a different model set, it
leaves the current remote model unchanged and reports that limitation rather than claiming success.

While an Agent task is running on macOS, the service holds an idle-sleep assertion and releases it
as soon as the task finishes or fails. On Windows, the controller isolates the active process in a
new process group and uses a cooperative stop before terminating it. Closing a MacBook lid,
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

On 19 Aug 2026, the named `08.19 Agentic` Edge tasks completed a 38-turn ChatGPT audit and a
9-turn Gemini audit with `bodycheck`. Grok completed its first read action and the live Submit/Enter
fallback was verified, but Grok Auto remained in a long second-turn thinking state during two
bounded audits; this provider-specific runtime limitation remains observable and is not reported
as a completed full audit.
