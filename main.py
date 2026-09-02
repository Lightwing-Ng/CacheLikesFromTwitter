"""Application entrypoint for agenticContext."""

# Code version: v1.2.1-codex.1

def _start_web_console() -> None:
    """Start the local web console with the resolved host Python runtime."""
    from app.core.config import DEFAULT_HOST, DEFAULT_PORT
    from app.core.logging_setup import configure_logging
    from app.core.version import APP_VERSION
    from app.web.app import create_app

    configure_logging(APP_VERSION)
    app = create_app()
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False, threaded=True)


def main() -> None:
    """Start the local web console."""
    _start_web_console()


if __name__ == "__main__":
    main()
