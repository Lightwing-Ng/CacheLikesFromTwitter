"""Tests for bounded local compute, fallback routing, and deterministic publication.

Code version: v1.0.0-codex.1
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

import app.core.compute_backend as compute_backend
from app.core.compute_backend import (
    GPUCapability,
    ImageAnalysisJob,
    ImageAnalysisResult,
    analyze_image_batch,
    analyze_image_paths,
    analyze_image_payload,
    detect_gpu_capability,
)
from app.core.compute_metrics import PerformanceMetrics
from app.core.compute_queue import BoundedWorkQueue, DeterministicCommitCoordinator
from app.core.compute_resources import (
    ComputeResourceSnapshot,
    MAX_CPU_PROCESS_WORKERS,
    discover_compute_resources,
    resolve_cpu_process_workers,
)


def _image_payload(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (48, 32), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_analysis_preserves_legacy_shape_and_rejects_invalid_payload() -> None:
    properties = analyze_image_payload(_image_payload((10, 20, 30)))

    assert properties is not None
    assert len(properties[0]) == 256
    assert properties[1:] == (48, 32)
    assert analyze_image_payload(b"not-an-image") is None


def test_cpu_batch_results_are_deterministic_and_metrics_are_bounded(tmp_path: Path) -> None:
    paths = {
        f"file-{index}": tmp_path / f"image-{index}.png"
        for index in range(3)
    }
    for index, path in enumerate(paths.values()):
        path.write_bytes(_image_payload((index, 20, 40)))

    metrics = PerformanceMetrics()
    result = analyze_image_paths(paths, workers=1, metrics=metrics)

    assert list(result) == ["file-0", "file-1", "file-2"]
    assert all(value is not None for value in result.values())
    assert metrics.snapshot()["image_analysis"]["count"] == 3
    assert metrics.snapshot()["image_analysis"]["backend"] == "cpu"


def test_gpu_partial_batch_is_discarded_and_cpu_recomputes_every_job() -> None:
    jobs = tuple(
        ImageAnalysisJob(f"file-{index}", _image_payload((index, 20, 40)))
        for index in range(16)
    )

    class FakeGPU:
        def capability(self) -> GPUCapability:
            return GPUCapability(available=True, backend="test")

        def analyze(self, submitted_jobs):
            return tuple(
                ImageAnalysisResult(jobs[0].identity, analyze_image_payload(jobs[0].payload))
                for _ in range(1)
            )

    class FakeCPU:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def analyze(self, submitted_jobs, *, workers=None):
            self.calls.append(tuple(job.identity for job in submitted_jobs))
            return tuple(
                ImageAnalysisResult(job.identity, analyze_image_payload(job.payload))
                for job in submitted_jobs
            )

    cpu = FakeCPU()
    result = analyze_image_batch(
        jobs,
        backend_preference="auto",
        cpu_backend=cpu,
        gpu_backend=FakeGPU(),
    )

    assert result.backend == "cpu"
    assert result.gpu_fallback is True
    assert [item.identity for item in result.results] == [job.identity for job in jobs]
    assert cpu.calls == [tuple(job.identity for job in jobs)]


def test_gpu_initialization_failure_uses_a_clean_cpu_recompute() -> None:
    jobs = tuple(
        ImageAnalysisJob(f"file-{index}", _image_payload((index, 20, 40)))
        for index in range(16)
    )

    class BrokenGPU:
        def capability(self) -> GPUCapability:
            raise RuntimeError("driver initialization failed")

        def analyze(self, _jobs):
            raise AssertionError("analyze must not run after initialization failure")

    result = analyze_image_batch(jobs, backend_preference="gpu", gpu_backend=BrokenGPU())

    assert result.backend == "cpu"
    assert result.gpu_fallback is True
    assert len(result.results) == len(jobs)


@pytest.mark.parametrize("failure", ["duplicate", "unknown", "oom"])
def test_gpu_batch_integrity_failures_always_recompute_the_complete_batch(failure: str) -> None:
    jobs = tuple(
        ImageAnalysisJob(f"file-{index}", _image_payload((index, 20, 40)))
        for index in range(16)
    )

    class BrokenGPU:
        def capability(self) -> GPUCapability:
            return GPUCapability(available=True, backend="test")

        def analyze(self, submitted_jobs):
            if failure == "oom":
                raise MemoryError("simulated GPU OOM")
            if failure == "duplicate":
                return (
                    ImageAnalysisResult(submitted_jobs[0].identity, analyze_image_payload(submitted_jobs[0].payload)),
                    ImageAnalysisResult(submitted_jobs[0].identity, analyze_image_payload(submitted_jobs[0].payload)),
                )
            return (
                ImageAnalysisResult("unknown-file", analyze_image_payload(submitted_jobs[0].payload)),
            )

    class RecordingCPU:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def analyze(self, submitted_jobs, *, workers=None):
            self.calls.append(tuple(job.identity for job in submitted_jobs))
            return tuple(
                ImageAnalysisResult(job.identity, analyze_image_payload(job.payload))
                for job in submitted_jobs
            )

    cpu = RecordingCPU()
    result = analyze_image_batch(
        jobs,
        backend_preference="auto",
        cpu_backend=cpu,
        gpu_backend=BrokenGPU(),
    )

    assert result.backend == "cpu"
    assert result.gpu_fallback is True
    assert [item.identity for item in result.results] == [job.identity for job in jobs]
    assert cpu.calls == [tuple(job.identity for job in jobs)]


def test_cpu_worker_failure_recomputes_the_complete_batch_in_parent() -> None:
    jobs = tuple(
        ImageAnalysisJob(f"file-{index}", _image_payload((index, 20, 40)))
        for index in range(2)
    )

    class BrokenCPU:
        def analyze(self, _jobs, *, workers=None):
            raise RuntimeError("worker crashed")

    result = analyze_image_batch(jobs, cpu_backend=BrokenCPU())

    assert result.worker_recovery is True
    assert [item.identity for item in result.results] == ["file-0", "file-1"]


def test_gpu_capability_is_unavailable_in_the_base_install() -> None:
    capability = detect_gpu_capability()

    assert capability.available is False
    assert "optional" in capability.reason.lower()


def test_metrics_reject_unbounded_stage_and_backend_labels() -> None:
    metrics = PerformanceMetrics()

    with pytest.raises(ValueError, match="stage"):
        metrics.record_stage(
            "/private/path",
            count=1,
            wall_seconds=0,
            cpu_seconds=0,
        )
    with pytest.raises(ValueError, match="backend"):
        metrics.record_stage(
            "image_analysis",
            count=1,
            wall_seconds=0,
            cpu_seconds=0,
            backend="provider-response",
        )


def test_resource_discovery_and_worker_resolution_have_hard_limits() -> None:
    resources = discover_compute_resources(
        logical_cpu_count=64,
        physical_cpu_count=32,
        memory_bytes=8 * 1024 * 1024 * 1024,
    )

    assert resources.cpu_process_workers == MAX_CPU_PROCESS_WORKERS
    assert resources.max_in_flight_bytes == 256 * 1024 * 1024
    assert resolve_cpu_process_workers(10_000, workload_size=100, resources=resources) == MAX_CPU_PROCESS_WORKERS
    assert resolve_cpu_process_workers(8, workload_size=1, resources=resources) == 1


def test_bounded_queue_applies_capacity_and_stop() -> None:
    queue = BoundedWorkQueue[str](1)

    assert queue.put("first") is True
    assert queue.qsize() == 1
    assert queue.put("second", should_stop=lambda: True) is False
    assert queue.get_nowait() == "first"


def test_in_flight_payload_budget_flushes_before_oversized_parent_analysis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resources = ComputeResourceSnapshot(
        logical_cpu_count=1,
        physical_cpu_count=1,
        memory_bytes=1,
        cpu_process_workers=1,
        max_in_flight_bytes=8,
    )
    small_path = tmp_path / "small.bin"
    oversized_path = tmp_path / "oversized.bin"
    small_path.write_bytes(b"small")
    oversized_path.write_bytes(b"oversized")
    submitted_batches: list[tuple[str, ...]] = []
    parent_paths: list[Path] = []

    def fake_batch(jobs, **_kwargs):
        submitted_batches.append(tuple(job.identity for job in jobs))
        return compute_backend.ImageBatchResult(
            tuple(ImageAnalysisResult(job.identity, None) for job in jobs),
            "cpu",
        )

    monkeypatch.setattr(compute_backend, "analyze_image_batch", fake_batch)
    monkeypatch.setattr(
        compute_backend,
        "analyze_image_path",
        lambda path: parent_paths.append(path) or ("parent", 1, 1),
    )

    result = analyze_image_paths(
        {"small": small_path, "oversized": oversized_path},
        resources=resources,
    )

    assert submitted_batches == [("small",)]
    assert parent_paths == [oversized_path]
    assert result == {"small": None, "oversized": ("parent", 1, 1)}


def test_commit_coordinator_deduplicates_and_releases_in_stable_order() -> None:
    committed: list[tuple[str, str]] = []
    coordinator = DeterministicCommitCoordinator(
        ["first", "second", "third"],
        commit=lambda identity, result: committed.append((identity, result)),
    )

    assert coordinator.submit("third", "C") is True
    assert coordinator.drain_ready() == ()
    assert coordinator.submit("first", "A") is True
    assert coordinator.submit("first", "duplicate") is False
    assert coordinator.submit("second", "B") is True

    assert coordinator.drain_ready() == (("first", "A"), ("second", "B"), ("third", "C"))
    assert committed == [("first", "A"), ("second", "B"), ("third", "C")]
    assert coordinator.pending_count == 0
