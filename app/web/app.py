"""Flask application for the local web console."""

# Code version: v1.5.1-gpt5.4.1

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app.core.browser_sessions import build_browser_options, probe_browser_session
from app.core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    CrawlConfig,
    load_saved_config,
    save_config,
)
from app.core.grok_downloader import build_grok_initial_snapshot, reset_grok_state
from app.core.grok_service import GrokDownloadService
from app.core.logging_setup import configure_logging, get_log_file_path
from app.core.service import CacheLikesService
from app.core.state import TaskState, utc_now
from app.core.version import APP_VERSION


def create_app() -> Flask:
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
    saved_config = load_saved_config()

    def build_reconciled_grok_snapshot() -> dict[str, Any]:
        """Refresh Grok cache counters from disk without discarding live task status."""
        snapshot = grok_state.snapshot()
        if snapshot.get("running"):
            return snapshot

        hydrated = build_grok_initial_snapshot(APP_VERSION)
        hydrated_payload = asdict(hydrated)
        snapshot["account_name"] = hydrated_payload["account_name"]
        snapshot["output_dir"] = hydrated_payload["output_dir"]
        snapshot["downloaded_posts"] = hydrated_payload["downloaded_posts"]
        snapshot["downloaded_tweets"] = hydrated_payload["downloaded_tweets"]
        snapshot["downloaded_images"] = hydrated_payload["downloaded_images"]
        snapshot["downloaded_videos"] = hydrated_payload["downloaded_videos"]
        if snapshot.get("phase") in {"idle", "finished", "completed", "success", "stopped"}:
            snapshot["message"] = hydrated_payload["message"]
        return snapshot

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
        snapshot = state.snapshot()
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
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

    @app.get("/settings")
    def settings():
        snapshot = state.snapshot()
        return render_template(
            "settings.html",
            snapshot=snapshot,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            saved_config=saved_config,
            log_file_path=str(get_log_file_path()),
        )

    @app.post("/start")
    def start():
        nonlocal saved_config
        config = parse_form_config(saved_config)
        saved_config = config
        save_config(saved_config)
        try:
            service.start(config)
        except RuntimeError as exc:
            state.finish_error(str(exc))
        return redirect(url_for("index"))

    @app.post("/stop")
    def stop():
        service.request_stop()
        return redirect(url_for("index"))

    @app.post("/grok/start")
    def start_grok():
        try:
            grok_service.start()
        except RuntimeError as exc:
            grok_state.finish_error(str(exc))
        return redirect(url_for("grok"))

    @app.post("/grok/stop")
    def stop_grok():
        grok_service.request_stop()
        return redirect(url_for("grok"))

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
        return jsonify(state.snapshot())

    @app.get("/api/grok/status")
    def api_grok_status():
        return jsonify(build_reconciled_grok_snapshot())

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
