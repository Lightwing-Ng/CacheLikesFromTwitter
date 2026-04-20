"""Flask application for the local web console."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app.core.config import (
    DEFAULT_CHROME_PROFILE_DIRECTORY,
    DEFAULT_CHROME_USER_DATA_DIR,
    DEFAULT_HOST,
    DEFAULT_PORT,
    CrawlConfig,
)
from app.core.service import CacheLikesService
from app.core.state import TaskState
from app.core.version import APP_VERSION


def create_app() -> Flask:
    """Build and configure the Flask app."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )

    state = TaskState(version=APP_VERSION)
    service = CacheLikesService(state)

    @app.get("/")
    def index():
        snapshot = state.snapshot()
        return render_template(
            "index.html",
            snapshot=snapshot,
            version=APP_VERSION,
            default_host=DEFAULT_HOST,
            default_port=DEFAULT_PORT,
            default_chrome_user_data_dir=str(DEFAULT_CHROME_USER_DATA_DIR),
            default_chrome_profile_directory=DEFAULT_CHROME_PROFILE_DIRECTORY,
        )

    @app.post("/start")
    def start():
        config = CrawlConfig(
            headless=request.form.get("headless") == "on",
            max_scroll_rounds=int(request.form.get("max_scroll_rounds", "200") or 200),
            scroll_pause_seconds=float(request.form.get("scroll_pause_seconds", "1.2") or 1.2),
            stale_round_limit=int(request.form.get("stale_round_limit", "8") or 8),
            chrome_user_data_dir=Path(
                request.form.get("chrome_user_data_dir", str(DEFAULT_CHROME_USER_DATA_DIR)).strip()
            ).expanduser(),
            chrome_profile_directory=request.form.get(
                "chrome_profile_directory", DEFAULT_CHROME_PROFILE_DIRECTORY
            ).strip()
            or DEFAULT_CHROME_PROFILE_DIRECTORY,
            account_name_override=request.form.get("account_name_override", "").strip(),
        )
        try:
            service.start(config)
        except RuntimeError as exc:
            state.finish_error(str(exc))
        return redirect(url_for("index"))

    @app.get("/api/status")
    def api_status():
        return jsonify(state.snapshot())

    return app
