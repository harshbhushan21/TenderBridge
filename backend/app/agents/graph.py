"""TenderBridge LangGraph construction and execution helpers."""
from __future__ import annotations

from typing import Any

from backend.app.agents.nodes.core import (
    bid_score,
    eligibility_and_risk,
    extract_key_facts,
    finalize,
    gate1_review,
    intake_guard,
    load_tender,
    merge_and_dedupe,
    reconcile_corrigenda,
    route_requirements,
    shred_requirements,
    write_no_bid_report,
)
from backend.app.agents.nodes.drafting import (
    after_gate2,
    gate2_review,
    needs_rewrite,
    plan_response,
    rewrite_failed,
    verify_claims,
    write_sections,
)
from backend.app.ops.events import emit_event
from backend.app.schemas.graph_state import TenderState


def _after_intake(state: TenderState) -> str:
    return "load_tender" if state.get("intake_ok") else "finalize"


def _after_gate1(state: TenderState) -> str:
    """A No-Bid decision (or a NO_BID recommendation the approver did not overturn) gets the report.
    Drafting is a separate graph started after a bid approval (build_drafting_graph)."""
    action = (state.get("gate1_decision") or {}).get("action")
    no_bid = (state.get("assessment") or {}).get("recommendation") == "NO_BID"
    return "write_no_bid_report" if action == "no_bid" or (no_bid and action != "approve_bid") else "finalize"


def _instrument(name: str, fn):
    """Emit node_started / node_completed / node_failed / human_review_required events."""
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

    for name, fn in {
        "intake_guard": intake_guard, "load_tender": load_tender,
        "shred_requirements": shred_requirements, "merge_and_dedupe": merge_and_dedupe,
        "extract_key_facts": extract_key_facts, "reconcile_corrigenda": reconcile_corrigenda,
        "route_requirements": route_requirements, "eligibility_and_risk": eligibility_and_risk,
        "bid_score": bid_score, "gate1_review": gate1_review,
        "write_no_bid_report": write_no_bid_report, "finalize": finalize,
    }.items():
        graph.add_node(name, _instrument(name, fn))
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
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def build_drafting_graph(*, checkpointer: Any = None):
    """Cited drafting after a Gate 1 bid approval, on the persisted analysis:
    plan -> write -> verify (-> rewrite -> verify, bounded) -> Gate 2 (-> write on request_changes) -> finalize."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(TenderState)
    for name, fn in {"plan_response": plan_response, "write_sections": write_sections,
                     "verify_claims": verify_claims, "rewrite_failed": rewrite_failed,
                     "gate2_review": gate2_review, "finalize": finalize}.items():
        graph.add_node(name, _instrument(name, fn))
    graph.add_edge(START, "plan_response")
    graph.add_edge("plan_response", "write_sections")
    graph.add_edge("write_sections", "verify_claims")
    graph.add_conditional_edges("verify_claims",
                                lambda st: "rewrite_failed" if needs_rewrite(st) else "gate2_review")
    graph.add_edge("rewrite_failed", "verify_claims")
    graph.add_conditional_edges("gate2_review", after_gate2)
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def run_analysis(state: TenderState, *, checkpointer: Any = None) -> dict[str, Any]:
    """Run a complete deterministic analysis and return the JSON state."""
    result = build_graph(checkpointer=checkpointer).invoke(state)
    result.pop("_session", None)
    return result
