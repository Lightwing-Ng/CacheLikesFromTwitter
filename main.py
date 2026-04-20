"""Application entrypoint for CacheLikesFromTwitter."""

from app.web.app import create_app


def main() -> None:
    """Start the local web console."""
    app = create_app()
    app.run(host="127.0.0.1", port=8666, debug=False, threaded=True)


if __name__ == "__main__":
    main()
