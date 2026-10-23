"""Requirement fan-out used by the Gate 1 analysis graph."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any


def route_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    category = requirement.get("category", "other")
    tool = {
        "eligibility_financial": "financial_rules",
        "eligibility_experience": "project_rules",
        "eligibility_certification": "certificate_rules",
        "eligibility_registration": "registration_rules",
        "personnel": "personnel_rules",
        "commercial": "commercial_rules",
    }.get(category, "rag_grader")
    return {"requirement_id": requirement["requirement_id"], "category": category, "tool": tool}


def fan_out_requirements(requirements: list[dict[str, Any]], *,
                         max_workers: int = 4) -> list[dict[str, Any]]:
    """Route requirements concurrently with a bounded worker pool."""
    with ThreadPoolExecutor(max_workers=max(1, max_workers),
                            thread_name_prefix="requirement-route") as pool:
        return list(pool.map(route_requirement, requirements))


def send_routes(requirements: list[dict[str, Any]]) -> list[Any]:
    """Return LangGraph Send objects for callers that build a fan-out graph."""
    try:
        from langgraph.constants import Send
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("LangGraph is required for requirement fan-out") from exc
    return [Send("route_requirement", {"requirement": item}) for item in requirements]
