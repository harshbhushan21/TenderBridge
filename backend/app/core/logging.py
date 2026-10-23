"""Structured logging with request/tender/run context variables."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
tender_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("tender_id", default=None)
version_var: contextvars.ContextVar[int | None] = contextvars.ContextVar("tender_version", default=None)
run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)

_CONTEXT_VARS: dict[str, contextvars.ContextVar[Any]] = {
    "request_id": request_id_var,
    "tender_id": tender_id_var,
    "tender_version": version_var,
    "run_id": run_id_var,
}


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for name, var in _CONTEXT_VARS.items():
            setattr(record, name, var.get())
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in _CONTEXT_VARS:
            val = getattr(record, name, None)
            if val is not None:
                payload[name] = val
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = " ".join(
            f"{n}={getattr(record, n)}" for n in _CONTEXT_VARS if getattr(record, n, None) is not None
        )
        base = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        if ctx:
            base += f" [{ctx}]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if json_output else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, msg, extra={"extra_fields": fields})
