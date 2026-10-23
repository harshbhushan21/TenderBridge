"""TenderBridge LangGraph construction and execution helpers."""
from __future__ import annotations

from typing import Any

from backend.app.agents.nodes.core import (
    bid_score,
    eligibility_and_risk,
    extract_key_facts,
    finalize,
    intake_guard,
    load_tender,
    merge_and_dedupe,
    reconcile_corrigenda,
    route_requirements,
    shred_requirements,
    write_no_bid_report,
)
from backend.app.schemas.graph_state import TenderState


def _after_intake(state: TenderState) -> str:
    return "load_tender" if state.get("intake_ok") else "finalize"


def _after_score(state: TenderState) -> str:
    assessment = state.get("assessment") or {}
    return "write_no_bid_report" if assessment.get("recommendation") == "NO_BID" else "finalize"


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
    graph.add_node("intake_guard", intake_guard)
    graph.add_node("load_tender", load_tender)
    graph.add_node("shred_requirements", shred_requirements)
    graph.add_node("merge_and_dedupe", merge_and_dedupe)
    graph.add_node("reconcile_corrigenda", reconcile_corrigenda)
    graph.add_node("extract_key_facts", extract_key_facts)
    graph.add_node("route_requirements", route_requirements)
    graph.add_node("eligibility_and_risk", eligibility_and_risk)
    graph.add_node("bid_score", bid_score)
    graph.add_node("write_no_bid_report", write_no_bid_report)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "intake_guard")
    graph.add_conditional_edges("intake_guard", _after_intake)
    graph.add_edge("load_tender", "shred_requirements")
    graph.add_edge("shred_requirements", "merge_and_dedupe")
    graph.add_edge("merge_and_dedupe", "reconcile_corrigenda")
    graph.add_edge("reconcile_corrigenda", "extract_key_facts")
    graph.add_edge("extract_key_facts", "route_requirements")
    graph.add_edge("route_requirements", "eligibility_and_risk")
    graph.add_edge("eligibility_and_risk", "bid_score")
    graph.add_conditional_edges("bid_score", _after_score)
    graph.add_edge("write_no_bid_report", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def run_analysis(state: TenderState, *, checkpointer: Any = None) -> dict[str, Any]:
    """Run a complete deterministic analysis and return the JSON state."""
    result = build_graph(checkpointer=checkpointer).invoke(state)
    result.pop("_session", None)
    return result
