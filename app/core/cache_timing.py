"""Cooperative pacing for provider-specific cache scans.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_for_cache_scan(
    seconds: float,
    should_stop: Callable[[], bool],
    wait: Callable[[float], None] | None = None,
) -> bool:
    """Wait between scans while honoring stop requests within 250 milliseconds."""
    wait = wait or time.sleep
    remaining = max(0.0, seconds)
    while remaining > 0:
        if should_stop():
            return True
        interval = min(0.25, remaining)
        wait(interval)
        remaining -= interval
    return should_stop()
