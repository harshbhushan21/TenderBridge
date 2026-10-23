"""LangGraph shared state.

State values are kept JSON-serialisable (dicts / lists of model dumps) so that
any checkpointer (memory, sqlite, postgres) can persist them. Use the helpers
`as_models()` to rehydrate Pydantic models inside nodes.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def merge_by_key(key: str):
    """Reducer: merge two lists of dicts, later items replace earlier ones with same key."""
    def _reduce(left: list[dict] | None, right: list[dict] | None) -> list[dict]:
        if right is None:
            return left or []
        if left is None:
            return list(right)
        if right and right[0] == {"__reset__": True}:
            return list(right[1:])
        out: dict[Any, dict] = {d[key]: d for d in left if key in d}
        order = [d[key] for d in left if key in d]
        for d in right:
            k = d.get(key)
            if k not in out:
                order.append(k)
            out[k] = d
        return [out[k] for k in order]
    return _reduce


def merge_dict(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class TenderState(TypedDict, total=False):
    # --- identity ---
    tender_id: str
    tender_version: int
    analysis_run_id: str
    company_id: str
    mode: Literal["full_analysis", "impact"]       # impact = incremental re-analysis
    analysis_mode: Literal["focused", "full"]
    previous_run_id: str | None
    previous_version: int | None

    # --- intake ---
    intake_ok: bool
    stop_reason: str | None
    flags: Annotated[list[dict], operator.add]    # GuardrailFlag dumps

    # --- tender content ---
    sections: list[dict]                          # ParsedSection dumps (effective version)
    raw_requirements: Annotated[list[dict], operator.add]   # fan-out results from shredder
    requirements: Annotated[list[dict], merge_by_key("requirement_id")]
    key_facts: dict                               # KeyFacts dump
    amendment_ids: list[str]
    change_map: dict                              # requirement_id -> [change_id]
    invalidated_checks: list[str]
    reusable_checks: list[str]
    derived_impacts: list[dict]
    routes: list[dict]                            # requirement_id -> check/tool chosen by the router

    # --- analysis ---
    compliance: Annotated[list[dict], merge_by_key("requirement_id")]
    risks: Annotated[list[dict], merge_by_key("risk_id")]
    assessment: dict                              # BidAssessment dump
    scoring_policy: dict                          # active deterministic rule/scoring pack
    scoring_factors: dict[str, float]             # optional precomputed factor inputs
    static_scores: dict[str, float]               # policy-owned non-tender factor inputs

    # --- gate 1 ---
    gate1_decision: dict | None                   # GateDecision dump

    # --- drafting ---
    response_plan: dict
    drafts: Annotated[list[dict], merge_by_key("section_key")]
    verifier_reports: Annotated[list[dict], merge_by_key("draft_id")]
    rewrite_counts: Annotated[dict, merge_dict]
    gate2_reviews: Annotated[dict, merge_dict]    # section_key -> DraftReview dump
    compliance_gaps: list[dict]

    # --- outputs / ops ---
    exports: Annotated[list[dict], operator.add]
    no_bid_report: dict | None
    errors: Annotated[list[str], operator.add]
    usage: Annotated[dict, merge_dict]            # node -> {calls, tokens, cost}
    node_timings: Annotated[dict, merge_dict]


def as_models(items: list[dict] | None, model: type[M]) -> list[M]:
    return [model.model_validate(i) for i in (items or [])]


def as_model(item: dict | None, model: type[M]) -> M | None:
    return model.model_validate(item) if item else None


def dump(obj: BaseModel | list[BaseModel]) -> Any:
    if isinstance(obj, list):
        return [o.model_dump(mode="json") for o in obj]
    return obj.model_dump(mode="json")
