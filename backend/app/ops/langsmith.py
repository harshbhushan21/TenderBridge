"""LangSmith tracing (optional) and the redaction applied to every trace and audit record.

Tracing is off unless LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set. When on, one
LangSmith client is installed globally with `hide_inputs/hide_outputs/hide_metadata = redact`,
so manual `@traceable` runs *and* the automatic LangGraph / LangChain runs (nodes, chat models)
pass through the same redaction before anything leaves the process.

Trace shape for one analysis:
  analysis_run (chain)                     metadata: tender_id, version, run_id, mode, thread_id
    LangGraph                              automatic
      <node> (one per graph node)          automatic
        hybrid_search (retriever) | rule checks (tool) | key facts (parser) | ChatGroq (llm) ...
A Gate 1 resume is a new `gate1_resume` root with the same thread_id, so LangSmith shows the
analysis and its approval as one thread.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from enum import Enum
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

log = get_logger(__name__)

MAX_TRACE_TEXT = 4000  # long document text is cut in traces: enough to debug, less to leak
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(sk|pk|lsv2|gsk|hf|AIza|ghp|xox[bp])[-_A-Za-z0-9]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),
]
_SECRET_KEYS = re.compile(r"(api[_-]?key|secret|password|token(?!s\b|_count|_usage)|authorization)", re.I)
_DROP_KEYS = frozenset({"session", "_session", "s", "db"})  # DB handles are not trace data


def redact_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact(obj: Any, *, max_text: int | None = None) -> Any:
    """Recursively mask emails, phones, PAN, Aadhaar-like numbers and API keys; values under
    secret-looking keys are replaced. Unknown objects become redacted strings."""
    if obj is None or isinstance(obj, (bool, int, float, datetime, date)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, str):
        text = redact_text(obj)
        return text if max_text is None or len(text) <= max_text else \
            f"{text[:max_text]}... [{len(text) - max_text} chars truncated]"
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if isinstance(k, str) and _SECRET_KEYS.search(k) else redact(v, max_text=max_text))
                for k, v in obj.items() if not (isinstance(k, str) and k in _DROP_KEYS)}
    if isinstance(obj, (list, tuple, set)):
        return [redact(v, max_text=max_text) for v in obj]
    dump = getattr(obj, "model_dump", None)  # pydantic models
    if callable(dump):
        try:
            return redact(dump(mode="json"), max_text=max_text)
        except Exception:
            pass
    return redact_text(repr(obj))[:500]


def redact_for_trace(obj: Any) -> Any:
    return redact(obj, max_text=MAX_TRACE_TEXT)


_configured: bool | None = None


def configure_tracing() -> bool:
    """Install (or explicitly disable) LangSmith tracing from settings. Idempotent."""
    global _configured
    if _configured is not None:
        return _configured
    s = get_settings()  # also exports LANGSMITH_API_KEY from .env into os.environ
    key = s.langsmith_api_key or s.langchain_api_key
    try:
        import langsmith as ls
    except ImportError:  # pragma: no cover - langsmith is a core dependency
        _configured = False
        return False
    if not s.langsmith_tracing or key is None or not key.get_secret_value().strip():
        if s.langsmith_tracing:
            log.warning("LANGSMITH_TRACING=true but no LANGSMITH_API_KEY: tracing stays off")
        ls.configure(enabled=False)
        _configured = False
        return False
    client = ls.Client(api_key=key.get_secret_value().strip(), api_url=s.langsmith_endpoint or None,
                       hide_inputs=redact_for_trace,
                       hide_outputs=redact_for_trace, hide_metadata=redact_for_trace)
    ls.configure(client=client, enabled=True, project_name=s.langsmith_project)
    log.info("LangSmith tracing on (project %s); inputs/outputs are redacted", s.langsmith_project)
    _configured = True
    return True


def tracing_enabled() -> bool:
    return bool(_configured)


def _drop_handles(inputs: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in inputs.items() if k not in _DROP_KEYS}


def traceable(name: str | None = None, *, run_type: str = "chain",
              process_inputs: Callable[[dict[str, Any]], Any] | None = None,
              process_outputs: Callable[[Any], Any] | None = None, **kw: Any) -> Callable:
    """`langsmith.traceable` that drops DB sessions from inputs. Redaction itself happens in the
    client (configure_tracing), so it also covers automatic LangChain runs. With tracing off the
    decorator costs one context check per call."""
    def deco(fn: Callable) -> Callable:
        try:
            from langsmith import traceable as ls_traceable
        except ImportError:  # pragma: no cover
            return fn
        inputs = (lambda d: process_inputs(_drop_handles(d))) if process_inputs else _drop_handles
        return ls_traceable(name=name or fn.__name__, run_type=run_type,  # type: ignore[call-overload]
                            process_inputs=inputs, process_outputs=process_outputs, **kw)(fn)
    return deco


def retrieval_outputs(chunks: Any) -> dict[str, Any]:
    """LangSmith's retriever view: {"documents": [{page_content, metadata}]}. Text of KB chunks that
    not every role may read is withheld: traces are visible to people the KB filter would block."""
    docs = []
    for c in chunks or []:
        meta = dict(getattr(c, "metadata", {}) or {})
        roles = list(meta.get("allowed_roles") or [])
        restricted = bool(roles) and "all" not in roles
        docs.append({"page_content": f"[RESTRICTED: {c.doc_id} p.{c.page}]" if restricted else c.text,
                     "metadata": {"doc_id": c.doc_id, "page": c.page, "section_path": c.section_path,
                                  "score": round(float(c.score), 4), "scope": str(getattr(c.scope, "value", c.scope))}})
    return {"documents": docs}


def current_parent_headers() -> dict[str, str] | None:
    """Headers of the active trace, to continue it in another thread (background runs)."""
    try:
        from langsmith.run_helpers import get_current_run_tree
        rt = get_current_run_tree()
        return rt.to_headers() if rt is not None else None
    except Exception:
        return None


@contextmanager
def continue_trace(parent: dict[str, str] | None) -> Iterator[None]:
    """Make runs in this thread children of `parent` (from current_parent_headers)."""
    if not parent or not tracing_enabled():
        yield
        return
    from langsmith import tracing_context
    with tracing_context(parent=parent):
        yield



def summarize_sections(inputs: dict[str, Any]) -> dict[str, Any]:
    """Inputs carrying every tender section are traced as counts and doc ids, not full text."""
    out = dict(inputs)
    for key in ("sections", "base_sections", "rows"):
        value = out.get(key)
        if isinstance(value, list) and len(value) > 5:
            ids = sorted({str((v.get("doc_id") if isinstance(v, dict) else getattr(v, "doc_id", "")) or "")
                          for v in value} - {""})
            out[key] = {"count": len(value), "doc_ids": ids[:10]}
    return out
