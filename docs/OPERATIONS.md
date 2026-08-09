# Operations guide

Documentation version: `v1.0.2-codex.1`

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

The console has no login or authorization layer. Keep it on a trusted local network, do not expose
it through router port forwarding, and do not publish it through a public tunnel or reverse proxy.

## Browser-session preconditions

- X caching begins from the currently signed-in Likes page in a supported host browser.
- Grok and ChatGPT syncing use their existing authenticated browser sessions.
- Chrome, Edge, and Safari support differs by source and automation engine; use the session probe
  in the console before a long sync.
- The first Chromium-backed run works best after normal Chrome windows are closed, because a
  profile lock can prevent Playwright from creating its isolated context.
- Do not add or repeatedly troubleshoot login flows as part of normal runtime operation. The
  application assumes an existing signed-in session.

## Local data

| Location | Contents |
| --- | --- |
| `local_store/x/` | X media and cache-catalog state |
| `local_store/grok/` | Grok media, catalog, manifest, and work queue |
| `local_store/chatgpt/<project-name>/` | ChatGPT images and catalog state |
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
- Cache inconsistency: use the local-media browser to inspect the affected source before choosing a
  source-specific reset. Avoid deleting catalog or manifest files by hand.

## Safe development checks

Run `./scripts/test.sh` or `./scripts/check.sh` for offline validation. Pytest redirects all
default runtime paths into temporary directories; tests must never be pointed at the production
cache, log, settings, or browser-profile locations.
