"""Incremental amendment impact classification."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from backend.app.schemas.amendments import AmendmentChange, DerivedImpact
from backend.app.tools.amendment_diff import invalidation_for


def classify_impacts(changes: Sequence[AmendmentChange | dict[str, Any]],
                     requirement_ids: set[str]) -> dict[str, list[Any]]:
    direct: list[Any] = []
    derived: list[Any] = []
    for raw in changes:
        change = raw if isinstance(raw, AmendmentChange) else AmendmentChange.model_validate(raw)
        direct.append(change)
        affected = [rid for rid in change.affected_requirement_ids if rid in requirement_ids]
        for check in change.downstream_impacts or invalidation_for(change):
            derived.append(DerivedImpact(
                impact_id=f"IMP-{change.change_id}-{check}", caused_by=[change.change_id],
                requirement_id=affected[0] if affected else None, check_key=check,
                summary=f"{check} must be re-evaluated after {change.change_id}.",
                severity="high" if check in {"certificate_validity", "project_eligibility"} else "medium",
            ))
    return {"direct_amendments": direct, "derived_impacts": derived}


def reusable_checks(all_checks: set[str], invalidated: set[str]) -> list[str]:
    return sorted(all_checks - invalidated)
