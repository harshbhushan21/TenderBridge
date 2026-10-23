"""Policy-driven deterministic bid scoring.

The scorer accepts already-evaluated factors. It never asks an LLM to perform
arithmetic or decide whether a mandatory hard gate failed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

from backend.app.schemas.assessment import (
    BidAssessment,
    CriterionScore,
    HardGateResult,
    Recommendation,
)
from backend.app.schemas.eligibility import EligibilityStatus, RiskLevel
from backend.app.tools.rule_pack import load_rule_pack

_DEFAULT_FACTOR_LABELS = {
    "strategic_fit": "Strategic fit",
    "technical_capability": "Technical capability",
    "eligibility_confidence": "Eligibility confidence",
    "commercial_risk": "Commercial risk",
    "delivery_capacity": "Delivery capacity",
}


def _weights(policy: dict[str, Any]) -> dict[str, float]:
    raw = policy.get("weights") or {}
    total = sum(float(v) for v in raw.values())
    if not total:
        return {}
    return {str(k): float(v) / total for k, v in raw.items()}


def score_bid(
    *,
    tender_id: str,
    tender_version: int,
    analysis_run_id: str,
    factors: dict[str, float],
    hard_gates: list[HardGateResult] | None = None,
    conditions: list[str] | None = None,
    top_risks: list[str] | None = None,
    analysis_mode: str = "focused",
    rule_pack: dict[str, Any] | None = None,
) -> BidAssessment:
    """Calculate a weighted score and apply mandatory gates first."""
    policy = rule_pack or load_rule_pack()
    weights = _weights(policy)
    hard = hard_gates or []
    failures = [gate.requirement_id for gate in hard if not gate.passed]
    score = round(sum(float(factors.get(key, 0.0)) * weight
                      for key, weight in weights.items()), int(policy.get("rounding", 2)))
    thresholds = policy.get("thresholds") or {}
    bid_threshold = float(thresholds.get("bid", 70))
    conditional_threshold = float(thresholds.get("conditional", 55))
    condition_list = list(conditions or [])
    if failures:
        recommendation = Recommendation.NO_BID
    elif score >= bid_threshold:
        recommendation = Recommendation.BID_WITH_CONDITIONS if condition_list else Recommendation.BID
    elif score >= conditional_threshold:
        recommendation = Recommendation.BID_WITH_CONDITIONS
    else:
        recommendation = Recommendation.NO_BID
    criteria = [
        CriterionScore(
            key=key,
            label=_DEFAULT_FACTOR_LABELS.get(key, key.replace("_", " ").title()),
            weight=round(weights.get(key, 0.0) * 100, 4),
            raw_score=round(float(value), 2),
            weighted=round(float(value) * weights.get(key, 0.0), 2),
            inputs={"source": "deterministic_factor"},
        )
        for key, value in factors.items()
        if key in weights
    ]
    narrative = "Mandatory hard gates override the weighted score."
    if failures:
        narrative += f" Failed hard gates: {', '.join(failures)}."
    return BidAssessment(
        tender_id=tender_id,
        tender_version=tender_version,
        analysis_run_id=analysis_run_id,
        score=score,
        recommendation=recommendation,
        criteria=criteria,
        hard_gates=hard,
        hard_gate_failures=failures,
        conditions=condition_list,
        top_risks=list(top_risks or []),
        narrative=narrative,
        policy_version=str(policy.get("version", "default")),
        analysis_mode=cast(Literal["focused", "full"],
                           analysis_mode if analysis_mode in {"focused", "full"} else "focused"),
        created_at=datetime.now(UTC),
    )


def factors_from_results(
    statuses: list[EligibilityStatus],
    risk_levels: list[RiskLevel],
    *,
    static_scores: dict[str, float] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Derive the non-narrative factors used when no technical evaluator exists."""
    loaded = policy or load_rule_pack()
    status_points = loaded.get("eligibility_confidence_values") or {}
    risk_deductions = loaded.get("risk_deductions") or {}
    eligibility = (sum(float(status_points.get(s.value, 0.0)) for s in statuses) /
                   len(statuses) * 100) if statuses else 0.0
    # Policy: "100 minus risk_deductions per clause verdict" -> deductions add up
    # across clauses (v1: 25 + 5x5 = 50 -> 50; v2: 25 + 2x5 = 35 -> 65), floored at 0.
    commercial = max(0.0, 100.0 - sum(float(risk_deductions.get(r.value, 25.0)) for r in risk_levels))
    values = dict(static_scores or {})
    values.setdefault("eligibility_confidence", eligibility)
    values.setdefault("commercial_risk", commercial)
    return values


score_assessment = score_bid
