"""Conservative local resource discovery for optional compute stages."""

# Code version: v1.0.0-codex.1

from __future__ import annotations

import os
from dataclasses import dataclass


MAX_CPU_PROCESS_WORKERS = 8
MIN_COMPUTE_IN_FLIGHT_BYTES = 16 * 1024 * 1024
DEFAULT_COMPUTE_IN_FLIGHT_BYTES = 128 * 1024 * 1024
MAX_COMPUTE_IN_FLIGHT_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ComputeResourceSnapshot:
    """Describe safe budgets discovered without adding a runtime dependency."""

    logical_cpu_count: int
    physical_cpu_count: int | None
    memory_bytes: int | None
    cpu_process_workers: int
    max_in_flight_bytes: int


def _physical_memory_bytes() -> int | None:
    """Read physical memory when the host exposes POSIX sysconf values."""
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
    if page_size <= 0 or page_count <= 0:
        return None
    return page_size * page_count


def _bounded_process_workers(logical_cpu_count: int, physical_cpu_count: int | None) -> int:
    """Reserve one core where possible and cap process fan-out globally."""
    usable_cpu_count = physical_cpu_count or logical_cpu_count
    if usable_cpu_count <= 2:
        return 1
    return max(1, min(MAX_CPU_PROCESS_WORKERS, usable_cpu_count - 1))


def discover_compute_resources(
    *,
    logical_cpu_count: int | None = None,
    physical_cpu_count: int | None = None,
    memory_bytes: int | None = None,
) -> ComputeResourceSnapshot:
    """Return conservative CPU and memory budgets with safe fallback values."""
    detected_logical = logical_cpu_count if logical_cpu_count is not None else os.cpu_count()
    logical = max(1, int(detected_logical or 1))
    physical = (
        max(1, int(physical_cpu_count))
        if physical_cpu_count is not None and int(physical_cpu_count) > 0
        else None
    )
    detected_memory = memory_bytes if memory_bytes is not None else _physical_memory_bytes()
    memory = max(1, int(detected_memory)) if detected_memory is not None and int(detected_memory) > 0 else None
    if memory is None:
        in_flight_bytes = DEFAULT_COMPUTE_IN_FLIGHT_BYTES
    else:
        in_flight_bytes = min(
            MAX_COMPUTE_IN_FLIGHT_BYTES,
            max(MIN_COMPUTE_IN_FLIGHT_BYTES, memory // 8),
        )
    return ComputeResourceSnapshot(
        logical_cpu_count=logical,
        physical_cpu_count=physical,
        memory_bytes=memory,
        cpu_process_workers=_bounded_process_workers(logical, physical),
        max_in_flight_bytes=in_flight_bytes,
    )


def resolve_cpu_process_workers(
    requested_workers: int | None = None,
    *,
    workload_size: int = 0,
    resources: ComputeResourceSnapshot | None = None,
) -> int:
    """Resolve one bounded process count, keeping tiny batches on one process."""
    if workload_size <= 1:
        return 1
    snapshot = resources or discover_compute_resources()
    try:
        requested = int(requested_workers) if requested_workers is not None else snapshot.cpu_process_workers
    except (TypeError, ValueError):
        requested = snapshot.cpu_process_workers
    return max(1, min(snapshot.cpu_process_workers, MAX_CPU_PROCESS_WORKERS, requested))
