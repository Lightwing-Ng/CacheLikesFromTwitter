"""Repeatable synthetic benchmark for the local image-analysis stage.

Code version: v1.0.2-codex.1
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIXTURE_IMAGE_COUNT = max(
    1,
    int(
        os.environ.get(
            "AGENTIC_CONTEXT_BENCHMARK_IMAGE_COUNT",
            os.environ.get("CACHELIKES_BENCHMARK_IMAGE_COUNT", "32"),
        )
    ),
)
FIXTURE_SIZE = (1_024, 1_024)
WARMUP_RUNS = 1
MEASURED_RUNS = 5


def _build_fixture(root: Path) -> list[Path]:
    """Create deterministic image inputs in an isolated temporary directory."""
    paths: list[Path] = []
    for index in range(FIXTURE_IMAGE_COUNT):
        path = root / f"fixture-{index}.png"
        image = Image.new(
            "RGB",
            FIXTURE_SIZE,
            (index * 7 % 255, index * 13 % 255, index * 29 % 255),
        )
        image.save(path, format="PNG", compress_level=1)
        paths.append(path)
    return paths


def _measure(callable_, runs: int = MEASURED_RUNS) -> dict[str, object]:
    """Measure a fixed callable after one explicit warmup phase."""
    for _ in range(WARMUP_RUNS):
        callable_()
    wall_seconds: list[float] = []
    cpu_seconds: list[float] = []
    for _ in range(runs):
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        callable_()
        wall_seconds.append(time.perf_counter() - wall_start)
        cpu_seconds.append(time.process_time() - cpu_start)
    return {
        "wall_seconds": [round(value, 6) for value in wall_seconds],
        "wall_median_seconds": round(statistics.median(wall_seconds), 6),
        "cpu_seconds": [round(value, 6) for value in cpu_seconds],
        "cpu_median_seconds": round(statistics.median(cpu_seconds), 6),
    }


def main() -> None:
    """Run before/after-compatible measurements without production paths."""
    from app.core.chatgpt_downloader import chatgpt_visual_properties
    from app.core.compute_backend import analyze_image_paths
    from app.core.compute_metrics import PerformanceMetrics
    from app.core.compute_resources import discover_compute_resources

    with tempfile.TemporaryDirectory(prefix="agenticContext-compute-benchmark-") as temporary_root:
        paths = _build_fixture(Path(temporary_root))
        before = _measure(lambda: [chatgpt_visual_properties(path) for path in paths])
        path_map = {str(index): path for index, path in enumerate(paths)}
        last_after_metrics: dict[str, dict[str, object]] = {}

        def measure_bounded_backend() -> None:
            metrics = PerformanceMetrics()
            analyze_image_paths(path_map, metrics=metrics)
            last_after_metrics.clear()
            last_after_metrics.update(metrics.snapshot())

        after = _measure(measure_bounded_backend)
    print(
        json.dumps(
            {
                "fixture_images": FIXTURE_IMAGE_COUNT,
                "fixture_size": list(FIXTURE_SIZE),
                "warmup_runs": WARMUP_RUNS,
                "measured_runs": MEASURED_RUNS,
                "resources": {
                    "logical_cpu_count": discover_compute_resources().logical_cpu_count,
                    "cpu_process_workers": discover_compute_resources().cpu_process_workers,
                    "max_in_flight_bytes": discover_compute_resources().max_in_flight_bytes,
                },
                "before_legacy_sequential": before,
                "after_bounded_cpu_backend": after,
                "after_backend_metrics": last_after_metrics,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
