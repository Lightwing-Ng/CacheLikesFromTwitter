"""Structured logging configuration for the application."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import LOGS_ROOT


_CONFIGURED = False
_RUN_ID = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
_JOB_ID: ContextVar[str] = ContextVar("cachelikes_job_id", default="-")

_STANDARD_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", _RUN_ID),
            "job_id": getattr(record, "job_id", _JOB_ID.get()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.threadName,
            "process": record.processName,
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Render concise console logs with key context."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts = [
            timestamp,
            record.levelname,
            record.name,
            f"job_id={getattr(record, 'job_id', _JOB_ID.get())}",
            record.getMessage(),
        ]
        if record.exc_info:
            parts.append(self.formatException(record.exc_info))
        return " | ".join(parts)


def configure_logging(app_version: str) -> Path:
    """Configure process-wide logging once and return the log file path."""
    global _CONFIGURED
    log_file = LOGS_ROOT / "cachelikes.log.jsonl"
    LOGS_ROOT.mkdir(parents=True, exist_ok=True)

    if _CONFIGURED:
        return log_file

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(JsonFormatter())

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.captureWarnings(True)
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    _CONFIGURED = True
    logging.getLogger("app.bootstrap").info(
        "Structured logging configured.",
        extra={
            "run_id": _RUN_ID,
            "job_id": _JOB_ID.get(),
            "app_version": app_version,
            "log_file": str(log_file),
            "logs_root": str(LOGS_ROOT),
        },
    )
    return log_file


def set_job_id(job_id: str) -> Any:
    """Bind the current job identifier to the logging context."""
    return _JOB_ID.set(job_id)


def reset_job_id(token: Any) -> None:
    """Restore the previous job identifier after a job completes."""
    _JOB_ID.reset(token)


def get_log_file_path() -> Path:
    """Return the primary JSON log file path."""
    return LOGS_ROOT / "cachelikes.log.jsonl"
