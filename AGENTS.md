# AGENTS.md

Code policy version: v1.1.0-agent-contract.1

This file defines mandatory collaboration rules for all coding agents in this repository (Claude, Codex, Antigravity, Trae, and future agents).

## 1) Scope and Priority
- This document applies to all AI-authored changes in this repository.
- Follow direct user instructions first.
- Then follow repository rules in this file.
- Keep behavior deterministic and auditable.

## 2) Change Discipline
- Make the smallest correct change that solves the requested problem.
- Do not refactor unrelated code unless explicitly requested.
- Do not modify files outside task scope.
- Preserve existing behavior unless behavior change is required by the request.

## 3) Read Before Edit
- Read target files and closely related call sites before editing.
- Verify assumptions from current source, not memory.
- If requirements are ambiguous, ask for clarification before high-impact changes.

## 4) Style and Structure
- Keep code comments and technical docs in American English.
- Reuse existing project patterns for naming, layout, and error handling.
- Prefer clear, maintainable code over clever one-liners.
- Avoid introducing new dependencies unless strictly necessary.

## 5) Testing and Verification
- Run focused checks for touched areas.
- Add or update tests when behavior changes or regression risk is meaningful.
- Do not add low-value tests that only mirror implementation details.
- If tests are not added, explain why validation is still sufficient.

## 6) UI and Frontend Changes
- Use local assets first (icons, images, styles) before introducing new resources.
- Maintain accessibility basics: labels, keyboard reachability, and semantic structure.
- Keep responsive behavior consistent with existing breakpoints and patterns.

## 7) Safety and Git Hygiene
- Never run destructive commands (for example, reset/clean forcefully) without explicit approval.
- Never revert unrelated local changes made by the user.
- Do not amend commits unless explicitly requested.
- Keep commits logically grouped and easy to review.

## 8) Host Runtime and Local Tooling
- Treat the authenticated likes page for the currently signed-in X account as the canonical entry page for this project.
- Assume Chrome on the host machine is already authenticated for that page.
- Do not rework, replace, or repeatedly troubleshoot login unless the user explicitly asks for login-related changes.
- Assume future user sessions will also start from that already logged-in page.
- Default to hot-starting from the host machine's PyCharm when local development launch is needed.
- Do not kill the existing PyCharm process unless the user explicitly requests it.
- Use `/usr/local/bin/python3.13` as the required interpreter for project execution unless the user explicitly overrides it.
- On this machine, treat `python3` as the valid Python alias and do not assume `python` is available or preferred.

## 9) Handoff Requirements
- Summarize what changed and why.
- Include touched file paths.
- Report verification steps performed and their outcomes.
- Call out known limitations or follow-up recommendations.

## 10) Definition of Done
- Requested behavior is implemented.
- Relevant checks pass or known failures are clearly reported.
- No unrelated files are changed.
- Handoff summary is complete and actionable.
