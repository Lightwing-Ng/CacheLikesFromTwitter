"""Application entrypoint for CacheLikesFromTwitter."""

# Code version: v1.0.1-codex.1

from app.core.logging_setup import configure_logging
from app.core.config import DEFAULT_HOST, DEFAULT_PORT
from app.core.version import APP_VERSION
from app.web.app import create_app


def main() -> None:
    """Start the local web console."""
    configure_logging(APP_VERSION)
    app = create_app()
    app.run(host=DEFAULT_HOST, port=DEFAULT_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
