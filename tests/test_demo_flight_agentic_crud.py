"""Controller integration coverage against a copied Global Flight Atlas workspace.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

import pytest

from app.core.computer_use_agent import ComputerUseSettings, WorkspaceController


DEMO_FLIGHT_ROOT = Path("/Users/lightwing/Desktop/demo_flight")
DEMO_FLIGHT_FILES = (
    "README.md",
    "app.js",
    "index.html",
    "serve.py",
    "styles.css",
    "test_verify.py",
    "verify.py",
)


@pytest.mark.integration
def test_copied_demo_flight_supports_safe_agentic_crud_and_cold_verification() -> None:
    """Use the real demo as immutable input and exercise the controller end-to-end."""
    if not DEMO_FLIGHT_ROOT.is_dir():
        pytest.skip("The local demo_flight acceptance project is unavailable.")

    source_readme = DEMO_FLIGHT_ROOT / "README.md"
    source_digest = hashlib.sha256(source_readme.read_bytes()).hexdigest()

    with TemporaryDirectory(prefix="demo-flight-agentic-") as raw_workspace:
        workspace = Path(raw_workspace) / "demo_flight"
        workspace.mkdir()
        for name in DEMO_FLIGHT_FILES:
            shutil.copy2(DEMO_FLIGHT_ROOT / name, workspace / name)

        controller = WorkspaceController(
            workspace,
            ComputerUseSettings(
                workspace_path=str(workspace),
                command_timeout_seconds=30,
            ),
            lambda: False,
        )

        listed = controller.execute({"action": "list", "path": ".", "depth": 1})
        assert listed["ok"]
        assert set(DEMO_FLIGHT_FILES).issubset(set(listed["entries"]))

        readme = controller.execute({"action": "read", "path": "README.md"})
        assert readme["ok"]
        assert readme["sha256"] == source_digest
        assert "Global Flight Atlas" in readme["content"]

        replaced = controller.execute(
            {
                "action": "replace",
                "path": "README.md",
                "old": "production-oriented",
                "new": "agent-verified",
            }
        )
        assert replaced == {
            "ok": True,
            "action": "replace",
            "path": "README.md",
            "changed_characters": -5,
        }

        written = controller.execute(
            {
                "action": "write",
                "path": "agentic-evidence.txt",
                "content": "Temporary controller evidence only.\n",
            }
        )
        assert written["ok"]
        evidence = controller.execute({"action": "read", "path": "agentic-evidence.txt"})
        assert evidence["ok"]
        assert re.fullmatch(r"[0-9a-f]{64}", str(evidence["sha256"]))

        rejected_delete = controller.execute(
            {
                "action": "delete",
                "path": "agentic-evidence.txt",
                "expected_sha256": "0" * 64,
            }
        )
        assert not rejected_delete["ok"]
        assert "SHA-256" in rejected_delete["error"]

        deleted = controller.execute(
            {
                "action": "delete",
                "path": "agentic-evidence.txt",
                "expected_sha256": evidence["sha256"],
            }
        )
        assert deleted == {
            "ok": True,
            "action": "delete",
            "path": "agentic-evidence.txt",
            "deleted_bytes": len("Temporary controller evidence only.\n".encode()),
        }
        assert not (workspace / "agentic-evidence.txt").exists()

        verification = controller.execute(
            {
                "action": "run",
                "command": "python3.13 -m unittest -v test_verify.py",
            }
        )
        assert verification["ok"], verification["output"]
        assert verification["exit_code"] == 0
        assert not verification["mutated_workspace"]
        assert "OK" in verification["output"]

        bodycheck = controller.execute({"action": "bodycheck"})
        assert bodycheck["ok"]
        assert bodycheck["verification_current"]
        assert bodycheck["bodycheck_current"]

    assert hashlib.sha256(source_readme.read_bytes()).hexdigest() == source_digest
