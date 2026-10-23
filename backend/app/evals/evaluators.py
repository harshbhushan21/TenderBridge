"""Small, composable evaluators used by the Phase 8 harness."""
from __future__ import annotations

from typing import Any


def recall(expected: set[str], actual: set[str]) -> float:
    return 1.0 if not expected else len(expected & actual) / len(expected)


def evaluate_requirements(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = {str(item.get("requirement_id")) for item in expected}
    actual_ids = {str(item.get("requirement_id")) for item in actual}
    found = len(expected_ids & actual_ids)
    for item in expected:
        if str(item.get("requirement_id")) in actual_ids:
            continue
        locate = str(item.get("locate_span") or item.get("text") or "").lower()
        tokens = set(locate.split())
        if any(locate and (locate in str(row.get("text", "")).lower()
                           or len(tokens & set(str(row.get("text", "")).lower().split()))
                           / max(len(tokens), 1) >= 0.6) for row in actual):
            found += 1
    return {"expected": len(expected_ids), "found": found,
            "recall": found / len(expected_ids) if expected_ids else 0.0}


def evaluate_retrieval(expected: list[dict[str, Any]], retrieved: dict[str, list[str]],
                       k: int = 6) -> dict[str, Any]:
    hits = 0
    for item in expected:
        answer_id = str(item.get("answer_id") or item.get("expected_id") or "")
        if answer_id and answer_id in retrieved.get(str(item.get("id") or item.get("question")), [])[:k]:
            hits += 1
    return {"questions": len(expected), "hits": hits, "recall_at_6": hits / len(expected) if expected else 0.0}
