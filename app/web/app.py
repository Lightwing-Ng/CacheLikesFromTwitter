"""Flask application for the local web console."""

# Code version: v1.16.0-codex.1

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from markdown_it import MarkdownIt
from markupsafe import Markup

from app.core.browser_sessions import browser_descriptors, build_browser_options, probe_browser_session
from app.core.chatgpt_downloader import build_chatgpt_initial_snapshot, reset_chatgpt_state
from app.core.chatgpt_service import ChatGPTDownloadService
from app.core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_MAX_MEDIA_FILE_SIZE_MIB,
    MIN_MAX_MEDIA_FILE_SIZE_MIB,
    CrawlConfig,
    LOCAL_STORE_ROOT,
    MAX_CHATGPT_SCAN_WAIT_SECONDS,
    MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    MIN_CHATGPT_SCAN_WAIT_SECONDS,
    MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
    load_saved_config,
    save_config,
)
from app.core.grok_downloader import build_grok_initial_snapshot, reset_grok_state
from app.core.grok_service import GrokDownloadService
from app.core.logging_setup import configure_logging, get_log_file_path
from app.core.local_media_browser import (
    LocalMediaCatalog,
    format_captured_at_timestamp_label,
    normalize_browser_filters,
    resolve_local_media_path,
)
from app.core.service import CacheLikesService
from app.core.shadow_backup import (
    ShadowBackupError,
    ShadowBackupService,
    choose_shadow_backup_destination,
)
from app.core.state import TaskState, build_initial_snapshot, utc_now
from app.core.version import APP_VERSION
from app.web.cache_sources import CACHE_SOURCE_VIEWS, get_cache_source_label, get_cache_source_view


CACHE_RECONCILE_PHASES = {"idle", "finished", "completed", "success", "stopped"}
PROMPT_MARKDOWN_RENDERER = MarkdownIt(
    "commonmark",
    {"html": False, "linkify": False, "typographer": False},
)


def render_prompt_markdown(value: str) -> Markup:
    """Render stored ChatGPT prompt Markdown while escaping embedded HTML."""
    prompt = str(value or "").replace("\x00", "").strip()
    return Markup(PROMPT_MARKDOWN_RENDERER.render(prompt)) if prompt else Markup("")


@dataclass(frozen=True, slots=True)
class CacheRuntimeAdapter:
    """Connect one registered cache page to its task runtime."""

    state: TaskState
    service: Any
    hydrate_snapshot: Callable[[], Any]


def reconcile_cached_snapshot(snapshot: dict[str, Any], hydrated_payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh persisted cache counters only for stable non-error task states."""
    if snapshot.get("running") or snapshot.get("phase") not in CACHE_RECONCILE_PHASES:
        return snapshot

    snapshot["account_name"] = hydrated_payload["account_name"]
    snapshot["output_dir"] = hydrated_payload["output_dir"]
    snapshot["downloaded_posts"] = hydrated_payload["downloaded_posts"]
    snapshot["downloaded_tweets"] = hydrated_payload["downloaded_tweets"]
    if "discovered_images" in hydrated_payload:
        snapshot["discovered_images"] = hydrated_payload["discovered_images"]
    snapshot["downloaded_images"] = hydrated_payload["downloaded_images"]
    snapshot["downloaded_videos"] = hydrated_payload["downloaded_videos"]
    snapshot["message"] = hydrated_payload["message"]
    return snapshot


def create_app(local_store_root: Path | str | None = None) -> Flask:
    """Build and configure the Flask app."""
    configure_logging(APP_VERSION)
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )

    media_catalog = LocalMediaCatalog(local_store_root or LOCAL_STORE_ROOT)
    app.extensions["local_media_catalog"] = media_catalog
    shadow_backup_service = ShadowBackupService(media_catalog.local_store_root)
    app.extensions["shadow_backup_service"] = shadow_backup_service
    state = TaskState(version=APP_VERSION)
    service = CacheLikesService(state, shadow_backup_service=shadow_backup_service)
    grok_state = TaskState(version=APP_VERSION, snapshot_factory=build_grok_initial_snapshot)
    grok_service = GrokDownloadService(grok_state, shadow_backup_service=shadow_backup_service)
    chatgpt_state = TaskState(version=APP_VERSION, snapshot_factory=build_chatgpt_initial_snapshot)
    chatgpt_service = ChatGPTDownloadService(chatgpt_state, shadow_backup_service=shadow_backup_service)
    saved_config = load_saved_config()
    cache_runtimes = {
        "x": CacheRuntimeAdapter(
            state=state,
            service=service,
            hydrate_snapshot=lambda: build_initial_snapshot(APP_VERSION),
        ),
        "grok": CacheRuntimeAdapter(
            state=grok_state,
            service=grok_service,
            hydrate_snapshot=lambda: build_grok_initial_snapshot(APP_VERSION),
        ),
        "chatgpt": CacheRuntimeAdapter(
            state=chatgpt_state,
            service=chatgpt_service,
            hydrate_snapshot=lambda: build_chatgpt_initial_snapshot(
                APP_VERSION,
                project_name=saved_config.chatgpt_project_name,
            ),
        ),
    }

    @app.context_processor
    def inject_cache_source_views() -> dict[str, Any]:
        """Expose the ordered cache registry to every dock instance."""
        return {"cache_sources": CACHE_SOURCE_VIEWS}

    def serialize_media_item(item) -> dict[str, Any]:
        """Serialize one browser item without exposing local absolute paths."""
        media_url = (
            url_for("browser_deleted_preview", stable_id=item.stable_id)
            if item.is_deleted
            else url_for("browser_media", relative_path=item.relative_path)
        )
        return {
            "id": item.stable_id,
            "source": item.source,
            "source_label": get_cache_source_label(item.source),
            "media_kind": item.media_kind,
            "media_kind_label": item.media_kind.title(),
            "relative_path": item.relative_path,
            "filename": item.filename,
            "title": item.title,
            "description": item.description,
            "prompt_markdown": item.prompt_markdown,
            "creator": item.creator,
            "project_name": item.project_name,
            "source_url": item.source_url,
            "resource_key": item.resource_key,
            "captured_at_label": item.captured_at_label,
            "content_bytes": item.content_bytes,
            "size_label": format_media_size(item.content_bytes),
            "media_url": media_url,
            "preview_url": media_url,
            "alt_text": item.alt_text,
            "width": item.width,
            "height": item.height,
            "is_deleted": item.is_deleted,
        }

    def build_reconciled_cache_snapshot(source_key: str) -> dict[str, Any]:
        """Refresh one registered source without discarding live task status."""
        runtime = cache_runtimes.get(source_key)
        if runtime is None:
            raise KeyError(source_key)
        return reconcile_cached_snapshot(runtime.state.snapshot(), asdict(runtime.hydrate_snapshot()))

    def build_reconciled_snapshot() -> dict[str, Any]:
        """Refresh X cache counters from disk without discarding live task status."""
        return build_reconciled_cache_snapshot("x")

    def build_reconciled_grok_snapshot() -> dict[str, Any]:
        """Refresh Grok cache counters from disk without discarding live task status."""
        return build_reconciled_cache_snapshot("grok")

    def build_reconciled_chatgpt_snapshot() -> dict[str, Any]:
        """Refresh ChatGPT image counters from disk without discarding live task status."""
        return build_reconciled_cache_snapshot("chatgpt")

    def parse_int_field(
        field_name: str,
        fallback: int,
        minimum: int = 1,
        maximum: int | None = None,
    ) -> int:
        """Parse one integer form field while tolerating display separators."""
        raw_value = (request.form.get(field_name, str(fallback)) or str(fallback)).replace(",", "").strip()
        parsed = max(minimum, int(raw_value or fallback))
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def parse_float_field(
        field_name: str,
        fallback: float,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        """Parse one float form field while tolerating display separators."""
        raw_value = (request.form.get(field_name, str(fallback)) or str(fallback)).replace(",", "").strip()
        parsed = float(raw_value or fallback)
        if minimum is not None:
            parsed = max(minimum, parsed)
        if maximum is not None:
            parsed = min(maximum, parsed)
        return parsed

    def parse_checkbox_field(field_name: str, fallback: bool, preserve_missing: bool) -> bool:
        """Parse one checkbox while partial cache forms preserve unrelated settings."""
        raw_value = request.form.get(field_name)
        if raw_value is None:
            return fallback if preserve_missing else False
        return raw_value == "on"

    def parse_form_config(
        base: CrawlConfig | None = None,
        *,
        preserve_missing_booleans: bool = False,
    ) -> CrawlConfig:
        source = base or CrawlConfig()
        return CrawlConfig(
            headless=parse_checkbox_field("headless", source.headless, preserve_missing_booleans),
            download_workers=parse_int_field("download_workers", source.download_workers),
            max_media_file_size_mib=parse_int_field(
                "max_media_file_size_mib",
                source.max_media_file_size_mib,
                minimum=MIN_MAX_MEDIA_FILE_SIZE_MIB,
                maximum=MAX_MAX_MEDIA_FILE_SIZE_MIB,
            ),
            max_media_items=parse_int_field("max_media_items", source.max_media_items),
            max_scroll_rounds=parse_int_field("max_scroll_rounds", source.max_scroll_rounds),
            scroll_pause_seconds=parse_float_field("scroll_pause_seconds", source.scroll_pause_seconds),
            stale_round_limit=parse_int_field("stale_round_limit", source.stale_round_limit),
            x_browser=(request.form.get("x_browser", source.x_browser) or source.x_browser).strip().lower(),
            grok_browser=(request.form.get("grok_browser", source.grok_browser) or source.grok_browser).strip().lower(),
            chatgpt_browser=(request.form.get("chatgpt_browser", source.chatgpt_browser) or source.chatgpt_browser)
            .strip()
            .lower(),
            chatgpt_project_url=(
                request.form.get("chatgpt_project_url", source.chatgpt_project_url) or source.chatgpt_project_url
            ).strip()
            or source.chatgpt_project_url,
            chatgpt_project_name=(
                request.form.get("chatgpt_project_name", source.chatgpt_project_name) or source.chatgpt_project_name
            ).strip()
            or source.chatgpt_project_name,
            chatgpt_startup_timeout_seconds=parse_float_field(
                "chatgpt_startup_timeout_seconds",
                source.chatgpt_startup_timeout_seconds,
                minimum=MIN_CHATGPT_STARTUP_TIMEOUT_SECONDS,
                maximum=MAX_CHATGPT_STARTUP_TIMEOUT_SECONDS,
            ),
            chatgpt_scan_wait_seconds=parse_float_field(
                "chatgpt_scan_wait_seconds",
                source.chatgpt_scan_wait_seconds,
                minimum=MIN_CHATGPT_SCAN_WAIT_SECONDS,
                maximum=MAX_CHATGPT_SCAN_WAIT_SECONDS,
            ),
            chrome_user_data_dir=Path(
                request.form.get("chrome_user_data_dir", str(source.chrome_user_data_dir)).strip()
            ).expanduser(),
            chrome_profile_directory=request.form.get(
                "chrome_profile_directory", source.chrome_profile_directory
            ).strip()
            or source.chrome_profile_directory,
            account_name_override=request.form.get("account_name_override", source.account_name_override).strip(),
            shadow_backup_enabled=parse_checkbox_field(
                "shadow_backup_enabled",
                source.shadow_backup_enabled,
                preserve_missing_booleans,
            ),
            shadow_backup_auto_sync=parse_checkbox_field(
                "shadow_backup_auto_sync",
                source.shadow_backup_auto_sync,
                preserve_missing_booleans,
            ),
            shadow_backup_mirror_deletions=parse_checkbox_field(
                "shadow_backup_mirror_deletions",
                source.shadow_backup_mirror_deletions,
                preserve_missing_booleans,
            ),
            shadow_backup_destination=Path(
                (
                    request.form.get("shadow_backup_destination", str(source.shadow_backup_destination))
                    or str(source.shadow_backup_destination)
                ).strip()
            ).expanduser(),
        )

    def render_cache_source_page(source_key: str):
        """Render one source through the shared cache-page contract."""
        cache_source = get_cache_source_view(source_key)
        if cache_source is None or source_key not in cache_runtimes:
            abort(404)
        return render_template(
            cache_source.template_name,
            cache_source=cache_source,
            snapshot=build_reconciled_cache_snapshot(source_key),
            saved_config=saved_config,
            browser_options=build_browser_options(saved_config),
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

    @app.get("/")
    def index():
        return render_cache_source_page("x")

    @app.get("/grok")
    def grok():
        return render_cache_source_page("grok")

    @app.get("/chatgpt")
    def chatgpt():
        return render_cache_source_page("chatgpt")

    @app.get("/settings")
    def settings():
        snapshot = build_reconciled_snapshot()
        grok_snapshot = build_reconciled_grok_snapshot()
        chatgpt_snapshot = build_reconciled_chatgpt_snapshot()
        return render_template(
            "settings.html",
            snapshot=snapshot,
            grok_snapshot=grok_snapshot,
            chatgpt_snapshot=chatgpt_snapshot,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            saved_config=saved_config,
            log_file_path=str(get_log_file_path()),
            local_store_root=str(media_catalog.local_store_root),
            shadow_backup_snapshot=shadow_backup_service.snapshot(),
        )

    @app.get("/browser")
    def browser():
        filters = normalize_browser_filters(
            source=request.args.get("source"),
            media_kind=request.args.get("kind"),
            query=request.args.get("q"),
            sort=request.args.get("sort"),
            page=request.args.get("page"),
        )
        force_refresh = request.args.get("refresh") == "1"
        all_items = media_catalog.snapshot(force_refresh=force_refresh)
        media_page = media_catalog.query(
            source=filters["source"],
            media_kind=filters["kind"],
            query=filters["q"],
            sort=filters["sort"],
            page=filters["page"],
        )
        media_payload = [serialize_media_item(item) for item in media_page.items]
        return render_template(
            "browser.html",
            media_page=media_page,
            media_payload=media_payload,
            filters=filters,
            has_any_media=bool(all_items),
            format_captured_at_timestamp_label=format_captured_at_timestamp_label,
            format_media_size=format_media_size,
            render_prompt_markdown=render_prompt_markdown,
            version=APP_VERSION,
        )

    @app.get("/browser/media/<path:relative_path>")
    def browser_media(relative_path: str):
        resolved_path = resolve_local_media_path(media_catalog.local_store_root, relative_path)
        if resolved_path is None:
            abort(404)
        return send_file(resolved_path, conditional=True, etag=True, max_age=0)

    @app.get("/browser/deleted-preview/<stable_id>")
    def browser_deleted_preview(stable_id: str):
        resolved_path = media_catalog.deleted_preview_path(stable_id)
        if resolved_path is None:
            abort(404)
        return send_file(resolved_path, conditional=True, etag=True, max_age=0)

    @app.post("/api/browser/media/<stable_id>/delete")
    def delete_browser_media(stable_id: str):
        try:
            item = media_catalog.delete(stable_id)
        except KeyError:
            return jsonify({"error": "Cached media was not found."}), 404
        except FileNotFoundError:
            return jsonify({"error": "Cached media is no longer available."}), 404
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"item": serialize_media_item(item)})

    @app.post("/api/browser/media/<stable_id>/restore")
    def restore_browser_media(stable_id: str):
        try:
            item = media_catalog.restore(stable_id)
        except KeyError:
            return jsonify({"error": "Removed media was not found."}), 404
        except FileNotFoundError:
            return jsonify({"error": "The retained preview is no longer available."}), 404
        except (OSError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"item": serialize_media_item(item)})

    def start_cache_source_runtime(source_key: str):
        """Persist shared form values and start one registered runtime."""
        nonlocal saved_config
        cache_source = get_cache_source_view(source_key)
        runtime = cache_runtimes.get(source_key)
        if cache_source is None or runtime is None:
            abort(404)
        config = parse_form_config(saved_config, preserve_missing_booleans=True)
        saved_config = config
        save_config(saved_config)
        if cache_source.require_browser_ready:
            browser_name = getattr(config, cache_source.browser_config_field)
            descriptor = browser_descriptors(config).get(browser_name)
            if descriptor is None:
                runtime.state.finish_error(f"Unsupported {cache_source.label} browser: {browser_name}")
                return redirect(url_for(cache_source.view_endpoint))
        try:
            runtime.service.start(config)
        except RuntimeError as exc:
            if runtime.service.is_running():
                runtime.state.append_event(str(exc))
                runtime.state.update(last_error=str(exc))
            else:
                runtime.state.finish_error(str(exc))
        return redirect(url_for(cache_source.view_endpoint))

    def stop_cache_source_runtime(source_key: str):
        """Request a safe stop for one registered runtime."""
        cache_source = get_cache_source_view(source_key)
        runtime = cache_runtimes.get(source_key)
        if cache_source is None or runtime is None:
            abort(404)
        runtime.service.request_stop()
        return redirect(url_for(cache_source.view_endpoint))

    @app.post("/cache/<source_key>/start")
    def start_cache_source(source_key: str):
        return start_cache_source_runtime(source_key)

    @app.post("/cache/<source_key>/stop")
    def stop_cache_source(source_key: str):
        return stop_cache_source_runtime(source_key)

    @app.post("/start")
    def start():
        return start_cache_source_runtime("x")

    @app.post("/stop")
    def stop():
        return stop_cache_source_runtime("x")

    @app.post("/grok/start")
    def start_grok():
        return start_cache_source_runtime("grok")

    @app.post("/grok/stop")
    def stop_grok():
        return stop_cache_source_runtime("grok")

    @app.post("/chatgpt/start")
    def start_chatgpt():
        return start_cache_source_runtime("chatgpt")

    @app.post("/chatgpt/stop")
    def stop_chatgpt():
        return stop_cache_source_runtime("chatgpt")

    @app.post("/chatgpt/reset")
    def reset_chatgpt():
        if chatgpt_service.is_running():
            chatgpt_state.append_event("Reset skipped because a ChatGPT sync is still running.")
            chatgpt_state.update(last_error="Cannot reset ChatGPT state while a sync is running.")
            return redirect(url_for("chatgpt"))

        result = reset_chatgpt_state(project_name=saved_config.chatgpt_project_name)
        snapshot = build_chatgpt_initial_snapshot(
            APP_VERSION,
            project_name=saved_config.chatgpt_project_name,
        )
        message = (
            f"Reset ChatGPT state. Removed {result.removed_media_files} image files, "
            f"{result.removed_state_files} state files, "
            f"{result.removed_partial_files} partial files."
        )
        snapshot.message = message
        snapshot.recent_events = [f"[{utc_now()}] {message}"]
        chatgpt_state.replace_snapshot(snapshot)
        return redirect(url_for("chatgpt"))

    @app.post("/grok/reset")
    def reset_grok():
        if grok_service.is_running():
            grok_state.append_event("Reset skipped because a Grok sync is still running.")
            grok_state.update(last_error="Cannot reset Grok state while a sync is running.")
            return redirect(url_for("grok"))

        result = reset_grok_state()
        snapshot = build_grok_initial_snapshot(APP_VERSION)
        message = (
            f"Reset Grok state. Removed {result.removed_media_files} media files, "
            f"{result.removed_state_files} state files, "
            f"{result.removed_partial_files} partial files."
        )
        snapshot.message = message
        snapshot.recent_events = [f"[{utc_now()}] {message}"]
        grok_state.replace_snapshot(snapshot)
        return redirect(url_for("grok"))

    @app.post("/settings")
    def save_settings():
        nonlocal saved_config
        saved_config = parse_form_config(saved_config)
        save_config(saved_config)
        return redirect(url_for("settings"))

    @app.post("/settings/shadow-backup/sync")
    def start_shadow_backup_sync():
        nonlocal saved_config
        saved_config = parse_form_config(saved_config)
        save_config(saved_config)
        try:
            shadow_backup_service.start(saved_config)
        except ShadowBackupError as exc:
            shadow_backup_service.record_start_error(exc)
        return redirect(url_for("settings"))

    @app.get("/api/settings/shadow-backup/status")
    def api_shadow_backup_status():
        return jsonify(shadow_backup_service.snapshot())

    @app.post("/api/settings/shadow-backup/destination")
    def choose_shadow_backup_destination_route():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            return jsonify({"error": "The folder picker is only available from this Mac."}), 403

        payload = request.get_json(silent=True) or {}
        requested_initial_path = payload.get("initial_path")
        initial_value = (
            requested_initial_path.strip()
            if isinstance(requested_initial_path, str)
            else str(saved_config.shadow_backup_destination)
        )
        try:
            selected_path = choose_shadow_backup_destination(
                Path(initial_value or str(saved_config.shadow_backup_destination))
            )
        except ShadowBackupError as exc:
            return jsonify({"error": str(exc)}), 500

        if selected_path is None:
            return jsonify({"cancelled": True})
        return jsonify({"destination": str(selected_path)})

    @app.get("/api/status")
    def api_status():
        return jsonify(build_reconciled_cache_snapshot("x"))

    @app.get("/api/grok/status")
    def api_grok_status():
        return jsonify(build_reconciled_cache_snapshot("grok"))

    @app.get("/api/chatgpt/status")
    def api_chatgpt_status():
        return jsonify(build_reconciled_cache_snapshot("chatgpt"))

    @app.get("/api/cache/<source_key>/status")
    def api_cache_status(source_key: str):
        if get_cache_source_view(source_key) is None or source_key not in cache_runtimes:
            abort(404)
        return jsonify(build_reconciled_cache_snapshot(source_key))

    @app.get("/api/browser-session")
    def api_browser_session():
        platform_name = request.args.get("platform", "").strip().lower()
        browser_name = request.args.get("browser", "").strip().lower()
        try:
            payload = probe_browser_session(platform_name, browser_name, saved_config)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(payload)

    return app


def format_media_size(content_bytes: int) -> str:
    """Render a byte count as a compact, readable English file size."""
    size = max(0, int(content_bytes))
    if size < 1_024:
        return f"{size:,} B"
    if size < 1_024**2:
        return f"{size / 1_024:.2f} KiB"
    if size < 1_024**3:
        return f"{size / 1_024**2:.2f} MiB"
    return f"{size / 1_024**3:.2f} GiB"
