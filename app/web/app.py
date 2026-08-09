"""Flask application for the local web console."""

# Code version: v1.9.0-codex.1

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

from app.core.browser_sessions import browser_descriptors, build_browser_options, probe_browser_session
from app.core.chatgpt_downloader import build_chatgpt_initial_snapshot, reset_chatgpt_state
from app.core.chatgpt_service import ChatGPTDownloadService
from app.core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    CrawlConfig,
    LOCAL_STORE_ROOT,
    load_saved_config,
    save_config,
)
from app.core.grok_downloader import build_grok_initial_snapshot, reset_grok_state
from app.core.grok_service import GrokDownloadService
from app.core.logging_setup import configure_logging, get_log_file_path
from app.core.local_media_browser import LocalMediaCatalog, normalize_browser_filters, resolve_local_media_path
from app.core.service import CacheLikesService
from app.core.state import TaskState, build_initial_snapshot, utc_now
from app.core.version import APP_VERSION


CACHE_RECONCILE_PHASES = {"idle", "finished", "completed", "success", "stopped"}


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

    state = TaskState(version=APP_VERSION)
    service = CacheLikesService(state)
    grok_state = TaskState(version=APP_VERSION, snapshot_factory=build_grok_initial_snapshot)
    grok_service = GrokDownloadService(grok_state)
    chatgpt_state = TaskState(version=APP_VERSION, snapshot_factory=build_chatgpt_initial_snapshot)
    chatgpt_service = ChatGPTDownloadService(chatgpt_state)
    media_catalog = LocalMediaCatalog(local_store_root or LOCAL_STORE_ROOT)
    app.extensions["local_media_catalog"] = media_catalog
    saved_config = load_saved_config()

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
            "source_label": {"x": "X", "grok": "Grok", "chatgpt": "ChatGPT"}.get(
                item.source, item.source.title()
            ),
            "media_kind": item.media_kind,
            "media_kind_label": item.media_kind.title(),
            "relative_path": item.relative_path,
            "filename": item.filename,
            "title": item.title,
            "description": item.description,
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

    def build_reconciled_snapshot() -> dict[str, Any]:
        """Refresh X cache counters from disk without discarding live task status."""
        snapshot = state.snapshot()
        hydrated = build_initial_snapshot(APP_VERSION)
        return reconcile_cached_snapshot(snapshot, asdict(hydrated))

    def build_reconciled_grok_snapshot() -> dict[str, Any]:
        """Refresh Grok cache counters from disk without discarding live task status."""
        snapshot = grok_state.snapshot()
        hydrated = build_grok_initial_snapshot(APP_VERSION)
        return reconcile_cached_snapshot(snapshot, asdict(hydrated))

    def build_reconciled_chatgpt_snapshot() -> dict[str, Any]:
        """Refresh ChatGPT image counters from disk without discarding live task status."""
        snapshot = chatgpt_state.snapshot()
        hydrated = build_chatgpt_initial_snapshot(
            APP_VERSION,
            project_name=saved_config.chatgpt_project_name,
        )
        return reconcile_cached_snapshot(snapshot, asdict(hydrated))

    def parse_int_field(field_name: str, fallback: int, minimum: int = 1) -> int:
        """Parse one integer form field while tolerating display separators."""
        raw_value = (request.form.get(field_name, str(fallback)) or str(fallback)).replace(",", "").strip()
        return max(minimum, int(raw_value or fallback))

    def parse_float_field(field_name: str, fallback: float) -> float:
        """Parse one float form field while tolerating display separators."""
        raw_value = (request.form.get(field_name, str(fallback)) or str(fallback)).replace(",", "").strip()
        return float(raw_value or fallback)

    def parse_form_config(base: CrawlConfig | None = None) -> CrawlConfig:
        source = base or CrawlConfig()
        return CrawlConfig(
            headless=request.form.get("headless") == "on",
            download_workers=parse_int_field("download_workers", source.download_workers),
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
            chrome_user_data_dir=Path(
                request.form.get("chrome_user_data_dir", str(source.chrome_user_data_dir)).strip()
            ).expanduser(),
            chrome_profile_directory=request.form.get(
                "chrome_profile_directory", source.chrome_profile_directory
            ).strip()
            or source.chrome_profile_directory,
            account_name_override=request.form.get("account_name_override", source.account_name_override).strip(),
        )

    @app.get("/")
    def index():
        snapshot = build_reconciled_snapshot()
        return render_template(
            "index.html",
            snapshot=snapshot,
            saved_config=saved_config,
            browser_options=build_browser_options(saved_config),
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

    @app.get("/grok")
    def grok():
        snapshot = build_reconciled_grok_snapshot()
        return render_template(
            "grok.html",
            snapshot=snapshot,
            browser_options=build_browser_options(saved_config),
            saved_config=saved_config,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

    @app.get("/chatgpt")
    def chatgpt():
        snapshot = build_reconciled_chatgpt_snapshot()
        return render_template(
            "chatgpt.html",
            snapshot=snapshot,
            browser_options=build_browser_options(saved_config),
            saved_config=saved_config,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

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
            format_media_size=format_media_size,
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

    @app.post("/start")
    def start():
        nonlocal saved_config
        config = parse_form_config(saved_config)
        saved_config = config
        save_config(saved_config)
        try:
            service.start(config)
        except RuntimeError as exc:
            if service.is_running():
                state.append_event(str(exc))
                state.update(last_error=str(exc))
            else:
                state.finish_error(str(exc))
        return redirect(url_for("index"))

    @app.post("/stop")
    def stop():
        service.request_stop()
        return redirect(url_for("index"))

    @app.post("/grok/start")
    def start_grok():
        nonlocal saved_config
        config = parse_form_config(saved_config)
        saved_config = config
        save_config(saved_config)
        descriptor = browser_descriptors(config).get(config.grok_browser)
        if descriptor is None:
            grok_state.finish_error(f"Unsupported Grok browser: {config.grok_browser}")
            return redirect(url_for("grok"))
        try:
            grok_service.start(config)
        except RuntimeError as exc:
            if grok_service.is_running():
                grok_state.append_event(str(exc))
                grok_state.update(last_error=str(exc))
            else:
                grok_state.finish_error(str(exc))
        return redirect(url_for("grok"))

    @app.post("/grok/stop")
    def stop_grok():
        grok_service.request_stop()
        return redirect(url_for("grok"))

    @app.post("/chatgpt/start")
    def start_chatgpt():
        nonlocal saved_config
        config = parse_form_config(saved_config)
        saved_config = config
        save_config(saved_config)
        descriptor = browser_descriptors(config).get(config.chatgpt_browser)
        if descriptor is None:
            chatgpt_state.finish_error(f"Unsupported ChatGPT browser: {config.chatgpt_browser}")
            return redirect(url_for("chatgpt"))
        try:
            chatgpt_service.start(config)
        except RuntimeError as exc:
            if chatgpt_service.is_running():
                chatgpt_state.append_event(str(exc))
                chatgpt_state.update(last_error=str(exc))
            else:
                chatgpt_state.finish_error(str(exc))
        return redirect(url_for("chatgpt"))

    @app.post("/chatgpt/stop")
    def stop_chatgpt():
        chatgpt_service.request_stop()
        return redirect(url_for("chatgpt"))

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

    @app.get("/api/status")
    def api_status():
        return jsonify(build_reconciled_snapshot())

    @app.get("/api/grok/status")
    def api_grok_status():
        return jsonify(build_reconciled_grok_snapshot())

    @app.get("/api/chatgpt/status")
    def api_chatgpt_status():
        return jsonify(build_reconciled_chatgpt_snapshot())

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
        return f"{size / 1_024:.1f} KB"
    if size < 1_024**3:
        return f"{size / 1_024**2:.1f} MB"
    return f"{size / 1_024**3:.1f} GB"
