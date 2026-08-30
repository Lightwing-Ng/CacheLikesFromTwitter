"""Focused regression tests for the local web console."""

# Code version: v1.88.1-codex.7

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.core.state import TaskSnapshot
from app.core.config import CrawlConfig
from app.core.chat_history_browser import query_chat_history
from app.core.computer_use_agent import ComputerUseSettings
from app.core.local_media_browser import LocalMediaCatalog, LocalMediaPage, local_file_manager_label, stable_media_id
from app.core.resource_persistence import GEMINI_HISTORY_SCHEMA, write_parquet_rows_atomic
from app.web.app import (
    create_app,
    format_media_size,
    reconcile_cached_snapshot,
    render_cached_message,
    render_prompt_markdown,
)
from app.web.cache_sources import CACHE_SOURCE_VIEWS


SIDEBAR_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/sidebar.js"
SETTINGS_NAVIGATION_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/settings-navigation.js"
)
SETTINGS_DIRECTORY_PICKER_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/settings-directory-picker.js"
)
COMPUTER_USE_AGENT_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/computer-use-agent.js"
)
AGENT_SETTINGS_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/agent-settings.js"
)
CACHE_PAGE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/cache-page.js"
CHATGPT_PAGE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/chatgpt-page.js"
SEGMENTED_CONTROL_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/segmented-control.js"
PAGINATION_MOTION_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/pagination-motion.js"
BROWSER_SESSION_PICKER_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/browser-session-picker.js"
)
BROWSER_SESSION_STATUS_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/browser-session-status.js"
)
NUMERIC_INPUT_FORMAT_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/numeric-input-format.js"
)
LOCAL_MEDIA_BROWSER_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/local-media-browser.js"
BROWSER_SEARCH_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/browser-search.js"
BROWSER_FILTER_SELECT_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/browser-filter-select.js"
BROWSER_SEARCH_STYLE_PATH = Path(__file__).resolve().parents[1] / "app/web/static/browser-search.css"
BROWSER_SESSION_MESSAGES_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "app/web/static/browser-session-messages.js"
)
FUSE_ASSET_PATH = Path(__file__).resolve().parents[1] / "app/web/static/vendor/fuse.min.mjs"
THEME_MODE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/theme-mode.js"
BROWSER_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app/web/templates/browser.html"
CACHE_PAGE_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app/web/templates/_cache_page.html"
PAGINATION_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "app/web/templates/_pagination.html"
WAITING_MODAL_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/waiting-modal.js"
LANGUAGE_RENDERING_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/language-rendering.js"
LOADING_SPINNER_ASSET_PATH = Path(__file__).resolve().parents[1] / "app/web/static/images/loading.spinner.svg"
FAVICON_ASSET_PATH = Path(__file__).resolve().parents[1] / "app/web/static/images/favicon.svg"
GEMINI_LOGO_ASSET_PATH = (
    Path(__file__).resolve().parents[1]
    / "app/web/static/images/Google_Gemini_logo_2025_symbol.svg"
)
MAGNIFYING_GLASS_ASSET_PATH = Path(__file__).resolve().parents[1] / "app/web/static/images/magnifyingglass.svg"


class WebAppTests(unittest.TestCase):
    """Validate the index page renders live progress metrics."""

    def test_cache_source_registry_is_alphabetized_and_extensible(self) -> None:
        labels = [source.label for source in CACHE_SOURCE_VIEWS]

        self.assertEqual(labels, sorted(labels, key=str.casefold))
        self.assertEqual([source.key for source in CACHE_SOURCE_VIEWS], ["chatgpt", "gemini", "grok", "x"])
        self.assertEqual(len({source.template_name for source in CACHE_SOURCE_VIEWS}), len(CACHE_SOURCE_VIEWS))
        self.assertEqual({source.start_button_label for source in CACHE_SOURCE_VIEWS}, {"Start"})
        self.assertEqual(
            {source.key for source in CACHE_SOURCE_VIEWS if source.show_content_mode},
            {"chatgpt", "gemini", "grok"},
        )
        self.assertEqual(
            {source.key for source in CACHE_SOURCE_VIEWS if source.browser_panel_label == "Authorized browser"},
            {"chatgpt", "gemini", "grok"},
        )

    def test_cache_source_switcher_uses_one_complete_registry_on_gemini(self) -> None:
        app = create_app()

        with app.test_client() as client:
            body = client.get("/cache/gemini").get_data(as_text=True)

        option_ids = [
            body.index(f'id="cache_source_switcher_option_{source}"')
            for source in ("chatgpt", "gemini", "grok", "x")
        ]
        assert option_ids == sorted(option_ids)
        for source in ("chatgpt", "gemini", "grok"):
            expected_path = (
                "/cache/chatgpt"
                if source == "chatgpt"
                else "/cache/gemini"
                if source == "gemini"
                else f"/browser?view=text&amp;session_view=1&amp;q=&amp;source={source}&amp;sort=newest"
            )
            self.assertIn(
                f'data-cache-source-switcher-path="{expected_path}"',
                body,
            )

    def test_chatgpt_source_switcher_includes_gemini(self) -> None:
        app = create_app()

        with app.test_client() as client:
            body = client.get("/cache/chatgpt").get_data(as_text=True)

        option_ids = [
            body.index(f'id="cache_source_switcher_option_{source}"')
            for source in ("chatgpt", "gemini", "grok", "x")
        ]
        assert option_ids == sorted(option_ids)
        self.assertIn('data-cache-source-switcher-path="/cache/gemini"', body)

    def test_gemini_logo_asset_is_square_symbol_only_and_full_color(self) -> None:
        markup = GEMINI_LOGO_ASSET_PATH.read_text(encoding="utf-8")

        self.assertIn('viewBox="0 0 64.895 64.896"', markup)
        self.assertNotIn("currentColor", markup)
        self.assertNotIn("<text", markup)
        for color in ("#FC413D", "#FFE432", "#00B95C", "#3186FF"):
            with self.subTest(color=color):
                self.assertIn(color, markup)

    def test_index_includes_progress_metric_counters(self) -> None:
        app = create_app()

        with app.test_client() as client:
            response = client.get("/cache/x")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="progress_downloaded_posts"', body)
        self.assertIn('id="progress_downloaded_images"', body)
        self.assertIn('id="progress_downloaded_videos"', body)

    def test_pages_declare_the_sibling_style_favicon(self) -> None:
        app = create_app()

        with app.test_client() as client:
            responses = (
                client.get("/cache/x"),
                client.get("/browser"),
                client.get("/settings"),
                client.get("/agent", follow_redirects=True),
            )

        favicon_markup = FAVICON_ASSET_PATH.read_text(encoding="utf-8")
        self.assertIn('fill="#0055cc"', favicon_markup)
        self.assertIn('fill="#16a34a"', favicon_markup)
        for response in responses:
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn(
                '<link rel="icon" type="image/svg+xml" href="/static/images/favicon.svg?v=',
                body,
            )

    def test_pages_load_the_global_simplified_chinese_language_boundary(self) -> None:
        app = create_app()

        with app.test_client() as client:
            responses = (
                client.get("/cache/x"),
                client.get("/browser"),
                client.get("/settings"),
                client.get("/agent", follow_redirects=True),
            )

        for response in responses:
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn(
                'src="/static/language-rendering.js?v=language-rendering-v1.0.0-codex.1"',
                body,
            )

        script = LANGUAGE_RENDERING_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'const SIMPLIFIED_CHINESE_LANGUAGE = "zh-CN";',
            "const HAN_CHARACTER_PATTERN =",
            "new MutationObserver",
            "attributeFilter: LANGUAGE_TEXT_ATTRIBUTES,",
            'document.addEventListener("input", (event) => {',
            'boundary.setAttribute("lang", SIMPLIFIED_CHINESE_LANGUAGE);',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_agent_uses_canonical_browser_provider_paths(self) -> None:
        with patch(
            "app.core.computer_use_agent.load_computer_use_settings",
            return_value=ComputerUseSettings(browser="edge", platform="chatgpt"),
        ):
            app = create_app()

        with app.test_client() as client:
            legacy = client.get("/agent")
            selected = client.get("/agent/edge/gemini")
            invalid = client.get("/agent/safari/gemini")

        self.assertEqual(legacy.status_code, 302)
        self.assertEqual(legacy.headers["Location"], "/agent/edge/chatgpt")
        self.assertEqual(selected.status_code, 200)
        body = selected.get_data(as_text=True)
        self.assertIn(
            'name="platform" value="gemini" data-agent-combobox-input data-agent-platform-input',
            body,
        )
        self.assertIn('name="browser" value="edge"', body)
        self.assertIn('data-browser-session-platform="gemini"', body)
        self.assertIn('href="/agent/edge/gemini"', body)
        self.assertEqual(invalid.status_code, 404)

    def test_chatgpt_notice_names_the_selected_background_browser(self) -> None:
        with patch(
            "app.web.app.load_saved_config",
            return_value=CrawlConfig(chatgpt_browser="safari"),
        ), patch("app.core.browser_sessions.is_macos_host", return_value=True):
            app = create_app()
        with app.test_client() as client:
            response = client.get("/cache/chatgpt")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("offscreen Safari session", body)
        self.assertIn(">Safari session</span>", body)
        self.assertNotIn("offscreen Edge session", body)

    def test_chatgpt_notice_preserves_a_saved_safari_label_when_registry_is_host_limited(self) -> None:
        with patch(
            "app.web.app.load_saved_config",
            return_value=CrawlConfig(chatgpt_browser="safari"),
        ), patch("app.core.browser_sessions.is_macos_host", return_value=False):
            app = create_app()

        with app.test_client() as client:
            response = client.get("/cache/chatgpt")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("offscreen Safari session", body)

    def test_pages_share_the_direct_cache_dock_link(self) -> None:
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with app.test_client() as client:
                grok_response = client.get("/cache/grok")
                chatgpt_response = client.get("/cache/chatgpt")
                gemini_response = client.get("/cache/gemini")
                index_response = client.get("/cache/x")
                settings_response = client.get("/settings")
                browser_response = client.get("/browser?view=media")
                agent_response = client.get("/agent", follow_redirects=True)

        grok_body = grok_response.get_data(as_text=True)
        chatgpt_body = chatgpt_response.get_data(as_text=True)
        gemini_body = gemini_response.get_data(as_text=True)
        index_body = index_response.get_data(as_text=True)
        settings_body = settings_response.get_data(as_text=True)
        browser_body = browser_response.get_data(as_text=True)
        agent_body = agent_response.get_data(as_text=True)

        self.assertEqual(grok_response.status_code, 200)
        self.assertEqual(chatgpt_response.status_code, 200)
        self.assertEqual(gemini_response.status_code, 200)
        self.assertEqual(settings_response.status_code, 200)
        self.assertEqual(browser_response.status_code, 200)
        self.assertNotIn('<p class="workspace-kicker">Live snapshot</p>', grok_body)
        self.assertNotIn('class="notice-floating notice-floating-banner notice-inline-banner grok-warning-banner"', grok_body)
        self.assertNotIn("Forced workaround", grok_body)
        self.assertIn('<p class="workspace-kicker">Live snapshot</p>', index_body)
        self.assertIn('<p class="workspace-kicker">Live snapshot</p>', chatgpt_body)
        self.assertIn('data-section-link="settings"', grok_body)
        self.assertIn('data-cache-source-switcher-path="/cache/chatgpt"', grok_body)
        self.assertIn('data-section-link="local-resources"', browser_body)
        self.assertIn("Gemini history cache overview", gemini_body)
        self.assertIn(
            "--cache-source-mark: url('/static/images/Google_Gemini_logo_2025_symbol.svg')",
            gemini_body,
        )
        self.assertIn(
            'class="cache-source-mark browser-source-filter-mark is-full-color"',
            gemini_body,
        )
        self.assertIn('name="gemini_browser"', gemini_body)
        self.assertIn('name="gemini_max_conversations"', gemini_body)
        self.assertIn("Max sessions", gemini_body)
        self.assertIn("Sessions discovered", gemini_body)
        self.assertNotIn("Conversations discovered", gemini_body)
        self.assertIn('name="gemini_scroll_pause_seconds"', gemini_body)
        self.assertIn('name="gemini_stale_round_limit"', gemini_body)
        self.assertIn('action="/cache/gemini/start"', gemini_body)
        self.assertNotIn('class="cache-common-config"', gemini_body)
        for body in (index_body, grok_body, chatgpt_body):
            self.assertIn('href="/settings#settings-downloads"', body)
            self.assertNotIn('class="cache-common-config', body)
        self.assertIn('href="/settings#settings-downloads"', gemini_body)
        self.assertIn("ChatGPT cache overview", chatgpt_body)
        self.assertIn("workspace-header cache-workspace-header", chatgpt_body)
        self.assertIn("cache-overview-title-card", chatgpt_body)
        self.assertIn("cache-workspace-content", chatgpt_body)
        self.assertLess(
            chatgpt_body.index("cache-overview-title-card"),
            chatgpt_body.index('id="overview"'),
        )
        self.assertIn("Sessions discovered", chatgpt_body)
        self.assertGreaterEqual(chatgpt_body.count('href="/cache/chatgpt"'), 2)
        self.assertIn(
            'chatgpt-page.js?v=chatgpt-page-v1.2.1-codex.1',
            chatgpt_body,
        )
        self.assertIn('data-browser-session-account-label="ChatGPT"', chatgpt_body)
        self.assertIn('data-browser-session-hide-ready-message="true"', chatgpt_body)
        self.assertIn(">ChatGPT account</strong>", chatgpt_body)
        self.assertNotIn("The ChatGPT account in the selected browser is ready.", chatgpt_body)
        self.assertIn('data-chatgpt-content-mode-input', chatgpt_body)
        self.assertIn('data-chatgpt-media-config', chatgpt_body)
        self.assertIn('name="chatgpt_project_url"', chatgpt_body)
        project_url_input_end = chatgpt_body.index(
            ">",
            chatgpt_body.index('name="chatgpt_project_url"'),
        )
        project_url_input_start = chatgpt_body.rfind("<input", 0, project_url_input_end)
        project_url_input = chatgpt_body[project_url_input_start:project_url_input_end]
        self.assertNotIn("required", project_url_input)
        self.assertIn('name="chatgpt_startup_timeout_seconds"', chatgpt_body)
        self.assertIn('name="chatgpt_scan_wait_seconds"', chatgpt_body)
        self.assertIn("Project or chat URL", chatgpt_body)
        self.assertIn("Known images skipped this run", chatgpt_body)
        self.assertIn("Media failures this run", chatgpt_body)
        self.assertIn("Task failures", chatgpt_body)
        self.assertIn('data-status-field="task_failures"', chatgpt_body)
        self.assertIn('id="output_dir"', chatgpt_body)
        self.assertIn('data-status-field="output_dir"', chatgpt_body)
        self.assertIn('class="text-input-control settings-directory-input output-directory-input"', chatgpt_body)
        self.assertIn('aria-label="Output directory"', chatgpt_body)
        self.assertIn('data-output-directory-open', chatgpt_body)
        self.assertIn('class="icon settings-directory-choose-icon"', chatgpt_body)
        self.assertIn('output-directory-status', chatgpt_body)
        self.assertNotIn('name="chatgpt_project_name"', chatgpt_body)
        self.assertIn('data-platform="chatgpt"', chatgpt_body)
        self.assertIn('action="/cache/chatgpt/start"', chatgpt_body)
        self.assertNotIn('class="status-copy chatgpt-sidebar-note"', chatgpt_body)
        self.assertIn('id="status_progress_value"', chatgpt_body)
        self.assertIn('id="progress_processed_label"', chatgpt_body)
        self.assertIn('pagination-motion.js?v=pagination-motion-v1.1.0-codex.1', chatgpt_body)
        self.assertIn('cache-page.js?v=cache-page-v1.8.0-codex.3', chatgpt_body)
        self.assertIn('segmented-control.js?v=segmented-control-v1.0.2-codex.1', chatgpt_body)
        self.assertIn('data-cache-content-mode', chatgpt_body)
        self.assertIn('href="/cache/chatgpt"', chatgpt_body)
        self.assertIn('data-cache-content-mode', grok_body)
        self.assertIn(
            'href="/browser?view=text&amp;session_view=1&amp;q=&amp;source=grok&amp;sort=newest"',
            grok_body,
        )
        self.assertIn('href="/cache/grok"', grok_body)
        self.assertIn('action="/cache/grok/text/start"', grok_body)
        self.assertIn('action="/cache/grok/text/stop"', grok_body)
        self.assertIn('data-cache-content-mode', gemini_body)
        self.assertIn(
            'href="/browser?view=text&amp;session_view=1&amp;q=&amp;source=gemini&amp;sort=newest"',
            gemini_body,
        )
        self.assertIn('href="/cache/gemini"', gemini_body)
        for body in (index_body, grok_body, chatgpt_body, gemini_body):
            with self.subTest(cache_action_state=body[:40]):
                self.assertIn('data-cache-action-row', body)
                self.assertIn('data-action-running="false"', body)
                stop_form_start = body.index('class="sidebar-form sidebar-form-stop"')
                stop_form_end = body.index(">", stop_form_start)
                self.assertIn("hidden", body[stop_form_start:stop_form_end])
                self.assertIn(">Start</button>", body)
        self.assertIn('browser-session-status.js?v=browser-session-status-v1.8.0-codex.1', chatgpt_body)
        self.assertIn('browser-session-picker.js?v=browser-session-picker-v1.8.0-codex.1', chatgpt_body)
        chatgpt_form_identifier = chatgpt_body.index('id="start_form_chatgpt"')
        chatgpt_form_start = chatgpt_body.rfind("<form", 0, chatgpt_form_identifier)
        chatgpt_form_end = chatgpt_body.index("</form>", chatgpt_form_start)
        chatgpt_form = chatgpt_body[chatgpt_form_start:chatgpt_form_end]
        self.assertEqual(chatgpt_form.count('class="field"'), 3)
        self.assertEqual(chatgpt_form.count("text-input-control"), 3)
        self.assertEqual(chatgpt_form.count('data-cache-number-field'), 2)
        self.assertEqual(chatgpt_form.count('data-cache-number-stepper="increment"'), 2)
        self.assertEqual(chatgpt_form.count('data-cache-number-stepper="decrement"'), 2)
        self.assertIn('data-number-min="1"', chatgpt_form)
        self.assertIn('data-number-max="600"', chatgpt_form)
        self.assertIn('data-number-step="0.1"', chatgpt_form)
        cache_page_script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        chatgpt_page_script = CHATGPT_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        numeric_input_script = NUMERIC_INPUT_FORMAT_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("function initializeNumberSteppers()", numeric_input_script)
        self.assertNotIn("function initializeNumberSteppers()", cache_page_script)
        self.assertIn("data.progress_unit", cache_page_script)
        self.assertIn('const cacheActionRow = document.querySelector("[data-cache-action-row]");', cache_page_script)
        self.assertIn('cacheActionRow.dataset.actionRunning = String(isRunning);', cache_page_script)
        self.assertIn('const startAction = document.querySelector(".sidebar-form-start");', cache_page_script)
        self.assertIn('startAction.hidden = isRunning;', cache_page_script)
        self.assertIn('stopAction.hidden = !isRunning;', cache_page_script)
        for source, body in (
            ("x", index_body),
            ("grok", grok_body),
            ("chatgpt", chatgpt_body),
            ("settings", settings_body),
        ):
            with self.subTest(common_config_source=source):
                if source == "settings":
                    self.assertEqual(body.count('class="cache-common-config"'), 1)
                    self.assertIn('name="download_workers"', body)
                    self.assertIn('name="max_media_file_size_mib"', body)
                    self.assertIn('id="settings_cache_common_config_help"', body)
                    self.assertIn(
                        'numeric-input-format.js?v=numeric-input-format-v1.1.0-codex.1',
                        body,
                    )
                    continue
                self.assertNotIn('class="cache-common-config', body)
                self.assertNotIn('name="download_workers"', body)
                self.assertNotIn('name="max_media_file_size_mib"', body)
                self.assertNotIn(f'id="{source}_cache_common_config_help"', body)
                self.assertIn('href="/settings#settings-downloads"', body)

        for page_source, body in (
            ("grok", grok_body),
            ("chatgpt", chatgpt_body),
            ("gemini", gemini_body),
            ("x", index_body),
            ("settings", settings_body),
            ("local-resources", browser_body),
            ("agent", agent_body),
        ):
            with self.subTest(page=page_source):
                dock_start = body.index('<nav class="sidebar-dock"')
                dock_end = body.index("</nav>", dock_start) + len("</nav>")
                dock_markup = body[dock_start:dock_end]
                self.assertEqual(dock_markup.count('data-cache-source-option='), 0)
                self.assertEqual(dock_markup.count('data-section-link='), 4)
                self.assertEqual(dock_markup.count('data-dock-section='), 4)
                self.assertLess(
                    dock_markup.index('data-dock-section="agent"'),
                    dock_markup.index('data-dock-section="cache"'),
                )
                self.assertLess(
                    dock_markup.index('data-dock-section="cache"'),
                    dock_markup.index('data-dock-section="local-resources"'),
                )
                self.assertLess(
                    dock_markup.index('data-dock-section="local-resources"'),
                    dock_markup.index('data-dock-section="settings"'),
                )
                self.assertIn('aria-label="Agent"', dock_markup)
                self.assertIn('class="icon dock-icon dock-icon-agent"', dock_markup)
                self.assertNotIn('class="dock-brand-icon"', dock_markup)
                self.assertIn('data-dock-section="cache"', dock_markup)
                self.assertIn('data-dock-section="local-resources"', dock_markup)
                self.assertIn('data-dock-section="settings"', dock_markup)
                self.assertEqual(dock_markup.count('aria-current="page"'), 1)
                expected_cache_source = page_source if page_source in {"x", "grok", "chatgpt", "gemini"} else "chatgpt"
                self.assertIn(f'href="/cache/{expected_cache_source}"', dock_markup)
                self.assertIn('href="/browser?view=text', dock_markup)
                self.assertIn('aria-label="Cache"', dock_markup)
                self.assertIn('data-tooltip="Cache"', dock_markup)
                self.assertIn('class="icon dock-icon dock-icon-cache"', dock_markup)
                self.assertIn('aria-label="Local resources"', dock_markup)
                self.assertIn('data-tooltip="Local resources"', dock_markup)
                self.assertNotIn('class="icon dock-icon dock-icon-chats"', dock_markup)
                self.assertNotIn('data-cache-source-menu', dock_markup)
                self.assertNotIn('sidebar-dock-cache-trigger', dock_markup)
                self.assertNotIn('sidebar-dock-cache-dropdown', dock_markup)
                self.assertNotIn('aria-haspopup', dock_markup)
                self.assertNotIn('aria-expanded', dock_markup)
                self.assertNotIn('class="browser-picker-option-icon"', dock_markup)
                self.assertIn('src="/static/sidebar.js?v=sidebar-v1.20.0-codex.1"', body)
                self.assertIn('src="/static/responsive.js?v=responsive-v1.0.0-codex.1"', body)
                expected_style_version = "style-v2.90.1-codex.9"
                self.assertIn(expected_style_version, body)
                self.assertIn('src="/static/theme-mode.js?v=theme-mode-v1.0.0-codex.1"', body)
                self.assertIn('id="global_theme_toggle"', body)
                self.assertIn('class="global-quick-action-button global-theme-toggle"', body)
                self.assertIn('class="sidebar-dock-label"', dock_markup)
                self.assertNotIn("cachelikes:browser-sidebar-open", body)
                self.assertIn('waiting-modal.js?v=waiting-modal-v1.1.0-codex.1', body)
                self.assertIn('id="cache_wait_modal"', body)
                self.assertIn('class="workspace-modal-overlay cache-wait-modal"', body)
                self.assertIn('suggestion-loading-spinner workspace-modal-icon', body)

        sidebar_script = SIDEBAR_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'const sidebarOverlayMedia = window.CACHELIKES_RESPONSIVE.media("sidebarOverlayMax");',
            "const shouldShowBackdrop = sidebarOverlayMedia.matches && isSidebarOpen;",
            'const dockLocationMemoryPrefix = "cachelikes:dock-location:v1:";',
            'const dockSections = new Set(["agent", "cache", "local-resources", "settings"]);',
            'const agentRoutePattern = /^\\/agent\\/(?:safari\\/chatgpt|(?:edge|chrome)\\/(?:chatgpt|gemini|grok|claude))$/;',
            'const localResourceFilterNames = ["view", "source", "kind", "q", "sort", "session_view"];',
            'const cacheSectionPaths = new Set(["/cache/x", "/cache/grok", "/cache/chatgpt", "/cache/gemini"]);',
            'if (targetUrl.pathname === "/browser") return "/cache/chatgpt";',
            'const legacyCachePathMap = new Map([',
            'window.sessionStorage.getItem(dockLocationMemoryKey(section))',
            'window.sessionStorage.setItem(dockLocationMemoryKey(section), normalizedLocation);',
            'sidebarDock.querySelectorAll("[data-dock-section], [data-section-link]")',
            'function dockSectionForLink(link) {',
            'function dockSectionForCurrentPath() {',
            'function syncDockActiveState() {',
            'link.setAttribute("aria-current", "page");',
            'link.removeAttribute("aria-current");',
            'document.querySelector(".browser-filter-form")',
            'return cacheSectionPaths.has(normalizedPath) ? normalizedPath : "/cache/chatgpt";',
            'data-settings-category][aria-current="page"]',
            'localResourceFilterForm?.addEventListener("input", rememberCurrentDockLocation);',
            'sidebarDock?.addEventListener("click", (event) => {',
            'if (rememberedLocation) dockLink.href = rememberedLocation;',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, sidebar_script)

        self.assertNotIn("browserFilterNames", sidebar_script)
        self.assertNotIn('window.matchMedia("(max-width:', sidebar_script)
        for body, sidebar_title in (
            (index_body, "Cache"),
            (grok_body, "Cache"),
            (chatgpt_body, "Cache"),
            (gemini_body, "Chats"),
            (browser_body, "Local resources"),
            (settings_body, "Settings"),
            (agent_body, "Agent"),
        ):
            with self.subTest(sidebar_title=sidebar_title):
                hero_markup = f'<section class="hero" data-layout-role="sidebar-title">\n                <h1>{sidebar_title}</h1>\n            </section>'
                self.assertIn(hero_markup, body)
        for body in (index_body, grok_body, chatgpt_body, gemini_body):
            with self.subTest(session_page=body[:40]):
                self.assertIn('data-role="browser-session-spinner"', body)
                heading_start = body.index('<div class="section-heading">')
                heading_end = body.index('</div>', heading_start) + len('</div>')
                heading_markup = body[heading_start:heading_end]
                self.assertIn('data-cache-source-switcher', heading_markup)
                self.assertIn('data-cache-source-switcher-trigger', heading_markup)
                self.assertIn('class="trade-strategy-select form-select trade-strategy-trigger browser-session-trigger cache-source-switcher-trigger"', heading_markup)
                self.assertIn('aria-label="Switch cache source"', heading_markup)
                expected_source_options = 4
                self.assertEqual(
                    heading_markup.count('data-cache-source-switcher-option='),
                    expected_source_options,
                )
                current_source = next(
                    source
                    for source in ("x", "grok", "chatgpt", "gemini")
                    if f'data-cache-source="{source}"' in body
                )
                expected_paths = (
                    (
                        "/cache/chatgpt",
                        "/cache/gemini",
                        "/browser?view=text&amp;session_view=1&amp;q=&amp;source=grok&amp;sort=newest",
                        "/cache/x",
                    )
                    if current_source == "gemini"
                    else ("/cache/chatgpt", "/cache/gemini", "/cache/grok", "/cache/x")
                )
                for expected_path in expected_paths:
                    self.assertIn(f'data-cache-source-switcher-path="{expected_path}"', heading_markup)
                self.assertNotIn('<p class="section-kicker">Download</p>', heading_markup)
                self.assertNotIn('<select', heading_markup)
                self.assertIn('class="cache-phase-live-marker"', body)
                self.assertIn('role="status"', body)
                self.assertIn('id="recent_events_pagination"', body)
                self.assertIn(
                    'class="browser-pagination local-store-pagination local-store-pagination--floating events-pagination"',
                    body,
                )
                pagination_start = body.index('id="recent_events_pagination"')
                pagination_end = body.index(">", pagination_start)
                pagination_markup = body[pagination_start:pagination_end]
                self.assertIn('aria-label="Recent event pages"', pagination_markup)
                self.assertIn("hidden", pagination_markup)
                self.assertNotIn('class="local-store-pagination-indicator" aria-hidden="true"></span>', body)
                self.assertNotIn('class="events-page-button"', body)
                self.assertNotIn('class="events-page-indicator"', body)
        self.assertIn('data-section-link="local-resources"', browser_body)
        self.assertIn("Cached media browser", browser_body)
        self.assertIn('data-browser-source-filter', browser_body)
        self.assertEqual(browser_body.count('data-browser-source-filter-option='), 4)
        self.assertIn('browser-source-filter.js?v=browser-source-filter-v1.2.0-codex.1', browser_body)
        self.assertIn('class="trade-strategy-select form-select trade-strategy-trigger browser-source-filter-trigger"', browser_body)

        self.assertIn('class="trade-strategy-dropdown-option browser-source-filter-option', browser_body)
        self.assertNotIn('<p class="section-kicker">Local cache</p>', browser_body)
        self.assertNotIn('status-chip status-collecting">Manageable', browser_body)
        self.assertIn("--cache-source-mark: url('/static/images/x.svg')", browser_body)
        self.assertIn("--cache-source-mark: url('/static/images/grok.svg')", browser_body)
        self.assertIn("--cache-source-mark: url('/static/images/ChatGPT-Logo.svg')", browser_body)
        self.assertNotIn("Apply filters", browser_body)
        self.assertIn('id="status_progress_detail"', grok_body)
        self.assertIn("data.queued_tweets", cache_page_script)
        self.assertIn("data.processed_tweets", cache_page_script)
        self.assertIn("function setStatusValueIfChanged", cache_page_script)
        self.assertIn("element instanceof HTMLInputElement", cache_page_script)
        for fragment in (
            'const contentModeStorageKey = "cachelikes:browser-content-mode:v1";',
            'mediaConfig.hidden = normalizedMode === "text";',
            'event.preventDefault();',
            'contentModeInput.value = normalizedMode;',
        ):
            with self.subTest(chatgpt_page_fragment=fragment):
                self.assertIn(fragment, chatgpt_page_script)
        self.assertNotIn('id="reset_button"', grok_body)
        self.assertIn('id="reset_button"', settings_body)
        self.assertIn('id="reset_chatgpt_button"', settings_body)
        self.assertIn("<h2>Configuration center</h2>", settings_body)
        self.assertEqual(settings_body.count('class="workspace-kicker"'), 0)
        self.assertIn('name="chatgpt_startup_timeout_seconds"', settings_body)
        self.assertIn('name="chatgpt_scan_wait_seconds"', settings_body)
        self.assertIn('name="max_media_file_size_mib"', settings_body)
        self.assertIn("Max cached file size (MiB)", settings_body)
        self.assertIn('name="shadow_backup_enabled"', settings_body)
        self.assertIn('name="shadow_backup_auto_sync"', settings_body)
        self.assertIn('name="shadow_backup_mirror_deletions"', settings_body)
        self.assertIn('name="shadow_backup_destination"', settings_body)
        self.assertIn('id="shadow_backup_choose_destination"', settings_body)
        self.assertIn('class="shadow-backup-destination-control settings-directory-control settings-directory-control-readonly"', settings_body)
        self.assertIn('class="shadow-backup-destination-control settings-directory-control"', settings_body)
        self.assertIn('class="secondary-button settings-directory-choose-button shadow-backup-choose-button"', settings_body)
        self.assertEqual(settings_body.count('class="icon settings-directory-choose-icon"'), 2)
        self.assertNotIn("Choose folder…", settings_body)
        self.assertEqual(settings_body.count("data-settings-directory-picker"), 2)
        self.assertIn('data-shadow-backup-status-spinner', settings_body)
        self.assertIn('data-shadow-backup-status-copy', settings_body)
        self.assertNotIn('id="shadow_backup_phase"', settings_body)
        self.assertNotIn('class="sidebar-section anchor-section" id="settings"', settings_body)
        self.assertIn('formaction="/settings/shadow-backup/sync"', settings_body)
        self.assertEqual(settings_body.count('class="settings-action-package settings-callout-card-primary'), 2)
        self.assertIn('class="settings-action-package settings-callout-card-primary settings-agent-terminal-action"', settings_body)
        self.assertIn('class="settings-action-package settings-callout-card-primary shadow-backup-actions"', settings_body)
        self.assertIn('class="icon icon-settings-agent"', settings_body)
        self.assertIn('class="icon icon-settings-cloud"', settings_body)
        self.assertIn('data-agent-terminal-authorization-status aria-live="polite" hidden></span>', settings_body)
        self.assertIn('data-agent-terminal-authorization-button', settings_body)
        self.assertIn('class="settings-inline-button settings-inline-button-primary shadow-backup-sync-button"', settings_body)
        self.assertIn('shadow-backup-settings.js?v=shadow-backup-settings-v1.3.0-codex.2', settings_body)
        self.assertIn('settings-directory-picker.js?v=settings-directory-picker-v1.3.0-codex.1', settings_body)
        self.assertIn("Reset Grok state", settings_body)
        self.assertIn("Reset ChatGPT state", settings_body)

    def test_cache_source_switcher_uses_one_complete_registry_on_every_cache_page(self) -> None:
        app = create_app()

        with app.test_client() as client:
            bodies = {
                source: client.get(f"/cache/{source}").get_data(as_text=True)
                for source in ("chatgpt", "gemini", "grok")
            }

        expected_options = ("chatgpt", "gemini", "grok", "x")
        expected_paths_by_page = {
            "chatgpt": ("/cache/chatgpt", "/cache/gemini", "/cache/grok", "/cache/x"),
            "gemini": (
                "/cache/chatgpt",
                "/cache/gemini",
                "/browser?view=text&amp;session_view=1&amp;q=&amp;source=grok&amp;sort=newest",
                "/cache/x",
            ),
            "grok": ("/cache/chatgpt", "/cache/gemini", "/cache/grok", "/cache/x"),
        }
        for page_source, body in bodies.items():
            with self.subTest(page_source=page_source):
                aside_start = body.index('<aside class="panel sidebar"')
                aside_end = body.index("</aside>", aside_start)
                aside = body[aside_start:aside_end]
                self.assertEqual(
                    [
                        option
                        for option in expected_options
                        if f'data-cache-source-switcher-option="{option}"' in aside
                    ],
                    list(expected_options),
                )
                for expected_path in expected_paths_by_page[page_source]:
                    self.assertIn(
                        f'data-cache-source-switcher-path="{expected_path}"',
                        aside,
                    )

    def test_agent_control_plane_allows_private_lan_with_password(self) -> None:
        with patch(
            "app.core.computer_use_agent.load_computer_use_settings",
            return_value=ComputerUseSettings(browser="edge", platform="chatgpt"),
        ):
            app = create_app()

        lan_environ = {"REMOTE_ADDR": "192.168.124.20"}
        lan_headers = {"Host": "192.168.124.10:8666"}
        with patch.dict("os.environ", {"CACHELIKES_AGENT_PASSWORD": "195135"}):
            with app.test_client() as client:
                local_page = client.get("/agent", follow_redirects=True)
                local_status = client.get("/api/agent/status")
                removed_reveal = client.post("/api/agent/owner-token/reveal")
                lan_page = client.get(
                    "/agent",
                    headers=lan_headers,
                    environ_overrides=lan_environ,
                )
                lan_status = client.get(
                    "/api/agent/status",
                    headers=lan_headers,
                    environ_overrides=lan_environ,
                )
                wrong_unlock = client.post(
                    "/agent/unlock",
                    data={"password": "000000"},
                    headers=lan_headers,
                    environ_overrides=lan_environ,
                )
                correct_unlock = client.post(
                    "/agent/unlock",
                    data={"password": "195135"},
                    headers=lan_headers,
                    environ_overrides=lan_environ,
                )
                unlocked_lan_page = client.get(
                    "/agent",
                    follow_redirects=True,
                    headers=lan_headers,
                    environ_overrides=lan_environ,
                )
                unlocked_lan_status = client.get(
                    "/api/agent/status",
                    headers=lan_headers,
                    environ_overrides=lan_environ,
                )
                remote_page = client.get(
                    "/agent",
                    environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                )
                remote_status = client.get(
                    "/api/agent/status",
                    environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                )
                rebound_host_page = client.get(
                    "/agent",
                    headers={"Host": "malicious.example"},
                )

        self.assertEqual(local_page.status_code, 200)
        self.assertEqual(local_status.status_code, 200)
        self.assertEqual(removed_reveal.status_code, 404)
        self.assertEqual(lan_page.status_code, 200)
        self.assertEqual(lan_status.status_code, 401)
        self.assertEqual(wrong_unlock.status_code, 401)
        self.assertEqual(correct_unlock.status_code, 303)
        self.assertEqual(correct_unlock.headers["Location"], "/agent/edge/chatgpt")
        self.assertIn("HttpOnly", correct_unlock.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", correct_unlock.headers["Set-Cookie"])
        self.assertEqual(unlocked_lan_page.status_code, 200)
        self.assertEqual(unlocked_lan_status.status_code, 200)
        self.assertEqual(remote_page.status_code, 403)
        self.assertEqual(remote_status.status_code, 403)
        self.assertEqual(rebound_host_page.status_code, 403)
        locked_body = lan_page.get_data(as_text=True)
        self.assertIn('class="workspace-modal-dialog agent-access-dialog"', locked_body)
        self.assertIn('id="agent_access_password"', locked_body)
        self.assertEqual(locked_body.count('class="agent-access-slot"'), 6)
        self.assertNotIn("195135", locked_body)
        self.assertIn("no-store", lan_page.headers["Cache-Control"])
        self.assertIn("The password is incorrect.", wrong_unlock.get_data(as_text=True))
        local_body = local_page.get_data(as_text=True)
        self.assertIn("ChatGPT Web Agent", local_body)
        self.assertNotIn('id="agent_phase_chip"', local_body)
        self.assertIn("Idle ·", local_body)
        self.assertNotIn("public tunnel, API key, or copied password", local_body)
        self.assertNotIn('data-agent-engine-kicker', local_body)
        self.assertNotIn('data-agent-engine-copy', local_body)
        self.assertNotIn("With thanks to", local_body)
        self.assertNotIn('class="agent-open-source-credit"', local_body)
        self.assertNotIn('class="trade-strategy-combobox agent-combobox agent-os-combobox"', local_body)
        self.assertNotIn('data-agent-terminal-authorization-button', local_body)
        self.assertNotIn('data-agent-terminal-authorization-status', local_body)
        self.assertIn('name="operating_system" value="macos" data-agent-prompt-os', local_body)
        self.assertIn('data-agent-combobox-option="safari"', local_body)
        self.assertNotIn('name="port"', local_body)
        self.assertIn('id="agent_project_path"', local_body)
        self.assertIn('aria-describedby="agent_project_path_status"', local_body)
        self.assertIn('id="agent_project_path_status"', local_body)
        self.assertNotIn('aria-describedby="true"', local_body)
        self.assertIn('data-directory-field="agent_allowed_root"', local_body)
        self.assertIn('data-agent-project-name', local_body)
        self.assertIn('<span class="field-label">Current project</span>', local_body)
        self.assertNotIn('<span class="field-label">Local project</span>', local_body)
        project_name_position = local_body.index('data-agent-project-name')
        project_picker_position = local_body.index(
            'class="shadow-backup-destination-control settings-directory-control"'
        )
        self.assertLess(project_name_position, project_picker_position)
        self.assertNotIn('stop MCP before switching projects.', local_body)
        self.assertNotIn('id="agent_context_policy"', local_body)
        self.assertNotIn('class="secondary-button settings-directory-choose-button agent-runtime-log-open"', local_body)
        self.assertNotIn('class="shadow-backup-destination-control agent-runtime-log-control"', local_body)
        self.assertNotIn('class="icon agent-runtime-log-open-icon"', local_body)
        self.assertNotIn('<span class="field-label">Context package</span>', local_body)
        self.assertIn('class="agent-composer-shell"', local_body)
        self.assertIn('id="agent_response_output" lang="zh-CN"', local_body)
        self.assertIn('data-agent-project-name', local_body)
        self.assertNotIn('class="agent-composer-preview"', local_body)
        self.assertNotIn('data-agent-markdown-preview', local_body)
        self.assertIn('id="agent_ask_button"', local_body)
        self.assertNotIn('id="agent_stop_button"', local_body)
        self.assertNotIn("Stop request", local_body)
        self.assertNotIn('id="agent_mcp_url"', local_body)
        self.assertNotIn('<dt>Local MCP</dt>', local_body)
        self.assertNotIn('<span class="field-label">Workspace</span>', local_body)
        self.assertNotIn('<p class="workspace-kicker">Task</p>', local_body)
        self.assertNotIn('<p class="workspace-kicker">Live result</p>', local_body)
        self.assertIn('settings-directory-picker.js?v=settings-directory-picker-v1.3.0-codex.1', local_body)
        self.assertIn('browser-session-status.js?v=browser-session-status-v1.8.0-codex.1', local_body)
        self.assertIn('pagination-motion.js?v=pagination-motion-v1.1.0-codex.1', local_body)
        self.assertIn('computer-use-agent.js?v=computer-use-agent-v3.25.0-codex.1', local_body)
        self.assertIn('data-agent-effort-field', local_body)
        self.assertIn('name="chatgpt_effort"', local_body)
        self.assertIn('data-agent-browser-session', local_body)
        self.assertIn('data-browser-session-platform="chatgpt"', local_body)
        self.assertIn('data-browser-session-scope="agent"', local_body)
        self.assertIn('data-role="browser-session-account"', local_body)
        self.assertIn('data-browser-session-account-label="ChatGPT"', local_body)
        self.assertIn('data-agent-terminal-execution-status', local_body)
        self.assertIn('data-agent-terminal-execution-copy', local_body)
        self.assertIn('data-agent-terminal-execution-checkmark', local_body)
        self.assertIn('<span class="agent-terminal-execution-label">Terminal permission</span>', local_body)
        self.assertNotIn('Terminal execution permission:', local_body)
        self.assertIn('data-agent-platform-input', local_body)
        self.assertIn('data-agent-combobox-option="gemini"', local_body)
        self.assertIn('data-agent-combobox-option="grok"', local_body)
        self.assertIn('data-agent-remote-label="Gemini 3.1 Pro"', local_body)
        self.assertIn('data-agent-remote-label="Auto"', local_body)
        self.assertIn('aria-label="Model: 5.6 Sol"', local_body)
        self.assertIn('data-agent-combobox-label="5.6 Sol"', local_body)
        self.assertIn('ChatGPT · 5.6 Sol', local_body)
        self.assertIn('Gemini · 3.1 Pro', local_body)
        self.assertIn('Grok · Build', local_body)
        self.assertIn('data-agent-combobox-option="safari"', local_body)
        self.assertIn('data-agent-heading', local_body)
        self.assertIn('data-agent-prompt-input', local_body)
        self.assertIn('data-agent-prompt-os', local_body)
        self.assertIn('data-agent-model-input', local_body)
        self.assertIn('data-agent-combobox-option="gpt-5.6-sol"', local_body)
        self.assertIn('data-agent-model-strength="100"', local_body)
        self.assertIn('GPT-5.6 Sol', local_body)
        self.assertIn('id="agent_activity_panel"', local_body)
        self.assertIn('id="agent_error_record"', local_body)
        self.assertIn('data-agent-error-record-content', local_body)
        self.assertIn('class="agent-error-record-scroll"', local_body)

        self.assertIn('class="agent-response-output"', local_body)
        self.assertIn('class="agent-response-question-header', local_body)
        self.assertIn('data-agent-response-question', local_body)
        self.assertIn('id="agent_response_question_header"', local_body)
        self.assertIn('data-browser-session-message-toggle', local_body)
        self.assertIn('class="agent-response-answer browser-media-prompt-markdown', local_body)
        self.assertIn('data-agent-response-answer-content', local_body)
        self.assertIn('data-agent-response-pagination', local_body)
        self.assertIn('class="browser-pagination local-store-pagination agent-response-pagination"', local_body)
        self.assertIn('browser-session-messages.js?v=browser-session-messages-v1.0.1-codex.1', local_body)
        self.assertNotIn('data-agent-web-only', local_body)
        self.assertNotIn("Starts a new root-level ChatGPT session for this task.", local_body)
        self.assertNotIn("Choose where this task continues; new session is the default.", local_body)
        self.assertIn('data-agent-combobox-spinner', local_body)
        self.assertIn('class="browser-media-round-action browser-media-source-link agent-conversation-link"', local_body)
        self.assertIn('href="https://chatgpt.com/"', local_body)
        self.assertIn('data-agent-open-conversation', local_body)
        self.assertIn('data-agent-browser="edge"', local_body)
        self.assertIn('aria-label="Open ChatGPT in Edge"', local_body)
        self.assertIn('data-agent-conversation-link-label', local_body)
        self.assertIn('class="icon browser-media-source-link-icon"', local_body)
        self.assertNotIn("Local control plane for a signed-in ChatGPT web session", local_body)
        self.assertNotIn("third-party agent bridge", local_body)
        self.assertNotIn("Allowed workspace root", local_body)
        self.assertNotIn("Public HTTPS origin", local_body)
        self.assertNotIn("OAuth owner password", local_body)
        self.assertNotIn("agent_owner_token_reveal", local_body)
        self.assertNotIn("owner_token", json.dumps(local_status.get_json()))
        self.assertIn("runtime", local_status.get_json())
        self.assertIn("terminal_execution", local_status.get_json()["runtime"])
        self.assertNotIn("native", local_status.get_json())

        task_position = local_body.index("agent-task-card")
        response_position = local_body.index("agent-response-card")
        prompt_form_position = local_body.index('id="agent_prompt_form"')
        self.assertLess(task_position, response_position)
        self.assertLess(response_position, prompt_form_position)
        self.assertIn(
            '<article class="report-card workspace-article-card agent-task-card">\n'
            '                    <article class="agent-response-card"',
            local_body,
        )

    def test_agent_browser_session_scope_uses_control_plane_gate_and_no_store(
        self,
    ) -> None:
        status_payload = {
            "platform": "chatgpt",
            "browser": "edge",
            "browser_label": "Edge",
            "logged_in": True,
            "can_download": False,
            "account_name": "ChatGPT account",
            "message": "Ready",
        }
        lan_environ = {"REMOTE_ADDR": "192.168.124.20"}
        lan_headers = {"Host": "192.168.124.10:8666"}

        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with patch(
                "app.web.app.probe_and_collect_chatgpt_sources",
                return_value=(status_payload, None),
            ) as probe:
                with app.test_client() as client:
                    locked_lan_response = client.get(
                        "/api/browser-session?platform=chatgpt&browser=edge&scope=agent",
                        headers=lan_headers,
                        environ_overrides=lan_environ,
                    )
                    disallowed_network_response = client.get(
                        "/api/browser-session?platform=chatgpt&browser=edge&scope=agent",
                        environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                    )
                    disallowed_host_response = client.get(
                        "/api/browser-session?platform=chatgpt&browser=edge&scope=agent",
                        headers={"Host": "malicious.example"},
                    )
                    probe.assert_not_called()

                    loopback_response = client.get(
                        "/api/browser-session?platform=chatgpt&browser=edge&scope=agent"
                    )

        self.assertEqual(locked_lan_response.status_code, 401)
        self.assertEqual(disallowed_network_response.status_code, 403)
        self.assertEqual(disallowed_host_response.status_code, 403)
        self.assertEqual(loopback_response.status_code, 200)
        self.assertIn("no-store", loopback_response.headers["Cache-Control"])
        self.assertEqual(loopback_response.headers["Pragma"], "no-cache")
        self.assertEqual(loopback_response.headers["Expires"], "0")
        probe.assert_called_once()

    def test_agent_browser_status_card_uses_compact_provider_and_terminal_rows(self) -> None:
        app = create_app()

        with app.test_client() as client:
            response = client.get("/agent", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('class="browser-session-status-card browser-session-status-card-compact"', body)
        self.assertIn('data-browser-session-account-label="ChatGPT"', body)
        self.assertIn('<span class="agent-terminal-execution-label">Terminal permission</span>', body)
        self.assertIn('data-agent-terminal-execution-checkmark', body)
        self.assertNotIn('Terminal execution permission:', body)
        status_item_start = body.index('<div class="browser-session-status-item">')
        status_item_end = body.index('</div>', status_item_start) + len('</div>')
        status_item = body[status_item_start:status_item_end]
        self.assertIn('data-role="browser-session-spinner"', status_item)
        self.assertIn('data-role="browser-session-account"', status_item)
        self.assertLess(
            status_item.index('data-role="browser-session-spinner"'),
            status_item.index('data-role="browser-session-account"'),
        )

    def test_agent_status_renders_safe_markdown_for_live_updates(self) -> None:
        app = create_app()
        agent_service = app.extensions["computer_use_agent_service"]
        snapshot = agent_service.snapshot()
        snapshot["response"] = "**Verified** <script>alert('x')</script>"
        snapshot["history"] = [
            {
                "prompt": "Inspect rendering",
                "response": "**History** <script>alert('history')</script>",
            }
        ]

        with patch.object(agent_service, "snapshot", return_value=snapshot):
            with app.test_client() as client:
                payload = client.get("/api/agent/status").get_json()

        response_html = payload["agent"]["response_html"]
        self.assertIn("<strong>Verified</strong>", response_html)
        self.assertNotIn("<script>", response_html)
        self.assertIn("&lt;script&gt;", response_html)
        history_html = payload["agent"]["history"][0]["response_html"]
        self.assertIn("<strong>History</strong>", history_html)
        self.assertNotIn("<script>", history_html)
        self.assertIn("&lt;script&gt;", history_html)

    def test_agent_page_renders_error_traceback_in_a_collapsible_record(self) -> None:
        app = create_app()
        agent_service = app.extensions["computer_use_agent_service"]
        snapshot = agent_service.snapshot()
        snapshot.update(
            {
                "last_error": "The selected provider tab navigated away from the newly created session.",
                "error_traceback": "Traceback (most recent call last):\nRuntimeError: <unsafe>",
                "message": "The selected provider tab navigated away from the newly created session.",
                "phase": "failed",
                "platform": "chatgpt",
                "browser": "edge",
            }
        )

        with patch.object(agent_service, "snapshot", return_value=snapshot):
            with app.test_client() as client:
                body = client.get("/agent/edge/chatgpt").get_data(as_text=True)

        self.assertIn('<details class="agent-error-record" id="agent_error_record" open>', body)
        self.assertIn('class="agent-error-record-scroll"', body)
        self.assertIn('data-agent-error-record-content', body)
        self.assertIn("Traceback (most recent call last):", body)
        self.assertIn("RuntimeError: &lt;unsafe&gt;", body)

    def test_agent_page_isolates_completed_snapshots_by_provider_and_browser(self) -> None:
        app = create_app()
        agent_service = app.extensions["computer_use_agent_service"]
        snapshot = agent_service.snapshot()
        snapshot.update(
            {
                "activity": [
                    {
                        "status": "complete",
                        "label": "STALE_ACTIVITY_SENTINEL",
                        "detail": "Old ChatGPT activity",
                        "meta": "Earlier run",
                    }
                ],
                "browser": "edge",
                "history": [
                    {
                        "prompt": "STALE_HISTORY_PROMPT_SENTINEL",
                        "response": "STALE_HISTORY_RESPONSE_SENTINEL",
                    }
                ],
                "message": "STALE_MESSAGE_SENTINEL",
                "phase": "finished",
                "platform": "chatgpt",
                "prompt": "STALE_PROMPT_SENTINEL",
                "response": "STALE_RESPONSE_SENTINEL",
                "running": False,
            }
        )

        with patch.object(agent_service, "snapshot", return_value=snapshot):
            with app.test_client() as client:
                matching_body = client.get("/agent/edge/chatgpt").get_data(as_text=True)
                provider_mismatch = client.get("/agent/edge/grok").get_data(as_text=True)
                browser_mismatch = client.get("/agent/chrome/chatgpt").get_data(as_text=True)

        self.assertIn("STALE_HISTORY_RESPONSE_SENTINEL", matching_body)
        for body in (provider_mismatch, browser_mismatch):
            with self.subTest(route_body=body[:80]):
                self.assertNotIn("STALE_ACTIVITY_SENTINEL", body)
                self.assertNotIn("STALE_HISTORY_PROMPT_SENTINEL", body)
                self.assertNotIn("STALE_HISTORY_RESPONSE_SENTINEL", body)
                self.assertNotIn("STALE_MESSAGE_SENTINEL", body)
                self.assertNotIn("STALE_PROMPT_SENTINEL", body)
                self.assertNotIn("STALE_RESPONSE_SENTINEL", body)
                self.assertNotIn('id="agent_phase_chip"', body)
                self.assertIn("Idle ·", body)
                self.assertIn(
                    'data-agent-prompt-input required></textarea>',
                    body,
                )

    def test_agent_project_picker_uses_the_shared_directory_route(self) -> None:
        selected_path = Path("/tmp/Selected Agent Project")
        app = create_app()

        with patch("app.web.app.choose_settings_directory", return_value=selected_path) as picker:
            with app.test_client() as client:
                response = client.post(
                    "/api/settings/directory",
                    json={
                        "field": "agent_allowed_root",
                        "initial_path": "/tmp/Existing Agent Project",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"directory": str(selected_path)})
        picker.assert_called_once_with(
            Path("/tmp/Existing Agent Project"),
            "Select local Agent project folder",
        )

    def test_agent_project_picker_syncs_runtime_workspace_and_project_name(self) -> None:
        script = COMPUTER_USE_AGENT_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'workspacePath: promptForm.querySelector(\'input[name="workspace_path"]\')',
            'elements.projectPath?.addEventListener("change"',
            'elements.workspacePath.value = normalizedPath',
            'elements.projectName.textContent = projectNameFromPath(normalizedPath)',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_agent_preferences_persist_the_exact_project_and_execution_choices(self) -> None:
        with TemporaryDirectory() as raw_root:
            workspace = Path(raw_root) / "Selected Project"
            workspace.mkdir()
            initial_settings = ComputerUseSettings(workspace_path=str(workspace))
            with patch(
                "app.core.computer_use_agent.load_computer_use_settings",
                return_value=initial_settings,
            ):
                app = create_app()
                with patch(
                    "app.core.computer_use_agent.save_computer_use_settings"
                ) as save_computer_use_settings:
                    with app.test_client() as client:
                        response = client.post(
                            "/api/agent/preferences",
                            json={
                                "workspace_path": str(workspace),
                                "operating_system": "macos",
                                "browser": "safari",
                            },
                        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["settings"]["workspace_path"], str(workspace.resolve()))
        save_computer_use_settings.assert_called_once()

    def test_agent_terminal_authorization_route_is_local_and_platform_aware(self) -> None:
        app = create_app()
        opened = {
            "opened": True,
            "operating_system": "macos",
            "application": "Terminal",
            "destination": "System Settings > Privacy & Security > Full Disk Access",
            "message": "System Settings opened.",
        }

        with patch("app.web.app.launch_terminal_authorization", return_value=opened) as launch:
            with app.test_client() as client:
                response = client.post(
                    "/api/agent/terminal-authorization",
                    json={"operating_system": "macos"},
                )
                remote_response = client.post(
                    "/api/agent/terminal-authorization",
                    json={"operating_system": "macos"},
                    environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), opened)
        self.assertEqual(remote_response.status_code, 403)
        launch.assert_called_once_with("macos")

    def test_agent_conversation_route_opens_the_current_target_in_the_selected_browser(self) -> None:
        app = create_app()
        agent_service = app.extensions["computer_use_agent_service"]
        snapshot = agent_service.snapshot()
        snapshot["conversation_url"] = "https://chatgpt.com/c/current-session"
        snapshot["browser"] = "edge"
        opened = {
            "opened": True,
            "platform": "chatgpt",
            "browser": "edge",
            "application": "Microsoft Edge",
            "url": "https://chatgpt.com/c/current-session",
            "targeted_conversation": True,
            "background": False,
        }

        with patch.object(agent_service, "snapshot", return_value=snapshot):
            with patch(
                "app.web.app.open_agent_in_browser",
                return_value=opened,
            ) as open_browser:
                with app.test_client() as client:
                    response = client.post("/api/agent/open-conversation")
                    remote_response = client.post(
                        "/api/agent/open-conversation",
                        environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), opened)
        self.assertEqual(remote_response.status_code, 403)
        open_browser.assert_called_once_with(
            "chatgpt",
            "edge",
            "https://chatgpt.com/c/current-session",
            background=False,
        )

    def test_agent_sidebar_log_and_chat_composer_keep_runtime_targets_in_sync(self) -> None:
        script = COMPUTER_USE_AGENT_SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn('elements.promptOs.value = selectedOs()', script)
        self.assertIn('elements.promptPlatform.value = selectedPlatform()', script)
        self.assertIn('elements.promptBrowser.value = selectedBrowser()', script)
        self.assertIn('elements.modelInput.value = selectedModel()', script)
        self.assertIn('elements.effortInput.value = selectedChatgptEffort()', script)
        self.assertIn('chatgpt_effort: selectedChatgptEffort()', script)
        self.assertIn('syncModelOptionsForPlatform()', script)
        self.assertIn('syncChatgptEffortOptions(agent)', script)
        self.assertIn('agent?.available_efforts', script)
        self.assertIn('data-agent-effort-generated', script)
        self.assertIn('browserStatusController?.setPlatform?.(platform)', script)
        self.assertIn('platform: selectedPlatform()', script)
        self.assertIn('selectedValue(".agent-model-combobox", "")', script)
        self.assertIn('option.dataset.agentModelStrength', script)
        self.assertIn('syncPlatformState();', script)
        self.assertIn('selectedValue(".agent-browser-combobox", "edge")', script)
        self.assertIn('elements.ask.classList.toggle("is-stop", running)', script)
        self.assertIn('mutate("/api/agent/stop")', script)
        self.assertIn('mutate("/api/agent/resume")', script)
        self.assertIn("CATALOG_TIMEOUT_MS = 15000", script)
        self.assertIn('query.set("refresh", "1")', script)
        self.assertIn("loadAgentSources({forceRefresh: true})", script)
        self.assertIn("Recent sessions timed out after 15 seconds.", script)
        self.assertIn("clearCatalogLoadingState", script)
        self.assertIn('requestJson("/api/agent/open-conversation"', script)
        self.assertIn('elements.conversationLink.classList.toggle("is-traditional-handoff"', script)
        self.assertIn("agent?.traditional_handoff_available", script)
        self.assertIn('agent.phase !== "failed"', script)
        self.assertNotIn('document.getElementById("agent_stop_button")', script)

    def test_agent_session_source_contract_is_explicit_and_not_persisted(self) -> None:
        app = create_app()
        agent_service = app.extensions["computer_use_agent_service"]
        with patch.object(agent_service, "start") as start:
            with app.test_client() as client:
                response = client.post(
                    "/api/agent/ask",
                    json={
                        "prompt": "Inspect fonts",
                        "workspace_path": str(Path(__file__).resolve().parents[1]),
                        "operating_system": "macos",
                        "browser": "safari",
                        "model": "gpt-5.6-sol",
                        "session_mode": "recent",
                        "conversation_url": "https://chatgpt.com/c/recent-session",
                        "project_url": "",
                        "session_title": "Font audit",
                        "read_only": True,
                    },
                )

        self.assertEqual(response.status_code, 202)
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs["session_mode"], "recent")
        self.assertEqual(start.call_args.kwargs["conversation_url"], "https://chatgpt.com/c/recent-session")
        self.assertEqual(start.call_args.kwargs["session_title"], "Font audit")
        self.assertEqual(start.call_args.kwargs["model"], "gpt-5.6-sol")
        self.assertTrue(start.call_args.kwargs["read_only"])

    def test_agent_page_exposes_session_source_controls(self) -> None:
        app = create_app()
        script = COMPUTER_USE_AGENT_SCRIPT_PATH.read_text(encoding="utf-8")

        with app.test_client() as client:
            body = client.get("/agent", follow_redirects=True).get_data(as_text=True)

        for fragment in (
            'data-agent-session-mode',
            'data-agent-session-list="recent"',
            'data-agent-session-list="projects"',
            'data-agent-session-list="project-sessions"',
            'Choose a project first',
            'name="session_mode" value="new"',
            'name="conversation_url" value=""',
            'name="project_url" value=""',
            'name="session_title" value=""',
            'computer-use-agent-v3.25.0-codex.1',
            'data-agent-effort-field',
            'data-agent-effort-input',
            'data-agent-direct-list="true"',
            'data-agent-session-list-state',
            'data-agent-combobox-icon="/static/images/plus.circle.svg"',
            'src="/static/images/plus.circle.svg" alt="" data-agent-combobox-selected-icon',
            'data-agent-combobox-icon="/static/images/clock.fill.svg"',
            'src="/static/images/clock.fill.svg" alt="" aria-hidden="true">\n                                    <span class="trade-strategy-dropdown-text">Recent sessions</span>',
            'suggestion-loading-spinner agent-empty-response-spinner',
            'data-agent-session-history-spinner',
            'data-agent-empty-response-copy',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, body)
        self.assertIn('function syncSessionModeTrigger()', script)
        self.assertIn('syncComboboxTriggerFromOption(combobox, option)', script)
        self.assertIn('const isDirectList = combobox.dataset.agentDirectList === "true"', script)
        self.assertIn("selectedOption?.dataset.agentComboboxLabel", script)
        self.assertNotIn('data-agent-session-platforms="chatgpt"', body)

    def test_agent_page_exposes_a_collapsed_two_line_composer_control(self) -> None:
        app = create_app()
        script = COMPUTER_USE_AGENT_SCRIPT_PATH.read_text(encoding="utf-8")

        with app.test_client() as client:
            body = client.get("/agent", follow_redirects=True).get_data(as_text=True)

        for fragment in (
            'id="agent_prompt_input"',
            'rows="2"',
            'data-agent-composer-overflow-toggle',
            'aria-controls="agent_prompt_input"',
            'aria-expanded="false"',
            'aria-label="Expand question or task"',
            'browser-session-message-toggle-icon',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, body)
        self.assertNotIn(
            'local-store-pagination--floating agent-response-pagination',
            body,
        )
        self.assertIn("function setPromptExpanded(expanded)", script)
        self.assertIn("function promptCollapsedHeight()", script)

    def test_agent_page_exposes_the_four_web_provider_model_pairs(self) -> None:
        app = create_app()
        script = COMPUTER_USE_AGENT_SCRIPT_PATH.read_text(encoding="utf-8")

        with app.test_client() as client:
            body = client.get("/agent", follow_redirects=True).get_data(as_text=True)

        self.assertIn('<span class="field-label">Web service</span>', body)
        self.assertIn('class="browser-picker-option-icon" src="/static/images/ChatGPT-Logo.svg"', body)
        self.assertIn('data-agent-combobox-icon="/static/images/Google_Gemini_logo_2025_symbol.svg"', body)
        self.assertIn('data-agent-combobox-icon="/static/images/grok.svg"', body)
        self.assertIn('data-agent-combobox-icon="/static/images/claude.svg"', body)
        self.assertIn('class="browser-session-trigger-leading"', body)
        self.assertIn('data-browser-session-platform="chatgpt"', body)
        self.assertIn('data-agent-combobox-option="gpt-5.6-sol"', body)
        self.assertIn('data-agent-combobox-option="gemini-3.1-pro"', body)
        self.assertIn('data-agent-combobox-option="grok-build"', body)
        self.assertIn('data-agent-combobox-option="claude-auto"', body)
        self.assertIn('placeholder="Do anything"', body)
        self.assertIn('elements.promptInput.placeholder = "Do anything"', script)

    def test_agent_browser_alias_and_claude_route_render_the_shared_workspace(self) -> None:
        with patch(
            "app.core.computer_use_agent.load_computer_use_settings",
            return_value=ComputerUseSettings(browser="edge", platform="chatgpt"),
        ):
            app = create_app()

        with app.test_client() as client:
            browser_alias = client.get("/agent/edge/")
            claude_page = client.get("/agent/edge/claude")
            safari_claude_page = client.get("/agent/safari/claude")

        self.assertEqual(browser_alias.status_code, 302)
        self.assertEqual(browser_alias.headers["Location"], "/agent/edge/chatgpt")
        self.assertEqual(claude_page.status_code, 200)
        claude_body = claude_page.get_data(as_text=True)
        self.assertIn("Claude Web Agent", claude_body)
        self.assertIn('data-agent-platform-home-url="https://claude.ai/new"', claude_body)
        self.assertEqual(safari_claude_page.status_code, 404)

    def test_claude_agent_browser_bootstrap_reuses_one_status_and_source_payload(self) -> None:
        source_payload = {
            "platform": "claude",
            "recent_sessions": [],
            "projects": [],
            "limit": 20,
        }
        status_payload = {
            "platform": "claude",
            "browser": "edge",
            "browser_label": "Edge",
            "logged_in": True,
            "can_download": True,
            "account_name": "Claude account",
            "message": "Edge verified Claude.",
        }
        app = create_app()
        with patch(
            "app.web.app.probe_and_collect_claude_sources",
            return_value=(status_payload, source_payload),
        ) as probe:
            with app.test_client() as client:
                response = client.get(
                    "/api/browser-session?platform=claude&browser=edge&scope=agent"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["agent_sources"], source_payload)
        probe.assert_called_once()

    def test_grok_agent_browser_bootstrap_uses_home_composer_and_reuses_sources(self) -> None:
        source_payload = {
            "platform": "grok",
            "recent_sessions": [{"id": "grok-1", "url": "https://grok.com/c/grok-1"}],
            "projects": [],
            "limit": 20,
        }
        status_payload = {
            "platform": "grok",
            "browser": "edge",
            "browser_label": "Edge",
            "logged_in": True,
            "can_download": True,
            "account_name": "Grok account",
            "message": "Edge verified Grok.",
        }
        app = create_app()
        with patch(
            "app.web.app.probe_and_collect_grok_sources",
            return_value=(status_payload, source_payload),
        ) as probe, patch("app.web.app.probe_browser_session") as legacy_probe:
            with app.test_client() as client:
                response = client.get(
                    "/api/browser-session?platform=grok&browser=edge&scope=agent"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["agent_sources"], source_payload)
        probe.assert_called_once()
        legacy_probe.assert_not_called()

    def test_agent_preferences_accept_gemini_and_grok_model_choices(self) -> None:
        with TemporaryDirectory() as raw_root:
            workspace = Path(raw_root) / "Selected Project"
            workspace.mkdir()
            initial_settings = ComputerUseSettings(workspace_path=str(workspace))
            with patch(
                "app.core.computer_use_agent.load_computer_use_settings",
                return_value=initial_settings,
            ):
                app = create_app()
                with patch("app.core.computer_use_agent.save_computer_use_settings"):
                    with app.test_client() as client:
                        gemini_response = client.post(
                            "/api/agent/preferences",
                            json={
                                "workspace_path": str(workspace),
                                "operating_system": "macos",
                                "platform": "gemini",
                                "browser": "edge",
                                "model": "gemini-3.1-pro",
                            },
                        )
                        grok_response = client.post(
                            "/api/agent/preferences",
                            json={
                                "workspace_path": str(workspace),
                                "operating_system": "macos",
                                "platform": "grok",
                                "browser": "chrome",
                                "model": "grok-build",
                            },
                        )

        self.assertEqual(gemini_response.status_code, 200)
        self.assertEqual(gemini_response.get_json()["settings"]["model"], "gemini-3.1-pro")
        self.assertEqual(grok_response.status_code, 200)
        self.assertEqual(grok_response.get_json()["settings"]["platform"], "grok")
        self.assertEqual(grok_response.get_json()["settings"]["model"], "grok-build")

    def test_agent_source_routes_are_loopback_only_and_delegate_selected_browser(self) -> None:
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with patch("app.web.app.list_chatgpt_agent_sources", return_value={"recent_sessions": [], "projects": []}) as sources:
                with patch("app.web.app.list_chatgpt_project_sessions", return_value={"sessions": []}) as sessions:
                    with patch(
                        "app.web.app.fetch_chatgpt_conversation_history",
                        return_value={
                            "conversation_url": "https://chatgpt.com/c/demo-session",
                            "title": "Demo session",
                            "history": [
                                {
                                    "prompt": "Inspect the fonts.",
                                    "response": "The project uses Inter.",
                                    "started_at": "2026-08-14T01:01:00Z",
                                    "finished_at": "2026-08-14T01:02:00Z",
                                }
                            ],
                            "limit": 100,
                        },
                    ) as history:
                        with app.test_client() as client:
                            source_response = client.get("/api/agent/chatgpt-sources?browser=edge")
                            project_response = client.get(
                                "/api/agent/chatgpt-project-sessions?browser=edge&project_url=https://chatgpt.com/g/g-p-demo/project"
                            )
                            history_response = client.get(
                                "/api/agent/chatgpt-session-history?browser=edge&conversation_url=https://chatgpt.com/c/demo-session"
                            )
                            remote_response = client.get(
                                "/api/agent/chatgpt-sources?browser=edge",
                                environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                            )

        self.assertEqual(source_response.status_code, 200)
        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(remote_response.status_code, 403)
        sources.assert_called_once()
        sessions.assert_called_once()
        history.assert_called_once()
        self.assertIn("<p>The project uses Inter.</p>", history_response.get_json()["history"][0]["response_html"])

    def test_agent_provider_source_route_reuses_one_recent_session_contract(self) -> None:
        payload = {
            "platform": "gemini",
            "browser_label": "Edge",
            "recent_sessions": [
                {
                    "id": "gemini-session",
                    "title": "Gemini task",
                    "url": "https://gemini.google.com/app/gemini-session",
                    "updated_at": "",
                }
            ],
            "projects": [],
            "limit": 20,
        }
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with patch("app.web.app.list_agent_sources", return_value=payload) as sources:
                with app.test_client() as client:
                    response = client.get("/api/agent/sources?platform=gemini&browser=edge")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["recent_sessions"], payload["recent_sessions"])
        self.assertEqual(response.get_json()["projects"], payload["projects"])
        self.assertEqual(response.get_json()["cache"]["status"], "miss")
        sources.assert_called_once()
        self.assertEqual(sources.call_args.args[:2], ("gemini", "edge"))

    def test_agent_browser_session_bootstrap_reuses_each_provider_cache_until_refresh(self) -> None:
        providers = (
            ("chatgpt", "ChatGPT", "probe_and_collect_chatgpt_sources"),
            ("grok", "Grok", "probe_and_collect_grok_sources"),
            ("claude", "Claude", "probe_and_collect_claude_sources"),
        )

        for platform, platform_label, collector_name in providers:
            with self.subTest(platform=platform):
                first_status_payload = {
                    "platform": platform,
                    "browser": "edge",
                    "browser_label": "Edge",
                    "logged_in": True,
                    "can_download": True,
                    "account_name": f"{platform_label} account",
                    "message": "Ready",
                }
                second_status_payload = {
                    **first_status_payload,
                    "message": "Refreshed",
                }
                first_source_payload = {
                    "platform": platform,
                    "browser_label": "Edge",
                    "recent_sessions": [{"id": f"{platform}-first"}],
                    "projects": [],
                    "limit": 20,
                }
                second_source_payload = {
                    **first_source_payload,
                    "recent_sessions": [{"id": f"{platform}-refreshed"}],
                }
                with TemporaryDirectory() as raw_root:
                    app = create_app(Path(raw_root) / "local_store")
                    with patch(
                        f"app.web.app.{collector_name}",
                        side_effect=[
                            (first_status_payload, first_source_payload),
                            (second_status_payload, second_source_payload),
                        ],
                    ) as bootstrap, patch("app.web.app.list_agent_sources") as sources:
                        with app.test_client() as client:
                            first_response = client.get(
                                f"/api/browser-session?platform={platform}&browser=edge&scope=agent"
                            )
                            cached_response = client.get(
                                f"/api/browser-session?platform={platform}&browser=edge&scope=agent"
                            )
                            refreshed_response = client.get(
                                f"/api/browser-session?platform={platform}&browser=edge&scope=agent&refresh=1"
                            )
                            catalog_response = client.get(
                                f"/api/agent/sources?platform={platform}&browser=edge"
                            )

                self.assertEqual(first_response.status_code, 200)
                self.assertEqual(
                    first_response.get_json()["agent_sources"]["recent_sessions"],
                    [{"id": f"{platform}-first"}],
                )
                self.assertNotIn("cache", first_response.get_json())
                self.assertEqual(cached_response.status_code, 200)
                self.assertEqual(cached_response.get_json()["message"], "Ready")
                self.assertEqual(
                    cached_response.get_json()["agent_sources"]["recent_sessions"],
                    [{"id": f"{platform}-first"}],
                )
                self.assertEqual(refreshed_response.status_code, 200)
                self.assertEqual(refreshed_response.get_json()["message"], "Refreshed")
                self.assertEqual(
                    refreshed_response.get_json()["agent_sources"]["recent_sessions"],
                    [{"id": f"{platform}-refreshed"}],
                )
                self.assertEqual(catalog_response.status_code, 200)
                self.assertEqual(
                    catalog_response.get_json()["recent_sessions"],
                    [{"id": f"{platform}-refreshed"}],
                )
                self.assertEqual(catalog_response.get_json()["cache"]["status"], "hit")
                self.assertEqual(bootstrap.call_count, 2)
                sources.assert_not_called()

    def test_agent_browser_session_refresh_does_not_retain_sources_after_readiness_fails(self) -> None:
        ready_status_payload = {
            "platform": "chatgpt",
            "browser": "edge",
            "browser_label": "Edge",
            "logged_in": True,
            "can_download": True,
            "account_name": "ChatGPT account",
            "message": "Ready",
        }
        unavailable_status_payload = {
            **ready_status_payload,
            "logged_in": False,
            "can_download": False,
            "message": "Sign in to ChatGPT in Edge.",
        }
        source_payload = {
            "platform": "chatgpt",
            "browser_label": "Edge",
            "recent_sessions": [{"id": "recent-1"}],
            "projects": [],
            "limit": 20,
        }
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with patch(
                "app.web.app.probe_and_collect_chatgpt_sources",
                side_effect=[
                    (ready_status_payload, source_payload),
                    (unavailable_status_payload, None),
                ],
            ) as bootstrap:
                with app.test_client() as client:
                    ready_response = client.get(
                        "/api/browser-session?platform=chatgpt&browser=edge&scope=agent"
                    )
                    refreshed_response = client.get(
                        "/api/browser-session?platform=chatgpt&browser=edge&scope=agent&refresh=1"
                    )

        self.assertEqual(ready_response.status_code, 200)
        self.assertIn("agent_sources", ready_response.get_json())
        self.assertEqual(refreshed_response.status_code, 200)
        self.assertFalse(refreshed_response.get_json()["can_download"])
        self.assertNotIn("agent_sources", refreshed_response.get_json())
        self.assertNotIn("agent_sources_error", refreshed_response.get_json())
        self.assertEqual(bootstrap.call_count, 2)

    def test_agent_provider_source_route_reuses_parquet_until_explicit_refresh(self) -> None:
        first_payload = {
            "platform": "gemini",
            "browser_label": "Edge",
            "recent_sessions": [{"id": "first-session"}],
            "projects": [],
            "limit": 20,
        }
        second_payload = {
            "platform": "gemini",
            "browser_label": "Edge",
            "recent_sessions": [{"id": "second-session"}],
            "projects": [],
            "limit": 20,
        }
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with patch("app.web.app.list_agent_sources", side_effect=[first_payload, second_payload]) as sources:
                with app.test_client() as client:
                    first_response = client.get("/api/agent/sources?platform=gemini&browser=edge")
                    cached_response = client.get("/api/agent/sources?platform=gemini&browser=edge")
                    refreshed_response = client.get(
                        "/api/agent/sources?platform=gemini&browser=edge&refresh=1"
                    )

        self.assertEqual(first_response.get_json()["recent_sessions"], [{"id": "first-session"}])
        self.assertEqual(first_response.get_json()["cache"]["status"], "miss")
        self.assertEqual(cached_response.get_json()["recent_sessions"], [{"id": "first-session"}])
        self.assertEqual(cached_response.get_json()["cache"]["status"], "hit")
        self.assertEqual(refreshed_response.get_json()["recent_sessions"], [{"id": "second-session"}])
        self.assertEqual(refreshed_response.get_json()["cache"]["status"], "refreshed")
        self.assertEqual(sources.call_count, 2)

    def test_agent_source_route_filters_a_persisted_gemini_creation_alias(self) -> None:
        cached_payload = {
            "platform": "gemini",
            "browser_label": "Edge",
            "recent_sessions": [],
            "projects": [
                {
                    "id": "create",
                    "title": "New notebook",
                    "url": "https://gemini.google.com/app/create",
                    "updated_at": "",
                },
                {
                    "id": "notebook-1",
                    "title": "Research notebook",
                    "url": "https://gemini.google.com/app/notebook-1",
                    "updated_at": "",
                },
            ],
            "limit": 20,
        }
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            app.extensions["agent_source_cache"].store(
                platform="gemini",
                browser="edge",
                source_kind="sources",
                payload=cached_payload,
            )
            with patch("app.web.app.list_agent_sources") as sources:
                with app.test_client() as client:
                    response = client.get(
                        "/api/agent/sources?platform=gemini&browser=edge"
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cache"]["status"], "hit")
        self.assertEqual(
            response.get_json()["projects"],
            [
                {
                    "id": "notebook-1",
                    "title": "Research notebook",
                    "url": "https://gemini.google.com/app/notebook-1",
                    "updated_at": "",
                }
            ],
        )
        sources.assert_not_called()

    def test_agent_project_route_reuses_one_project_session_contract(self) -> None:
        project_url = "https://grok.com/project/project-1?tab=conversations"
        payload = {
            "platform": "grok",
            "project_url": project_url,
            "sessions": [
                {
                    "id": "grok-session",
                    "title": "Grok project task",
                    "url": "https://grok.com/project/project-1?chat=grok-session",
                    "updated_at": "",
                }
            ],
            "limit": 20,
        }
        with TemporaryDirectory() as raw_root:
            app = create_app(Path(raw_root) / "local_store")
            with patch("app.web.app.list_agent_project_sessions", return_value=payload) as sessions:
                with app.test_client() as client:
                    response = client.get(
                        "/api/agent/project-sessions?platform=grok&browser=edge&project_url="
                        "https://grok.com/project/project-1?tab=conversations"
                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["sessions"], payload["sessions"])
        self.assertEqual(response.get_json()["cache"]["status"], "miss")
        sessions.assert_called_once()
        self.assertEqual(sessions.call_args.args[:3], ("grok", "edge", project_url))

    def test_agent_session_history_route_rejects_non_chatgpt_urls(self) -> None:
        app = create_app()

        with patch("app.web.app.fetch_chatgpt_conversation_history") as history:
            with app.test_client() as client:
                response = client.get(
                    "/api/agent/chatgpt-session-history?browser=edge&conversation_url=https://example.com/c/demo"
                )

        self.assertEqual(response.status_code, 400)
        history.assert_not_called()

    def test_agent_client_uses_computer_use_readiness_activity_and_chat_keyboard_contract(self) -> None:
        script = COMPUTER_USE_AGENT_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const hostOperatingSystem = runtime.host_operating_system || ""',
            'if (hostOperatingSystem && selectedOs() !== hostOperatingSystem)',
            'if (!runtime.ready)',
            'lastBrowserStatus.can_download',
            'requestJson("/api/agent/preferences"',
            'selectedValue(".agent-os-combobox", elements.promptOs?.value || "macos")',
            'const sessionSourceChoice = trigger.closest(".agent-session-mode-combobox")',
            'trigger.disabled = !sessionSourceChoice',
            'event.key !== "Enter" || event.shiftKey || event.isComposing',
            "promptForm.requestSubmit()",
            "renderActivity(agent.activity, running)",
            "function renderErrorRecord(agent)",
            "errorRecordContent.textContent = errorText",
            "elements.errorRecord.hidden = !errorText",
            "renderAgentResponse(agent)",
            "renderTerminalExecution(lastPayload.runtime)",
            "function formatAgentPhase(phase)",
            "function agentReadinessCopy(phase, message)",
            "function setAgentReadiness(phase, message)",
            "setAgentReadiness(phase, readiness.message)",
            "elements.readiness.dataset.phase",
            'elements.responseAnswer.innerHTML = entry?.response_html || ""',
            "buildAgentPaginationItems(totalPages, responseHistoryPage)",
            "function buildAgentPaginationRanges(firstPage, lastPage, chunkSize = 5)",
            "createAgentPaginationRangePicker(item, pagination)",
            "bindAgentPaginationRangeInteractions()",
            "agentPaginationRangeFocusRestore",
            'data-pagination-range-trigger',
            'data-pagination-range-menu',
            "paginationMotion?.capturePaginationAnimation(",
            "bindCompletedAgentSession(agent, completedTransition)",
            "function agentSnapshotMatchesSelection(agent)",
            "const persistedAgent = lastPayload.agent || {};",
            "running || agentSnapshotMatchesSelection(persistedAgent)",
            "function applyAgentSources(payload)",
            "lastBrowserStatus?.agent_sources",
            "lastBrowserStatus?.agent_sources_error",
            'let appliedBootstrapSignature = ""',
            "bootstrapSignature !== appliedBootstrapSignature",
            "sourceRequestId += 1",
            'const BOOTSTRAPPED_SOURCE_PLATFORMS = new Set(["chatgpt", "grok", "claude"])',
            "loadSelectedSessionHistory(input.value)",
            "/api/agent/chatgpt-session-history?",
            "Loading the selected ChatGPT session history…",
            'statusMessageCopy: document.querySelector("[data-agent-empty-response-copy]")',
            'statusSpinner: document.querySelector("[data-agent-session-history-spinner]")',
            "elements.statusSpinner.hidden = !remoteSessionHistoryLoading",
            "remoteHistoryMatchesSelection()",
            "sessionTitleOverride = option.dataset.agentComboboxLabel || \"\"",
            "elements.activityList.scrollTop = elements.activityList.scrollHeight",
            "elements.responseOutput.hidden = !entry",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn("MCP runtime", script)
        self.assertNotIn("agent_phase_chip", script)

    def test_agent_settings_client_owns_host_detection_and_terminal_authorization(self) -> None:
        script = AGENT_SETTINGS_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.querySelector("[data-agent-settings-operating-system]")',
            'document.querySelector("[data-agent-terminal-authorization-button]")',
            'document.querySelector("[data-agent-terminal-authorization-status]")',
            'operatingSystem.dataset.agentHostOperatingSystem',
            'operatingSystem.dispatchEvent(new Event("change", {bubbles: true}))',
            'fetch("/api/agent/terminal-authorization"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_chatgpt_cache_navigation_ignores_retired_agent_platform_query(self) -> None:
        app = create_app()

        with app.test_client() as client:
            response = client.get("/cache/chatgpt?agent_platform=gemini")
            agent_response = client.get("/agent", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Set-Cookie", response.headers)
        agent_body = agent_response.get_data(as_text=True)
        self.assertIn('name="operating_system" value="macos"', agent_body)
        self.assertNotIn("Gemini Agent", agent_body)

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

    def test_shadow_backup_sync_redirects_back_to_cloud_category(self) -> None:
        app = create_app()
        shadow_backup_service = app.extensions["shadow_backup_service"]

        with patch.object(shadow_backup_service, "start") as start_sync:
            with app.test_client() as client:
                response = client.post("/settings/shadow-backup/sync")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/settings#settings-cloud")
        start_sync.assert_called_once()

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
        self.assertIn("<h2>Configuration center</h2>", body)
        self.assertEqual(body.count('class="workspace-kicker"'), 0)
        self.assertIn(
            'settings-navigation.js?v=settings-navigation-v1.1.1-codex.1',
            body,
        )
        self.assertIn('id="settings_form"', body)
        settings_form_start = body.index('id="settings_form"')
        settings_form_end = body.index("</form>", settings_form_start)
        self.assertGreater(settings_form_end, settings_form_start)
        for category in ("downloads", "chatgpt", "agent", "cloud", "maintenance"):
            with self.subTest(category=category):
                self.assertIn(f'data-settings-category="{category}"', body)
                self.assertIn(f'data-settings-panel="{category}"', body)
                self.assertIn(f'id="settings-{category}"', body)

        script = SETTINGS_NAVIGATION_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'window.addEventListener("hashchange"',
            'link.setAttribute("aria-current", "page")',
            "panel.hidden = !isActive;",
            'window.CACHELIKES_RESPONSIVE.media("sidebarOverlayMax").matches',
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
            "AbortController",
            "/api/settings/directory/validate",
            "The folder picker did not respond. You can type the path directly.",
        ):
            with self.subTest(directory_picker_fragment=fragment):
                self.assertIn(fragment, directory_picker_script)

    def test_computer_use_settings_live_in_the_agent_category_and_persist(self) -> None:
        with patch(
            "app.core.computer_use_agent.load_computer_use_settings",
            return_value=ComputerUseSettings(),
        ):
            app = create_app()
            with patch("app.web.app.save_config"), patch(
                "app.core.computer_use_agent.save_computer_use_settings"
            ) as save_computer_use_settings:
                with app.test_client() as client:
                    settings_response = client.get("/settings")
                    save_response = client.post(
                        "/settings",
                        data={
                            "agent_operating_system": "macos",
                            "agent_context_limit_mib": "64",
                            "agent_max_turns": "50",
                            "agent_command_timeout_seconds": "240",
                            "agent_macos_system_prompt": "macOS controller prompt with bodycheck",
                            "agent_windows_system_prompt": "Windows PowerShell controller prompt",
                        },
                    )

        settings_body = settings_response.get_data(as_text=True)
        self.assertEqual(settings_response.status_code, 200)
        self.assertIn('data-settings-category="agent"', settings_body)
        self.assertIn('data-settings-panel="agent"', settings_body)
        self.assertIn('id="settings-agent"', settings_body)
        self.assertIn('name="agent_operating_system"', settings_body)
        self.assertIn('data-agent-settings-operating-system', settings_body)
        self.assertIn('data-agent-terminal-authorization-button', settings_body)
        self.assertIn('data-agent-terminal-authorization-status', settings_body)
        self.assertIn('agent-settings.js?v=agent-settings-v1.0.0-codex.1', settings_body)
        self.assertIn('name="agent_context_limit_mib"', settings_body)
        self.assertIn('name="agent_max_turns"', settings_body)
        self.assertIn('name="agent_command_timeout_seconds"', settings_body)
        self.assertIn('name="agent_macos_system_prompt"', settings_body)
        self.assertIn('name="agent_windows_system_prompt"', settings_body)
        self.assertIn("Computer Use Agent", settings_body)
        self.assertIn("2 million tokens", settings_body)
        self.assertNotIn("Public HTTPS origin", settings_body)
        self.assertNotIn('name="port"', settings_body)
        self.assertEqual(save_response.status_code, 302)
        save_computer_use_settings.assert_called_once()
        saved_agent_settings = save_computer_use_settings.call_args.args[0]
        self.assertEqual(saved_agent_settings.context_limit_mib, 64)
        self.assertEqual(saved_agent_settings.max_turns, 50)
        self.assertEqual(saved_agent_settings.command_timeout_seconds, 240)

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
            "targetUrl.href === window.location.href",
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
            "if (totalPages <= 1) return [];",
            'items.push({ kind: "previous", page: startPage - 1 })',
            'items.push({ kind: "ellipsis" })',
            'button.className = `local-store-page-button',
            'indicator.className = "local-store-pagination-indicator"',
            "function positionRecentEventsPaginationIndicator({ immediate = false } = {})",
            "paginationMotion.positionPaginationIndicator(",
            "paginationMotion?.capturePaginationAnimation(",
            "paginationMotion.animatePaginationIndicator(",
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

    def test_pagination_motion_reuses_capture_and_replay_animation_pattern(self) -> None:
        script = PAGINATION_MOTION_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            "function capturePaginationAnimation(",
            "function animatePaginationIndicator(",
            'indicator.style.transition = "none";',
            "void indicator.offsetWidth;",
            "window.requestAnimationFrame(() => {",
            'pagination.classList.add("is-animated", "is-animating");',
            "getPaginationMotionDurationMs(pagination)",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_recent_events_pagination_hides_when_only_one_page_is_available(self) -> None:
        script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")

        expected_fragments = (
            "function buildRecentEventsPaginationState(totalPages, currentPage)",
            "const shouldRender = normalizedTotalPages > 1;",
            "recentEventsPagination.hidden = !paginationState.shouldRender;",
            "recentEventsPagination.replaceChildren();",
            'recentEventsPagination.style.removeProperty("--local-store-pagination-slots");',
            'recentEventsPagination.classList.remove("is-animated");',
        )

        for fragment in expected_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

    def test_browser_pagination_surfaces_share_the_single_rendering_macro(self) -> None:
        browser_template = BROWSER_TEMPLATE_PATH.read_text(encoding="utf-8")
        pagination_template = PAGINATION_TEMPLATE_PATH.read_text(encoding="utf-8")

        self.assertIn('{% from "_pagination.html" import render_browser_pagination %}', browser_template)
        self.assertIn("render_browser_pagination(", browser_template)
        self.assertIn("{% if pagination_items %}", pagination_template)
        self.assertIn("local-store-pagination--floating is-animated", pagination_template)
        self.assertNotIn('media_page.total_pages > 1', browser_template)
        self.assertNotIn('text_page.total_pages > 1', browser_template)

    def test_cache_status_polling_preserves_optimistic_content_and_avoids_repeated_rendering(self) -> None:
        script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        template = CACHE_PAGE_TEMPLATE_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const statusPollIntervalMs = 3_000;',
            'if (nextSignature === recentEventsSignature) return;',
            'if (nextSignature === lastRenderedStatusSignature && !statusRefreshFailed) return;',
            'if (!statusUrl || statusRefreshInFlight || document.hidden) return;',
            'document.addEventListener("visibilitychange", handleVisibilityChange);',
            'scheduleStatusRefresh();',
            'const datetimeFormatter = new Intl.DateTimeFormat("en-GB",',
            'if (element.dataset.statusFormat === "datetime")',
            'formatDatetime(rawValue)',
            'function formatRecentEvent(eventText)',
            'formatRecentEvent(eventText)',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn("window.setInterval(refreshStatus", script)
        self.assertNotIn("\n    refreshStatus();\n", script)
        self.assertEqual(template.count('data-status-format="datetime"'), 2)
        self.assertIn("format_datetime_label(snapshot.started_at)", template)
        self.assertIn("format_datetime_label(snapshot.finished_at)", template)

    def test_browser_status_uses_stale_while_revalidate_without_duplicate_probes(self) -> None:
        script = BROWSER_SESSION_STATUS_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const SESSION_CACHE_TTL_MS = 300_000;',
            'const SESSION_STALE_MAX_AGE_MS = 1_800_000;',
            'const statusRequests = new Map();',
            'function requestBrowserStatus(platform, browserId, scope, options = {})',
            'const refresh = options.refresh === true;',
            'const requestKey = `${requestScope}:${platform}:${browserId}:${refresh ? "refresh" : "default"}`;',
            'if (refresh) query.set("refresh", "1");',
            'async function load(browserId, options = {})',
            'const forceRefresh = options.force === true;',
            'requestBrowserStatus(requestPlatform, activeBrowser, scope, {refresh: forceRefresh})',
            'let statusRequestRevision = 0;',
            'requestRevision !== statusRequestRevision',
            'setStatus(cachedStatus.payload, activeBrowser);',
            'if (cachedStatus.payload.can_download && cachedStatus.ageMs < SESSION_CACHE_TTL_MS) return;',
            'setRefreshingState(activeBrowser);',
            'return load(activeBrowser, {force: true});',
            'if (statusRequests.has(requestKey)) return statusRequests.get(requestKey);',
            'statusCard.setAttribute("aria-busy", "true");',
            'showStatusCheckmark(isReady ? "ready" : "error");',
            'function hideStatusCheckmark()',
            'if (statusSpinner) statusSpinner.hidden = false;',
            'activeBrowser !== browserId\n                    || platform !== requestPlatform\n                    || requestRevision !== statusRequestRevision',
            'const hideReadyMessage = statusCard?.dataset.browserSessionHideReadyMessage === "true";',
            'statusMessage.hidden = (hideReadyMessage && isReady) || !payload.message;',
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

    def test_browser_search_lives_in_heading_and_exposes_local_recommendations(self) -> None:
        app = create_app()

        with app.test_client() as client:
            body = client.get("/browser?view=text&source=all&sort=newest&session_view=1").get_data(
                as_text=True
            )

        self.assertEqual(body.count('name="q"'), 1)
        self.assertIn('id="browser_filter_form"', body)
        self.assertIn('form="browser_filter_form"', body)
        self.assertGreater(body.index("data-browser-search"), body.index("</aside>"))
        self.assertIn("browser-search.css?v=browser-search-v1.3.5-codex.1", body)
        self.assertIn('type="module"', body)
        self.assertIn("browser-search.js?v=browser-search-v2.0.2-codex.1", body)
        self.assertIn("browser-session-messages.js?v=browser-session-messages-v1.0.1-codex.1", body)
        self.assertIn("browser-filter-select.js?v=browser-filter-select-v1.0.0-codex.1", body)
        self.assertIn("data-browser-local-resources-header-actions", body)
        self.assertIn('class="icon browser-search-icon"', body)
        self.assertIn('placeholder="Search cached text"', body)
        self.assertNotIn("<span>Search</span>", body)

        search_script = BROWSER_SEARCH_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'const storageKey = "cachelikes:browser-search-history:v1";',
            'import Fuse from "./vendor/fuse.min.mjs?v=fuse-js-v7.3.0";',
            "includeMatches: true",
            "tokenMatch: \"all\"",
            "useTokenSearch: true",
            "const fuzzyScoreThreshold = 0.2;",
            "function appendHighlightedText",
            'event.key === "ArrowDown"',
            'event.key === "Enter"',
            "function submitSearch",
            "submitSearch();",
            "form.requestSubmit();",
            "function parseServerCandidates",
            "function findLiteralMatches",
            "const literalMatches = findLiteralMatches(candidates, queryText);",
            'input.dataset.browserSearchGlobalScope === "true"',
            'sessionField.disabled = true;',
        ):
            with self.subTest(search_script_fragment=fragment):
                self.assertIn(fragment, search_script)
        self.assertIn(
            '".browser-media-card-title, .browser-session-table-title, .browser-chat-message-title"',
            search_script,
        )

        filter_select_script = BROWSER_FILTER_SELECT_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'document.querySelectorAll(".browser-filter-form select.form-select")',
            'aria-haspopup", "listbox"',
            'className = "trade-strategy-dropdown browser-filter-select-dropdown"',
            'select.dispatchEvent(new Event("change", {bubbles: true}))',
            'event.key === "ArrowDown"',
            'event.key === "Escape"',
        ):
            with self.subTest(filter_select_script_fragment=fragment):
                self.assertIn(fragment, filter_select_script)

        search_style = BROWSER_SEARCH_STYLE_PATH.read_text(encoding="utf-8")
        self.assertIn(".browser-content-card {", search_style)
        self.assertIn("min-width: 0;", search_style)
        controls_layer_start = search_style.index(
            ".browser-session-controls-row:has(.browser-session-control-button:hover, .browser-session-control-button:focus-visible) {"
        )
        controls_layer_rule = search_style[
            controls_layer_start:search_style.index("\n}", controls_layer_start)
        ]
        self.assertIn("position: relative;", controls_layer_rule)
        self.assertIn("z-index: var(--layer-global-popover);", controls_layer_rule)
        self.assertIn(".browser-filter-select-dropdown .trade-strategy-dropdown-option {", search_style)
        self.assertIn("grid-template-columns: 16px minmax(0, 1fr);", search_style)
        self.assertIn(".browser-heading-copy {", search_style)
        for fragment in (
            "display: flex;",
            "align-items: center;",
            "min-height: var(--workspace-title-rail-control-height);",
        ):
            with self.subTest(heading_copy_fragment=fragment):
                self.assertIn(fragment, search_style)
        self.assertIn(".browser-heading-tools {", search_style)
        for fragment in (
            "display: flex;",
            "flex: 0 1 322px;",
            "width: min(322px, 34vw);",
            "border: 1px solid var(--theme-glass-border);",
            "background: var(--liquid-glass-background);",
            "background: var(--frosted-glass-opaque-background, var(--glass-popover-background));",
            "background-clip: padding-box;",
            ".browser-search-control:focus-within {",
            "box-shadow: var(--glass-chip-shadow-hover);",
            "min-height: 32px;",
            "padding-block: 2px;",
            ".browser-summary-card .browser-heading-tools .browser-session-actions {",
            "transform: translateX(2px);",
            "@media (min-width: 901px)",
            ".browser-session-detail-actions--session {",
            "flex-wrap: nowrap;",
            ".browser-session-detail-actions--session > .browser-search-field {",
            "--browser-session-search-input-inline-size: 256px;",
            "flex: 0 1 calc(var(--browser-session-search-input-inline-size) + 2px);",
            "width: min(calc(var(--browser-session-search-input-inline-size) + 2px), 100%);",
            ".browser-search-input::placeholder {",
        ):
            with self.subTest(search_style_fragment=fragment):
                self.assertIn(fragment, search_style)
        self.assertIn(".browser-local-resources-header-actions {", search_style)
        self.assertIn('mask: url("/static/images/magnifyingglass.svg") center/contain no-repeat;', search_style)
        self.assertIn("justify-content: flex-end;", search_style)
        self.assertIn(".browser-search-suggestion.is-active", search_style)
        self.assertIn(".browser-search-match", search_style)
        self.assertLess(FUSE_ASSET_PATH.stat().st_size, 1_000_000)
        self.assertIn("Fuse.js v7.3.0", FUSE_ASSET_PATH.read_text(encoding="utf-8")[:240])
        self.assertIn('viewBox="0 0 24.7656 24.6387"', MAGNIFYING_GLASS_ASSET_PATH.read_text(encoding="utf-8"))

        session_message_script = BROWSER_SESSION_MESSAGES_SCRIPT_PATH.read_text(encoding="utf-8")
        for fragment in (
            'document.querySelectorAll("[data-browser-session-message-toggle]")',
            'button.closest(".browser-session-table-message-shell")',
            'shell.classList.toggle("is-expanded", nextExpanded);',
            "source.scrollHeight > source.clientHeight + 1",
        ):
            with self.subTest(session_message_script_fragment=fragment):
                self.assertIn(fragment, session_message_script)

    def test_browser_text_search_leaves_session_scope_and_lists_global_cjk_match(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            history_path = root / "llm" / "gemini" / "history.parquet"
            write_parquet_rows_atomic(
                history_path,
                [
                    {
                        "schema_version": 1,
                        "platform": "gemini",
                        "conversation_id": "selected",
                        "conversation_url": "https://gemini.google.com/app/selected",
                        "conversation_title": "Selected session",
                        "message_key": "selected:0",
                        "turn_index": 0,
                        "message_index": 0,
                        "role": "user",
                        "author_label": "You",
                        "content_text": "Current session message",
                        "content_html": "",
                        "content_sha256": "selected-hash",
                        "source_links": [],
                        "model_label": "",
                        "first_seen_at": "2026-08-12T05:00:00Z",
                        "last_seen_at": "2026-08-12T05:00:00Z",
                    },
                    {
                        "schema_version": 1,
                        "platform": "gemini",
                        "conversation_id": "atour",
                        "conversation_url": "https://gemini.google.com/app/atour",
                        "conversation_title": "亚朵星球：体验驱动的睡眠专家",
                        "message_key": "atour:0",
                        "turn_index": 0,
                        "message_index": 0,
                        "role": "assistant",
                        "author_label": "Gemini",
                        "content_text": "A matching message in another session",
                        "content_html": "",
                        "content_sha256": "atour-hash",
                        "source_links": [],
                        "model_label": "",
                        "first_seen_at": "2026-08-11T05:00:00Z",
                        "last_seen_at": "2026-08-11T05:00:00Z",
                    },
                ],
                GEMINI_HISTORY_SCHEMA,
            )
            app = create_app(root)
            session_id = query_chat_history(root, source="gemini", session_view=True).sessions[0].stable_id
            with app.test_client() as client:
                response = client.get(
                    f"/browser?view=text&source=gemini&sort=newest&session_view=1&session={session_id}&q=亚朵"
                )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("亚朵星球：体验驱动的睡眠专家", body)
        self.assertIn("browser-session-index-table", body)
        self.assertNotIn("browser-session-detail-actions--session", body)
        self.assertNotIn('name="session" value=', body)
        self.assertNotIn('data-chat-message-id=', body)
        self.assertIn('data-browser-search-global-scope="true"', body)
        self.assertIn('data-browser-search-submit-copy="Press Enter to search all cached text."', body)

    def test_browser_page_and_secure_media_route_use_isolated_cache(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            image_path = root / "x" / "demo" / "image.jpg"
            video_path = root / "media" / "grok" / "clip.mp4"
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
            link_path = root / "media" / "grok" / "outside.mp4"
            try:
                link_path.symlink_to(outside_path)
            except OSError as exc:
                self.skipTest(f"symlinks are unavailable: {exc}")

            app = create_app(root)
            with app.test_client() as client:
                browser_response = client.get("/browser?view=media")
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
            self.assertIn("/browser/media/grok/clip.mp4", body)
            self.assertNotIn("/browser/media/media/", body)
            self.assertIn("style-v2.90.1-codex.9", body)
            self.assertIn("/static/images/photo.stack.svg", body)
            self.assertIn('pagination-motion.js?v=pagination-motion-v1.1.0-codex.1', body)
            self.assertIn('local-media-browser.js?v=local-media-browser-v1.31.1-codex.1', body)
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

    def test_browser_content_mode_switches_to_cached_text_and_points_to_media(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            history_path = root / "llm" / "gemini" / "history.parquet"
            conversation_url = "https://gemini.google.com/app/demo"
            write_parquet_rows_atomic(
                history_path,
                [
                    {
                        "schema_version": 1,
                        "platform": "gemini",
                        "conversation_id": "demo",
                        "conversation_url": conversation_url,
                        "conversation_title": "Demo conversation",
                        "message_key": "demo:0:user",
                        "turn_index": 0,
                        "message_index": 0,
                        "role": "user",
                        "author_label": "You",
                        "content_text": "A cached text message",
                        "content_html": "<p><strong>Rich</strong> cached text message</p>",
                        "content_sha256": "hash",
                        "source_links": [],
                        "model_label": "",
                        "first_seen_at": "2026-08-12T05:00:00Z",
                        "last_seen_at": "2026-08-12T05:00:00Z",
                    },
                    {
                        "schema_version": 1,
                        "platform": "gemini",
                        "conversation_id": "demo",
                        "conversation_url": conversation_url,
                        "conversation_title": "Demo conversation",
                        "message_key": "demo:0:assistant",
                        "turn_index": 0,
                        "message_index": 1,
                        "role": "assistant",
                        "author_label": "Gemini",
                        "content_text": '{"size":"1024x1792","n":1}',
                        "content_html": "",
                        "content_sha256": "hash-image",
                        "source_links": [],
                        "model_label": "",
                        "first_seen_at": "2026-08-12T05:00:01Z",
                        "last_seen_at": "2026-08-12T05:00:01Z",
                    },
                ],
                GEMINI_HISTORY_SCHEMA,
            )
            media_path = root / "media" / "chatgpt" / "Demo" / "image.png"
            media_path.parent.mkdir(parents=True)
            media_path.write_bytes(b"image")
            (media_path.parent / ".chatgpt_catalog.json").write_text(
                json.dumps(
                    {
                        "entries": {
                            "file-demo": {
                                "file_id": "file-demo",
                                "relative_path": "image.png",
                                "conversation_url": conversation_url,
                                "conversation_title": "Demo conversation",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            app = create_app(root)
            with app.test_client() as client:
                text_response = client.get("/browser?source=gemini&view=text&session_view=1&sort=newest")
                session_id = query_chat_history(root, source="gemini", session_view=True).sessions[0].stable_id
                detail_response = client.get(
                    f"/browser?source=gemini&view=text&session_view=1&sort=newest&session={session_id}"
                )
                filtered_detail_response = client.get(
                    f"/browser?source=gemini&view=text&session_view=1&sort=newest&session={session_id}&q=Rich"
                )
                empty_detail_response = client.get(
                    f"/browser?source=gemini&view=text&session_view=1&sort=newest&session={session_id}&q=missing"
                )
                export_response = client.get(
                    f"/browser/session/{session_id}/export?source=gemini&sort=newest"
                )
                page_export_response = client.get(
                    f"/browser/session/{session_id}/export?source=gemini&sort=newest&page=1&scope=page"
                )
                media_response = client.get("/browser?view=media&media_id=media-placeholder")

        text_body = text_response.get_data(as_text=True)
        detail_body = detail_response.get_data(as_text=True)
        filtered_detail_body = filtered_detail_response.get_data(as_text=True)
        empty_detail_body = empty_detail_response.get_data(as_text=True)
        media_body = media_response.get_data(as_text=True)
        self.assertEqual(text_response.status_code, 200)
        self.assertIn('name="view" type="radio" value="text" checked', text_body)
        self.assertIn("Cached text browser", text_body)
        self.assertIn('browser-session-table', text_body)
        self.assertIn('browser-text-summary-card', text_body)
        self.assertNotIn("browser-session-detail-actions--session", text_body)
        self.assertIn("browser-session-detail-actions--session", detail_body)
        browser_template = BROWSER_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn('class="workspace-header browser-workspace-header workspace-mobile-summary-shell" data-mobile-summary-fixed', browser_template)
        self.assertIn('class="report-card workspace-content-card browser-content-card', browser_template)
        self.assertIn('class="browser-content-toolbar"', browser_template)
        self.assertIn('class="browser-session-table-number"', browser_template)
        self.assertIn('class="browser-chat-role-mark"', browser_template)
        self.assertIn('aria-label="Cached Gemini sessions"', text_body)
        self.assertIn("Session", text_body)
        self.assertIn("Session name", text_body)
        self.assertIn(">No.</th>", text_body)
        self.assertIn("Messages", text_body)
        self.assertIn("browser-session-source-mark", text_body)
        self.assertIn("Google_Gemini_logo_2025_symbol.svg", text_body)
        self.assertIn("browser-session-table-updated-link", text_body)
        self.assertIn('href="https://gemini.google.com/app/demo"', text_body)
        self.assertIn("/browser?view=text&amp;source=gemini", text_body)
        self.assertIn("browser-session-index-table", text_body)
        self.assertIn("session_page=1", text_body)
        self.assertIn("Back to all sessions", browser_template)
        self.assertIn("browser-session-neighbor-nav", browser_template)
        self.assertIn("browser-local-resources-header-actions", browser_template)
        self.assertIn("data-browser-session-message-toggle", browser_template)
        self.assertIn("browser-session-table-message-shell", browser_template)
        self.assertIn(
            'format_chat_message_timestamp_label(message.last_seen_at)',
            browser_template,
        )
        self.assertIn("No matching messages found.", browser_template)
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("<strong>Rich</strong> cached text message", detail_body)
        self.assertEqual(filtered_detail_response.status_code, 200)
        self.assertIn("Demo conversation", filtered_detail_body)
        self.assertIn("browser-session-index-table", filtered_detail_body)
        self.assertNotIn("browser-session-detail-actions--session", filtered_detail_body)
        self.assertNotIn("<strong>Rich</strong> cached text message", filtered_detail_body)
        self.assertEqual(filtered_detail_body.count('data-chat-message-id='), 0)
        self.assertEqual(empty_detail_response.status_code, 200)
        self.assertIn("No text messages match these filters.", empty_detail_body)
        self.assertNotIn("<strong>Rich</strong> cached text message", empty_detail_body)
        self.assertIn("browser-session-message-toggle", detail_body)
        self.assertIn("browser-session-actions", detail_body)
        self.assertNotIn('<p class="workspace-kicker">Session</p>', detail_body)
        self.assertNotIn('class="browser-session-detail-summary"', detail_body)
        self.assertIn("browser-session-actions-trigger", detail_body)
        self.assertIn('class="icon browser-session-safari-icon"', detail_body)
        self.assertNotIn("browser.safari.png", detail_body)
        self.assertIn("Open original in Safari", detail_body)
        self.assertIn("Export Markdown", detail_body)
        self.assertIn("Refresh current page", detail_body)
        self.assertIn("Export current page results", detail_body)
        self.assertIn("browser-session-drawer-refresh-icon", detail_body)
        self.assertIn("data-browser-session-refresh-url", detail_body)
        self.assertIn("scope=page", detail_body)
        self.assertIn("browser-session-actions.js?v=browser-session-actions-v1.1.0-codex.1", detail_body)
        self.assertEqual(export_response.status_code, 200)
        self.assertEqual(export_response.mimetype, "text/markdown")
        self.assertIn('attachment; filename="Demo_conversation.md"', export_response.headers["Content-Disposition"])
        self.assertIn("# Demo conversation", export_response.get_data(as_text=True))
        self.assertEqual(page_export_response.status_code, 200)
        self.assertEqual(page_export_response.mimetype, "text/markdown")
        self.assertIn('attachment; filename="Demo_conversation_page_1.md"', page_export_response.headers["Content-Disposition"])
        self.assertIn("- Messages: 2", page_export_response.get_data(as_text=True))
        self.assertIn('class="browser-media-preview"', detail_body)
        self.assertIn('target="_blank"', detail_body)
        self.assertIn('/browser/media/chatgpt/Demo/image.png', detail_body)
        self.assertNotIn("Related media:", detail_body)
        self.assertNotIn('{"size":"1024x1792","n":1}', detail_body)
        self.assertNotIn("Open conversation", text_body)
        self.assertNotIn("Cached text conversations", text_body)
        self.assertNotIn("view=media&amp;media_id=media-", text_body)
        self.assertNotIn('class="browser-gallery"', text_body)
        self.assertEqual(media_response.status_code, 200)
        self.assertIn('name="view" type="radio" value="media" checked', media_body)
        self.assertNotIn('class="browser-pagination', text_body)
        self.assertNotIn('class="browser-pagination', media_body)

    def test_browser_pagination_ellipses_render_accessible_range_menus(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            app = create_app(root)
            media_page = LocalMediaPage(
                items=(),
                total_count=24 * 457,
                image_count=24 * 457,
                video_count=0,
                current_page=53,
                total_pages=457,
            )
            with (
                patch.object(LocalMediaCatalog, "snapshot", return_value=(object(),)),
                patch.object(LocalMediaCatalog, "query", return_value=media_page),
                app.test_client() as client,
            ):
                response = client.get("/browser?view=media&source=x&page=53")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-pagination-ellipsis="leading"', body)
        self.assertIn('data-pagination-ellipsis="trailing"', body)
        self.assertIn('aria-label="Show earlier pages"', body)
        self.assertIn('aria-label="Show later pages"', body)
        self.assertIn('role="menuitem"', body)
        self.assertIn('data-pagination-range-start="1"', body)
        self.assertIn('>1-5</a>', body)
        self.assertIn('>46-50</a>', body)
        self.assertIn('>56-60</a>', body)
        self.assertIn('>446-450</a>', body)
        self.assertIn('>451-457</a>', body)

    def test_browser_card_uses_filename_metadata_and_binary_size_units(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            media_path = root / "media" / "chatgpt" / "demo-project" / "img_file.png"
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
                response = client.get("/browser?view=media&source=chatgpt")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("browser-media-card-topline", body)
        self.assertNotIn("browser-source-chip", body)
        self.assertNotIn("browser-media-type", body)
        self.assertIn('class="browser-media-card-title" title="img_file.png">img_file.png</span>', body)
        self.assertNotIn("browser-media-card-description", body)
        self.assertNotIn("Session name:</dt>", body)
        self.assertIn("foundation-metric-card", body)
        self.assertIn("Created on:</dt><dd>09/08/2026 15:09:50 (HKT)</dd>", body)
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
            project_dir = root / "media" / "chatgpt" / "demo-project"
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
                first_response = client.get("/browser?view=media&source=chatgpt&sort=oldest&page=1")
                second_response = client.get("/browser?view=media&source=chatgpt&sort=oldest&page=2")
                chronological_response = client.get(
                    "/browser?view=media&source=chatgpt&sort=newest&session_view=0&page=1"
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
        self.assertIn('data-chatgpt-session-label="Newest session"', first_body)
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
        pagination_template = PAGINATION_TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn("session_view=('1' if filters.session_view else '0')", pagination_template)

        chronological_positions = [
            chronological_body.index(filename)
            for filename in ("new-latest.png", "older-session.png", "new-old.png")
        ]
        self.assertEqual(chronological_positions, sorted(chronological_positions))

    def test_legacy_gemini_browser_url_falls_back_to_chatgpt_media_sessions(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            project_dir = root / "media" / "chatgpt" / "demo-project"
            project_dir.mkdir(parents=True)
            for filename in ("new-session.png", "older-session.png"):
                (project_dir / filename).write_bytes(filename.encode("utf-8"))
            (project_dir / ".chatgpt_catalog.json").write_text(
                json.dumps(
                    {
                        "entries": {
                            "file-new": {
                                "file_id": "file-new",
                                "relative_path": "new-session.png",
                                "conversation_url": "https://chatgpt.com/c/new-session",
                                "conversation_title": "Newest session",
                                "created_at": "2026-08-10T09:00:00Z",
                            },
                            "file-old": {
                                "file_id": "file-old",
                                "relative_path": "older-session.png",
                                "conversation_url": "https://chatgpt.com/c/older-session",
                                "conversation_title": "Older session",
                                "created_at": "2026-08-09T09:00:00Z",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            app = create_app(root)
            with app.test_client() as client:
                response = client.get("/browser?view=media&source=gemini&q=&sort=newest&session_view=1")

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="view" type="radio" value="media" checked', body)
        self.assertIn("Cached media browser", body)
        self.assertIn('data-browser-source-filter-selected-label>ChatGPT</span>', body)
        self.assertIn('aria-label="ChatGPT sessions"', body)
        self.assertIn("1 / 2", body)

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
        rendered = str(render_prompt_markdown("**Safe** <script>alert('x')</script> 简体中文"))

        self.assertIn("<strong>Safe</strong>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("简体中文", rendered)
        self.assertNotIn("簡體中文", rendered)

    def test_prompt_markdown_renderer_supports_chatgpt_gfm_blocks(self) -> None:
        rendered = str(
            render_prompt_markdown(
                "| Check | Result |\n| --- | --- |\n| Font | **Pass** |\n\n~~old~~"
            )
        )

        self.assertIn("<table>", rendered)
        self.assertIn("<th>Check</th>", rendered)
        self.assertIn("<strong>Pass</strong>", rendered)
        self.assertIn("<s>old</s>", rendered)

    def test_cached_message_renderer_preserves_sanitized_rich_text(self) -> None:
        rendered = str(
            render_cached_message(
                "Fallback **text**",
                '<div><h3>Heading</h3><ol><li><b>Bold</b></li></ol>'
                '<script>alert(1)</script><a href="javascript:alert(2)">Unsafe</a>'
                '<a href="https://example.com">Safe link</a></div>',
            )
        )

        self.assertIn("<h3>Heading</h3>", rendered)
        self.assertIn("<ol><li><b>Bold</b></li></ol>", rendered)
        self.assertNotIn("alert", rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertIn('href="https://example.com"', rendered)

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

    def test_browser_pagination_range_menu_scrolls_only_when_content_overflows(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const naturalMenuHeight = paginationRangeMenuContentHeight(menu);',
            'menu.classList.toggle("is-scrollable", naturalMenuHeight > menu.clientHeight + 1);',
            'menu?.classList.remove("is-scrollable");',
        ):
            self.assertIn(fragment, script)

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

    def test_browser_prompt_remarks_script_supports_persisted_tags(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const promptRemarkRemoveButtons = Array.from(document.querySelectorAll("[data-prompt-remark-remove]"));',
            'const datalist = document.querySelector("[data-prompt-remark-options]");',
            'function updatePromptRemarkOptions(options)',
            'function renderPromptRemarks(root, remarks)',
            'method: "POST"',
            'method: "DELETE"',
            'encodeURIComponent(promptId)',
            'if (event.key !== "Enter" || event.isComposing) return;',
            'const root = input.closest("[data-prompt-remarks]");',
            'addPromptRemark(root, input.value.trim());',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        self.assertNotIn("[data-prompt-remark-add]", script)

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

    def test_browser_content_mode_defaults_to_text_and_remembers_the_blue_segment(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const contentModeStorageKey = "cachelikes:browser-content-mode:v1";',
            'window.sessionStorage.getItem(contentModeStorageKey)',
            'window.sessionStorage.setItem(contentModeStorageKey, mode);',
            'if (!currentUrl.searchParams.has("view") && rememberedContentMode)',
            'const checkedContentMode = contentModeInputs.find((input) => input.checked)?.value || "text";',
            'rememberContentMode(event.target.value);',
            'function navigateToContentMode(mode) {',
            'const contentModeNavigationTitles = Object.freeze({',
            'function renderOptimisticContentModeNavigation(mode) {',
            'const formData = new FormData(filterForm);',
            'formData.set("view", mode);',
            'workspace.dataset.browserNavigationSkeleton = "1";',
            'document.documentElement.setAttribute("aria-busy", "true");',
            'const fallbackTimer = window.setTimeout(commitNavigation, 120);',
            'window.requestAnimationFrame(() => {',
            'window.location.assign(targetUrl.toString());',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        from app.core.local_media_browser import normalize_browser_filters

        self.assertEqual(normalize_browser_filters(source="all")["view"], "text")
        self.assertEqual(normalize_browser_filters(source="all", view="media")["view"], "media")

        app = create_app()
        with app.test_client() as client:
            body = client.get(
                "/browser?view=text&source=all&q=&sort=newest&session_view=1"
            ).get_data(as_text=True)
        self.assertLess(body.index('id="browser_view_text"'), body.index('id="browser_view_media"'))
        self.assertLess(body.index('id="browser_view_media"'), body.index('id="browser_view_prompts"'))
        self.assertIn('data-option-count="3"', body)
        self.assertIn('data-segmented-active-index="0"', body)

    def test_segmented_control_script_exposes_the_shared_layout_contract(self) -> None:
        script = SEGMENTED_CONTROL_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'const selector = ".segmented-control[data-option-count], .range-mode-shell[data-option-count]";',
            'setAttributeIfChanged(shell, "data-option-count", String(optionCount));',
            'setAttributeIfChanged(shell, "data-segmented-active-index", String(activeIndex));',
            'setStylePropertyIfChanged(shell, "--segmented-option-count", String(optionCount));',
            'setStylePropertyIfChanged(shell, "--segmented-active-index", String(activeIndex));',
            'setAttributeIfChanged(option, "aria-checked", String(isActive));',
            "const includesSegmentedControl = records.some((record) => (",
            "Array.from(record.addedNodes).some((node) => (",
            "childList: true,",
            'window.CACHELIKES_SEGMENTED_CONTROLS = Object.freeze({sync, syncAll});',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

        observer_options = script.split("observer.observe(document.body, {", 1)[1]
        self.assertNotIn("attributes: true", observer_options)
        self.assertNotIn("attributeFilter:", observer_options)

    def test_text_browser_exposes_chatgpt_media_cache_entrypoint(self) -> None:
        app = create_app()

        with app.test_client() as client:
            all_text_body = client.get(
                "/browser?view=text&source=all&q=&sort=newest&session_view=1"
            ).get_data(as_text=True)
            chatgpt_text_body = client.get(
                "/browser?view=text&source=chatgpt&q=&sort=newest&session_view=1"
            ).get_data(as_text=True)
            gemini_text_body = client.get(
                "/browser?view=text&source=gemini&q=&sort=newest&session_view=1"
            ).get_data(as_text=True)

        for body in (all_text_body, chatgpt_text_body):
            self.assertIn("ChatGPT Media cache", body)
            self.assertIn(
                'href="/browser?view=media&amp;source=chatgpt&amp;q=&amp;sort=newest&amp;session_view=1"',
                body,
            )
        self.assertNotIn('data-media-cache-path=', chatgpt_text_body)
        self.assertNotIn('data-media-cache-path=', all_text_body)
        self.assertNotIn("ChatGPT Media cache", gemini_text_body)

    def test_browser_session_refresh_starts_and_polls_one_chatgpt_session(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.querySelector("[data-chatgpt-session-refresh]")',
            'fetch("/api/browser/chatgpt/session/refresh", {',
            'body: JSON.stringify({ conversation_url: conversationUrl })',
            'const statusUrl = startPayload.status_url || "/api/chatgpt/status";',
            'const initialResourceCount = Number(startPayload.resource_count) || 0;',
            'let refreshSummary = {',
            'if (snapshot.running) continue;',
            '(Number(snapshot.downloaded_images) || 0) - initialResourceCount',
            'session_discovered: refreshSummary.discoveredImages',
            'session_cached: refreshSummary.cachedImages',
            'session_skipped: refreshSummary.skippedImages',
            'session_failed: refreshSummary.failedImages',
            'refreshedUrl.searchParams.set("session_updated", String(updatedCount));',
            'document.querySelector("[data-chatgpt-session-refresh-banner]")',
            'Added ${imageCountLabel(updatedCount)}',
            'Pulled ${imageCountLabel(updatedCount)} from ChatGPT session ${sessionLabel}',
            'Nothing new was pulled; the local media cache is unchanged.',
            'The ChatGPT image cache now contains',
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
            project_dir = root / "media" / "chatgpt" / "demo-project"
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
        self.assertEqual(local_response.get_json()["file_manager"], local_file_manager_label())
        reveal.assert_called_once_with(image_path.resolve())
        self.assertEqual(remote_response.status_code, 403)
        self.assertEqual(missing_response.status_code, 404)

    def test_cache_output_directory_route_opens_only_for_local_clients(self) -> None:
        with TemporaryDirectory() as raw_root:
            root = Path(raw_root) / "local_store"
            app = create_app(root)
            with patch("app.web.app.open_directory_path") as open_directory:
                with app.test_client() as client:
                    local_response = client.post("/api/cache/chatgpt/output-directory/open")
                    remote_response = client.post(
                        "/api/cache/chatgpt/output-directory/open",
                        environ_overrides={"REMOTE_ADDR": "192.0.2.1"},
                    )

        self.assertEqual(local_response.status_code, 200)
        self.assertEqual(local_response.get_json()["file_manager"], local_file_manager_label())
        open_directory.assert_called_once()
        self.assertEqual(remote_response.status_code, 403)

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
                deleted_browser = client.get("/browser?view=media")
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
