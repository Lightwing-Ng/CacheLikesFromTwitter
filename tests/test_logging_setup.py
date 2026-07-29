"""Focused regression tests for structured logging setup.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import json
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

from app.core import logging_setup


class LoggingSetupTests(unittest.TestCase):
    """Validate log file creation and JSON line output."""

    def test_configure_logging_creates_json_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_root = Path(temp_dir) / "logs"
            with patch.object(logging_setup, "LOGS_ROOT", logs_root):
                logging_setup._CONFIGURED = False
                root_logger = logging_setup.logging.getLogger()
                original_handlers = list(root_logger.handlers)
                for handler in original_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()

                try:
                    log_file = logging_setup.configure_logging("test-version")
                    logger = logging_setup.logging.getLogger("tests.logging")
                    logger.info("Structured log smoke test.", extra={"probe": "ok"})
                    for handler in logging_setup.logging.getLogger().handlers:
                        if isinstance(handler, RotatingFileHandler):
                            handler.flush()

                    self.assertTrue(log_file.exists())
                    payload = json.loads(log_file.read_text(encoding="utf-8").splitlines()[-1])
                    self.assertEqual(payload["message"], "Structured log smoke test.")
                    self.assertEqual(payload["probe"], "ok")
                finally:
                    current_handlers = list(root_logger.handlers)
                    for handler in current_handlers:
                        root_logger.removeHandler(handler)
                        handler.close()
                    for handler in original_handlers:
                        root_logger.addHandler(handler)
                    logging_setup._CONFIGURED = False


if __name__ == "__main__":
    unittest.main()
