"""Focused regression tests for the application entrypoint.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import io
import sys
import types
import unittest
from unittest.mock import Mock, patch

import main


class MainEntrypointTests(unittest.TestCase):
    """Validate interpreter protection and the normal startup path."""

    def test_main_rejects_wrong_python_before_starting_flask(self) -> None:
        """A non-3.13 runtime exits without loading the web application."""
        stderr = io.StringIO()

        with (
            patch.object(main.sys, "version_info", (3, 14, 3)),
            patch.object(main.sys, "executable", "/opt/homebrew/bin/python3.14"),
            patch.object(main, "_start_web_console") as start_web_console,
            patch.object(main.sys, "stderr", stderr),
        ):
            with self.assertRaises(SystemExit) as error:
                main.main()

        self.assertEqual(error.exception.code, 1)
        self.assertIn("requires Python 3.13", stderr.getvalue())
        self.assertIn("Flask was not started", stderr.getvalue())
        self.assertIn("/usr/local/bin/python3.13 main.py", stderr.getvalue())
        start_web_console.assert_not_called()

    def test_start_web_console_preserves_existing_flask_configuration(self) -> None:
        """The supported-runtime startup uses the established app settings."""
        configure_logging = Mock()
        create_app = Mock()
        app = Mock()
        create_app.return_value = app
        runtime_modules = {
            "app.core.config": types.SimpleNamespace(DEFAULT_HOST="0.0.0.0", DEFAULT_PORT=8666),
            "app.core.logging_setup": types.SimpleNamespace(configure_logging=configure_logging),
            "app.core.version": types.SimpleNamespace(APP_VERSION="v1.4.0"),
            "app.web.app": types.SimpleNamespace(create_app=create_app),
        }

        with patch.dict(sys.modules, runtime_modules):
            main._start_web_console()

        configure_logging.assert_called_once_with("v1.4.0")
        create_app.assert_called_once_with()
        app.run.assert_called_once_with(host="0.0.0.0", port=8666, debug=False, threaded=True)

    def test_main_starts_web_console_with_python_313(self) -> None:
        """Python 3.13 continues to invoke the normal startup path."""
        with (
            patch.object(main.sys, "version_info", (3, 13, 0)),
            patch.object(main, "_start_web_console") as start_web_console,
        ):
            main.main()

        start_web_console.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
