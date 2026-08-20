# Architecture guide

Documentation version: `v1.7.0-codex.1`

## Runtime flow

```text
main.py
  -> supported Python 3.13/3.14 runtime resolution
  -> structured logging setup
  -> app.web.app.create_app()
  -> Flask routes and static UI
  -> app.core services, browser sessions, downloaders, and local catalogs
```

`main.py` is the only supported application entrypoint. The shell runtime resolver accepts Python
3.13 or 3.14 and the module itself remains runtime-agnostic before Flask is imported.
`create_app()` builds independent state containers for the X, Grok, and ChatGPT workflows,
registers the local-media browser, and serves the Flask routes.

## Core package boundary

The application layer imports `app.core` through five domain façades instead of reaching into
every implementation module:

- `app/core/foundation/`: runtime configuration, logging, version, and task state.
- `app/core/browser/`: browser descriptors, session probes, and provider-neutral X page identity.
- `app/core/storage/`: local media, chat history, and shadow-backup operations.
- `app/core/providers/`: X, Gemini, Grok, and ChatGPT workflows.
- `app/core/agent/`: Agent access control, source discovery, and Computer Use orchestration.

The original flat modules remain import-compatible during this migration. New application-layer
code should depend on the domain façades; provider and storage implementations may continue to
use their existing compatibility imports until each slice is moved. `browser.x_session` is a leaf
module: it owns X identity/readiness helpers so `browser_sessions` no longer needs an implicit
runtime import back into `scraper`.

The intended dependency direction is:

```text
app.web
  -> core domain façades
     -> core implementations
        -> foundation, browser leaves, and storage primitives
```

Core modules must not import `app.web`, templates, or frontend JavaScript. A domain façade should
export only the symbols needed by its caller and should not become a second implementation file.

## Application layers

- `app/core/config.py`: runtime defaults, persisted settings, paths, and input normalization.
- `app/core/state.py`: thread-safe task snapshots and cache-summary hydration.
- `app/core/service.py`: X Likes collection and yt-dlp orchestration.
- `app/core/grok_service.py` and `app/core/chatgpt_service.py`: background sync lifecycle,
  stop signaling, and shared cache-task exclusion.
- `app/core/grok_history.py` and `app/core/grok_history_service.py`: authenticated Grok Text
  API traversal, normalized message persistence, and the independent Grok Text worker.
- `app/core/scraper.py` and `app/core/browser_sessions.py`: X timeline discovery and browser
  session probing for Chrome, Edge, and Safari.
- `app/core/downloader.py`, `app/core/grok_downloader.py`, and
  `app/core/chatgpt_downloader.py`: source-specific cache acquisition, recovery state, and
  content validation.
- `app/core/chatgpt_agent_sources.py`: authenticated browser-mediated catalogs of the 20 most
  recent root ChatGPT sessions, projects, and project sessions for the Agent sidebar. Its Agent
  bootstrap combines ChatGPT readiness and root-catalog collection in one browser context.
- `app/core/agent_session_sources.py`: the provider-neutral Agent session and Project adapter;
  it maps ChatGPT Projects, Gemini Notebooks, and Grok Projects into one URL and source contract.
- `app/core/agent_source_cache.py`: the shared typed Parquet catalog for Agent recent sessions,
  Projects, and Project sessions. Its cache key isolates provider, browser, source kind, and
  Project URL, while atomic replacement preserves the other providers' entries.
- `app/core/agent_access_security.py`: the Agent password resolver, constant-time password
  comparison, and loopback/private-network request boundary.
- `app/core/computer_use_agent.py`: selected ChatGPT, Gemini, or Grok Web session targets, bounded context
  packages, the local JSON action protocol, project path confinement, command policy, and
  mandatory bodycheck ordering for the optional Agent workspace.
- `app/core/cache_catalog.py` and `app/core/local_media_browser.py`: durable local indexes,
  media discovery, secure path resolution, deletion tombstones, and restoration.
- `app/core/logging_setup.py`: process-wide JSON-line logging.
- `app/web/`: Flask routes, templates, style tokens, and first-party browser JavaScript.

Web routes may orchestrate core services and present serialized state. Core modules must not
depend on templates or browser DOM details. Source-specific automation belongs at a browser or
transport boundary, while durable cache and state rules stay in core modules.

## Responsive application-shell contract

The browser shell has two independent responsive boundaries. Content enters its compact phone
layout at `600 px` and below. The sidebar enters a fixed overlay at `900 px` and below, which
covers current iPad portrait widths without forcing tablet content into the phone layout.

`style.css` publishes both semantic values as CSS custom properties. `responsive.js` reads those
tokens and is the only first-party JavaScript module allowed to construct width-based media
queries. The templates load it before the sidebar bootstrap, which applies the stored
`cachelikes:sidebar-open` session state or defaults a new overlay session to collapsed. The main
sidebar controller owns the open and collapsed classes, `aria-expanded`, sidebar inertness, and
the backdrop's `hidden`, `aria-hidden`, inert, and tab-index states.

In overlay mode, safe-area-aware fixed geometry keeps the sidebar and toggle inside the viewport.
The backdrop sits below the sidebar, dock, and toggle. A global `[hidden]` rule makes hidden state
authoritative over responsive display rules, while closed sidebar and backdrop states also disable
pointer events explicitly.

## Chinese language presentation boundary

Every document shell loads `language-rendering.js`. The boundary annotator never rewrites text
or Unicode code points; it only marks untagged Han-containing controls and dynamic content as
`lang="zh-CN"` so macOS and browser font selection use the intended Simplified Chinese context.

All source values remain byte-for-byte stable: form controls, URLs, `data-*` attributes, JSON,
code-like content, and explicitly tagged `lang` boundaries are untouched. This is a display
context fix for macOS glyph selection, not a Simplified-to-Traditional conversion layer.

## Source flows

### X Likes cache

```text
authenticated X browser session
  -> scraper collects canonical liked-post URLs
  -> CacheLikesService schedules bounded workers
  -> yt-dlp downloads media using the selected browser cookies
  -> local_store/x/ and its durable cache catalog
```

The service deduplicates URLs, respects a cooperative stop request, shares one cross-workflow
task lock, and records the resulting summary in `TaskState`.

### Grok media cache

```text
authenticated Grok browser session
  -> GrokDownloadService
  -> catalog, manifest, and work queue
  -> validated media files in local_store/media/grok/
```

The Grok downloader persists catalog, resumable download-manifest, and work-queue state. A
rebuild verifies local media rather than trusting filenames alone. Snapshot and reset helpers
resolve their default cache directory at call time so tests can safely redirect it.

### Grok Text cache

```text
authenticated Edge session cloned into an isolated Chromium context
  -> paginated /rest/app-chat/conversations API
  -> response-node tree and batched load-responses API
  -> GrokHistoryStore
  -> local_store/llm/grok/history.parquet
```

Grok Text is deliberately separate from the Grok media runtime. Conversation pagination
uses `nextPageToken` as the next request's `pageToken`; the visible sidebar is not a
complete history source. Each response ID is stable within its conversation, so the
store uses `<conversation-id>:<response-id>` as the message key and atomically replaces
one conversation at a time. See [CACHE_HANDOFF.md](CACHE_HANDOFF.md) for the operator
workflow and recovery rules.

### ChatGPT image cache

```text
configured ChatGPT project or conversation URL
  -> ChatGPTDownloadService
  -> bounded parallel conversation workers with isolated Edge contexts
  -> original-image discovery, download claims, and catalog validation
  -> local_store/media/chatgpt/<project-name>/
```

Up to three workers scan conversations and download original image payloads concurrently. Each
worker owns its Playwright context and recycles its page after a bounded number of conversations;
recoverable page failures receive one retry. Catalog claims and atomic writes prevent duplicate
workers from corrupting the local index. Only image payloads that pass signature validation are
retained. The project name is sanitized before it becomes a cache path.

### Gemini Text cache

```text
authenticated Safari session
  -> one standard task-owned background window
  -> Gemini virtualized conversation navigation
  -> rendered user-query and model-response extraction
  -> atomic local_store/llm/gemini/history.parquet replacement
  -> native window close with Safari window-ID verification
```

Safari contexts are serialized across processes. The worker never reuses the user's
current window, never creates a replacement after the user closes the owned window,
and never leaves a hidden or blank reusable shell. JavaScript execution is bounded by
an AppleScript timeout. Conversation rows are replaced atomically per session, so a
stopped run preserves every previously verified session without duplicating messages.

### Local-media browser

`LocalMediaCatalog` reads the X, Grok, and ChatGPT cache trees and returns safe relative paths to
the Flask application. The browser route allows only readable supported media below the configured
cache root. Deleting an item moves it to a recoverable hidden browser-trash area and records a
tombstone; restoring it moves the retained preview back to its original safe path.

### Web Computer Use Agent

```text
selected local project
  -> provider-neutral recent session/Project catalog
  -> new or selected signed-in ChatGPT, Gemini, or Grok Web conversation
  -> bounded Markdown context package
  -> one JSON controller action at a time
  -> confined local read/change/check
  -> compact observation returned to the same conversation
  -> current bodycheck
  -> final Markdown result
  -> on an Edge and ChatGPT failure with an exact conversation URL:
       failed state retained
       same conversation opened in traditional Edge with background activation
       local file actions and bodycheck remain unfinished
```

The web model never receives direct process or filesystem authority. The local controller resolves
every path below the selected project, separates explicit file actions from a restricted command
layer, bounds turns and output, and rejects final completion after an edit until bodycheck passes.
Controller actions travel in fenced `json` code blocks, and the browser reader prefers the literal
code-block text so Markdown rendering cannot consume source-code punctuation before parsing.
The provider adapter validates each official root session, Project, or Project session before the
task; the selection is run-scoped and the default remains a new root session.
Source discovery is persisted separately from message history through a three-level read-through
path: process memory, the shared Parquet catalog, and the authenticated browser collector. The
`/agent` source routes reuse a 15-minute entry by default, coalesce concurrent refreshes by cache
key, and use stale-while-revalidate after expiry. They accept `refresh=1` for an explicit synchronous
browser re-check. A failed refresh falls back to the last known entry and marks the response as
stale; no remote conversation messages are written by this catalog.
The ChatGPT `/agent` status route performs the account probe and root source collection together
for one browser launch, returns the catalog to the page, and seeds the same cache through its
explicit `store` path. This keeps the status request and Recent sessions selection on one browser
opening; Project-session loading remains isolated by its canonical Project URL key.
Agent Chromium tasks clone the selected Edge or Chrome profile into a task-owned offscreen,
minimized context. Both suppress browser prompts and clean the task-owned profile on exit. Stale
cleanup is restricted to abandoned application-prefixed temporary directories older than 24 hours;
the user's normal browser profile and unrelated temporary paths are not modified.
Traditional failure handoff does not reuse that writable clone. It sends only the normalized official
conversation URL to the browser selected by the completed or failed run. On macOS, automatic Edge
handoff creates a traditional Edge window through the application's AppleScript model without an
`activate` command; user-triggered opening uses normal activation. Neither path grants the remote
ChatGPT page local filesystem authority.

## Data ownership

| Location | Owner and purpose | Git policy |
| --- | --- | --- |
| `local_store/` | User media, source catalogs, queues, manifests, and deletion previews | Ignored except `.gitkeep` |
| `logs/` | Local structured JSON-line logs | Ignored except `.gitkeep` |
| Platform-native CacheLikesFromTwitter settings path (`~/Library/Application Support/...` on macOS; `%APPDATA%\CacheLikesFromTwitter\...` on Windows) | Device-local configuration | Outside the repository |
| `app/`, `tests/`, `docs/`, `scripts/` | Versioned source, contracts, and checks | Committed |

`CACHELIKES_RUNTIME_ROOT` and `CACHELIKES_SETTINGS_PATH` are internal runtime-injection inputs.
Production startup leaves them unset. Pytest sets both before imports so tests cannot resolve the
user-owned locations above.

## Cross-workflow and safety invariants

- Only one cache job may own the shared `CacheTaskLock` at once, regardless of source.
- Account, project, and filename fragments are normalized before becoming local paths.
- File-serving routes reject traversal, symlink escape, hidden-state paths, unreadable files, and
  unsupported media extensions.
- Reset and browser deletion are data-changing operations. They must remain explicit user actions
  and must never be exercised against production data by the default suite.
- Browser automation starts from an already authenticated host session. It must not introduce a
  login-repair workflow without explicit product direction.
- Agent source context is an external data transfer to the selected ChatGPT account. The local UI
  discloses that boundary; tests never submit real project data or open authenticated profiles.
- The Flask server binds to the LAN by design. Cache and Local resources routes remain trusted-LAN
  surfaces. The Agent control plane accepts loopback directly and requires a signed session after
  a six-digit password unlock for RFC1918 or IPv6 ULA requests; public and host-rebinding requests
  are rejected.

## Testing boundary

Tests use pure functions, temporary directories, fakes, mocks, and Flask's `test_client()`.
They do not launch an authenticated browser, invoke yt-dlp, touch external services, or access
production cache, logs, settings, or browser profiles. See [TESTING.md](TESTING.md) for the
enforced quality gate and writing guidance.
