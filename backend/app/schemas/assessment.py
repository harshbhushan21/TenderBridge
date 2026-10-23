"""Bid scoring, human decisions, response plans, drafts and verification."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.documents import SourceSpan


class Recommendation(str, Enum):
    BID = "BID"
    BID_WITH_CONDITIONS = "BID_WITH_CONDITIONS"
    NO_BID = "NO_BID"


class ApprovalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    review_required = "review_required"


# --------------------------------------------------------------------------- #
# Scoring policy — loaded from demo_config/bid_scoring_policy.json             #
# --------------------------------------------------------------------------- #
class ScoringCriterion(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str                       # "eligibility_strength", "commercial_risk", "strategic_fit"...
    label: str = ""
    weight: float                  # weights are normalised by the scorer
    # Optional deterministic mapping: each sub-signal -> points (0..100)
    signal: str | None = None      # which computed signal feeds this criterion
    points: dict[str, float] = Field(default_factory=dict)
    default_score: float | None = None


class BidScoringPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str = "default"
    criteria: list[ScoringCriterion] = Field(default_factory=list)
    bid_threshold: float = 80.0                # >= => BID (if no conditions)
    conditional_threshold: float = 60.0        # >= => BID_WITH_CONDITIONS
    hard_gate_categories: list[str] = Field(default_factory=lambda: [
        "eligibility_financial", "eligibility_experience", "eligibility_certification",
        "eligibility_registration",
    ])
    # statuses which turn a passing hard gate into a "condition"
    conditional_statuses: list[str] = Field(default_factory=lambda: [
        "needs_action", "meets_with_undertaking", "partial", "needs_human",
    ])
    # Static inputs (strategic fit etc.) that are policy judgments, not tender facts
    static_scores: dict[str, float] = Field(default_factory=dict)
    risk_level_points: dict[str, float] = Field(default_factory=lambda: {
        "within_policy": 100.0, "review": 60.0, "escalate": 20.0,
    })
    status_points: dict[str, float] = Field(default_factory=lambda: {
        "meets": 100.0, "meets_with_substitution": 90.0, "meets_with_undertaking": 85.0,
        "needs_action": 60.0, "partial": 50.0, "needs_human": 50.0, "gap": 0.0,
    })
    rounding: int = 2


class CriterionScore(BaseModel):
    key: str
    label: str
    weight: float
    raw_score: float               # 0..100
    weighted: float
    rationale: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)


class HardGateResult(BaseModel):
    requirement_id: str
    label: str
    status: str
    passed: bool
    summary: str
    evidence: list[SourceSpan] = Field(default_factory=list)


class BidAssessment(BaseModel):
    tender_id: str
    tender_version: int
    analysis_run_id: str
    score: float
    recommendation: Recommendation
    criteria: list[CriterionScore] = Field(default_factory=list)
    hard_gates: list[HardGateResult] = Field(default_factory=list)
    hard_gate_failures: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    narrative: str = ""
    policy_version: str = "default"
    analysis_mode: Literal["focused", "full"] = "focused"
    created_at: datetime | None = None


class GateDecision(BaseModel):
    """Gate 1 human decision (version-bound)."""
    tender_version: int
    action: Literal["approve_bid", "no_bid", "defer"]
    reviewer: str
    comment: str | None = None
    conditions_accepted: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Drafting                                                                     #
# --------------------------------------------------------------------------- #
class PlannedSection(BaseModel):
    section_key: str               # "T1-2", "T1-4"
    title: str
    format_ref: str | None = None  # "Format T-1 §2"
    requirement_ids: list[str] = Field(default_factory=list)
    evaluation_criteria: list[str] = Field(default_factory=list)
    kb_queries: list[str] = Field(default_factory=list)
    max_words: int = 600
    notes: str = ""


class ResponsePlan(BaseModel):
    tender_id: str
    tender_version: int
    sections: list[PlannedSection] = Field(default_factory=list)
    unmapped_requirement_ids: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    claim_id: str
    text: str
    citations: list[SourceSpan] = Field(default_factory=list)
    claim_type: Literal["numeric", "certification", "client", "date", "capability", "sla",
                        "personnel", "other"] = "other"


class SectionDraft(BaseModel):
    draft_id: str
    tender_id: str
    tender_version: int
    section_key: str
    title: str
    body_markdown: str
    claims: list[Claim] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)  # missing evidence => placeholder
    revision: int = 0
    status: ApprovalStatus = ApprovalStatus.pending
    stale: bool = False


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Literal["supported", "unsupported", "contradicted", "conditional", "unverifiable"]
    reason: str
    evidence: list[SourceSpan] = Field(default_factory=list)


class VerifierReport(BaseModel):
    draft_id: str
    revision: int
    verdicts: list[ClaimVerdict] = Field(default_factory=list)
    passed: bool = False
    feedback: str = ""

    @property
    def failed_claims(self) -> list[ClaimVerdict]:
        return [v for v in self.verdicts if v.verdict in ("unsupported", "contradicted")]


class DraftReview(BaseModel):
    """Gate 2 per-section review."""
    action: Literal["approve", "edit", "reject", "request_changes"]
    reviewer: str
    comment: str | None = None
    edited_markdown: str | None = None


class ComplianceGap(BaseModel):
    requirement_id: str
    reason: str
    severity: Literal["low", "medium", "high"] = "medium"
