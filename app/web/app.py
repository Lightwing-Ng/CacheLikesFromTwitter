"""Flask application for the local web console."""

# Code version: v1.2.0-codex.1

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app.core.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    CrawlConfig,
    load_saved_config,
    save_config,
)
from app.core.grok_downloader import build_grok_initial_snapshot
from app.core.grok_service import GrokDownloadService
from app.core.logging_setup import configure_logging, get_log_file_path
from app.core.service import CacheLikesService
from app.core.state import TaskState
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

    def parse_form_config(base: CrawlConfig | None = None) -> CrawlConfig:
        source = base or CrawlConfig()
        return CrawlConfig(
            headless=request.form.get("headless") == "on",
            max_media_items=int(
                request.form.get("max_media_items", str(source.max_media_items)) or source.max_media_items
            ),
            max_scroll_rounds=int(
                request.form.get("max_scroll_rounds", str(source.max_scroll_rounds)) or source.max_scroll_rounds
            ),
            scroll_pause_seconds=float(
                request.form.get("scroll_pause_seconds", str(source.scroll_pause_seconds))
                or source.scroll_pause_seconds
            ),
            stale_round_limit=int(
                request.form.get("stale_round_limit", str(source.stale_round_limit)) or source.stale_round_limit
            ),
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
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            log_file_path=str(get_log_file_path()),
        )

    @app.get("/grok")
    def grok():
        snapshot = grok_state.snapshot()
        return render_template(
            "grok.html",
            snapshot=snapshot,
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
        config = saved_config
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
        return jsonify(grok_state.snapshot())

    return app
