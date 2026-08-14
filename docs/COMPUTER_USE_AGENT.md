# Web Computer Use Agent

Documentation version: `v3.9.2-codex.1`

## Purpose

The Agent workspace is a browser-mediated fallback for times when the local coding-agent token
pool is constrained. It uses an already signed-in Web session for ChatGPT, Gemini, or Grok, with
Edge or Chrome as the supported background Chromium browsers. ChatGPT also remains available in
Safari for the existing session flows. Edge is the default because its Chromium controller does
not depend on desktop clicks; Chrome uses the same isolated controller.

The default is a new root-level session. ChatGPT can also join one of the 20 most recent root
sessions, start a session in one of the 20 most recent projects, or join one of that project's
20 most recent sessions. Gemini and Grok currently start a new root-level Web conversation.
The selected Web provider supplies reasoning; a bounded local macOS controller performs project
actions and returns compact observations to the same conversation.

This route uses no API, command-line coding-agent runtime, MCP connection, or third-party agent bridge.
ChatGPT plan limits, file-upload limits, data controls, storage, and retention still apply.

## Execution loop

1. Select one local project, a Web provider/model, and an authenticated browser on `/agent`.
   Configure the operating system in Settings → Agent; the setting detects the host and selects
   macOS or Windows automatically. If local permissions are needed, explicitly use `Open terminal
   permissions` in Settings → Agent. macOS opens Full Disk Access for the Terminal that starts
   the service; Windows requests PowerShell administrator authorization through UAC. Automatic
   detection never opens an authorization surface.
   The browser status card also reports whether the host Terminal or PowerShell executable is
   available and the selected project currently grants read, write, and directory-entry access.
2. Keep `New session` or choose a recent root session/project and, for a project, either
   `New session in project` or one of its recent sessions.
3. Enter a task. The service validates the selected provider's official URL and opens it in the
   selected browser profile.
4. The service builds one owner-readable Markdown context package containing the request,
   repository instruction files, a bounded file index, dirty-worktree status, and project entry
   files.
5. Chromium browsers attach the package directly when the selected provider exposes a file input,
   wait for the attachment to enable Send, click the semantic send control, and confirm that the
   provider accepted the prompt. If direct attachment is unavailable, the controller requests
   only the bounded files needed for the next action.
6. The selected Web provider returns exactly one JSON action at a time. The controller supports `list`, `read`,
   `search`, `replace`, `write`, `run`, `bodycheck`, and `final`.
7. A malformed non-JSON reply receives up to three strict-format corrections without spending the
   configured controller-action budget. This keeps a recoverable web-model formatting lapse from
   prematurely ending a valid task, while still bounding retries.
8. The controller rejects a final answer until `bodycheck` succeeds after the latest edit.
9. The local page renders the final Markdown and links to the selected Web conversation. When a
   ChatGPT recent session or project session is selected, the page fetches that conversation's
   read-only mapping through the selected signed-in browser and loads its user/assistant history
   into the same response article. The response card keeps one question-and-answer pair per page,
   opens on the newest page, and uses the shared paginator to revisit earlier exchanges. The
   question header and Markdown answer each have an independent vertical scroll region and reuse
   the standard expand/collapse control. The composer remains a non-shrinking bottom flex item so
   long responses cannot push it out of view. The sidebar session trigger follows the selected or
   newly completed conversation title.

## Safety boundary

- Every controller path resolves below the selected project. `.git` internals are inaccessible.
- Existing files change only through an exact, single-match replacement. New files use an
  explicit write action.
- Shell commands are restricted to bounded inspection, build, lint, and test work. The command
  layer rejects file-writing redirection, deletion, moving, installation, downloads, publishing,
  environment enumeration, and Git-history mutation.
- Stop ends Web-provider generation and terminates the current local process group.
- The Flask control routes accept host-loopback traffic and same-origin browser requests only.
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
applicable boundary and keeps the local byte ceiling configurable. Gemini and Grok may impose
different limits or attachment behavior, so the controller treats a missing attachment control
as a signal to fall back to bounded controller observations.

Windows appears in the selector and has an independent prompt, but execution is intentionally
blocked on a macOS host until a PowerShell-backed controller and Windows browser-session adapter
are implemented and verified.

Edge and Chrome run through an isolated clone of the selected signed-in profile and operate the
selected provider's DOM directly. Their task windows are offscreen, minimized, and configured not
to surface first-run, crash, notification, or repost prompts, so they do not steal focus or
interrupt normal macOS use. The user's original profile is never opened for writing. A normal task
exit closes the isolated context and removes its temporary profile; the next Chromium launch removes
only abandoned `cachelikes-edge-*` or `cachelikes-chrome-*` directories older than 24 hours. Safari
uses Apple Events and remains available only for ChatGPT's existing session flows.

The model selector is provider-specific: ChatGPT exposes `5.6 Sol`, Gemini exposes `3.1 Pro`, and
Grok exposes `Auto`. The controller selects the requested model only when the provider exposes a
matching visible menu option. If the remote UI is localized or exposes a different model set, it
leaves the current remote model unchanged and reports that limitation rather than claiming success.

While an Agent task is running on macOS, the service holds an idle-sleep assertion and releases it
as soon as the task finishes or fails. The display can turn off and the session can remain locked;
the assertion does not wake the display. Closing a MacBook lid, choosing Sleep, restarting, losing
network access, or ending the local service can still suspend or interrupt a task.

## Verification

Default tests use temporary projects, fake browser runners, and isolated settings paths. Live
read-only capability probes verified signed-in sessions, composers, send controls, and model-menu
behavior for ChatGPT, Gemini, and Grok in both Edge and Chrome on 14 Aug 2026. The probes did not
send project content. Any live signed-in browser run must be treated as an external data transfer;
confirm the target and data scope before sending a real project task.
