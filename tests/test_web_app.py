"""Focused regression tests for the local web console."""

# Code version: v1.42.1-codex.1

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.core.state import TaskSnapshot
from app.core.config import CrawlConfig
from app.core.local_media_browser import stable_media_id
from app.web.app import create_app, format_media_size, reconcile_cached_snapshot, render_prompt_markdown
from app.web.cache_sources import CACHE_SOURCE_VIEWS


SIDEBAR_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/sidebar.js"
SETTINGS_NAVIGATION_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/settings-navigation.js"
)
SETTINGS_DIRECTORY_PICKER_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/settings-directory-picker.js"
)
CACHE_PAGE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/cache-page.js"
BROWSER_SESSION_PICKER_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/browser-session-picker.js"
)
NUMERIC_INPUT_FORMAT_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/numeric-input-format.js"
)
LOCAL_MEDIA_BROWSER_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/local-media-browser.js"
THEME_MODE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/theme-mode.js"
BROWSER_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app/web/templates/browser.html"
WAITING_MODAL_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/waiting-modal.js"
LOADING_SPINNER_ASSET_PATH = Path(__file__).resolve().parents[1] / "app/web/static/images/loading.spinner.svg"


class WebAppTests(unittest.TestCase):
    """Validate the index page renders live progress metrics."""

    def test_cache_source_registry_is_alphabetized_and_extensible(self) -> None:
        labels = [source.label for source in CACHE_SOURCE_VIEWS]

        self.assertEqual(labels, sorted(labels, key=str.casefold))
        self.assertEqual([source.key for source in CACHE_SOURCE_VIEWS], ["chatgpt", "grok", "x"])
        self.assertEqual(len({source.template_name for source in CACHE_SOURCE_VIEWS}), len(CACHE_SOURCE_VIEWS))

    def test_index_includes_progress_metric_counters(self) -> None:
        app = create_app()

        with app.test_client() as client:
            response = client.get("/")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="progress_downloaded_posts"', body)
        self.assertIn('id="progress_downloaded_images"', body)
        self.assertIn('id="progress_downloaded_videos"', body)

    def test_chatgpt_notice_names_the_selected_background_browser(self) -> None:
        with patch(
            "app.web.app.load_saved_config",
            return_value=CrawlConfig(chatgpt_browser="safari"),
        ):
            app = create_app()
        with app.test_client() as client:
            response = client.get("/chatgpt")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("offscreen Safari session", body)
        self.assertIn(">Safari session</span>", body)
        self.assertNotIn("offscreen Edge session", body)

    def test_pages_share_the_direct_cache_dock_link(self) -> None:
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with app.test_client() as client:
                grok_response = client.get("/grok")
                chatgpt_response = client.get("/chatgpt")
                index_response = client.get("/")
                settings_response = client.get("/settings")
                browser_response = client.get("/browser")

        grok_body = grok_response.get_data(as_text=True)
        chatgpt_body = chatgpt_response.get_data(as_text=True)
        index_body = index_response.get_data(as_text=True)
        settings_body = settings_response.get_data(as_text=True)
        browser_body = browser_response.get_data(as_text=True)

        self.assertEqual(grok_response.status_code, 200)
        self.assertEqual(chatgpt_response.status_code, 200)
        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(browser_response.status_code, 200)
        self.assertIn('data-section-link="settings"', grok_body)
        self.assertIn('data-cache-source-switcher-path="/chatgpt"', grok_body)
        self.assertIn('data-section-link="browser"', browser_body)
        self.assertIn("ChatGPT cache overview", chatgpt_body)
        self.assertIn('name="chatgpt_project_url"', chatgpt_body)
        self.assertIn('name="chatgpt_startup_timeout_seconds"', chatgpt_body)
        self.assertIn('name="chatgpt_scan_wait_seconds"', chatgpt_body)
        self.assertIn("Project or chat URL", chatgpt_body)
        self.assertIn("Known images skipped this run", chatgpt_body)
        self.assertIn("Media failures this run", chatgpt_body)
        self.assertIn("Task failures", chatgpt_body)
        self.assertIn('data-status-field="task_failures"', chatgpt_body)
        self.assertNotIn('name="chatgpt_project_name"', chatgpt_body)
        self.assertIn('data-platform="chatgpt"', chatgpt_body)
        self.assertIn('action="/cache/chatgpt/start"', chatgpt_body)
        self.assertNotIn('class="status-copy chatgpt-sidebar-note"', chatgpt_body)
        self.assertIn('id="status_progress_value"', chatgpt_body)
        self.assertIn('id="progress_processed_label"', chatgpt_body)
        self.assertIn('cache-page.js?v=cache-page-v1.5.0-codex.1', chatgpt_body)
        self.assertIn(
            'browser-session-picker.js?v=browser-session-picker-v1.7.0-codex.1',
            chatgpt_body,
        )
        chatgpt_form_identifier = chatgpt_body.index('id="start_form_chatgpt"')
        chatgpt_form_start = chatgpt_body.rfind("<form", 0, chatgpt_form_identifier)
        chatgpt_form_end = chatgpt_body.index("</form>", chatgpt_form_start)
        chatgpt_form = chatgpt_body[chatgpt_form_start:chatgpt_form_end]
        self.assertIn("field-grid", chatgpt_form)
        self.assertIn('name="download_workers"', chatgpt_form)
        self.assertIn('name="max_media_file_size_mib"', chatgpt_form)
        self.assertEqual(chatgpt_form.count('class="field"'), 3)
        self.assertEqual(chatgpt_form.count("text-input-control"), 3)
        self.assertEqual(chatgpt_form.count('data-cache-number-field'), 4)
        self.assertEqual(chatgpt_form.count('data-cache-number-stepper="increment"'), 4)
        self.assertEqual(chatgpt_form.count('data-cache-number-stepper="decrement"'), 4)
        self.assertIn('data-number-min="1"', chatgpt_form)
        self.assertIn('data-number-max="600"', chatgpt_form)
        self.assertIn('data-number-step="0.1"', chatgpt_form)
        cache_page_script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        numeric_input_script = NUMERIC_INPUT_FORMAT_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("function initializeNumberSteppers()", numeric_input_script)
        self.assertNotIn("function initializeNumberSteppers()", cache_page_script)
        self.assertIn("data.progress_unit", cache_page_script)
        for source, body in (
            ("x", index_body),
            ("grok", grok_body),
            ("chatgpt", chatgpt_body),
            ("settings", settings_body),
        ):
            with self.subTest(common_config_source=source):
                self.assertEqual(body.count('class="cache-common-config"'), 1)
                self.assertIn("Shared cache configuration", body)
                self.assertIn('name="download_workers"', body)
                self.assertIn('name="max_media_file_size_mib"', body)
                self.assertIn(f'id="{source}_cache_common_config_help"', body)
                self.assertIn('numeric-input-format.js?v=numeric-input-format-v1.1.0-codex.1', body)
                self.assertEqual(
                    body.count('data-cache-number-field'),
                    body.count('class="formatted-number-input cache-number-input'),
                )
                self.assertEqual(
                    body.count('data-cache-number-field'),
                    body.count('data-cache-number-stepper="increment"'),
                )
                self.assertEqual(
                    body.count('data-cache-number-field'),
                    body.count('data-cache-number-stepper="decrement"'),
                )
        for body in (grok_body, chatgpt_body, index_body, settings_body, browser_body):
            with self.subTest(page=body[:40]):
                dock_start = body.index('<nav class="sidebar-dock"')
                dock_end = body.index("</nav>", dock_start) + len("</nav>")
                dock_markup = body[dock_start:dock_end]
                self.assertEqual(dock_markup.count('data-cache-source-option='), 0)
                self.assertEqual(dock_markup.count('data-section-link='), 3)
                self.assertEqual(dock_markup.count('data-dock-section='), 3)
                self.assertIn('data-dock-section="cache"', dock_markup)
                self.assertIn('data-dock-section="browser"', dock_markup)
                self.assertIn('data-dock-section="settings"', dock_markup)
                self.assertEqual(dock_markup.count('aria-current="page"'), 1)
                self.assertIn('href="/"', dock_markup)
                self.assertIn('aria-label="Caches"', dock_markup)
                self.assertIn('data-tooltip="Caches"', dock_markup)
                self.assertIn('class="icon dock-icon dock-icon-cache"', dock_markup)
                self.assertNotIn('data-cache-source-menu', dock_markup)
                self.assertNotIn('sidebar-dock-cache-trigger', dock_markup)
                self.assertNotIn('sidebar-dock-cache-dropdown', dock_markup)
                self.assertNotIn('aria-haspopup', dock_markup)
                self.assertNotIn('aria-expanded', dock_markup)
                self.assertNotIn('class="browser-picker-option-icon"', dock_markup)
                self.assertIn('src="/static/sidebar.js?v=sidebar-v1.7.1-codex.1"', body)
                self.assertIn('src="/static/theme-mode.js?v=theme-mode-v1.0.0-codex.1"', body)
                self.assertIn('id="global_theme_toggle"', body)
                self.assertIn('class="global-quick-action-button global-theme-toggle"', body)
                self.assertIn('class="sidebar-dock-label"', dock_markup)
                self.assertNotIn("cachelikes:browser-sidebar-open", body)
                self.assertIn('waiting-modal.js?v=waiting-modal-v1.0.0-codex.1', body)
                self.assertIn('id="cache_wait_modal"', body)
                self.assertIn('class="workspace-modal-overlay cache-wait-modal"', body)
                self.assertIn('suggestion-loading-spinner workspace-modal-icon', body)

        sidebar_script = SIDEBAR_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'const sidebarOverlayMedia = window.matchMedia("(max-width: 900px)");',
            "const shouldShowBackdrop = sidebarOverlayMedia.matches && isSidebarOpen;",
            'const dockLocationMemoryPrefix = "cachelikes:dock-location:v1:";',
            'const browserFilterNames = ["source", "kind", "q", "sort", "session_view"];',
            'window.sessionStorage.getItem(dockLocationMemoryKey(section))',
            'window.sessionStorage.setItem(dockLocationMemoryKey(section), normalizedLocation);',
            'sidebarDock.querySelectorAll("[data-dock-section], [data-section-link]")',
            'function dockSectionForLink(link) {',
            'document.querySelector(".browser-filter-form")',
            'data-cache-source-switcher-option][aria-selected="true"]',
            'data-settings-category][aria-current="page"]',
            'browserFilterForm?.addEventListener("input", rememberCurrentDockLocation);',
            'sidebarDock?.addEventListener("click", (event) => {',
            'if (rememberedLocation) dockLink.href = rememberedLocation;',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, sidebar_script)

        self.assertNotIn(
            'const browserFilterNames = ["source", "kind", "q", "sort", "page"]',
            sidebar_script,
        )
        self.assertNotIn('window.matchMedia("(max-width: 600px)")', sidebar_script)
        for body, sidebar_title in (
            (index_body, "Caches"),
            (grok_body, "Caches"),
            (chatgpt_body, "Caches"),
            (browser_body, "Browser"),
            (settings_body, "Settings"),
        ):
            with self.subTest(sidebar_title=sidebar_title):
                self.assertIn(
                    f'<section class="hero">\n                <h1>{sidebar_title}</h1>\n            </section>',
                    body,
                )
        for body in (index_body, grok_body, chatgpt_body):
            with self.subTest(session_page=body[:40]):
                self.assertIn('data-role="browser-session-spinner"', body)
                heading_start = body.index('<div class="section-heading">')
                heading_end = body.index('</div>', heading_start) + len('</div>')
                heading_markup = body[heading_start:heading_end]
                self.assertIn('data-cache-source-switcher', heading_markup)
                self.assertIn('data-cache-source-switcher-trigger', heading_markup)
                self.assertIn('class="trade-strategy-select form-select trade-strategy-trigger browser-session-trigger cache-source-switcher-trigger"', heading_markup)
                self.assertIn('aria-label="Switch cache source"', heading_markup)
                self.assertEqual(heading_markup.count('data-cache-source-switcher-option='), 3)
                self.assertIn('data-cache-source-switcher-path="/chatgpt"', heading_markup)
                self.assertIn('data-cache-source-switcher-path="/grok"', heading_markup)
                self.assertIn('data-cache-source-switcher-path="/"', heading_markup)
                self.assertNotIn('<p class="section-kicker">Download</p>', heading_markup)
                self.assertNotIn('<select', heading_markup)
                self.assertIn('class="cache-phase-live-marker"', body)
                self.assertIn('role="status"', body)
                self.assertIn('id="recent_events_pagination"', body)
                self.assertIn(
                    'class="browser-pagination local-store-pagination local-store-pagination--floating events-pagination is-animated"',
                    body,
                )
                self.assertIn('class="local-store-pagination-indicator" aria-hidden="true"></span>', body)
                self.assertNotIn('class="events-page-button"', body)
                self.assertNotIn('class="events-page-indicator"', body)
        self.assertIn('data-section-link="browser"', browser_body)
        self.assertIn("Cached media browser", browser_body)
        self.assertIn('data-browser-source-filter', browser_body)
        self.assertEqual(browser_body.count('data-browser-source-filter-option='), 4)
        self.assertIn('browser-source-filter.js?v=browser-source-filter-v1.2.0-codex.1', browser_body)
        self.assertIn('class="trade-strategy-select form-select trade-strategy-trigger browser-source-filter-trigger"', browser_body)
        self.assertIn('class="trade-strategy-dropdown-option browser-source-filter-option', browser_body)
        self.assertIn("--cache-source-mark: url('/static/images/x.svg')", browser_body)
        self.assertIn("--cache-source-mark: url('/static/images/grok.svg')", browser_body)
        self.assertIn("--cache-source-mark: url('/static/images/ChatGPT-Logo.svg')", browser_body)
        self.assertNotIn("Apply filters", browser_body)
        self.assertIn('id="status_progress_detail"', grok_body)
        self.assertIn("data.queued_tweets", cache_page_script)
        self.assertIn("data.processed_tweets", cache_page_script)
        self.assertNotIn('id="reset_button"', grok_body)
        self.assertIn('id="reset_button"', settings_body)
        self.assertIn('id="reset_chatgpt_button"', settings_body)
        self.assertIn('name="chatgpt_startup_timeout_seconds"', settings_body)
        self.assertIn('name="chatgpt_scan_wait_seconds"', settings_body)
        self.assertIn('name="max_media_file_size_mib"', settings_body)
        self.assertIn("Max cached file size (MiB)", settings_body)
        self.assertIn('name="shadow_backup_enabled"', settings_body)
        self.assertIn('name="shadow_backup_auto_sync"', settings_body)
        self.assertIn('name="shadow_backup_mirror_deletions"', settings_body)
        self.assertIn('name="shadow_backup_destination"', settings_body)
        self.assertIn('id="shadow_backup_choose_destination"', settings_body)
        self.assertIn('id="chrome_user_data_dir_choose"', settings_body)
        self.assertEqual(settings_body.count("data-settings-directory-picker"), 2)
        self.assertIn('data-shadow-backup-status-spinner', settings_body)
        self.assertIn('formaction="/settings/shadow-backup/sync"', settings_body)
        self.assertIn('shadow-backup-settings.js?v=shadow-backup-settings-v1.3.0-codex.1', settings_body)
        self.assertIn('settings-directory-picker.js?v=settings-directory-picker-v1.0.0-codex.1', settings_body)
        self.assertIn("Danger zone", settings_body)

    def test_shadow_backup_destination_control_uses_the_macos_folder_picker(self) -> None:
        selected_path = Path("/tmp/OneDrive/AICaches")
        app = create_app()

        with patch("app.web.app.choose_shadow_backup_destination", return_value=selected_path) as picker:
            with app.test_client() as client:
                response = client.post(
                    "/api/settings/shadow-backup/destination",
                    json={"initial_path": "/tmp/OneDrive"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"destination": str(selected_path)})
        picker.assert_called_once_with(Path("/tmp/OneDrive"))

    def test_settings_directory_picker_supports_registered_path_fields(self) -> None:
        selected_path = Path("/tmp/Chrome/User Data")
        app = create_app()

        with patch("app.web.app.choose_settings_directory", return_value=selected_path) as picker:
            with app.test_client() as client:
                response = client.post(
                    "/api/settings/directory",
                    json={
                        "field": "chrome_user_data_dir",
                        "initial_path": "/tmp/Chrome",
                    },
                )
                unknown_response = client.post(
                    "/api/settings/directory",
                    json={"field": "unsupported_path"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"directory": str(selected_path)})
        self.assertEqual(unknown_response.status_code, 400)
        picker.assert_called_once_with(
            Path("/tmp/Chrome"),
            "Select Chrome user data directory",
        )

    def test_settings_page_groups_controls_into_accessible_categories(self) -> None:
        app = create_app()

        with app.test_client() as client:
            response = client.get("/settings")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="Settings categories"', body)
        self.assertIn(
            'settings-navigation.js?v=settings-navigation-v1.0.0-codex.1',
            body,
        )
        self.assertIn(
            'class="settings-action-package settings-callout-card-primary settings-save-package"',
            body,
        )
        self.assertIn('class="settings-action-package-copy settings-callout-text"', body)
        self.assertIn('class="settings-callout-form settings-action-package-form"', body)
        self.assertIn('form="settings_form"', body)
        settings_form_start = body.index('id="settings_form"')
        settings_form_end = body.index("</form>", settings_form_start)
        save_package_start = body.index("data-settings-save-bar")
        self.assertLess(settings_form_end, save_package_start)
        for category in ("browser", "downloads", "chatgpt", "cloud", "maintenance"):
            with self.subTest(category=category):
                self.assertIn(f'data-settings-category="{category}"', body)
                self.assertIn(f'data-settings-panel="{category}"', body)
                self.assertIn(f'id="settings-{category}"', body)

        script = SETTINGS_NAVIGATION_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'window.addEventListener("hashchange"',
            'link.setAttribute("aria-current", "page")',
            "panel.hidden = !isActive;",
            'window.matchMedia("(max-width: 900px)").matches',
            "window.setSidebarOpen?.(false, { animate: true });",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        directory_picker_script = SETTINGS_DIRECTORY_PICKER_SCRIPT_PATH.read_text(
            encoding="utf-8"
        )
        for fragment in (
            'document.querySelectorAll("[data-settings-directory-picker]")',
            'fetch("/api/settings/directory"',
            "field: fieldName",
            "initial_path: input.value",
            'input.setAttribute("aria-invalid", "true")',
        ):
            with self.subTest(directory_picker_fragment=fragment):
                self.assertIn(fragment, directory_picker_script)

    def test_sidebar_script_has_no_cache_source_menu_controls(self) -> None:
        script = SIDEBAR_SCRIPT_PATH.read_text(encoding="utf-8")

        forbidden_fragments = (
            "data-cache-source-menu",
            "sidebar-dock-cache-trigger",
            "positionCacheSourceDropdown",
            "setCacheSourceMenuOpen",
            "cacheSourceDropdown",
            "cacheSourceOptions",
        )

        for fragment in forbidden_fragments:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, script)

    def test_cache_source_heading_switcher_navigates_within_the_local_app(self) -> None:
        script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")

        expected_fragments = (
            'document.querySelector("[data-cache-source-switcher]")',
            'cacheSourceSwitcher.querySelector("[data-cache-source-switcher-trigger]")',
            'cacheSourceSwitcher.querySelector("[data-cache-source-switcher-menu]")',
            'cacheSourceSwitcher.classList.toggle("is-cache-source-menu-open", isOpen)',
            'option.dataset.cacheSourceSwitcherPath',
            "new URL(targetPath, window.location.origin)",
            "targetUrl.origin !== window.location.origin",
            "window.location.assign(targetUrl.href)",
        )

        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_recent_events_use_the_resource_browser_pagination_pattern(self) -> None:
        script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")

        expected_fragments = (
            'document.getElementById("recent_events_pagination")',
            "function buildRecentEventsPaginationItems(totalPages, currentPage)",
            'items.push({ kind: "previous", page: startPage - 1 })',
            'items.push({ kind: "ellipsis" })',
            'button.className = `local-store-page-button',
            'indicator.className = "local-store-pagination-indicator"',
            "function positionRecentEventsPaginationIndicator()",
            'indicator.style.transform = `translate3d(${x}px, ${y}px, 0)`',
            'window.addEventListener("resize", positionRecentEventsPaginationIndicator',
        )

        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        for removed_identifier in (
            "recent_events_prev",
            "recent_events_next",
            "recent_events_page",
        ):
            with self.subTest(removed_identifier=removed_identifier):
                self.assertNotIn(removed_identifier, script)

    def test_cache_status_polling_preserves_optimistic_content_and_avoids_repeated_rendering(self) -> None:
        script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const statusPollIntervalMs = 3_000;',
            'if (nextSignature === recentEventsSignature) return;',
            'if (nextSignature === lastRenderedStatusSignature && !statusRefreshFailed) return;',
            'if (!statusUrl || statusRefreshInFlight || document.hidden) return;',
            'document.addEventListener("visibilitychange", handleVisibilityChange);',
            'scheduleStatusRefresh();',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn("window.setInterval(refreshStatus", script)
        self.assertNotIn("\n    refreshStatus();\n", script)

    def test_browser_status_uses_stale_while_revalidate_without_duplicate_probes(self) -> None:
        script = BROWSER_SESSION_PICKER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const SESSION_CACHE_TTL_MS = 300_000;',
            'const SESSION_STALE_MAX_AGE_MS = 1_800_000;',
            'const statusRequests = new Map();',
            'setStatus(cachedStatus.payload);',
            'setRefreshingState();',
            'if (statusRequests.has(requestKey)) return statusRequests.get(requestKey);',
            'statusCard.setAttribute("aria-busy", "true");',
            'if (activeBrowser !== browserId) return;',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_browser_copy_control_reports_a_replayable_feedback_state(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        expected_fragments = (
            "const copyFeedbackTimers = new WeakMap();",
            "function setCopyFeedback(button, didCopy)",
            'button.classList.remove("is-copied", "is-copy-failed");',
            'button.classList.add(didCopy ? "is-copied" : "is-copy-failed");',
            'feedback.textContent = didCopy ? "Original URL copied." : "Unable to copy original URL.";',
        )

        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_waiting_modal_describes_form_and_async_waits(self) -> None:
        script = WAITING_MODAL_SCRIPT_PATH.read_text(encoding="utf-8")
        spinner_asset = LOADING_SPINNER_ASSET_PATH.read_text(encoding="utf-8")

        for fragment in (
            "const activeWaits = new Map();",
            "function begin(options = {})",
            "window.CacheWaitModal = Object.freeze({ begin, show, hide });",
            'document.addEventListener("submit", (event) => {',
            'event.target.closest("a[data-wait-title], a[data-wait-copy]")',
            "Close waiting notification",
        ):
            with self.subTest(fragment=fragment):
                if fragment == "Close waiting notification":
                    self.assertIn(fragment, (Path(__file__).resolve().parents[1] / "app/web/templates/_waiting_modal.html").read_text(encoding="utf-8"))
                else:
                    self.assertIn(fragment, script)

        for fragment in (
            '<svg xmlns="http://www.w3.org/2000/svg"',
            'viewBox="0 0 24 24"',
            'stroke-linecap="round"',
        ):
            with self.subTest(spinner_fragment=fragment):
                self.assertIn(fragment, spinner_asset)

    def test_browser_page_and_secure_media_route_use_isolated_cache(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            image_path = root / "x" / "demo" / "image.jpg"
            video_path = root / "grok" / "clip.mp4"
            image_path.parent.mkdir(parents=True)
            video_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image")
            (image_path.parent / "image.info.json").write_text(
                '{"webpage_url":"https://x.com/demo/status/123"}',
                encoding="utf-8",
            )
            for index in range(24):
                (image_path.parent / f"extra-{index:02d}.jpg").write_bytes(b"extra-image")
            video_path.write_bytes(b"0123456789")
            outside_path = Path(raw_root) / "outside.mp4"
            outside_path.write_bytes(b"outside")
            link_path = root / "grok" / "outside.mp4"
            try:
                link_path.symlink_to(outside_path)
            except OSError as exc:
                self.skipTest(f"symlinks are unavailable: {exc}")

            app = create_app(root)
            with app.test_client() as client:
                browser_response = client.get("/browser")
                video_response = client.get(
                    "/browser/media/grok/clip.mp4",
                    headers={"Range": "bytes=0-3"},
                )
                invalid_extension = client.get("/browser/media/grok/.grok_catalog.json")
                traversal = client.get("/browser/media/grok/%2e%2e/%2e%2e/outside.mp4")
                external_link = client.get("/browser/media/grok/outside.mp4")

            body = browser_response.get_data(as_text=True)
            self.assertEqual(browser_response.status_code, 200)
            self.assertIn("Cached media browser", body)
            self.assertNotIn("No cached media found.", body)
            self.assertNotIn(str(root), body)
            self.assertIn("style-v2.45.0-codex.1", body)
            self.assertIn("/static/images/photo.stack.svg", body)
            self.assertIn('local-media-browser.js?v=local-media-browser-v1.20.0-codex.1', body)
            self.assertIn('data-media-source-link', body)
            self.assertIn('data-media-copy-source-url', body)
            self.assertIn('data-media-reveal', body)
            self.assertIn('class="icon browser-media-source-link-icon"', body)
            self.assertIn('class="icon browser-media-reveal-icon"', body)
            self.assertIn('class="browser-view-dock"', body)
            self.assertIn('data-browser-view="list"', body)
            self.assertIn('data-browser-view="grid"', body)
            self.assertIn('class="icon browser-view-icon browser-view-icon-list"', body)
            self.assertIn('class="icon browser-view-icon browser-view-icon-grid"', body)
            self.assertIn('class="browser-gallery" data-view="grid"', body)
            self.assertIn('Open original post', body)
            self.assertIn('https://x.com/demo/status/123', body)
            self.assertIn('class="local-store-pagination-indicator" aria-hidden="true"></span>', body)
            self.assertEqual(video_response.status_code, 206)
            self.assertEqual(video_response.headers["Content-Range"], "bytes 0-3/10")
            self.assertEqual(video_response.data, b"0123")
            self.assertEqual(invalid_extension.status_code, 404)
            self.assertEqual(traversal.status_code, 404)
            self.assertEqual(external_link.status_code, 404)

    def test_browser_card_uses_filename_metadata_and_binary_size_units(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            media_path = root / "chatgpt" / "Studio208cm" / "img_file.png"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"x" * 1_805_089)
            (media_path.parent / ".chatgpt_catalog.json").write_text(
                """{
                    "entries": {
                        "file-123": {
                            "file_id": "file-123",
                            "relative_path": "img_file.png",
                            "conversation_url": "https://chatgpt.com/c/demo-session",
                            "conversation_title": "A regular session",
                            "prompt_markdown": "**Frame the athlete** in profile.\\n\\n- Soft light\\n- Blue backdrop",
                            "first_seen_at": "2026-08-09T07:09:50Z"
                        }
                    }
                }""",
                encoding="utf-8",
            )
            app = create_app(root)
            with app.test_client() as client:
                response = client.get("/browser?source=chatgpt")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("browser-media-card-topline", body)
        self.assertNotIn("browser-source-chip", body)
        self.assertNotIn("browser-media-type", body)
        self.assertIn('class="browser-media-card-title" title="img_file.png">img_file.png</span>', body)
        self.assertNotIn("browser-media-card-description", body)
        self.assertIn("Session name:</dt><dd title=\"A regular session\">A regular session</dd>", body)
        self.assertIn("Created on:</dt><dd>9 Aug 2026 07:09</dd>", body)
        self.assertIn("Size:</dt><dd>1.72 MiB</dd>", body)
        self.assertIn('class="browser-media-prompt"', body)
        self.assertIn('data-media-prompt-toggle', body)
        self.assertIn('class="icon browser-media-prompt-expand-icon"', body)
        self.assertIn('aria-expanded="false"', body)
        self.assertIn("<strong>Frame the athlete</strong>", body)
        self.assertIn("<li>Soft light</li>", body)
        self.assertNotIn('id="browser_prompt_dialog"', body)
        self.assertIn('browser-media-copy-source-url', body)
        self.assertIn('data-media-copy-feedback', body)
        self.assertIn('data-media-reveal', body)

    def test_browser_paginates_chatgpt_by_session_and_labels_the_latest_image(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            project_dir = root / "chatgpt" / "Studio208cm"
            project_dir.mkdir(parents=True)
            for filename in ("new-old.png", "new-latest.png", "older-session.png"):
                (project_dir / filename).write_bytes(filename.encode("utf-8"))
            (project_dir / ".chatgpt_catalog.json").write_text(
                """{
                    "entries": {
                        "file-new-old": {
                            "file_id": "file-new-old",
                            "relative_path": "new-old.png",
                            "conversation_url": "https://chatgpt.com/c/new-session",
                            "conversation_title": "Newest session",
                            "created_at": "2026-08-08T08:00:00Z"
                        },
                        "file-new-latest": {
                            "file_id": "file-new-latest",
                            "relative_path": "new-latest.png",
                            "conversation_url": "https://chatgpt.com/c/new-session",
                            "conversation_title": "Newest session",
                            "created_at": "2026-08-10T09:00:00Z"
                        },
                        "file-older": {
                            "file_id": "file-older",
                            "relative_path": "older-session.png",
                            "conversation_url": "https://chatgpt.com/c/older-session",
                            "conversation_title": "Older session",
                            "created_at": "2026-08-09T10:00:00Z"
                        }
                    }
                }""",
                encoding="utf-8",
            )
            app = create_app(root)
            with app.test_client() as client:
                first_response = client.get("/browser?source=chatgpt&sort=oldest&page=1")
                second_response = client.get("/browser?source=chatgpt&sort=oldest&page=2")
                chronological_response = client.get(
                    "/browser?source=chatgpt&sort=newest&session_view=0&page=1"
                )

        first_body = first_response.get_data(as_text=True)
        second_body = second_response.get_data(as_text=True)
        chronological_body = chronological_response.get_data(as_text=True)
        self.assertEqual(first_response.status_code, 200)
        self.assertNotIn("Local media", first_body)
        self.assertNotIn("Browse cached media, remove unwanted resources", first_body)
        self.assertIn("Total resources", first_body)
        self.assertIn("Sessions", first_body)
        self.assertNotIn("Session resources", first_body)
        self.assertIn("Current session", first_body)
        self.assertIn("Newest session", first_body)
        self.assertIn("1 / 2", first_body)
        self.assertNotIn("resources in this session", first_body)
        self.assertNotIn("Latest image", first_body)
        self.assertIn("browser-session-controls-row", first_body)
        self.assertIn('class="browser-session-control-button browser-session-view-button"', first_body)
        self.assertIn('aria-label="Session View"', first_body)
        self.assertIn('aria-pressed="true"', first_body)
        self.assertIn('class="icon browser-session-view-icon"', first_body)
        self.assertIn('id="browser_session_view_tooltip"', first_body)
        self.assertIn('class="browser-session-control-tooltip"', first_body)
        self.assertIn('role="tooltip"', first_body)
        self.assertIn('class="browser-session-control-tooltip-title">Session View</span>', first_body)
        self.assertIn("Browse every cached resource in the current ChatGPT session.", first_body)
        self.assertNotIn('class="status-chip browser-filter-chip">Session view</span>', first_body)
        self.assertIn("Refresh this session", first_body)
        self.assertIn('data-chatgpt-session-refresh', first_body)
        self.assertIn('class="browser-session-control-button browser-session-refresh-button"', first_body)
        self.assertIn('aria-label="Refresh this session"', first_body)
        self.assertIn('class="icon browser-session-refresh-icon"', first_body)
        self.assertIn('id="browser_session_refresh_tooltip"', first_body)
        self.assertIn('data-session-refresh-tooltip-title', first_body)
        self.assertIn('data-session-refresh-tooltip-copy', first_body)
        self.assertIn("Check this ChatGPT session for newly generated images.", first_body)
        self.assertNotIn('class="secondary-button"\n                                data-chatgpt-session-refresh', first_body)
        self.assertIn('data-chatgpt-session-refresh-banner', first_body)
        self.assertIn('data-session-refresh-dismiss', first_body)
        self.assertIn('role="status"', first_body)
        self.assertIn('aria-live="polite"', first_body)
        self.assertIn('data-chatgpt-session-url="https://chatgpt.com/c/new-session"', first_body)
        self.assertIn('aria-label="ChatGPT sessions"', first_body)
        self.assertIn('aria-label="Session 2"', first_body)
        self.assertIn("Image order in session", first_body)
        self.assertIn("new-old.png", first_body)
        self.assertIn("new-latest.png", first_body)
        self.assertNotIn("older-session.png", first_body)
        self.assertIn("Older session", second_body)
        self.assertIn("2 / 2", second_body)
        self.assertIn("older-session.png", second_body)
        self.assertNotIn("new-latest.png", second_body)
        self.assertIn('data-chatgpt-session-view', chronological_body)
        self.assertIn('aria-pressed="false"', chronological_body)
        self.assertIn("Sort order", chronological_body)
        self.assertNotIn("Image order in session", chronological_body)
        self.assertIn("new-latest.png", chronological_body)
        self.assertIn("older-session.png", chronological_body)
        self.assertIn("new-old.png", chronological_body)
        self.assertIn('name="session_view" value="0"', chronological_body)
        self.assertIn(
            "session_view=('1' if filters.session_view else '0')",
            BROWSER_TEMPLATE_PATH.read_text(encoding="utf-8"),
        )

        chronological_positions = [
            chronological_body.index(filename)
            for filename in ("new-latest.png", "older-session.png", "new-old.png")
        ]
        self.assertEqual(chronological_positions, sorted(chronological_positions))

    def test_theme_toggle_reuses_sibling_light_dark_behavior(self) -> None:
        script = THEME_MODE_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const storageKey = "cachelikes:theme-mode";',
            'document.documentElement.setAttribute("data-theme-override", preference);',
            'toggle.dataset.effectiveTheme = currentMode;',
            'toggle.setAttribute("aria-pressed", String(currentMode === "dark"));',
            'const nextMode = effectiveMode() === "dark" ? "light" : "dark";',
        ):
            self.assertIn(fragment, script)

    def test_format_media_size_uses_two_decimal_binary_units(self) -> None:
        self.assertEqual(format_media_size(1_024), "1.00 KiB")
        self.assertEqual(format_media_size(1_805_089), "1.72 MiB")
        self.assertEqual(format_media_size(1_024**3), "1.00 GiB")

    def test_prompt_markdown_renderer_escapes_embedded_html(self) -> None:
        rendered = str(render_prompt_markdown("**Safe** <script>alert('x')</script>"))

        self.assertIn("<strong>Safe</strong>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_browser_prompt_expands_inline_inside_its_media_card(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.querySelectorAll("[data-media-prompt-toggle]")',
            'button.closest(".browser-media-prompt")',
            'prompt.classList.toggle("is-expanded", nextExpanded);',
            'button.setAttribute("aria-expanded", String(nextExpanded));',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn("promptDialog.showModal();", script)
        self.assertNotIn("promptDialogContent.replaceChildren(", script)

    def test_browser_prompt_hides_expand_control_when_default_copy_fits(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            "function updatePromptToggleVisibility()",
            "source.scrollHeight <= source.clientHeight + 1",
            "button.hidden = isFullyVisible;",
            'prompt.classList.toggle("is-fully-visible", isFullyVisible);',
            'button.getAttribute("aria-expanded") === "true"',
            'const promptResizeObserver = new ResizeObserver(',
            "document.fonts.ready.then(updatePromptToggleVisibility);",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_browser_reveal_control_posts_only_the_media_identifier(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.querySelectorAll("[data-media-reveal]")',
            'button.closest("[data-media-id]")',
            '/reveal`, {',
            'method: "POST"',
            'setRevealFeedback(button, payload.file_manager);',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn("item.relative_path", script)

    def test_browser_view_dock_switches_and_remembers_media_layout(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.querySelectorAll("[data-browser-view]")',
            'const mediaViewStorageKey = "cachelikes.browser.mediaView";',
            'mediaGallery.dataset.view = view;',
            'button.classList.toggle("is-active", isActive);',
            'button.setAttribute("aria-pressed", String(isActive));',
            'window.localStorage.setItem(mediaViewStorageKey, view);',
            'window.localStorage.getItem(mediaViewStorageKey);',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_browser_session_refresh_starts_and_polls_one_chatgpt_session(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.querySelector("[data-chatgpt-session-refresh]")',
            'fetch("/api/browser/chatgpt/session/refresh", {',
            'body: JSON.stringify({ conversation_url: conversationUrl })',
            'const statusUrl = startPayload.status_url || "/api/chatgpt/status";',
            'const initialResourceCount = Number(startPayload.resource_count) || 0;',
            'if (snapshot.running) continue;',
            '(Number(snapshot.downloaded_images) || 0) - initialResourceCount',
            'refreshedUrl.searchParams.set("session_updated", String(updatedCount));',
            'document.querySelector("[data-chatgpt-session-refresh-banner]")',
            'window.history.replaceState({}, "", currentUrl.toString());',
            '"session",',
            'refreshedUrl.searchParams.set("refresh", "1");',
            'setSessionRefreshTooltip(',
            '"Refreshing this session",',
            '"Checking ChatGPT for newly generated images.",',
            'button.setAttribute("aria-label", "Refreshing session…");',
            '"Refresh this session",',
            '"Check this ChatGPT session for newly generated images.",',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn('button.textContent = "Refreshing session…";', script)
        self.assertNotIn("button.dataset.tooltip", script)

    def test_browser_session_refresh_route_uses_a_temporary_session_url(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            project_dir = root / "chatgpt" / "Studio208cm"
            project_dir.mkdir(parents=True)
            media_path = project_dir / "img_file.png"
            media_path.write_bytes(b"chatgpt-image")
            conversation_url = "https://chatgpt.com/c/demo-session"
            (project_dir / ".chatgpt_catalog.json").write_text(
                """{
                    "entries": {
                        "file-123": {
                            "file_id": "file-123",
                            "relative_path": "img_file.png",
                            "conversation_url": "https://chatgpt.com/c/demo-session",
                            "conversation_title": "Demo session"
                        }
                    }
                }""",
                encoding="utf-8",
            )
            app = create_app(root)
            chatgpt_service = app.extensions["chatgpt_service"]
            with patch.object(chatgpt_service, "start") as start:
                with app.test_client() as client:
                    response = client.post(
                        "/api/browser/chatgpt/session/refresh",
                        json={"conversation_url": conversation_url},
                    )
                    invalid_response = client.post(
                        "/api/browser/chatgpt/session/refresh",
                        json={"conversation_url": "https://example.com/c/demo-session"},
                    )
                    uncataloged_response = client.post(
                        "/api/browser/chatgpt/session/refresh",
                        json={"conversation_url": "https://chatgpt.com/c/missing-session"},
                    )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["session_key"], "demo-session")
        self.assertEqual(response.get_json()["resource_count"], 1)
        self.assertEqual(response.get_json()["status_url"], "/api/chatgpt/status")
        self.assertEqual(start.call_args_list[0].args[0].chatgpt_project_url, conversation_url)
        self.assertEqual(invalid_response.status_code, 400)
        self.assertEqual(uncataloged_response.status_code, 202)
        self.assertEqual(uncataloged_response.get_json()["session_key"], "missing-session")
        self.assertEqual(
            start.call_args_list[1].args[0].chatgpt_project_url,
            "https://chatgpt.com/c/missing-session",
        )

    def test_browser_reveal_route_resolves_local_media_and_rejects_remote_clients(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            image_path = root / "x" / "demo" / "image.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image")
            stable_id = stable_media_id("x/demo/image.jpg")
            app = create_app(root)
            with patch("app.web.app.reveal_media_path") as reveal:
                with app.test_client() as client:
                    local_response = client.post(f"/api/browser/media/{stable_id}/reveal")
                    remote_response = client.post(
                        f"/api/browser/media/{stable_id}/reveal",
                        environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                    )
                    missing_response = client.post("/api/browser/media/missing/reveal")

        self.assertEqual(local_response.status_code, 200)
        self.assertEqual(local_response.get_json()["file_manager"], "Finder")
        reveal.assert_called_once_with(image_path.resolve())
        self.assertEqual(remote_response.status_code, 403)
        self.assertEqual(missing_response.status_code, 404)

    def test_browser_delete_and_restore_routes_keep_a_preview(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            image_path = root / "x" / "demo" / "image.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"image")
            (image_path.parent / "image.info.json").write_text(
                '{"webpage_url":"https://x.com/demo/status/123", "display_id":"123"}',
                encoding="utf-8",
            )
            stable_id = stable_media_id("x/demo/image.jpg")
            app = create_app(root)
            with app.test_client() as client:
                delete_response = client.post(f"/api/browser/media/{stable_id}/delete")
                deleted_preview = client.get(f"/browser/deleted-preview/{stable_id}")
                deleted_browser = client.get("/browser")
                restore_response = client.post(f"/api/browser/media/{stable_id}/restore")
                restored_media = client.get("/browser/media/x/demo/image.jpg")

        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(image_path.exists())
        self.assertEqual(deleted_preview.status_code, 200)
        self.assertIn('data-deleted="true"', deleted_browser.get_data(as_text=True))
        self.assertEqual(restore_response.status_code, 200)
        self.assertEqual(restored_media.status_code, 200)

    def test_cache_reconciliation_skips_failed_snapshots(self) -> None:
        snapshot = {
            "running": False,
            "phase": "failed",
            "message": "Failure.",
            "account_name": "demo_user",
            "output_dir": "/tmp/live",
            "downloaded_posts": 0,
            "downloaded_tweets": 0,
            "downloaded_images": 0,
            "downloaded_videos": 0,
        }
        hydrated = TaskSnapshot(
            version="v-test",
            account_name="x",
            output_dir="/tmp/cache",
            downloaded_posts=542,
            downloaded_tweets=542,
            downloaded_images=0,
            downloaded_videos=542,
            message="Ready. Found existing cache: 542 posts, 0 images, 542 videos.",
        )

        reconciled = reconcile_cached_snapshot(snapshot, asdict(hydrated))

        self.assertEqual(reconciled["message"], "Failure.")
        self.assertEqual(reconciled["downloaded_posts"], 0)
        self.assertEqual(reconciled["downloaded_videos"], 0)
        self.assertEqual(reconciled["output_dir"], "/tmp/live")

    def test_cache_reconciliation_hydrates_finished_snapshots(self) -> None:
        snapshot = {
            "running": False,
            "phase": "finished",
            "message": "Finished.",
            "account_name": "",
            "output_dir": "",
            "downloaded_posts": 1,
            "downloaded_tweets": 1,
            "downloaded_images": 1,
            "downloaded_videos": 0,
            "discovered_images": 771,
        }
        hydrated = TaskSnapshot(
            version="v-test",
            account_name="x",
            output_dir="/tmp/cache",
            downloaded_posts=542,
            downloaded_tweets=542,
            downloaded_images=0,
            downloaded_videos=542,
            message="Ready. Found existing cache: 542 posts, 0 images, 542 videos.",
        )

        reconciled = reconcile_cached_snapshot(snapshot, asdict(hydrated))

        self.assertEqual(reconciled["message"], "Finished.")
        self.assertEqual(reconciled["discovered_images"], 771)
        self.assertEqual(reconciled["downloaded_posts"], 542)
        self.assertEqual(reconciled["downloaded_videos"], 542)
        self.assertEqual(reconciled["output_dir"], "/tmp/cache")

    def test_cache_reconciliation_preserves_targeted_session_discovery_count(self) -> None:
        snapshot = {
            "running": False,
            "phase": "finished",
            "message": "Finished one session.",
            "account_name": "",
            "output_dir": "",
            "downloaded_posts": 0,
            "downloaded_tweets": 0,
            "downloaded_images": 733,
            "downloaded_videos": 0,
            "discovered_images": 3,
        }
        hydrated = TaskSnapshot(
            version="v-test",
            account_name="ChatGPT",
            output_dir="/tmp/cache",
            downloaded_images=733,
            message="Ready. Found existing cache: 733 images.",
        )

        reconciled = reconcile_cached_snapshot(snapshot, asdict(hydrated))

        self.assertEqual(reconciled["message"], "Finished one session.")
        self.assertEqual(reconciled["discovered_images"], 3)
        self.assertEqual(reconciled["downloaded_images"], 733)


if __name__ == "__main__":
    unittest.main()
