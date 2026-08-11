"""Focused regression tests for the local web console."""

# Code version: v1.19.0-codex.1

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.core.state import TaskSnapshot
from app.core.local_media_browser import stable_media_id
from app.web.app import create_app, format_media_size, reconcile_cached_snapshot, render_prompt_markdown
from app.web.cache_sources import CACHE_SOURCE_VIEWS


SIDEBAR_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/sidebar.js"
CACHE_PAGE_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/cache-page.js"
LOCAL_MEDIA_BROWSER_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "app/web/static/local-media-browser.js"
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

    def test_cache_pages_share_the_first_dock_menu(self) -> None:
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
        self.assertIn('href="/chatgpt"', grok_body)
        self.assertIn('data-section-link="browser"', browser_body)
        self.assertIn("ChatGPT cache overview", chatgpt_body)
        self.assertIn('name="chatgpt_project_url"', chatgpt_body)
        self.assertIn('name="chatgpt_startup_timeout_seconds"', chatgpt_body)
        self.assertIn('name="chatgpt_scan_wait_seconds"', chatgpt_body)
        self.assertIn("Project or chat URL", chatgpt_body)
        self.assertNotIn('name="chatgpt_project_name"', chatgpt_body)
        self.assertIn('data-platform="chatgpt"', chatgpt_body)
        self.assertIn('action="/cache/chatgpt/start"', chatgpt_body)
        self.assertNotIn('class="status-copy chatgpt-sidebar-note"', chatgpt_body)
        self.assertIn('id="status_progress_value"', chatgpt_body)
        self.assertIn('id="progress_processed_label"', chatgpt_body)
        self.assertIn('cache-page.js?v=cache-page-v1.0.0-codex.1', chatgpt_body)
        chatgpt_form_identifier = chatgpt_body.index('id="start_form_chatgpt"')
        chatgpt_form_start = chatgpt_body.rfind("<form", 0, chatgpt_form_identifier)
        chatgpt_form_end = chatgpt_body.index("</form>", chatgpt_form_start)
        chatgpt_form = chatgpt_body[chatgpt_form_start:chatgpt_form_end]
        self.assertIn("field-grid", chatgpt_form)
        self.assertIn('name="download_workers"', chatgpt_form)
        self.assertIn('name="max_media_file_size_mib"', chatgpt_form)
        self.assertEqual(chatgpt_form.count('class="field"'), 3)
        self.assertEqual(chatgpt_form.count("text-input-control"), 3)
        self.assertEqual(chatgpt_form.count('data-cache-number-field'), 2)
        self.assertEqual(chatgpt_form.count('data-cache-number-stepper="increment"'), 2)
        self.assertEqual(chatgpt_form.count('data-cache-number-stepper="decrement"'), 2)
        self.assertIn('min="1"', chatgpt_form)
        self.assertIn('max="600"', chatgpt_form)
        self.assertIn('step="0.1"', chatgpt_form)
        cache_page_script = CACHE_PAGE_SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("function initializeNumberSteppers()", cache_page_script)
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
                self.assertIn('src="/static/numeric-input-format.js"', body)
        for body in (grok_body, chatgpt_body, index_body, settings_body, browser_body):
            with self.subTest(page=body[:40]):
                dock_start = body.index('<nav class="sidebar-dock"')
                dock_end = body.index("</nav>", dock_start) + len("</nav>")
                dock_markup = body[dock_start:dock_end]
                source_positions = [
                    dock_markup.index(f'data-cache-source-option="{label}"')
                    for label in ("chatgpt", "grok", "x")
                ]
                self.assertEqual(source_positions, sorted(source_positions))
                self.assertEqual(dock_markup.count('data-cache-source-option='), 3)
                self.assertEqual(dock_markup.count('data-section-link='), 3)
                self.assertEqual(dock_markup.count('aria-current="page"'), 1)
                self.assertIn('class="sidebar-dock-cache-menu" data-cache-source-menu', dock_markup)
                self.assertIn('class="sidebar-dock-item sidebar-dock-cache-trigger', dock_markup)
                self.assertIn('class="trade-strategy-dropdown backtest-shared-select-dropdown sidebar-dock-cache-dropdown"', dock_markup)
                self.assertIn('data-tooltip="Caches"', dock_markup)
                self.assertIn('class="icon dock-icon dock-icon-cache"', dock_markup)
                if 'aria-selected="true"' in dock_markup:
                    self.assertIn('class="sidebar-dock-cache-current"', dock_markup)
                self.assertIn("--cache-source-mark: url('/static/images/x.svg')", dock_markup)
                self.assertIn("--cache-source-mark: url('/static/images/grok.svg')", dock_markup)
                self.assertIn("--cache-source-mark: url('/static/images/ChatGPT-Logo.svg')", dock_markup)
                self.assertNotIn('class="browser-picker-option-icon"', dock_markup)
                self.assertIn('src="/static/sidebar.js?v=', body)
                self.assertIn('class="sidebar-dock-label"', dock_markup)
                self.assertNotIn("cachelikes:browser-sidebar-open", body)
                self.assertIn('waiting-modal.js?v=waiting-modal-v1.0.0-codex.1', body)
                self.assertIn('id="cache_wait_modal"', body)
                self.assertIn('class="workspace-modal-overlay cache-wait-modal"', body)
                self.assertIn('suggestion-loading-spinner workspace-modal-icon', body)
        for body in (index_body, grok_body, chatgpt_body):
            with self.subTest(session_page=body[:40]):
                self.assertIn('data-role="browser-session-spinner"', body)
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
        self.assertIn('data-shadow-backup-status-spinner', settings_body)
        self.assertIn('formaction="/settings/shadow-backup/sync"', settings_body)
        self.assertIn('shadow-backup-settings.js?v=shadow-backup-settings-v1.2.0-codex.1', settings_body)
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

    def test_cache_source_menu_has_keyboard_and_dismissal_controls(self) -> None:
        script = SIDEBAR_SCRIPT_PATH.read_text(encoding="utf-8")

        expected_fragments = (
            'document.querySelector("[data-cache-source-menu]")',
            'querySelector(".sidebar-dock-cache-trigger")',
            'positionCacheSourceDropdown()',
            'getBoundingClientRect()',
            'window.innerWidth - dropdownRect.width - viewportPadding',
            'cacheSourceTrigger?.addEventListener("click"',
            'cacheSourceDropdown.hidden = !nextIsOpen;',
            'new Set(["ArrowDown", "ArrowUp", "Home", "End"])',
            'cacheSourceTrigger.removeAttribute("aria-activedescendant")',
            'event.key === "Escape"',
            'document.addEventListener("click"',
        )

        for fragment in expected_fragments:
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
            self.assertIn("style-v2.25.0-codex.1", body)
            self.assertIn('local-media-browser.js?v=local-media-browser-v1.14.0-codex.1', body)
            self.assertIn('data-media-source-link', body)
            self.assertIn('data-media-copy-source-url', body)
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
        self.assertIn('class="browser-media-card-title" title="img_file.png">img_file.png</span>', body)
        self.assertNotIn("browser-media-card-description", body)
        self.assertIn("Session:</dt><dd title=\"A regular session\">A regular session</dd>", body)
        self.assertIn("Created on:</dt><dd>9 Aug 2026, 07:09</dd>", body)
        self.assertIn("Size:</dt><dd>1.72 MiB</dd>", body)
        self.assertIn('class="browser-media-prompt"', body)
        self.assertIn('data-media-prompt-open', body)
        self.assertIn("<strong>Frame the athlete</strong>", body)
        self.assertIn("<li>Soft light</li>", body)
        self.assertIn('id="browser_prompt_dialog"', body)
        self.assertIn('class="browser-media-copy-source-url"', body)
        self.assertIn('data-media-copy-feedback', body)

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

        first_body = first_response.get_data(as_text=True)
        second_body = second_response.get_data(as_text=True)
        self.assertEqual(first_response.status_code, 200)
        self.assertIn("Newest session", first_body)
        self.assertIn("Session 1 of 2", first_body)
        self.assertIn("2 resources in this session", first_body)
        self.assertIn("Latest image 10 Aug 2026, 09:00", first_body)
        self.assertIn('aria-label="ChatGPT sessions"', first_body)
        self.assertIn('aria-label="Session 2"', first_body)
        self.assertIn("Image order in session", first_body)
        self.assertIn("new-old.png", first_body)
        self.assertIn("new-latest.png", first_body)
        self.assertNotIn("older-session.png", first_body)
        self.assertIn("Older session", second_body)
        self.assertIn("Session 2 of 2", second_body)
        self.assertIn("older-session.png", second_body)
        self.assertNotIn("new-latest.png", second_body)

    def test_format_media_size_uses_two_decimal_binary_units(self) -> None:
        self.assertEqual(format_media_size(1_024), "1.00 KiB")
        self.assertEqual(format_media_size(1_805_089), "1.72 MiB")
        self.assertEqual(format_media_size(1_024**3), "1.00 GiB")

    def test_prompt_markdown_renderer_escapes_embedded_html(self) -> None:
        rendered = str(render_prompt_markdown("**Safe** <script>alert('x')</script>"))

        self.assertIn("<strong>Safe</strong>", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_browser_prompt_expands_in_a_shared_dialog(self) -> None:
        script = LOCAL_MEDIA_BROWSER_SCRIPT_PATH.read_text(encoding="utf-8")

        for fragment in (
            'document.getElementById("browser_prompt_dialog")',
            'document.querySelectorAll("[data-media-prompt-open]")',
            "promptDialogContent.replaceChildren(",
            "promptDialog.showModal();",
            'promptDialog?.addEventListener("close"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, script)

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

        self.assertEqual(reconciled["message"], hydrated.message)
        self.assertEqual(reconciled["downloaded_posts"], 542)
        self.assertEqual(reconciled["downloaded_videos"], 542)
        self.assertEqual(reconciled["output_dir"], "/tmp/cache")


if __name__ == "__main__":
    unittest.main()
