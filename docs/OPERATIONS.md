# Operations guide

Documentation version: `v1.5.0-codex.2`

## Launch

Prepare the supported local runtime:

```bash
./scripts/setup_python.sh
```

Start the Flask console:

```bash
./scripts/run_app.sh
```

The normal server address is `http://127.0.0.1:8666`. The application also binds to `0.0.0.0`,
which permits access from trusted devices on the same LAN at `http://<host-lan-ip>:8666`.

Cache and Local resources routes have no login layer, so keep the console on a trusted local
network, do not expose it through router port forwarding, and do not publish it through a public
tunnel or reverse proxy. The Agent control plane is the exception: loopback requests continue
directly, while private-network requests to `/agent` and `/api/agent/*` require the six-digit
password gate. The default password is `195135`; set `CACHELIKES_AGENT_PASSWORD` before launch
to override it. A successful unlock is stored in the signed Flask session for that browser.

## Browser-session preconditions

- X caching begins from the currently signed-in Likes page in a supported host browser.
- Grok and ChatGPT syncing use their existing authenticated browser sessions.
- A Safari-backed Cache task owns one standard, visible background window with native
  window controls. It closes and verifies that exact window at task end; it must not
  hide, minimize, move offscreen, reuse, or accumulate Safari windows.
- Chrome, Edge, and Safari support differs by source and automation engine; use the session probe
  in the console before a long sync.
- Edge tasks clone the selected profile into one headless temporary context; Chrome tasks use
  an isolated background context. Neither brings a browser window to the front, sends desktop
  mouse or keyboard events, or writes to the user's normal profile. First-run, crash,
  notification, and repost prompts are disabled for the task-owned context.
- Normal task exit closes the isolated context and removes its temporary profile. Each subsequent
  Chromium launch also removes only abandoned `cachelikes-edge-*` or `cachelikes-chrome-*`
  directories older than 24 hours; unrelated temporary paths are not touched.
- Do not add or repeatedly troubleshoot login flows as part of normal runtime operation. The
  application assumes an existing signed-in session.

## Computer Use Agent

- `/agent` and its `/api/agent/*` control routes accept host-loopback requests directly. Requests
  from RFC1918 private IPv4 or IPv6 ULA addresses show the password gate before the Agent page or
  API is served; public and host-rebinding addresses remain rejected.
- Each task defaults to a new root-level ChatGPT Web conversation in the selected authenticated
  Safari, Edge, or Chrome session. The Agent sidebar can also join one of the 20 most recent root
  sessions, start a session in one of the 20 most recent projects, or join one of a project's
  20 most recent sessions.
- Settings → Agent controls the operating system, terminal permissions, context limit, turn limit,
  command timeout, and per-operating-system prompts. The operating-system setting detects the host and
  selects macOS or Windows automatically. macOS execution is available; Windows is represented for
  future configuration and is blocked on the current host.
- Chromium can attach the generated Markdown context directly. Safari falls back to compact
  on-demand reads because web content cannot programmatically assign a local file to a protected
  file input.
- Sending a task transmits the generated context and requested source excerpts to the selected
  ChatGPT account. Review ChatGPT data controls before using private or regulated source code.
- Stop requests end current web generation and terminate the active local command process group.
- Agent source discovery is cached in `local_store/agent/agent_source_catalog.parquet` for 15
  minutes per provider/browser/Project key. Fresh reads use process memory; the first read after a
  restart hydrates memory from Parquet. Expired passive reads return the previous catalog while a
  single background refresh runs for that key. Use `refresh=1` on `/api/agent/sources` or
  `/api/agent/project-sessions` for an intentional synchronous Edge/Chrome/Safari re-check. The
  response's `cache.status` is `hit`, `miss`, `refreshed`, or `stale`; a stale response means the
  browser check failed or is still refreshing while the previous catalog was retained.
- ChatGPT on `/agent` uses one agent-scoped browser bootstrap through Recent sessions: the same
  browser context verifies readiness, collects the root session/project catalog, returns it to the
  selector, and seeds the memory/Parquet cache. A second browser launch is reserved for a later
  Project-session selection or an explicit refresh.

## Local data

| Location | Contents |
| --- | --- |
| `local_store/x/` | X media and cache-catalog state |
| `local_store/grok/` | Grok media, catalog, manifest, and work queue |
| `local_store/chatgpt/<project-name>/` | ChatGPT images and catalog state |
| `local_store/llm/chatgpt/history.parquet` | ChatGPT typed text history |
| `local_store/llm/gemini/history.parquet` | Gemini typed text history |
| `local_store/llm/grok/history.parquet` | Grok typed text history |
| `local_store/agent/agent_source_catalog.parquet` | Provider-neutral Agent session and Project discovery cache |
| `local_store/.cache_task.lock` | Cross-source advisory task lock |
| `local_store/.browser-trash/` | Recoverable previews moved by the local-media browser |
| `local_store/.browser_deleted.json` | Browser deletion tombstones and exclusion identities |
| `logs/cachelikes.log.jsonl` | Structured local application log |
| `~/Library/Application Support/CacheLikesFromTwitter/settings.json` | Device-local saved settings |

All cache and log paths are ignored by Git. Back up local media before using any destructive reset
operation.

## Reset, deletion, and restoration

The local-media browser's Delete action moves a supported media file into recoverable browser trash
and records a tombstone so the same source resource is not immediately re-downloaded. Restore moves
the retained preview back to its original cache path.

The Grok and ChatGPT reset actions are more destructive: they remove their cached media and source
state for a complete future resync. Run them only while the corresponding task is idle and only when
you intend to discard that cache. Do not use reset operations as a routine troubleshooting step.

## Troubleshooting

- Missing Playwright Chromium: run `./scripts/setup_python.sh`, or run
  `CACHELIKES_PYTHON=/path/to/python3 -m playwright install chromium` with Python 3.13 or 3.14.
- Missing downloader: install the project requirements so `yt-dlp` is available to the selected
  supported interpreter.
- Browser profile lock: close duplicate normal browser windows, then retry the session probe.
- ChatGPT parallel sync: the project workflow uses up to three isolated Edge contexts; lower the
  shared Download workers setting only when the machine cannot sustain that browser load.
- Sync failure: inspect `logs/cachelikes.log.jsonl` for full structured diagnostics. The UI shows a
  bounded status message while retaining the detailed local log.
- Grok Text cache: use the `Cache text history` action on `/cache/grok`. It follows all Grok
  conversation pages and response trees; do not replace it with a visible-sidebar scroll. See
  [CACHE_HANDOFF.md](CACHE_HANDOFF.md) for status routes, verified counts, and recovery commands.
- Gemini Text cache: preserve the saved Safari navigation interval. If Safari reaches
  `Failed to open page`, stop that run, close its single task window, and restart after
  confirming the window count returned to baseline. Never accelerate the run by
  reducing the saved interval and never open parallel Safari task windows.
- Gemini Text on Edge: use the headless Chromium history-RPC path. It follows the authenticated
  `MaZiqc` cursor, stores a 24-hour discovery checkpoint, and resumes by skipping cached session
  IDs. The current verified run exposed `740` sessions and cached `736` text-bearing sessions
  with `4,045` messages. A no-text session is an expected skip; a Google human-verification
  challenge must stop the task and be reported to the operator.
- Cache inconsistency: use the local-media browser to inspect the affected source before choosing a
  source-specific reset. Avoid deleting catalog or manifest files by hand.

## Safe development checks

Run `./scripts/test.sh` or `./scripts/check.sh` for offline validation. Pytest redirects all
default runtime paths into temporary directories; tests must never be pointed at the production
cache, log, settings, or browser-profile locations.
