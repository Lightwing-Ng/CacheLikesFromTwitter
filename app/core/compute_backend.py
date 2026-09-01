"""Pure local image-analysis backends with optional GPU fallback routing."""

# Code version: v1.1.0-codex.1

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import io
import logging
from multiprocessing import get_context
import os
from pathlib import Path
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from .compute_metrics import PerformanceMetrics
from .compute_queue import DeterministicCommitCoordinator
from .compute_resources import (
    ComputeResourceSnapshot,
    discover_compute_resources,
    resolve_cpu_process_workers,
)


logger = logging.getLogger(__name__)

VISUAL_HASH_WIDTH = 32
VISUAL_HASH_HEIGHT = 32
MIN_PARALLEL_IMAGE_JOBS = 64
MAX_IMAGE_BATCH_JOBS = 64
GPU_MIN_IMAGE_JOBS = 16


@dataclass(frozen=True, slots=True)
class ImageAnalysisJob:
    """Carry immutable image bytes into a compute worker."""

    identity: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class ImageAnalysisResult:
    """Return one bounded image-analysis envelope from a worker."""

    identity: str
    properties: tuple[str, int, int] | None


@dataclass(frozen=True, slots=True)
class GPUCapability:
    """Describe a GPU adapter without importing an optional framework."""

    available: bool
    backend: str = ""
    reason: str = ""


class GPUImageAnalysisAdapter(Protocol):
    """Protocol for an explicitly injected, benchmarked optional GPU adapter."""

    def capability(self) -> GPUCapability:
        """Return current capability state."""

    def analyze(self, jobs: Sequence[ImageAnalysisJob]) -> Sequence[ImageAnalysisResult]:
        """Analyze one complete batch without writing durable application state."""


@dataclass(frozen=True, slots=True)
class ImageBatchResult:
    """Capture ordered results and the fallback path used for one batch."""

    results: tuple[ImageAnalysisResult, ...]
    backend: str
    gpu_fallback: bool = False
    worker_recovery: bool = False
    workers_used: int = 1


def detect_gpu_capability() -> GPUCapability:
    """Return the safe base-install capability state.

    No GPU framework is a base dependency and no backend is advertised until an
    independently installed adapter is injected and benchmarked.
    """
    return GPUCapability(
        available=False,
        reason="No optional GPU image-analysis adapter is installed.",
    )


def _visual_properties_from_source(source: Image.Image) -> tuple[str, int, int]:
    """Calculate visual properties from an already opened image source."""
    image = ImageOps.exif_transpose(source)
    width, height = image.size
    grayscale = image.convert("L").resize(
        (VISUAL_HASH_WIDTH + 1, VISUAL_HASH_HEIGHT),
        Image.Resampling.LANCZOS,
    )
    pixels = grayscale.tobytes()
    signature = 0
    row_width = VISUAL_HASH_WIDTH + 1
    for row in range(VISUAL_HASH_HEIGHT):
        row_start = row * row_width
        for column in range(VISUAL_HASH_WIDTH):
            signature = (signature << 1) | int(
                pixels[row_start + column + 1] > pixels[row_start + column]
            )
    return f"{signature:0{(VISUAL_HASH_WIDTH * VISUAL_HASH_HEIGHT) // 4}x}", width, height


def analyze_image_payload(payload: bytes) -> tuple[str, int, int] | None:
    """Decode one image payload and calculate the same stable dHash as ChatGPT."""
    try:
        with Image.open(io.BytesIO(payload)) as source:
            return _visual_properties_from_source(source)
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError):
        return None


def analyze_image_path(path: Path) -> tuple[str, int, int] | None:
    """Analyze one parent-owned path without materializing an oversized payload."""
    try:
        with Image.open(path) as source:
            return _visual_properties_from_source(source)
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError):
        return None


def _analyze_image_job(job: ImageAnalysisJob) -> ImageAnalysisResult:
    """Analyze one immutable job in either the parent or a process worker."""
    return ImageAnalysisResult(job.identity, analyze_image_payload(job.payload))


class CPUImageAnalysisBackend:
    """Use direct CPU work for small batches and bounded processes for larger ones."""

    def __init__(self, resources: ComputeResourceSnapshot | None = None) -> None:
        self.resources = resources or discover_compute_resources()

    def analyze(
        self,
        jobs: Sequence[ImageAnalysisJob],
        *,
        workers: int | None = None,
    ) -> tuple[ImageAnalysisResult, ...]:
        """Analyze jobs in input order without sharing application state."""
        materialized = tuple(jobs)
        if not materialized:
            return ()
        worker_count = resolve_cpu_process_workers(
            workers,
            workload_size=len(materialized),
            resources=self.resources,
        )
        if worker_count <= 1 or len(materialized) < MIN_PARALLEL_IMAGE_JOBS:
            return tuple(_analyze_image_job(job) for job in materialized)

        context = get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=context,
        ) as executor:
            return tuple(executor.map(_analyze_image_job, materialized, chunksize=1))


def _ordered_complete_results(
    identities: Iterable[str],
    results: Sequence[ImageAnalysisResult],
) -> tuple[ImageAnalysisResult, ...]:
    """Validate and order a backend envelope before any caller can use it."""
    expected = tuple(dict.fromkeys(str(identity) for identity in identities))
    coordinator = DeterministicCommitCoordinator[ImageAnalysisResult](expected)
    for result in results:
        if not isinstance(result, ImageAnalysisResult):
            raise ValueError("Image backend returned an invalid result envelope.")
        if not coordinator.submit(result.identity, result):
            raise ValueError("Image backend returned a duplicate or unknown result identity.")
    if coordinator.committed_count != len(expected):
        ready = coordinator.drain_ready()
        if len(ready) != len(expected):
            raise ValueError("Image backend returned a partial result batch.")
    else:
        ready = coordinator.drain_ready()
    return tuple(result for _identity, result in ready)


def analyze_image_batch(
    jobs: Sequence[ImageAnalysisJob],
    *,
    workers: int | None = None,
    backend_preference: str = "cpu",
    cpu_backend: CPUImageAnalysisBackend | None = None,
    gpu_backend: GPUImageAnalysisAdapter | None = None,
) -> ImageBatchResult:
    """Analyze one bounded batch and recompute it fully on CPU after GPU failure."""
    materialized = tuple(jobs)
    if not materialized:
        return ImageBatchResult((), "cpu")

    cpu = cpu_backend or CPUImageAnalysisBackend()
    use_gpu = backend_preference in {"auto", "gpu"} and gpu_backend is not None
    gpu_fallback = False
    if use_gpu:
        try:
            capability = gpu_backend.capability()
        except Exception:
            capability = GPUCapability(available=True, backend="unknown")
            gpu_fallback = True
        if capability.available and len(materialized) >= GPU_MIN_IMAGE_JOBS and not gpu_fallback:
            try:
                gpu_results = _ordered_complete_results(
                    (job.identity for job in materialized),
                    gpu_backend.analyze(materialized),
                )
            except Exception:
                gpu_fallback = True
                logger.warning(
                    "GPU image-analysis batch failed; discarding it and recomputing on CPU.",
                    extra={"stage": "image_analysis", "fallback": "cpu"},
                )
            else:
                return ImageBatchResult(gpu_results, "gpu")

    worker_recovery = False
    cpu_worker_count = (
        resolve_cpu_process_workers(
            workers,
            workload_size=len(materialized),
            resources=cpu.resources,
        )
        if isinstance(cpu, CPUImageAnalysisBackend)
        else 1
    )
    cpu_workers_used = (
        cpu_worker_count
        if cpu_worker_count > 1 and len(materialized) >= MIN_PARALLEL_IMAGE_JOBS
        else 1
    )
    try:
        cpu_results = cpu.analyze(materialized, workers=workers)
        ordered_cpu_results = _ordered_complete_results(
            (job.identity for job in materialized),
            cpu_results,
        )
    except Exception:
        worker_recovery = True
        logger.warning(
            "CPU image-analysis worker failed; recomputing the complete batch in the parent.",
            extra={"stage": "image_analysis", "fallback": "cpu-parent"},
        )
        ordered_cpu_results = _ordered_complete_results(
            (job.identity for job in materialized),
            tuple(_analyze_image_job(job) for job in materialized),
        )
        cpu_workers_used = 1
    return ImageBatchResult(
        ordered_cpu_results,
        "cpu",
        workers_used=cpu_workers_used,
        gpu_fallback=gpu_fallback,
        worker_recovery=worker_recovery,
    )


def analyze_image_paths(
    paths_by_identity: Mapping[str, Path],
    *,
    workers: int | None = None,
    backend_preference: str = "cpu",
    gpu_backend: GPUImageAnalysisAdapter | None = None,
    resources: ComputeResourceSnapshot | None = None,
    metrics: PerformanceMetrics | None = None,
) -> dict[str, tuple[str, int, int] | None]:
    """Read bounded payload batches and stream oversized files through the parent."""
    resource_snapshot = resources or discover_compute_resources()
    cpu_backend = CPUImageAnalysisBackend(resource_snapshot)
    results: dict[str, tuple[str, int, int] | None] = {}
    batch: list[ImageAnalysisJob] = []
    batch_bytes = 0

    def record_single_path(identity: str, path: Path) -> None:
        """Analyze an oversized or concurrently changed file without a payload batch."""
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        results[identity] = analyze_image_path(path)
        if metrics is not None:
            metrics.record_stage(
                "image_analysis",
                count=1,
                wall_seconds=time.perf_counter() - wall_start,
                cpu_seconds=time.process_time() - cpu_start,
                workers=1,
                backend="cpu",
            )

    def flush() -> None:
        nonlocal batch, batch_bytes
        if not batch:
            return
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        batch_result = analyze_image_batch(
            batch,
            workers=workers,
            backend_preference=backend_preference,
            cpu_backend=cpu_backend,
            gpu_backend=gpu_backend,
        )
        if metrics is not None:
            metrics.record_stage(
                "image_analysis",
                count=len(batch_result.results),
                wall_seconds=time.perf_counter() - wall_start,
                cpu_seconds=time.process_time() - cpu_start,
                workers=batch_result.workers_used,
                backend=batch_result.backend,
                gpu_fallback=batch_result.gpu_fallback,
                worker_recovery=batch_result.worker_recovery,
            )
        results.update({result.identity: result.properties for result in batch_result.results})
        batch = []
        batch_bytes = 0

    for identity, path in sorted(paths_by_identity.items(), key=lambda item: str(item[0])):
        identity = str(identity)
        resolved_path = Path(path)
        try:
            with resolved_path.open("rb") as handle:
                file_size = os.fstat(handle.fileno()).st_size
        except (OSError, ValueError):
            results[identity] = None
            continue
        if file_size < 0:
            results[identity] = None
            continue
        if batch and batch_bytes + file_size > resource_snapshot.max_in_flight_bytes:
            flush()
        if file_size > resource_snapshot.max_in_flight_bytes:
            record_single_path(identity, resolved_path)
            continue
        try:
            with resolved_path.open("rb") as handle:
                payload = handle.read(file_size)
        except OSError:
            flush()
            record_single_path(identity, resolved_path)
            continue
        if len(payload) != file_size:
            flush()
            record_single_path(identity, resolved_path)
            continue
        batch.append(ImageAnalysisJob(identity, payload))
        batch_bytes += len(payload)
        if len(batch) >= MAX_IMAGE_BATCH_JOBS:
            flush()
    flush()
    return results


__all__ = [
    "CPUImageAnalysisBackend",
    "GPUCapability",
    "GPUImageAnalysisAdapter",
    "ImageAnalysisJob",
    "ImageAnalysisResult",
    "ImageBatchResult",
    "analyze_image_batch",
    "analyze_image_path",
    "analyze_image_paths",
    "analyze_image_payload",
    "detect_gpu_capability",
]
