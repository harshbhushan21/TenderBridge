"""Requirement register and tender key facts."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.app.schemas.documents import SourceSpan


class RequirementCategory(str, Enum):
    eligibility_financial = "eligibility_financial"     # turnover, net worth
    eligibility_experience = "eligibility_experience"   # similar works
    eligibility_certification = "eligibility_certification"
    eligibility_registration = "eligibility_registration"  # Udyam, GST, OEM MAF, blacklisting
    personnel = "personnel"
    technical = "technical"          # scope / SLA / methodology
    commercial = "commercial"        # payment, PBG, penalty, LD, liability
    legal = "legal"
    submission = "submission"        # forms, formats, envelopes
    evaluation = "evaluation"        # scoring criteria
    other = "other"


class Modality(str, Enum):
    shall = "shall"        # mandatory
    should = "should"
    may = "may"
    informational = "informational"


class Requirement(BaseModel):
    requirement_id: str              # stable, e.g. "REQ-PQ-05"
    tender_id: str
    tender_version: int = 1
    clause_ref: str | None = None    # "PQ-05", "3.2.5"
    title: str = ""
    text: str                        # verbatim or near-verbatim clause
    category: RequirementCategory = RequirementCategory.other
    modality: Modality = Modality.shall
    mandatory: bool = True
    hard_gate: bool = False          # failing => NO_BID regardless of score
    section_path: str | None = None
    source: SourceSpan
    extra_sources: list[SourceSpan] = Field(default_factory=list)
    confidence: float = 1.0
    needs_review: bool = False
    superseded_by: str | None = None  # amendment change id
    amended: bool = False
    parsed_rule: dict[str, Any] | None = None  # EligibilityRule JSON if machine-checkable
    tags: list[str] = Field(default_factory=list)


class RequirementExtraction(BaseModel):
    """LLM structured output for the shredder (one section)."""
    requirements: list[ExtractedRequirement] = Field(default_factory=list)


class ExtractedRequirement(BaseModel):
    clause_ref: str | None = None
    title: str = ""
    text: str
    category: RequirementCategory = RequirementCategory.other
    modality: Modality = Modality.shall
    mandatory: bool = True
    page: int | None = None
    quote: str = Field(default="", description="Exact supporting quote from the section text")
    confidence: float = 0.8


RequirementExtraction.model_rebuild()


class Money(BaseModel):
    amount_inr: float               # canonical rupees
    display: str = ""               # original text e.g. "₹ 45 Cr"

    @property
    def crore(self) -> float:
        return self.amount_inr / 1e7

    @property
    def lakh(self) -> float:
        return self.amount_inr / 1e5


class KeyFact(BaseModel):
    name: str
    value: Any
    source: SourceSpan | None = None
    confidence: float = 1.0


class KeyFacts(BaseModel):
    tender_id: str
    tender_version: int = 1
    reference_no: str | None = None
    title: str | None = None
    buyer: str | None = None
    submission_deadline: datetime | None = None
    prebid_meeting: datetime | None = None
    bid_opening: datetime | None = None
    bid_validity_days: int | None = None
    estimated_value: Money | None = None
    emd: Money | None = None
    pbg_percent: float | None = None
    contract_period_months: int | None = None
    evaluation_method: str | None = None  # QCBS 70:30, L1, etc.
    general_turnover_threshold: Money | None = None
    mse_turnover_threshold: Money | None = None
    mse_relaxation_allowed: bool | None = None
    payment_terms: str | None = None
    penalty_cap_percent: float | None = None
    liability_cap: str | None = None
    facts: list[KeyFact] = Field(default_factory=list)  # all facts with sources
    missing: list[str] = Field(default_factory=list)   # never guessed

    def source_for(self, name: str) -> SourceSpan | None:
        for f in self.facts:
            if f.name == name:
                return f.source
        return None

    @property
    def deadline_date(self) -> date | None:
        return self.submission_deadline.date() if self.submission_deadline else None
