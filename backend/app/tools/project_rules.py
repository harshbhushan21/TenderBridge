"""Deterministic similar-work evaluation for PQ-style project rules."""
from __future__ import annotations

from datetime import date

from backend.app.ops.langsmith import traceable
from backend.app.schemas.eligibility import (
    Calculation,
    EligibilityStatus,
    ProjectRecord,
    RuleResult,
    SimilarWorkRule,
)
from backend.app.tools.date_normalization import subtract_years


def _similar(project: ProjectRecord, rule: SimilarWorkRule) -> bool:
    tags = {tag.lower() for tag in project.scope_tags}
    required = {tag.lower() for tag in rule.required_scope_tags}
    if required and not tags.intersection(required):
        return False
    if rule.client_types and project.client_type not in rule.client_types:
        return False
    if project.status == "ongoing" and not rule.allow_ongoing:
        return False
    if rule.require_completion_certificate and not project.completion_certificate:
        return False
    return True


def _pending_value(project: ProjectRecord) -> float | None:
    """Value a project could count for once the client certifies it: the bidder's
    own share, never the consortium total (PRJ-005: 45% of Rs 38 Cr = Rs 17.10 Cr)."""
    if project.contract_value_inr is None:
        return None
    if project.consortium_share_pct is not None:
        return project.contract_value_inr * project.consortium_share_pct / 100
    return project.contract_value_inr


@traceable(name="check_similar_work", run_type="tool")
def check_similar_work(projects: list[ProjectRecord], rule: SimilarWorkRule) -> RuleResult:
    """Evaluate every OR branch using client-certified eligible value only."""
    reference = rule.reference_date or date.today()
    lower_bound = subtract_years(reference, rule.window_years)
    candidates: list[dict] = []
    definite: list[ProjectRecord] = []
    pending: list[ProjectRecord] = []
    for project in projects:
        in_window = bool(project.completion_date and lower_bound <= project.completion_date <= reference)
        similar = _similar(project, rule) if in_window else False
        usable = project.eligible_value_inr is not None
        if in_window and similar and usable:
            definite.append(project)
        elif (in_window and similar and project.eligible_value_inr is None and rule.count_uncertified_share
              and _pending_value(project)):
            pending.append(project)
        candidates.append({
            "project_id": project.project_id,
            "eligible_value_inr": project.eligible_value_inr,
            "contract_value_inr": project.contract_value_inr,
            "pending_value_inr": _pending_value(project) if project in pending else None,
            "in_window": in_window,
            "similar": similar,
            "pending_client_certificate": project in pending,
        })

    branch_results: list[dict] = []
    passing_branch: dict | None = None
    for index, branch in enumerate(rule.branches):
        qualifying = [p for p in definite if (p.eligible_value_inr or 0) >= branch.min_value_inr]
        pending_ok = [p for p in pending if (_pending_value(p) or 0) >= branch.min_value_inr]
        pending_count = len(pending_ok)
        result = {
            "branch": chr(ord("a") + index),
            "required_count": branch.count,
            "threshold_inr": branch.min_value_inr,
            "definite": [p.project_id for p in qualifying],
            "pending_human": [p.project_id for p in pending_ok],
            "verdict": "meets" if len(qualifying) >= branch.count else (
                "needs_human" if len(qualifying) + pending_count >= branch.count else "gap"
            ),
        }
        branch_results.append(result)
        if result["verdict"] == "meets" and passing_branch is None:
            passing_branch = result

    if passing_branch:
        status = EligibilityStatus.meets
        summary = f"Similar-work branch {passing_branch['branch']} meets the requirement."
    elif any(r["verdict"] == "needs_human" for r in branch_results):
        status = EligibilityStatus.needs_human
        summary = "Similar-work evidence is incomplete and needs client-certified eligible value."
    else:
        status = EligibilityStatus.gap
        summary = "No similar-work branch meets the requirement."
    calculations = [
        Calculation(label="reference date", value=reference.isoformat()),
        Calculation(label="window start", value=lower_bound.isoformat()),
        Calculation(label="definite similar projects", value=[p.project_id for p in definite]),
        Calculation(label="branch results", value=branch_results),
    ]
    return RuleResult(rule_kind="similar_work", status=status, summary=summary,
                      calculations=calculations, candidates=candidates,
                      unknowns=["client-certified eligible value"] if status == EligibilityStatus.needs_human else [],
                      needs_human_reason="client-certified consortium share is missing"
                      if status == EligibilityStatus.needs_human else None)
