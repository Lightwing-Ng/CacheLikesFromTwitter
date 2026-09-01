"""Bounded compute queues and deterministic result publication."""

# Code version: v1.1.0-codex.1

from __future__ import annotations

from collections.abc import Callable, Iterable
from queue import Empty, Full, Queue
from typing import Generic, TypeVar


T = TypeVar("T")


class BoundedWorkQueue(Generic[T]):
    """Wrap ``queue.Queue`` with cooperative stop-aware backpressure."""

    def __init__(self, maxsize: int) -> None:
        self._queue: Queue[T] = Queue(maxsize=max(1, int(maxsize)))

    @property
    def maxsize(self) -> int:
        """Return the hard queue capacity."""
        return self._queue.maxsize

    def put(self, item: T, *, should_stop: Callable[[], bool] | None = None) -> bool:
        """Put one item or return false when cooperative cancellation is requested."""
        while True:
            if should_stop is not None and should_stop():
                return False
            try:
                self._queue.put(item, timeout=0.2)
                return True
            except Full:
                continue

    def get(self, timeout: float | None = None) -> T:
        """Get one item using the standard queue timeout semantics."""
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> T:
        """Get one item without waiting."""
        return self._queue.get_nowait()

    def task_done(self) -> None:
        """Mark one queue item as processed."""
        self._queue.task_done()

    def qsize(self) -> int:
        """Return the approximate current queue depth."""
        return self._queue.qsize()

    def empty(self) -> bool:
        """Return whether the queue is currently empty."""
        return self._queue.empty()


class DeterministicCommitCoordinator(Generic[T]):
    """Release out-of-order results in one stable identity order exactly once."""

    def __init__(self, identities: Iterable[str], commit: Callable[[str, T], None] | None = None) -> None:
        self._identities = tuple(dict.fromkeys(str(identity) for identity in identities))
        self._identity_set = set(self._identities)
        self._pending: dict[str, T] = {}
        self._committed: set[str] = set()
        self._next_index = 0
        self._commit = commit

    def submit(self, identity: str, result: T) -> bool:
        """Accept one known identity, ignoring duplicate or unknown completions."""
        key = str(identity)
        if key not in self._identity_set or key in self._pending or key in self._committed:
            return False
        self._pending[key] = result
        return True

    def drain_ready(self) -> tuple[tuple[str, T], ...]:
        """Return contiguous ready results and invoke the optional commit callback."""
        ready: list[tuple[str, T]] = []
        while self._next_index < len(self._identities):
            identity = self._identities[self._next_index]
            if identity not in self._pending:
                break
            result = self._pending.pop(identity)
            self._committed.add(identity)
            self._next_index += 1
            if self._commit is not None:
                self._commit(identity, result)
            ready.append((identity, result))
        return tuple(ready)

    @property
    def pending_count(self) -> int:
        """Return the number of submitted results waiting behind a gap."""
        return len(self._pending)

    @property
    def committed_count(self) -> int:
        """Return the number of identities released so far."""
        return len(self._committed)


__all__ = ["BoundedWorkQueue", "DeterministicCommitCoordinator", "Empty"]
