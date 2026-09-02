"""Regression tests for the application-to-core dependency boundary."""

# Code version: v1.0.1-codex.1

from __future__ import annotations

import ast
from pathlib import Path


def test_web_app_imports_core_through_domain_facades() -> None:
    """Keep the Flask layer independent from the flat core implementation modules."""
    source_path = Path(__file__).resolve().parents[1] / "app/web/app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    core_imports = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("app.core")
    }

    assert core_imports == {
        "app.core.agent",
        "app.core.browser",
        "app.core.foundation",
        "app.core.providers",
        "app.core.storage",
    }
