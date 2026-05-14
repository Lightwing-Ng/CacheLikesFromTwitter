# CacheLikesFromTwitter

Version: `v1.1.0`

This project starts a local web console on `http://127.0.0.1:8666` and caches media from the
currently logged-in X account's likes timeline into `local_store/<account_name>/`.

## Quick Start

```bash
/usr/local/bin/python3.13 -m pip install -r requirements.txt
/usr/local/bin/python3.13 -m playwright install chromium
```

Then open the project in PyCharm and run the shared `main` configuration with your system
`Python 3.13` interpreter.

## Notes

- The first run works best when normal Chrome windows are closed.
- The default Chrome profile path is macOS `~/Library/Application Support/Google/Chrome`.
- Media download relies on `yt-dlp --cookies-from-browser chrome`.
