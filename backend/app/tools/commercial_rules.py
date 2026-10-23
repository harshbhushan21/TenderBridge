"""Compare tender commercial clauses with the company's approved positions."""
from __future__ import annotations

from backend.app.schemas.eligibility import RiskLevel, RiskPositionRecord


def assess_commercial_risk(category: str, value: float | None,
                           position: RiskPositionRecord | None) -> dict:
    if position is None:
        return {"category": category, "level": RiskLevel.review.value,
                "summary": "No approved policy position is configured.", "approver": None}
    if value is None:
        return {"category": category, "level": RiskLevel.review.value,
                "summary": "Commercial value is missing and requires review.", "approver": position.approver}
    if position.higher_is_worse:
        level = RiskLevel.within_policy if position.within_policy_max is not None and value <= position.within_policy_max else (
            RiskLevel.review if position.review_max is None or value <= position.review_max else RiskLevel.escalate)
    else:
        level = RiskLevel.within_policy if position.within_policy_max is not None and value >= position.within_policy_max else (
            RiskLevel.review if position.review_max is None or value >= position.review_max else RiskLevel.escalate)
    return {"category": category, "level": level.value, "value": value,
            "policy": position.policy, "approver": position.approver,
            "summary": f"{category} is {level.value} against the approved policy."}


check_commercial_risk = assess_commercial_risk
