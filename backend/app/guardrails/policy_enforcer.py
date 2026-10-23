"""Central policy checks for decisions and agent tool calls."""
from __future__ import annotations

from typing import Any

from backend.app.guardrails.tool_allowlist import assert_allowed
from backend.app.ops.langsmith import traceable

APPROVER_ROLES = frozenset({"bid_manager", "admin"})
TERMINAL_RECOMMENDATIONS = frozenset({"BID", "BID_WITH_CONDITIONS", "NO_BID"})


def enforce_tools(node: str, tools: list[str]) -> None:
    assert_allowed(node, tools)


def enforce_gate_decision(*, role: str, decision: dict[str, Any],
                          current_version: int, recommendation: str | None = None) -> None:
    if role not in APPROVER_ROLES:
        raise PermissionError("only bid_manager or admin may decide Gate 1")
    if decision.get("tender_version") != current_version:
        raise ValueError("decision is bound to a superseded tender version")
    action = str(decision.get("action", ""))
    if action not in {"approve_bid", "no_bid", "defer"}:  # schemas.assessment.GateDecision.action
        raise ValueError(f"unsupported Gate 1 action: {action}")
    if recommendation and recommendation not in TERMINAL_RECOMMENDATIONS:
        raise ValueError("invalid system recommendation")


@traceable(name="enforce_hard_gate_policy", run_type="tool")
def enforce_assessment(assessment: dict[str, Any]) -> None:
    failures = assessment.get("hard_gate_failures") or []
    if failures and assessment.get("recommendation") != "NO_BID":
        raise ValueError("any hard-gate failure must produce NO_BID")
