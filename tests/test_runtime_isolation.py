"""Regression tests for the process-wide pytest runtime boundary.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from app.core import config
from app.core import grok_downloader
from app.web.app import create_app


def test_pytest_runtime_paths_are_outside_the_repository() -> None:
    """Keep default application construction away from user-owned runtime data."""
    assert config.RUNTIME_ROOT != config.PROJECT_ROOT
    assert not config.LOCAL_STORE_ROOT.is_relative_to(config.PROJECT_ROOT)
    assert not config.LOGS_ROOT.is_relative_to(config.PROJECT_ROOT)
    assert not config.LEGACY_SETTINGS_PATH.is_relative_to(config.PROJECT_ROOT)
    assert config.SETTINGS_PATH.is_relative_to(config.RUNTIME_ROOT)
    assert grok_downloader.GROK_TARGET_DIR.is_relative_to(config.RUNTIME_ROOT)

    application = create_app()
    catalog = application.extensions["local_media_catalog"]

    assert catalog.local_store_root == config.LOCAL_STORE_ROOT.resolve(strict=False)


def test_grok_snapshot_resolves_its_default_target_at_call_time(monkeypatch, tmp_path) -> None:
    """Allow tests to redirect the Grok cache without a frozen default argument."""
    target_dir = tmp_path / "grok"
    monkeypatch.setattr(grok_downloader, "GROK_TARGET_DIR", target_dir)

    snapshot = grok_downloader.build_grok_initial_snapshot("v-test")

    assert snapshot.output_dir == str(target_dir)
    assert target_dir.is_dir()


def test_runtime_helpers_preserve_production_defaults_when_unconfigured(monkeypatch, tmp_path) -> None:
    """Keep runtime injection opt-in outside pytest."""
    home_dir = tmp_path / "home"
    monkeypatch.delenv(config.RUNTIME_ROOT_ENV)
    monkeypatch.delenv(config.SETTINGS_PATH_ENV)
    monkeypatch.setenv("HOME", str(home_dir))

    assert config.resolve_runtime_root() == config.PROJECT_ROOT
    assert config.default_settings_path() == (
        home_dir / "Library/Application Support/CacheLikesFromTwitter/settings.json"
    )
