"""Application entrypoint for CacheLikesFromTwitter."""

# Code version: v1.1.0-codex.1

import sys


REQUIRED_PYTHON_VERSION = (3, 13)
REQUIRED_PYTHON_COMMAND = "/usr/local/bin/python3.13"


def _require_supported_python() -> None:
    """Exit before loading Flask when the required interpreter is not active."""
    if sys.version_info[:2] == REQUIRED_PYTHON_VERSION:
        return

    current_version = ".".join(str(component) for component in sys.version_info[:3])
    print(
        "CacheLikesFromTwitter requires Python 3.13; Flask was not started.\n"
        f"Current interpreter: {sys.executable} (Python {current_version}).\n"
        f"Restart from this project with: {REQUIRED_PYTHON_COMMAND} main.py",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _start_web_console() -> None:
    """Load runtime dependencies and start the local web console."""
    from app.core.config import DEFAULT_HOST, DEFAULT_PORT
    from app.core.logging_setup import configure_logging
    from app.core.version import APP_VERSION
    from app.web.app import create_app

    configure_logging(APP_VERSION)
    app = create_app()
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False, threaded=True)


def main() -> None:
    """Start the local web console."""
    _require_supported_python()
    _start_web_console()


if __name__ == "__main__":
    main()
