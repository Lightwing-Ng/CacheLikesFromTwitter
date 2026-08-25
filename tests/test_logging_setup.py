"""Focused regression tests for structured logging setup.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

import json
import logging
import stat
import sys
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
                    self.assertEqual(stat.S_IMODE(log_file.stat().st_mode), 0o600)
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

    def test_formatters_redact_browser_credentials_from_all_rendered_surfaces(
        self,
    ) -> None:
        secrets = {
            "message-access-secret-123",
            "message-json-secret-124",
            "extra-bearer-secret-456",
            "extra-cookie-secret-789",
            "extra-access-secret-012",
            "cause-bearer-secret-345",
            "cause-cookie-secret-678",
            "exception-session-secret-901",
            "stack-cookie-secret-234",
        }
        ordinary_status = (
            "Bearer authentication is ready; Cookie cache refreshed; "
            "session token rotation completed."
        )

        try:
            try:
                raise ValueError(
                    "Playwright Call log:\n"
                    "  - authorization: Bearer cause-bearer-secret-345\n"
                    "  - cookie: __Secure-next-auth.session-token=cause-cookie-secret-678; theme=light"
                )
            except ValueError as cause:
                raise RuntimeError(
                    "Browser response contained sessionToken=exception-session-secret-901"
                ) from cause
        except RuntimeError:
            exception_info = sys.exc_info()

        record = logging.LogRecord(
            name="tests.logging.redaction",
            level=logging.ERROR,
            pathname=__file__,
            lineno=123,
            msg='%s accessToken=%s body={"accessToken":"%s"}',
            args=(
                ordinary_status,
                "message-access-secret-123",
                "message-json-secret-124",
            ),
            exc_info=exception_info,
            func="test_redaction",
        )
        record.stack_info = (
            "Stack (most recent call last):\n"
            "  Set-Cookie: session_token=stack-cookie-secret-234; Path=/; HttpOnly"
        )
        record.request_context = {
            "headers": {
                "Authorization": "Bearer extra-bearer-secret-456",
                "Cookie": "session=extra-cookie-secret-789; theme=light",
            },
            "accessToken": "extra-access-secret-012",
            "status": ordinary_status,
        }

        json_line = logging_setup.JsonFormatter().format(record)
        payload = json.loads(json_line)
        console_line = logging_setup.ConsoleFormatter().format(record)

        for secret in secrets:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, json_line)
                self.assertNotIn(secret, console_line)

        self.assertEqual(
            payload["request_context"]["headers"]["Authorization"], "[REDACTED]"
        )
        self.assertEqual(payload["request_context"]["headers"]["Cookie"], "[REDACTED]")
        self.assertEqual(payload["request_context"]["accessToken"], "[REDACTED]")
        self.assertEqual(payload["request_context"]["status"], ordinary_status)
        self.assertIn("Playwright Call log:", payload["exception"])
        self.assertIn("direct cause", payload["exception"])
        self.assertIn("[REDACTED]", payload["exception"])
        self.assertIn("[REDACTED]", payload["stack"])
        self.assertIn(ordinary_status, payload["message"])
        self.assertIn(ordinary_status, console_line)
        self.assertNotIn("[REDACTED]]", json_line)
        self.assertNotIn("[REDACTED]]", console_line)
        self.assertGreaterEqual(json_line.count("[REDACTED]"), 8)

    def test_configure_logging_tightens_active_and_rotated_files_without_rewriting_them(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_root = Path(temp_dir) / "logs"
            logs_root.mkdir()
            active_log = logs_root / "cachelikes.log.jsonl"
            rotated_log = logs_root / "cachelikes.log.jsonl.1"
            active_content = '{"message":"existing active line"}\n'
            rotated_content = '{"message":"existing rotated line"}\n'
            active_log.write_text(active_content, encoding="utf-8")
            rotated_log.write_text(rotated_content, encoding="utf-8")
            active_log.chmod(0o644)
            rotated_log.chmod(0o644)

            with patch.object(logging_setup, "LOGS_ROOT", logs_root):
                logging_setup._CONFIGURED = False
                root_logger = logging_setup.logging.getLogger()
                original_handlers = list(root_logger.handlers)
                for handler in original_handlers:
                    root_logger.removeHandler(handler)
                    handler.close()

                try:
                    configured_log = logging_setup.configure_logging("test-version")
                    for handler in root_logger.handlers:
                        handler.flush()

                    self.assertEqual(configured_log, active_log)
                    self.assertEqual(stat.S_IMODE(active_log.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(rotated_log.stat().st_mode), 0o600)
                    self.assertTrue(
                        active_log.read_text(encoding="utf-8").startswith(
                            active_content
                        )
                    )
                    self.assertEqual(
                        rotated_log.read_text(encoding="utf-8"), rotated_content
                    )
                finally:
                    current_handlers = list(root_logger.handlers)
                    for handler in current_handlers:
                        root_logger.removeHandler(handler)
                        handler.close()
                    for handler in original_handlers:
                        root_logger.addHandler(handler)
                    logging_setup._CONFIGURED = False

    def test_owner_only_handler_keeps_new_rollovers_at_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "rollover.log.jsonl"
            handler = logging_setup.OwnerOnlyRotatingFileHandler(
                log_file,
                maxBytes=64,
                backupCount=2,
                encoding="utf-8",
            )
            handler.setFormatter(logging_setup.JsonFormatter())
            logger = logging.Logger("tests.logging.rollover")
            logger.addHandler(handler)
            try:
                logger.warning(
                    "First rollover message with enough content to cross the limit."
                )
                logger.warning(
                    "Second rollover message with enough content to cross the limit."
                )
                handler.flush()
            finally:
                handler.close()

            rotated_files = sorted(log_file.parent.glob(f"{log_file.name}.*"))
            self.assertTrue(rotated_files)
            for candidate in [log_file, *rotated_files]:
                with self.subTest(path=candidate.name):
                    self.assertEqual(stat.S_IMODE(candidate.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
