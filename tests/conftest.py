"""Shared pytest fixtures for isolated CacheLikesFromTwitter tests.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import os
from tempfile import TemporaryDirectory

import pytest
from flask import Flask
from flask.testing import FlaskClient


_TEST_HOME = TemporaryDirectory(prefix="cachelikes-pytest-home-")
os.environ["HOME"] = _TEST_HOME.name


def pytest_sessionfinish() -> None:
    """Remove the process-wide home-directory fixture after pytest exits."""
    _TEST_HOME.cleanup()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Flask:
    """Create a Flask application instance for route-level tests."""
    import app.core.grok_downloader as grok_downloader
    import app.core.logging_setup as logging_setup
    import app.core.state as state
    from app.web.app import create_app

    local_store = tmp_path / "local_store"
    monkeypatch.setattr(grok_downloader, "GROK_TARGET_DIR", local_store / "grok")
    monkeypatch.setattr(logging_setup, "LOGS_ROOT", tmp_path / "logs")
    monkeypatch.setattr(state, "LOCAL_STORE_ROOT", local_store)
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Return the configured Flask test client."""
    return app.test_client()
