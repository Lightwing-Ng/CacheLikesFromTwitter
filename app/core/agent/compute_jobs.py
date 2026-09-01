"""Durable local compute jobs for approved optimization entrypoints.

Code version: v1.1.0-codex.1
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from typing import Any


APPROVAL_FILENAME = ".cachelikes-compute.json"
COMPUTE_JOBS_DIRNAME = "compute-jobs"
DEFAULT_MAX_RUNTIME_SECONDS = 12 * 60 * 60
MAX_MAX_RUNTIME_SECONDS = 24 * 60 * 60
MAX_CONFIG_BYTES = 1 * 1024 * 1024
MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_LOG_TAIL_CHARS = 4_000
MAX_PROGRESS_BYTES = 64 * 1024
MAX_STATUS_TEXT_CHARS = 1_000
MACOS_SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
MACOS_NETWORK_DENY_PROFILE = "(version 1) (allow default) (deny network*)"
PROGRESS_FIELDS = frozenset(
    {
        "generation",
        "iteration",
        "evaluations_completed",
        "evaluations_total",
        "best_objective",
        "elapsed_seconds",
        "eta_seconds",
        "summary",
    }
)
TERMINAL_STATES = frozenset({"succeeded", "failed", "stopped", "interrupted"})
ACTIVE_STATES = frozenset({"starting", "running", "stopping"})
_ENTRYPOINT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}\Z")


class ComputeJobError(RuntimeError):
    """Raised when a durable compute-job request violates its contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace one JSON record atomically without following a linked leaf."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ComputeJobError("Compute-job metadata cannot use a symbolic link.")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json_object(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ComputeJobError(f"Required regular JSON file is unavailable: {path.name}")
    if path.stat().st_size > maximum_bytes:
        raise ComputeJobError(f"JSON file exceeds the {maximum_bytes:,}-byte limit: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ComputeJobError(f"Invalid JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ComputeJobError(f"JSON file must contain one object: {path.name}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _confined_regular_file(workspace: Path, raw_path: str, *, suffix: str) -> Path:
    candidate = Path(str(raw_path or "").strip())
    if not candidate.as_posix() or candidate.is_absolute() or ".." in candidate.parts:
        raise ComputeJobError("Compute-job paths must be relative and remain inside the workspace.")
    current = workspace
    for part in candidate.parts:
        current /= part
        if current.is_symlink():
            raise ComputeJobError("Compute-job paths cannot traverse symbolic links.")
    try:
        resolved = (workspace / candidate).resolve(strict=True)
    except OSError as exc:
        raise ComputeJobError("Compute-job path does not name an existing approved file.") from exc
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ComputeJobError("Compute-job paths must remain inside the workspace.") from exc
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode) or resolved.suffix.casefold() != suffix:
        raise ComputeJobError(f"Compute-job path must be a regular {suffix} file.")
    return resolved


def _process_identity(pid: int) -> str:
    """Return a stable-enough birth identity used to reject PID reuse."""
    if pid <= 0:
        return ""
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        fields = proc_stat.read_text(encoding="utf-8").split()
        if len(fields) > 21:
            return f"proc:{fields[21]}"
    except (OSError, UnicodeError):
        pass
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return ""
    return "ps:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity_matches(pid: Any, expected: Any) -> bool:
    try:
        normalized_pid = int(pid)
    except (TypeError, ValueError):
        return False
    expected_text = str(expected or "")
    return bool(expected_text) and _process_identity(normalized_pid) == expected_text


def _terminate_process_group(pid: int, *, timeout: float = 5.0) -> None:
    """Terminate only the identity-checked compute worker process group."""
    if os.name == "posix":
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _process_identity(pid):
                return
            time.sleep(0.05)
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def validate_optimizer_checkpoint(payload: Any) -> dict[str, Any]:
    """Validate the portable minimum checkpoint contract and return a copy."""
    if not isinstance(payload, dict):
        raise ComputeJobError("Optimizer checkpoint must be one JSON object.")
    required = {
        "schema_version",
        "optimizer_version",
        "iteration",
        "rng_state",
        "seed",
        "best_objective",
        "best_parameters",
        "evaluation_count",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ComputeJobError("Optimizer checkpoint is missing: " + ", ".join(missing))
    if payload.get("schema_version") != 1:
        raise ComputeJobError("Optimizer checkpoint schema_version must be 1.")
    for field_name in ("iteration", "evaluation_count"):
        value = payload.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ComputeJobError(f"Optimizer checkpoint {field_name} must be a non-negative integer.")
    if not isinstance(payload.get("best_parameters"), dict):
        raise ComputeJobError("Optimizer checkpoint best_parameters must be an object.")
    if "population" not in payload and "optimizer_state" not in payload:
        raise ComputeJobError("Optimizer checkpoint must include population or optimizer_state.")
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ComputeJobError("Optimizer checkpoint exceeds the bounded checkpoint size.")
    return dict(payload)


def write_optimizer_checkpoint_atomic(job_runtime: Path, payload: dict[str, Any]) -> Path:
    """Validate and atomically publish the latest complete optimizer checkpoint."""
    runtime = Path(job_runtime).resolve(strict=True)
    validated = validate_optimizer_checkpoint(payload)
    checkpoint_path = runtime / "checkpoint.json"
    _atomic_write_json(checkpoint_path, validated)
    return checkpoint_path


def write_compute_progress_atomic(job_runtime: Path, payload: dict[str, Any]) -> Path:
    """Publish one bounded progress heartbeat for job_status."""
    if not isinstance(payload, dict):
        raise ComputeJobError("Compute progress must be one JSON object.")
    unknown = sorted(set(payload).difference(PROGRESS_FIELDS))
    if unknown:
        raise ComputeJobError("Compute progress contains unsupported fields: " + ", ".join(unknown))
    normalized = dict(payload)
    if "summary" in normalized:
        normalized["summary"] = str(normalized["summary"])[:MAX_STATUS_TEXT_CHARS]
    encoded = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PROGRESS_BYTES:
        raise ComputeJobError("Compute progress exceeds the bounded progress size.")
    runtime = Path(job_runtime).resolve(strict=True)
    progress_path = runtime / "progress.json"
    _atomic_write_json(progress_path, normalized)
    return progress_path


class ComputeJobManager:
    """Create, reconcile, inspect, and stop durable local compute workers."""

    def __init__(
        self,
        workspace: Path,
        runtime_root: Path,
        *,
        caffeinate_executable: Path = Path("/usr/bin/caffeinate"),
    ) -> None:
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ComputeJobError("Compute-job workspace must be a directory.")
        self.runtime_root = Path(runtime_root).expanduser().resolve(strict=False) / COMPUTE_JOBS_DIRNAME
        self.workspace_key = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:24]
        self.jobs_root = self.runtime_root / self.workspace_key
        self._caffeinate_executable = caffeinate_executable
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.reconcile()

    def _metadata_path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", str(job_id or "")):
            raise ComputeJobError("Unknown compute job_id.")
        return self.jobs_root / job_id / "metadata.json"

    def _load_metadata(self, job_id: str) -> dict[str, Any]:
        return _read_json_object(self._metadata_path(job_id), maximum_bytes=128 * 1024)

    def _save_metadata(self, metadata: dict[str, Any]) -> None:
        job_id = str(metadata.get("job_id") or "")
        _atomic_write_json(self._metadata_path(job_id), metadata)

    def _all_metadata(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.jobs_root.glob("*/metadata.json")):
            try:
                record = _read_json_object(path, maximum_bytes=128 * 1024)
            except ComputeJobError:
                continue
            if record.get("workspace") == str(self.workspace):
                records.append(record)
        return records

    def _approved_entrypoint(self, entrypoint_id: str) -> tuple[Path, dict[str, Any]]:
        if not _ENTRYPOINT_ID_RE.fullmatch(entrypoint_id):
            raise ComputeJobError("Compute entrypoint id is invalid.")
        approval_path = self.workspace / APPROVAL_FILENAME
        approval = _read_json_object(approval_path, maximum_bytes=128 * 1024)
        if approval.get("schema_version") != 1 or not isinstance(approval.get("entrypoints"), list):
            raise ComputeJobError("Compute approval manifest must use schema_version 1.")
        matches = [
            item
            for item in approval["entrypoints"]
            if isinstance(item, dict) and item.get("id") == entrypoint_id
        ]
        if len(matches) != 1:
            raise ComputeJobError("Compute entrypoint is not uniquely approved by the workspace manifest.")
        record = dict(matches[0])
        entrypoint = _confined_regular_file(self.workspace, str(record.get("path") or ""), suffix=".py")
        expected_sha256 = str(record.get("sha256") or "").casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or _sha256_file(entrypoint) != expected_sha256:
            raise ComputeJobError("Compute entrypoint bytes do not match the approved SHA-256.")
        return entrypoint, record

    def reconcile(self) -> None:
        """Rebind live jobs and mark missing or identity-mismatched workers interrupted."""
        for metadata in self._all_metadata():
            if metadata.get("state") not in ACTIVE_STATES:
                self._release_assertion(metadata)
                continue
            pid = metadata.get("pid")
            identity = metadata.get("process_identity")
            if _identity_matches(pid, identity):
                if metadata.get("state") == "starting":
                    metadata["state"] = "running"
                    metadata["updated_at"] = _utc_now()
                    self._save_metadata(metadata)
                continue
            updated_at = str(metadata.get("updated_at") or "")
            try:
                age_seconds = (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(updated_at)
                ).total_seconds()
            except ValueError:
                age_seconds = 10.0
            if age_seconds < 2.0:
                continue
            metadata["state"] = "interrupted"
            metadata["updated_at"] = _utc_now()
            metadata["ended_at"] = metadata.get("ended_at") or metadata["updated_at"]
            metadata["message"] = "Worker identity is no longer present; explicit resume is available when a valid checkpoint exists."
            self._save_metadata(metadata)
            self._release_assertion(metadata)

    def _release_assertion(self, metadata: dict[str, Any]) -> None:
        pid = metadata.get("sleep_assertion_pid")
        identity = metadata.get("sleep_assertion_identity")
        if not _identity_matches(pid, identity):
            return
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, TypeError, ValueError):
            return

    def start(
        self,
        *,
        entrypoint_id: str,
        config_path: str,
        idempotency_key: str,
        resume_job_id: str = "",
    ) -> dict[str, Any]:
        """Start one detached worker after approval, confinement, and deduplication checks."""
        if not _IDEMPOTENCY_KEY_RE.fullmatch(idempotency_key):
            raise ComputeJobError("Compute job idempotency_key must contain 8 to 128 safe characters.")
        entrypoint, approval = self._approved_entrypoint(entrypoint_id)
        config = _confined_regular_file(self.workspace, config_path, suffix=".json")
        if config.stat().st_size > MAX_CONFIG_BYTES:
            raise ComputeJobError("Compute job config exceeds the bounded config size.")
        _read_json_object(config, maximum_bytes=MAX_CONFIG_BYTES)
        max_runtime = approval.get("max_runtime_seconds", DEFAULT_MAX_RUNTIME_SECONDS)
        if isinstance(max_runtime, bool) or not isinstance(max_runtime, int):
            raise ComputeJobError("Approved max_runtime_seconds must be an integer.")
        if not DEFAULT_MAX_RUNTIME_SECONDS <= max_runtime <= MAX_MAX_RUNTIME_SECONDS:
            raise ComputeJobError("Approved max_runtime_seconds must be between 43,200 and 86,400 seconds.")
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "entrypoint": entrypoint_id,
                    "entrypoint_sha256": _sha256_file(entrypoint),
                    "config": config.relative_to(self.workspace).as_posix(),
                    "config_sha256": _sha256_file(config),
                    "resume_job_id": resume_job_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.reconcile()
        for existing in self._all_metadata():
            if existing.get("idempotency_key") != idempotency_key:
                continue
            if existing.get("request_fingerprint") != request_fingerprint:
                raise ComputeJobError("Idempotency key was already used for a different compute request.")
            return self.status(str(existing["job_id"]))
        active = [item for item in self._all_metadata() if item.get("state") in ACTIVE_STATES]
        if active:
            raise ComputeJobError(f"Compute job {active[0]['job_id']} is already active; concurrency is limited to 1.")

        checkpoint_path: Path | None = None
        if resume_job_id:
            source = self._load_metadata(resume_job_id)
            if source.get("state") not in TERMINAL_STATES:
                raise ComputeJobError("Only a terminal compute job can be resumed.")
            if source.get("entrypoint") != entrypoint_id:
                raise ComputeJobError("Resume entrypoint does not match the prior job.")
            checkpoint_path = self.jobs_root / resume_job_id / "checkpoint.json"
            checkpoint = _read_json_object(checkpoint_path, maximum_bytes=MAX_CONFIG_BYTES)
            validate_optimizer_checkpoint(checkpoint)

        job_id = secrets.token_hex(16)
        job_root = self.jobs_root / job_id
        job_root.mkdir(mode=0o700, parents=False, exist_ok=False)
        config_snapshot = job_root / "config.json"
        config_snapshot.write_bytes(config.read_bytes())
        os.chmod(config_snapshot, 0o600)
        now = _utc_now()
        metadata: dict[str, Any] = {
            "schema_version": 1,
            "job_id": job_id,
            "workspace": str(self.workspace),
            "state": "starting",
            "pid": 0,
            "process_identity": "",
            "started_at": now,
            "updated_at": now,
            "ended_at": "",
            "entrypoint": entrypoint_id,
            "entrypoint_path": entrypoint.relative_to(self.workspace).as_posix(),
            "entrypoint_sha256": _sha256_file(entrypoint),
            "config_path": config.relative_to(self.workspace).as_posix(),
            "config_sha256": _sha256_file(config),
            "checkpoint_path": "checkpoint.json",
            "result_path": "result.json",
            "exit_status": None,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
            "resumed_from": resume_job_id,
            "max_runtime_seconds": max_runtime,
            "message": "Starting approved compute worker.",
            "sleep_assertion_pid": 0,
            "sleep_assertion_identity": "",
        }
        self._save_metadata(metadata)
        command = [
            sys.executable,
            "-m",
            "app.core.agent.compute_jobs",
            "--worker",
            str(job_root / "metadata.json"),
            str(entrypoint),
            str(config_snapshot),
            str(max_runtime),
        ]
        if checkpoint_path is not None:
            command.append(str(checkpoint_path))
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT", "WINDIR"}
        }
        package_root = Path(__file__).resolve().parents[3]
        environment["PYTHONPATH"] = str(package_root)
        environment["PYTHONUNBUFFERED"] = "1"
        environment["CACHELIKES_COMPUTE_JOB"] = job_id
        try:
            process = subprocess.Popen(
                command,
                cwd=self.workspace,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            metadata["state"] = "failed"
            metadata["updated_at"] = _utc_now()
            metadata["ended_at"] = metadata["updated_at"]
            metadata["message"] = "Approved compute worker could not start."
            self._save_metadata(metadata)
            raise ComputeJobError("Approved compute worker could not start.") from exc
        identity = ""
        previous_identity = ""
        for _ in range(50):
            current_identity = _process_identity(process.pid)
            if current_identity and current_identity == previous_identity:
                identity = current_identity
                break
            previous_identity = current_identity
            time.sleep(0.02)
        current_metadata = self._load_metadata(job_id)
        if current_metadata.get("state") in TERMINAL_STATES:
            return self.status(job_id)
        if not identity:
            _terminate_process_group(process.pid, timeout=1)
            metadata["state"] = "failed"
            metadata["updated_at"] = _utc_now()
            metadata["ended_at"] = metadata["updated_at"]
            metadata["message"] = "Compute worker identity could not be verified."
            self._save_metadata(metadata)
            raise ComputeJobError("Compute worker identity could not be verified.")
        metadata = current_metadata
        metadata["pid"] = process.pid
        metadata["process_identity"] = identity
        metadata["state"] = "running"
        metadata["updated_at"] = _utc_now()
        metadata["message"] = "Approved compute worker is running independently of the provider turn."
        self._start_sleep_assertion(metadata)
        self._save_metadata(metadata)
        return self.status(job_id)

    def _start_sleep_assertion(self, metadata: dict[str, Any]) -> None:
        if sys.platform != "darwin" or not self._caffeinate_executable.is_file():
            return
        try:
            process = subprocess.Popen(
                [str(self._caffeinate_executable), "-i", "-w", str(metadata["pid"])],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError:
            return
        identity = _process_identity(process.pid)
        if identity:
            metadata["sleep_assertion_pid"] = process.pid
            metadata["sleep_assertion_identity"] = identity

    def status(self, job_id: str = "") -> dict[str, Any]:
        """Return bounded metadata, progress, and a small log tail."""
        self.reconcile()
        records = self._all_metadata()
        if not job_id:
            if not records:
                return {"state": "idle", "active": False}
            records.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
            metadata = records[0]
        else:
            metadata = self._load_metadata(job_id)
        job_root = self.jobs_root / str(metadata["job_id"])
        progress: dict[str, Any] = {}
        progress_path = job_root / "progress.json"
        if progress_path.exists():
            try:
                raw_progress = _read_json_object(
                    progress_path,
                    maximum_bytes=MAX_PROGRESS_BYTES,
                )
                progress = {
                    key: value
                    for key, value in raw_progress.items()
                    if key in PROGRESS_FIELDS
                }
                if "summary" in progress:
                    progress["summary"] = str(progress["summary"])[
                        :MAX_STATUS_TEXT_CHARS
                    ]
            except ComputeJobError:
                progress = {"summary": "Latest progress heartbeat is invalid."}
        log_tail = ""
        log_path = job_root / "worker.log"
        try:
            with log_path.open("rb") as handle:
                handle.seek(max(0, log_path.stat().st_size - MAX_LOG_TAIL_CHARS * 4))
                log_tail = handle.read().decode("utf-8", errors="replace")[-MAX_LOG_TAIL_CHARS:]
        except OSError:
            pass
        can_resume = False
        checkpoint_path = job_root / "checkpoint.json"
        if metadata.get("state") in TERMINAL_STATES and checkpoint_path.is_file():
            try:
                validate_optimizer_checkpoint(
                    _read_json_object(checkpoint_path, maximum_bytes=MAX_CONFIG_BYTES)
                )
                can_resume = True
            except ComputeJobError:
                can_resume = False
        allowed = {
            key: metadata.get(key)
            for key in (
                "job_id",
                "state",
                "started_at",
                "updated_at",
                "ended_at",
                "entrypoint",
                "config_path",
                "exit_status",
                "checkpoint_path",
                "result_path",
                "resumed_from",
                "max_runtime_seconds",
                "message",
            )
        }
        allowed.update(
            {
                "active": metadata.get("state") in ACTIVE_STATES,
                "progress": progress,
                "log_tail": log_tail,
                "can_resume": can_resume,
            }
        )
        return allowed

    def stop(self, job_id: str) -> dict[str, Any]:
        """Stop only the identity-verified worker process group for one job."""
        metadata = self._load_metadata(job_id)
        if metadata.get("state") not in ACTIVE_STATES:
            return self.status(job_id)
        if not _identity_matches(metadata.get("pid"), metadata.get("process_identity")):
            metadata["state"] = "interrupted"
            metadata["updated_at"] = _utc_now()
            metadata["ended_at"] = metadata["updated_at"]
            metadata["message"] = "Worker identity changed; no process was terminated."
            self._save_metadata(metadata)
            raise ComputeJobError("Compute worker identity changed; refusing to terminate a reused PID.")
        metadata["state"] = "stopping"
        metadata["updated_at"] = _utc_now()
        self._save_metadata(metadata)
        _terminate_process_group(int(metadata["pid"]))
        metadata["state"] = "stopped"
        metadata["updated_at"] = _utc_now()
        metadata["ended_at"] = metadata["updated_at"]
        metadata["message"] = "Compute job was stopped with its owned process group."
        self._save_metadata(metadata)
        self._release_assertion(metadata)
        return self.status(job_id)


def _bounded_log_append(log_path: Path, data: bytes) -> None:
    with log_path.open("ab") as handle:
        handle.write(data)
    size = log_path.stat().st_size
    if size <= MAX_LOG_BYTES:
        return
    with log_path.open("rb") as handle:
        handle.seek(size - MAX_LOG_BYTES)
        retained = handle.read()
    with log_path.open("wb") as handle:
        handle.write(retained)


def _worker_main(arguments: list[str]) -> int:
    """Run the approved child and own terminal metadata publication."""
    if len(arguments) not in {4, 5}:
        return 64
    metadata_path = Path(arguments[0]).resolve(strict=True)
    entrypoint = Path(arguments[1]).resolve(strict=True)
    config = Path(arguments[2]).resolve(strict=True)
    max_runtime = int(arguments[3])
    checkpoint = Path(arguments[4]).resolve(strict=True) if len(arguments) == 5 else None
    job_root = metadata_path.parent
    command = [
        sys.executable,
        str(entrypoint),
        "--config",
        str(config),
        "--job-runtime",
        str(job_root),
    ]
    if checkpoint is not None:
        command.extend(["--resume", str(checkpoint)])
    if sys.platform == "darwin" and MACOS_SANDBOX_EXECUTABLE.is_file():
        command = [
            str(MACOS_SANDBOX_EXECUTABLE),
            "-p",
            MACOS_NETWORK_DENY_PROFILE,
            *command,
        ]
    environment = dict(os.environ)
    environment["CACHELIKES_COMPUTE_JOB_RUNTIME"] = str(job_root)
    log_path = job_root / "worker.log"
    started = time.monotonic()
    child = subprocess.Popen(
        command,
        cwd=entrypoint.parent,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )
    if child.stdout is None:
        return 70
    import selectors

    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    timed_out = False
    while child.poll() is None:
        if time.monotonic() - started >= max_runtime:
            timed_out = True
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
            break
        for key, _mask in selector.select(timeout=0.25):
            chunk = os.read(key.fileobj.fileno(), 64 * 1024)
            if chunk:
                _bounded_log_append(log_path, chunk)
    remainder = child.stdout.read()
    if remainder:
        _bounded_log_append(log_path, remainder)
    exit_status = child.wait()
    try:
        metadata = _read_json_object(metadata_path, maximum_bytes=128 * 1024)
    except ComputeJobError:
        return exit_status or 70
    if metadata.get("state") == "stopping":
        return exit_status
    metadata["exit_status"] = exit_status
    metadata["state"] = "succeeded" if exit_status == 0 and not timed_out else "failed"
    metadata["updated_at"] = _utc_now()
    metadata["ended_at"] = metadata["updated_at"]
    metadata["message"] = (
        "Compute job exceeded its approved runtime limit."
        if timed_out
        else ("Compute job completed." if exit_status == 0 else "Compute job exited with a failure status.")
    )
    _atomic_write_json(metadata_path, metadata)
    return exit_status


def _main(argv: list[str]) -> int:
    if not argv or argv[0] != "--worker":
        return 64
    return _worker_main(argv[1:])


if __name__ == "__main__":  # pragma: no cover - exercised through detached workers.
    raise SystemExit(_main(sys.argv[1:]))
