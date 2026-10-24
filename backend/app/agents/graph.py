"""TenderBridge LangGraph construction and execution helpers."""
from __future__ import annotations

from typing import Any

from backend.app.agents.nodes.core import (
    bid_score,
    eligibility_and_risk,
    extract_key_facts,
    finalize,
    gate1_review,
    gate2_review,
    intake_guard,
    load_tender,
    merge_and_dedupe,
    plan_response,
    reconcile_corrigenda,
    rewrite_failed,
    route_requirements,
    shred_requirements,
    verify_claims,
    write_no_bid_report,
    write_sections,
)
from backend.app.ops.events import emit_event
from backend.app.schemas.graph_state import TenderState


def _after_intake(state: TenderState) -> str:
    return "load_tender" if state.get("intake_ok") else "finalize"


def _after_score(state: TenderState) -> str:
    assessment = state.get("assessment") or {}
    return "write_no_bid_report" if assessment.get("recommendation") == "NO_BID" else "finalize"


def _after_gate1(state: TenderState) -> str:
    decision = state.get("gate1_decision") or {}
    if state.get("drafting_requested") and decision.get("action") == "approve_bid":
        return "plan_response"
    return "write_no_bid_report" if decision.get("action") == "approve_no_bid" else "finalize"


def build_graph(*, checkpointer: Any = None):
    """Build a compiled graph.

    Human approval is deliberately not auto-approved.  Callers can insert
    their Gate 1/Gate 2 endpoints around the returned assessment before
    enabling drafting; this graph safely stops after a no-bid report or score.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:  # pragma: no cover - dependency installation issue
        raise RuntimeError("LangGraph is required to build the agent graph") from exc

    graph = StateGraph(TenderState)

    def instrument(name: str, fn):
        def wrapped(state):
            emit_event(run_id=state.get("analysis_run_id"), tender_id=state.get("tender_id"),
                       version=state.get("tender_version"), event="node_started", node=name,
                       status="running")
            try:
                result = fn(state)
            except Exception as exc:
                if exc.__class__.__name__ in {"GraphInterrupt", "Interrupt"}:
                    emit_event(run_id=state.get("analysis_run_id"), tender_id=state.get("tender_id"),
                               version=state.get("tender_version"), event="human_review_required",
                               node=name, status="awaiting_human")
                    raise
                emit_event(run_id=state.get("analysis_run_id"), tender_id=state.get("tender_id"),
                           version=state.get("tender_version"), event="node_failed", node=name,
                           status="failed", message=str(exc))
                raise
            emit_event(run_id=state.get("analysis_run_id"), tender_id=state.get("tender_id"),
                       version=state.get("tender_version"), event="node_completed", node=name,
                       status="completed")
            return result
        return wrapped

    for name, fn in {
        "intake_guard": intake_guard, "load_tender": load_tender,
        "shred_requirements": shred_requirements, "merge_and_dedupe": merge_and_dedupe,
        "extract_key_facts": extract_key_facts, "reconcile_corrigenda": reconcile_corrigenda,
        "route_requirements": route_requirements, "eligibility_and_risk": eligibility_and_risk,
        "bid_score": bid_score, "gate1_review": gate1_review, "gate2_review": gate2_review,
        "write_no_bid_report": write_no_bid_report, "plan_response": plan_response,
        "write_sections": write_sections, "verify_claims": verify_claims,
        "rewrite_failed": rewrite_failed, "finalize": finalize,
    }.items():
        graph.add_node(name, instrument(name, fn))
    graph.add_edge(START, "intake_guard")
    graph.add_conditional_edges("intake_guard", _after_intake)
    graph.add_edge("load_tender", "shred_requirements")
    graph.add_edge("shred_requirements", "merge_and_dedupe")
    graph.add_edge("merge_and_dedupe", "extract_key_facts")
    graph.add_edge("extract_key_facts", "reconcile_corrigenda")  # amendments apply before routing
    graph.add_edge("reconcile_corrigenda", "route_requirements")
    graph.add_edge("route_requirements", "eligibility_and_risk")
    graph.add_edge("eligibility_and_risk", "bid_score")
    graph.add_edge("bid_score", "gate1_review")
    graph.add_conditional_edges("gate1_review", _after_gate1)
    graph.add_edge("write_no_bid_report", "finalize")
    graph.add_edge("plan_response", "write_sections")
    graph.add_edge("write_sections", "verify_claims")
    graph.add_edge("verify_claims", "rewrite_failed")
    graph.add_edge("rewrite_failed", "gate2_review")
    graph.add_edge("gate2_review", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def run_analysis(state: TenderState, *, checkpointer: Any = None) -> dict[str, Any]:
    """Run a complete deterministic analysis and return the JSON state."""
    result = build_graph(checkpointer=checkpointer).invoke(state)
    result.pop("_session", None)
    return result
