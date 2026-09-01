"""Bounded, privacy-safe metrics for local compute stages."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from threading import Lock


@dataclass(slots=True)
class _StageAccumulator:
    count: int = 0
    wall_seconds: float = 0.0
    cpu_seconds: float = 0.0
    max_workers: int = 1
    max_queue_depth: int = 0
    backend_counts: Counter[str] = field(default_factory=Counter)
    gpu_fallback_batches: int = 0
    worker_recovery_batches: int = 0


class PerformanceMetrics:
    """Collect only fixed stage names and numeric execution measurements."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._stages: dict[str, _StageAccumulator] = {}

    def record_stage(
        self,
        stage: str,
        *,
        count: int,
        wall_seconds: float,
        cpu_seconds: float,
        workers: int = 1,
        queue_depth: int = 0,
        backend: str = "cpu",
        gpu_fallback: bool = False,
        worker_recovery: bool = False,
    ) -> None:
        """Add one bounded numeric observation to a stage accumulator."""
        with self._lock:
            accumulator = self._stages.setdefault(stage, _StageAccumulator())
            accumulator.count += max(0, int(count))
            accumulator.wall_seconds += max(0.0, float(wall_seconds))
            accumulator.cpu_seconds += max(0.0, float(cpu_seconds))
            accumulator.max_workers = max(accumulator.max_workers, max(1, int(workers)))
            accumulator.max_queue_depth = max(accumulator.max_queue_depth, max(0, int(queue_depth)))
            accumulator.backend_counts[str(backend)] += 1
            accumulator.gpu_fallback_batches += int(bool(gpu_fallback))
            accumulator.worker_recovery_batches += int(bool(worker_recovery))

    @property
    def has_data(self) -> bool:
        """Return whether any stage has recorded an observation."""
        with self._lock:
            return bool(self._stages)

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Return JSON-safe stage metrics without paths or payload contents."""
        with self._lock:
            result: dict[str, dict[str, object]] = {}
            for stage, accumulator in sorted(self._stages.items()):
                backends = sorted(accumulator.backend_counts)
                result[stage] = {
                    "count": accumulator.count,
                    "wall_seconds": round(accumulator.wall_seconds, 6),
                    "cpu_seconds": round(accumulator.cpu_seconds, 6),
                    "workers": accumulator.max_workers,
                    "queue_depth": accumulator.max_queue_depth,
                    "backend": backends[0] if len(backends) == 1 else "mixed",
                    "gpu_fallback_batches": accumulator.gpu_fallback_batches,
                    "worker_recovery_batches": accumulator.worker_recovery_batches,
                }
            return result
