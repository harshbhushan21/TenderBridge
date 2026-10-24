"""Per-model request / token rate limits for free-tier providers, and 429 handling.

Limits come from `limits_per_model_from_plan` in llm_routing_and_budget.json (requests and tokens
per minute), keyed like "groq/openai/gpt-oss-20b" or "gemini-3-flash"; a model that is not listed
falls back to LLM_RPM / LLM_TPM (0 = unlimited). Calls wait for room in a sliding 60 s window
instead of hitting the provider's limit and silently falling back to a heuristic.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

log = get_logger(__name__)
WINDOW_S = 60.0


@dataclass
class Limits:
    rpm: int = 0  # 0 = unlimited
    tpm: int = 0


@dataclass
class _Window:
    limits: Limits
    calls: deque = field(default_factory=deque)  # (time, tokens)
    lock: threading.Lock = field(default_factory=threading.Lock)


_windows: dict[str, _Window] = {}
_windows_lock = threading.Lock()


@lru_cache
def configured_limits() -> dict[str, Limits]:
    from backend.app.llm.routing import get_routing_config, spec_from_plan

    out: dict[str, Limits] = {}
    for name, cfg in (get_routing_config().limits_per_model_from_plan or {}).items():
        spec = spec_from_plan(name)
        if spec and isinstance(cfg, dict):
            out[spec] = Limits(rpm=int(cfg.get("rpm") or 0), tpm=int(cfg.get("tpm") or 0))
    return out


def limits_for(model: str) -> Limits:
    s = get_settings()
    return configured_limits().get(model) or Limits(rpm=s.llm_rpm, tpm=s.llm_tpm)


def _window(model: str) -> _Window:
    with _windows_lock:
        if model not in _windows:
            _windows[model] = _Window(limits_for(model))
        return _windows[model]


def acquire(model: str, est_tokens: int) -> float:
    """Block until a call of ~est_tokens fits the model's per-minute limits. Returns seconds waited."""
    w = _window(model)
    if not w.limits.rpm and not w.limits.tpm:
        return 0.0
    waited = 0.0
    while True:
        with w.lock:
            now = time.monotonic()
            while w.calls and now - w.calls[0][0] >= WINDOW_S:
                w.calls.popleft()
            used = sum(t for _, t in w.calls)
            fits_rpm = not w.limits.rpm or len(w.calls) < w.limits.rpm
            # A single call larger than the whole TPM budget still goes once the window is empty.
            fits_tpm = not w.limits.tpm or used + est_tokens <= w.limits.tpm or not w.calls
            if fits_rpm and fits_tpm:
                w.calls.append((now, est_tokens))
                return waited
            pause = max(0.25, WINDOW_S - (now - w.calls[0][0]))
        if waited == 0.0:
            log.info("rate limit: waiting for %s (%d rpm / %d tpm)", model, w.limits.rpm, w.limits.tpm)
        time.sleep(min(pause, 5.0))
        waited += min(pause, 5.0)


def settle(model: str, actual_tokens: int) -> None:
    """Replace the estimate of the most recent call with the provider's token count."""
    w = _window(model)
    if actual_tokens <= 0:
        return
    with w.lock:
        if w.calls:
            t, _ = w.calls.pop()
            w.calls.append((t, actual_tokens))


_RETRY_AFTER = re.compile(r"(?:try again in|retry(?:[_ -]after)?[\"':= ]+)\s*([\d.]+)\s*(ms|s)?", re.I)


def is_rate_limited(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(k in text for k in ("ratelimit", "rate limit", "rate_limit", "429", "resourceexhausted",
                                   "resource_exhausted", "quota"))


def retry_after_s(exc: BaseException, attempt: int) -> float:
    """Provider-suggested wait ("try again in 7.5s", retry_after header), else exponential backoff."""
    for attr in ("retry_after", "retry_delay"):
        value = getattr(exc, attr, None)
        if isinstance(value, (int, float)) and value > 0:
            return min(float(value), 90.0)
    m = _RETRY_AFTER.search(str(exc))
    if m:
        value = float(m.group(1)) / (1000.0 if (m.group(2) or "").lower() == "ms" else 1.0)
        return min(max(value, 0.5) + 0.5, 90.0)
    return min(5.0 * 2 ** attempt, 60.0)
