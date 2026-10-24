"""Per-run LLM budget: call counter, token/cost tracking and hard caps.

A `RunBudget` is bound to the current context (contextvar) by the graph runner;
`check_budget()` is called before every LLM call and raises `BudgetExceeded`.
"""
from __future__ import annotations

import contextvars
import threading
from dataclasses import dataclass, field
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.errors import BudgetExceeded
from backend.app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class RunBudget:
    run_id: str | None = None
    max_cost_usd: float = 5.0
    max_calls: int = 400
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    unpriced_calls: int = 0  # calls to models with no configured price: cost unknown, not zero
    cancelled: bool = False
    per_node: dict[str, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def check(self, node: str | None = None) -> None:
        if self.cancelled:
            raise BudgetExceeded("run cancelled", details={"run_id": self.run_id})
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"LLM call cap reached ({self.max_calls})",
                                 details={"run_id": self.run_id, "node": node})
        if self.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(f"cost cap reached (${self.max_cost_usd:.2f})",
                                 details={"run_id": self.run_id, "node": node})

    def record(self, node: str | None, input_tokens: int, output_tokens: int, cost_usd: float | None) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            if cost_usd is None:
                self.unpriced_calls += 1
                cost_usd = 0.0
            self.cost_usd += cost_usd
            n = self.per_node.setdefault(node or "unknown", {"calls": 0, "input_tokens": 0,
                                                              "output_tokens": 0, "cost_usd": 0.0})
            n["calls"] += 1
            n["input_tokens"] += input_tokens
            n["output_tokens"] += output_tokens
            n["cost_usd"] += cost_usd

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "calls": self.calls, "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens, "cost_usd": round(self.cost_usd, 6),
            "unpriced_calls": self.unpriced_calls,
            "max_calls": self.max_calls, "max_cost_usd": self.max_cost_usd,
            "per_node": self.per_node,
        }


_current: contextvars.ContextVar[RunBudget | None] = contextvars.ContextVar("run_budget", default=None)
_registry: dict[str, RunBudget] = {}


def new_budget(run_id: str | None = None, *, usage: dict[str, Any] | None = None) -> RunBudget:
    """A run's budget; `usage` (a previous snapshot) carries totals across a Gate 1 resume."""
    s = get_settings()
    b = RunBudget(run_id=run_id, max_cost_usd=s.max_cost_usd, max_calls=s.max_llm_calls)
    if usage:
        b.calls = int(usage.get("calls", 0))
        b.input_tokens = int(usage.get("input_tokens", 0))
        b.output_tokens = int(usage.get("output_tokens", 0))
        b.cost_usd = float(usage.get("cost_usd", 0.0))
        b.unpriced_calls = int(usage.get("unpriced_calls", 0))
        b.per_node = {k: dict(v) for k, v in (usage.get("per_node") or {}).items()}
    if run_id:
        _registry[run_id] = b
    return b


def release_budget(run_id: str) -> None:
    _registry.pop(run_id, None)


def bind_budget(budget: RunBudget) -> contextvars.Token:
    return _current.set(budget)


def get_budget(run_id: str | None = None) -> RunBudget:
    if run_id and run_id in _registry:
        return _registry[run_id]
    b = _current.get()
    if b is None:
        b = new_budget(run_id)
        _current.set(b)
    return b


def cancel_run(run_id: str) -> bool:
    b = _registry.get(run_id)
    if b:
        b.cancelled = True
        return True
    return False


def check_budget(node: str | None = None) -> None:
    get_budget().check(node)


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  prices: dict[str, dict[str, float]] | None = None) -> float | None:
    """USD from `prices_per_million` in llm_routing_and_budget.json. None when the model has no
    price: the call is counted as unpriced (and the cost cap cannot see it), never as free."""
    p = (prices or {}).get(model) or (prices or {}).get(model.split(":", 1)[-1])
    if not p:
        return None
    return (input_tokens * p.get("input", 0.0) + output_tokens * p.get("output", 0.0)) / 1_000_000
