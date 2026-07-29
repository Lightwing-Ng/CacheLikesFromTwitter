# Visual Style Reference

## Authority

`/Users/lightwing/Desktop/antigravity/app` is the sibling project and the visual source
of truth for CacheLikesFromTwitter. When a UI decision is not explicitly constrained by
this project, follow the current implementation in that sibling project.

The reference applies to shared visual behavior, including the application shell,
typography, design tokens, frosted-glass surfaces, controls, overlays, responsive
behavior, and motion. It does not require copying product-specific financial views,
routes, assets, or JavaScript into this downloader.

## Color Token Source

The canonical palette is `/Users/lightwing/Desktop/antigravity/config.toml`, under
`[ui.theme.light]` and `[ui.theme.dark]`. `app/web/static/style.css` mirrors those
values through its `--theme-*`, status-color, glass, focus, and scrollbar tokens.

When the sibling project's theme changes, update both color-scheme variants here from
that configuration before adjusting component-specific CSS. Do not introduce replacement
hex values or derive a separate palette in this project.

## Required Workflow for UI Changes

1. Inspect the relevant reference files first. Start with
   `/Users/lightwing/Desktop/antigravity/app/web/static/assets/css/app.css`, then follow
   its imports in `foundation/`, `layout/`, `components/`, and `views/`.
2. Reuse the reference project's token names, font stack, spacing, corner radii, surface
   treatment, motion curves, and accessibility states where they apply to existing
   CacheLikesFromTwitter markup.
3. Keep CacheLikesFromTwitter-specific templates and interactions intact unless the
   requested change explicitly modifies behavior.
4. Verify the affected local page at `http://127.0.0.1:8666` at desktop and narrow
   viewport widths. Confirm the sidebar, dock, form controls, notices, and focus states
   remain usable.

## Local Adaptation

`app/web/static/style.css` contains a compatibility layer titled
`Sibling-project style synchronization`. It brings the shared shell, Univers Next
typography, frosted surfaces, and motion foundation into this project's existing
single-file stylesheet. Prefer extending that layer or migrating equivalent reference
rules deliberately; do not blindly paste whole product view styles.

If the sibling project changes materially, compare its current CSS modules with this
compatibility layer and update this document when the synchronization strategy changes.
