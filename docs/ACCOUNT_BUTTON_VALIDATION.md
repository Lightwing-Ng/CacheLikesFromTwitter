# Account probe recovery and secondary-button alignment

Documentation version: `v1.0.0`
Date: 5 Sep 2026

## Result

The Edge ChatGPT bootstrap had cached `logged_in: false` after navigation failed
with `net::ERR_CONNECTION_CLOSED`. A forced live probe succeeded with
`logged_in: true` and `can_download: true`; the existing Agent page then displayed
`Account verified`. No new account login or Agent prompt was submitted.

ChatGPT bootstrap failures before authentication now retain an unknown (`null`)
login state. The compact status card exposes failure details and a right-aligned
Recheck action that forces fresh verification. Confirmed signed-out responses
retain the login action. Client and ChatGPT bootstrap cache namespaces advance to
avoid reusing failures encoded under the old contract.

Both projects' secondary-button primitives now keep intrinsic width and align to
the right edge of their owning container. Agent status-copy fills its row so the
login action reaches the card's inner right edge. The catalog preview follows the
same contract.

## Changed paths and versions

- agenticContext: `app/core/chatgpt_agent_sources.py` v1.6.2-codex.1,
  `app/web/app.py` v1.60.1-codex.1,
  `app/web/static/browser-session-status.js` v1.9.1-codex.1,
  `app/web/static/style.css` v2.93.3-codex.1,
  `app/web/templates/_browser_session_status.html` v1.3.3-codex.1,
  and stylesheet/script versions in the six shared template consumers.
- Tests: `tests/test_chatgpt_agent_sources.py`, `tests/test_style_tokens.py`,
  `tests/test_web_app.py`, `tests/test_sidebar_e2e.py`,
  `tests/test_style_alignment_e2e.py`.
- Worthward: `app/web/static/assets/css/components/forms.css` v0.20.1,
  `app/web/static/assets/css/app.css` v0.70.2, cache-busting references in
  `app/web/templates/base.html` and `live_trading_unlock.html`,
  `tests/e2e/style-token-alignment.spec.mjs`, and `SHARED_UI_LAYOUT_CONTRACT.md`.
- Shared alignment documentation: `docs/STYLE_REFERENCE.md` and
  `/Users/lightwing/Desktop/SHARED_UI_SYNC.md`.

Pre-existing dirty changes in both workspaces were preserved. These paths may
also contain work that predates this task; no commit or reset was performed.

## Verification

- `/usr/local/bin/python3.13 -m pytest tests/test_chatgpt_agent_sources.py tests/test_style_tokens.py tests/test_web_app.py -q`:
  exit 0, 238 passed and 539 subtests passed.
- `/usr/local/bin/python3.13 -m pytest tests/test_style_alignment_e2e.py -q`:
  exit 0, 8 passed. Includes network failure, confirmed sign-out, right-aligned
  login/recheck, forced refresh, and ready-state recovery at 1,024px and 390px.
- Existing `test_agent_browser_status_login_action_matches_probe_state` cases:
  2 passed in the focused sidebar run.
- Worthward `./scripts/test.sh tests/test_table_style_tokens.py tests/test_web_token_registry.py tests/test_layout_anchor_contract.py`:
  exit 0, 75 passed.
- Worthward `./scripts/test_e2e.sh tests/e2e/style-token-alignment.spec.mjs`:
  exit 0, 4 passed at 1,024px, 800px, and 390px, including touch controls.
- JavaScript syntax, focused Ruff, and both `git diff --check` commands passed.
- Live 8666 and 8688 catalog DOM checks: secondary-button right edges differed
  from the owning demo edge by less than 0.001px at both tested sizes. The browser
  zoom yielded actual CSS viewport widths of 1,138px and 433px; exact breakpoint
  coverage comes from the isolated tests above. Temporary viewport overrides were
  reset and temporary tabs closed.
- agenticContext `./scripts/check.sh`: exit 1; 1,436 passed, 558 subtests passed,
  3 failed. Two pagination cases expect a composer gap of at least 23px but measure
  10px (`tests/test_sidebar_e2e.py:1671`); the completion case expects question
  header overflow but measures 128px content within a 140px header (`:8481`).
  These assertions concern existing response layout, not the new login/recheck
  selectors. No unrelated layout or test expectation was changed for this gate.
- Worthward `./scripts/check.sh`: Python passed 1,156 tests, 6 skipped, and
  180 subtests; JavaScript passed 319 tests. The broad browser suite recorded
  21 passed and 2 failed before being stopped (exit 130; 1 interrupted and
  284 not run). Failures: Backtest output drawer overlaps its chart heading;
  the Style token copy test expects the previously changed stepper to be 24px,
  while the current shared contract is 30px. The focused 4-case component suite
  passed independently. The isolated 8699 server was confirmed stopped.

The complete worktrees therefore do not have green full gates. These results are
not a claim that every pre-existing local change has been validated.

## Runtime and retained files

The user-owned services were not restarted. The 8666 process was verified to run
from agenticContext and still serves its cached older templates/backend. Reloading
picked up current static styling and the real recovered account status, but the
new backend failure classification and Recheck markup require a normal restart.

Computer Use denied Terminal access; isolated tests used the command executor
without changing or closing existing Terminal windows.

The final numbered-copy audit retained 23 files: 14 protected local-data/log files
and 9 different-byte coverage files. Six coverage candidates initially had no
primary; the full gates generated primary coverage files, and final hashing
confirmed that all nine coverage pairs differ. Nothing was
deleted. Metadata, hashes, Git state, and open-handle evidence are recorded in
`/tmp/account-buttons-housekeeping.json`. No synthetic data was written to
production stores; the forced real browser probe updated its normal source cache.
