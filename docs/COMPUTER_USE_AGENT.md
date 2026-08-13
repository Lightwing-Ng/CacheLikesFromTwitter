# ChatGPT Web Computer Use Agent

Documentation version: `v2.1.0-codex.1`

## Purpose

The Agent workspace is a browser-mediated fallback for times when the local coding-agent token
pool is constrained. It opens the user's selected ChatGPT Web session in an already signed-in
Safari, Edge, or Chrome session. A new root-level session is the default; the sidebar can also
join one of the 20 most recent root sessions, start a session in one of the 20 most recent
projects, or join one of that project's 20 most recent sessions. ChatGPT supplies reasoning; a
bounded local macOS controller performs project actions and returns compact observations to the
same conversation.

This route uses no API, command-line coding-agent runtime, MCP connection, or third-party agent bridge.
ChatGPT plan limits, file-upload limits, data controls, storage, and retention still apply.

## Execution loop

1. Select one local project and an authenticated browser on `/agent`; the operating-system control detects the host and selects macOS or Windows automatically.
2. Keep `New session` or choose a recent root session/project and, for a project, either
   `New session in project` or one of its recent sessions.
3. Enter a task. The service validates the selected official ChatGPT URL and opens it in the
   selected browser profile.
4. The service builds one owner-readable Markdown context package containing the request,
   repository instruction files, a bounded file index, dirty-worktree status, and project entry
   files.
5. Chromium browsers attach the package directly when ChatGPT exposes a file input. Safari uses
   the same prompt and streams requested project context through controller observations.
6. ChatGPT returns exactly one JSON action at a time. The controller supports `list`, `read`,
   `search`, `replace`, `write`, `run`, `bodycheck`, and `final`.
7. The controller rejects a final answer until `bodycheck` succeeds after the latest edit.
8. The local page renders the final Markdown and links to the visible ChatGPT conversation.

## Safety boundary

- Every controller path resolves below the selected project. `.git` internals are inaccessible.
- Existing files change only through an exact, single-match replacement. New files use an
  explicit write action.
- Shell commands are restricted to bounded inspection, build, lint, and test work. The command
  layer rejects file-writing redirection, deletion, moving, installation, downloads, publishing,
  environment enumeration, and Git-history mutation.
- Stop ends ChatGPT generation and terminates the current local process group.
- The Flask control routes accept host-loopback traffic and same-origin browser requests only.
- Project context and requested source files are transmitted to the selected ChatGPT account.

## Settings

Settings → Agent stores:

- the default target operating system;
- the context Markdown byte limit;
- the maximum controller-turn count;
- the local command timeout;
- separate macOS and Windows system prompts.

The OpenAI file-upload limit remains authoritative. As of 13 Aug 2026, ChatGPT documents a
512 MB hard file limit and a 2 million-token limit for text and document files. The application
uses the lower applicable boundary and keeps the local byte ceiling configurable.

Windows appears in the selector and has an independent prompt, but execution is intentionally
blocked on a macOS host until a PowerShell-backed controller and Windows browser-session adapter
are implemented and verified.

## Verification

Default tests use temporary projects, fake browser runners, and isolated settings paths. They do
not open authenticated profiles or submit real content to ChatGPT. A live signed-in browser run is
manual and must be treated as an external data transfer.
