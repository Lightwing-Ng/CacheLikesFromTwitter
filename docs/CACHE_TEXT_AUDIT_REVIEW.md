# Cache Text audit review

Documentation version: `v1.0.0-codex.1`
Reviewed: 6 Sep 2026
Implementation: ChatGPT downloader v1.47.0-codex.1, Web v1.63.0-codex.1,
Cache page JavaScript v1.10.0-codex.1, ChatGPT history schema v2.

## Verdict

The external audit correctly identified four correctness/interaction defects and one
Gemini documentation mismatch. Its conclusions are static evidence, not proof that
Edge authentication or any provider API currently works. These defects are not
inherently Edge-specific: the affected persistence, skip, and route contracts are shared.

| Finding | Revised assessment | Resolution |
| --- | --- | --- |
| ChatGPT history path | Confirmed P1. Default path prevents Local resources from seeing new history, but the report establishes neither irreversible data loss nor an application-wide P0 outage. | Writer and reset resolve the root above `media/chatgpt/<project>`, producing `local_store/llm/chatgpt/history.parquet`. |
| ChatGPT cached-ID skip | Confirmed P1. Source timestamps identify message time, not conversation freshness. | Discovery carries `update_time`. Nullable `provider_revision` is stored atomically with each session's messages. Only a non-empty matching revision and complete source timestamps allow skipping; missing or changed revisions refetch the mapping. |
| Grok remembered Text mode | Confirmed P1 for the source-selector/remembered-mode route. Clicking the Text segment itself already opens Local resources; the entire Text flow was not broken. | Shared forms submit `cache_content_mode`. In Text, the primary action reads `View text history`; the server redirects to Grok history before configuration writes or Media startup. Compatibility Text worker routes remain available. |
| ChatGPT Text hydration | Confirmed P1 for misleading durable status; not itself evidence of missing stored messages. | Text page and mode-qualified status hydrate canonical Sessions/Messages counters independently of image catalog repair. Media cards remain available when Media is selected. |
| Gemini resume | Confirmed P2 documentation mismatch. Default full refresh is conservative for freshness, though slower. | Corrected the runbook. The service still performs fresh discovery and refreshes all sessions. The optional ID-only skip mode is not enabled. |

## Additional defects corrected

- ChatGPT Text startup previously executed image catalog repair and visual deduplication
  before branching into Text. The Text worker now bypasses that Media preparation.
- A failed or rate-limited mapping fetch could return a partial result that the service
  labeled Finished. Unprocessed discovered sessions, or empty discovery, now produce an
  incomplete result and failed task status. Successfully persisted sessions remain intact.
  This does not prove provider pagination is exhaustive: discovery page limits and remote
  response semantics remain separate live-verification concerns.

## Changed files

- `app/core/chatgpt_downloader.py`: root resolution, revision capture/skip, independent
  text hydration/preparation, and incomplete results.
- `app/core/chatgpt_service.py`: incomplete results cannot finish successfully.
- `app/core/resource_persistence.py`: nullable ChatGPT revision column, schema v2.
- `app/core/providers/__init__.py`: export Text snapshot/counter helpers.
- `app/web/app.py`: mode-qualified Text hydration and Grok Text submission guard.
- `app/web/static/cache-page.js`: mode submission, mode-specific cards, status query.
- `app/web/templates/_cache_page.html`, `_cache_page_components.html`, `chatgpt.html`:
  hidden mode field and separate Text/Media metric cards, preserving the existing grid.
- `docs/CACHE_HANDOFF.md`: corrected ChatGPT destinations, persistence/freshness,
  Grok review behavior, and Gemini resume contract.
- `tests/test_chatgpt_downloader.py`, `tests/test_web_app.py`, `tests/test_sidebar_e2e.py`:
  regression coverage for the changes above.
- Local `../SHARED_UI_SYNC.md`: existing Text/Media row updated; sibling remains Pending.

## Verification

All provider/browser operations in automated checks use fixtures or disposable local
browser contexts. The pre-edit Git worktree was clean.

```bash
/usr/local/bin/python3.13 -m pytest tests/test_chatgpt_downloader.py tests/test_services_and_web.py tests/test_web_app.py tests/test_gemini_downloader.py tests/test_chat_history_browser.py tests/test_style_tokens.py -q --disable-warnings --maxfail=3
```

Result: 348 passed, 541 subtests passed. Coverage includes a default-runtime target
fixture, canonical reset, durable revision equality after reopening the store, changed
and unknown revisions, provider revision discovery, app recreation, Text/media
separation, and a no-Media-start Grok submission assertion.

```bash
/usr/local/bin/python3.13 -m pytest tests/test_sidebar_e2e.py -k 'cache_text_metrics_and_grok_runtime_boundary or cache_sidebar_text_media_switcher_defaults_to_text or cache_source_switcher_click_matrix' -q --disable-warnings --maxfail=2
```

Result: 11 passed, 198 deselected. New cases verify seeded persistent Text counters,
hidden Media cards, Grok review submission, remembered Media restoration, no JavaScript
errors, and no page overflow at 1,280px and 390px. Ruff, JavaScript syntax, and
`git diff --check` passed. This is focused validation, not a full quality-gate claim.

## Boundaries and follow-up

- No live Edge profile or provider network validation was performed. Claude's rendered
  discovery bounds and the other providers' remote completeness remain unverified.
- The user-owned 8666 service was not restarted. A runtime reload is needed before it
  can serve the changed application code.
- Existing history in the former `local_store/media/llm/chatgpt` directory was not
  migrated, merged, overwritten, or deleted. Future syncs write the canonical path;
  old-only data will not become visible merely by updating the application.
- Explicit migration needs separate reconciliation if remote messages are no longer
  available. Do not blindly replace an existing canonical file with a legacy file.
- The numbered-copy scan retained 15 existing candidates: different-byte files and/or
  protected local data. Metadata/hash evidence is in
  `/tmp/agentic-numbered-copy-final-review.json`. No cleanup deletion occurred.
- The historical `antigravity` path is unavailable; the current sibling Worthward base
  template was inspected read-only. No sibling implementation was changed or validated.
  Sibling UI sync pending: review the equivalent Cache Text/Media runtime and metric
  contract before convergence.
