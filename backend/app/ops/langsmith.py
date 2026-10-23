"""LangSmith tracing setup and PII/secret redaction for traces and audit."""
from __future__ import annotations

import functools
import os
import re
from collections.abc import Callable
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

log = get_logger(__name__)

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(sk|pk|lsv2|AIza|ghp|xox[bp])[-_A-Za-z0-9]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),
]
_SECRET_KEYS = re.compile(r"(api[_-]?key|secret|password|token|authorization)", re.I)


def redact_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact(obj: Any) -> Any:
    """Recursively mask emails, phones, PAN, Aadhaar-like numbers and API keys."""
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if isinstance(k, str) and _SECRET_KEYS.search(k) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact(v) for v in obj)
    return obj


_configured = False


def configure_tracing() -> bool:
    """Set LangSmith env vars from settings. Returns True when tracing is enabled."""
    global _configured
    s = get_settings()
    if not s.langsmith_tracing:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ.setdefault("LANGCHAIN_PROJECT", s.langsmith_project)
    os.environ.setdefault("LANGSMITH_PROJECT", s.langsmith_project)
    if not (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")):
        log.warning("LANGSMITH_TRACING enabled but no LANGSMITH_API_KEY set")
    _configured = True
    return True


def tracing_enabled() -> bool:
    return _configured


def traceable(name: str | None = None, **kw: Any) -> Callable:
    """`langsmith.traceable` with redacted inputs/outputs, or identity if unavailable."""
    def deco(fn: Callable) -> Callable:
        try:
            from langsmith import traceable as ls_traceable
            return ls_traceable(name=name or fn.__name__, process_inputs=redact,
                                process_outputs=redact, **kw)(fn)
        except Exception:
            @functools.wraps(fn)
            def wrapper(*a, **k):
                return fn(*a, **k)
            return wrapper
    return deco
