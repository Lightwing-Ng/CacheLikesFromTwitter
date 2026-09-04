# Engineering and test contract

Documentation version: `v1.3.2-codex.1`

This document supplements the repository-root [AGENTS.md](../AGENTS.md), which remains
authoritative. It records the project-specific documentation, testing, and handoff practices
adapted from the sibling project's quality model.

## Required reading before a change

- Read the root [AGENTS.md](../AGENTS.md) for repository-wide rules.
- Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing application flow, persistence,
  services, routes, or browser automation.
- Read [TESTING.md](TESTING.md) before changing code that has test or runtime-boundary impact.
- Read [OPERATIONS.md](OPERATIONS.md) before changing launch behavior, browser profiles,
  cache locations, deletion, reset, or LAN behavior.
- Read [CACHE_HANDOFF.md](CACHE_HANDOFF.md) before changing Cache routes, source switching,
  Text/Media behavior, LLM history persistence, or Grok synchronization.
- Read [STYLE_REFERENCE.md](STYLE_REFERENCE.md) before any markup, CSS, asset, or UI behavior
  change.
- Read [AGENT_OPTIMIZATION.md](AGENT_OPTIMIZATION.md) and the canonical shared contract it names
  before changing Site tools, WebMCP registration, capability metadata, or agent-facing schemas.
- Read [STATIC_FILE_HOUSEKEEPING.md](STATIC_FILE_HOUSEKEEPING.md) and its canonical shared
  contract before creating, copying, exporting, restoring, or removing static files. Complete the
  numbered-copy scan after the operation and before a commit, handoff, or final response.

## Runtime safety boundary

The following are user-owned production data or external boundaries:

- `local_store/` and its X, Grok, ChatGPT, and browser-deletion state
- `logs/` and the macOS agenticContext settings directory
- Chrome, Edge, and Safari profiles, including their authenticated sessions
- X, Grok, ChatGPT, yt-dlp, Playwright, and all network transport

Normal tests must not read, copy, modify, reset, or delete any of those production resources.
`tests/conftest.py` creates a process-scoped temporary runtime root before application modules
load. Do not bypass that boundary by importing the application before pytest has loaded
`conftest.py`, hard-coding `PROJECT_ROOT / "local_store"`, or clearing the test environment
variables.

Tests that genuinely require a signed-in browser or a live remote service must be marked
`@pytest.mark.live`, kept out of CI, and documented with their manual preconditions. Do not turn
a default test into a live test merely to increase coverage.

## Change workflow

1. Keep the change scoped to the requested behavior and identify the relevant architectural
   boundary.
2. Add or update behavior-level tests when regression risk is meaningful. Prefer deterministic
   fakes at the browser, subprocess, and transport boundaries.
3. Run the narrowest relevant test first, then run `./scripts/check.sh` on macOS/Linux or
   `.\scripts\check.ps1` on Windows for a complete change. After any static-file-producing
   operation, run the shared numbered-copy housekeeping workflow and record unresolved candidates.
4. Update the matching architecture, operations, testing, or known-constraints document when a
   contract changes.
5. Give every new or materially changed source file an explicit `Code version:` or
   `Documentation version:` marker. Use a patch-level increment for focused fixes and a
   higher-level increment for material changes.

## Handoff

State what changed, why it changed, the files touched, the exact validation performed, and any
remaining operating constraint. Do not represent browser, network, or cache behavior as verified
unless it was tested safely and explicitly.
