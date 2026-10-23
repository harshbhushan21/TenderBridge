"""Corrigendum / amendment diff and impact schemas."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.schemas.documents import SourceSpan


class ChangeType(str, Enum):
    date_change = "date_change"
    value_change = "value_change"        # amounts, percentages
    clause_replaced = "clause_replaced"
    clause_added = "clause_added"
    clause_deleted = "clause_deleted"
    clarification = "clarification"      # pre-bid clarification with authority
    eligibility_change = "eligibility_change"
    commercial_change = "commercial_change"
    format_change = "format_change"
    other = "other"


class AmendmentStatus(str, Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    diff_ready = "diff_ready"
    confirmed = "confirmed"
    rejected = "rejected"
    failed = "failed"


ChangeKind = Literal["added", "changed", "removed", "superseded", "clarified", "no_change"]


class AmendmentChange(BaseModel):
    """A DIRECT document amendment (as published by the buyer)."""
    change_id: str                     # "CHG-01"
    change_type: ChangeType
    kind: ChangeKind = "changed"       # what happened to the provision (corrigendum_diff_gold vocabulary)
    part: Literal["A", "B"] | None = None  # A = amendment, B = pre-bid response (A prevails)
    clause_ref: str | None = None
    field: str | None = None           # key-fact name if mapped e.g. "submission_deadline"
    old_value: str | None = None
    new_value: str | None = None
    old_source: SourceSpan | None = None
    new_source: SourceSpan
    affected_requirement_ids: list[str] = Field(default_factory=list)
    downstream_impacts: list[str] = Field(default_factory=list)  # check keys to invalidate
    summary: str = ""
    confidence: float = 1.0
    needs_review: bool = False


class DerivedImpact(BaseModel):
    """A company-specific consequence of an amendment (e.g. ISO expires before new deadline)."""
    impact_id: str
    caused_by: list[str]               # change_ids
    requirement_id: str | None = None
    check_key: str
    before: str | None = None
    after: str | None = None
    summary: str
    severity: str = "medium"           # low | medium | high | blocking


class AmendmentDiff(BaseModel):
    amendment_id: str
    tender_id: str
    base_version: int
    target_version: int
    changes: list[AmendmentChange] = Field(default_factory=list)
    derived_impacts: list[DerivedImpact] = Field(default_factory=list)  # preview, filled after rerun
    invalidated_checks: list[str] = Field(default_factory=list)
    reusable_checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None


class AmendmentConfirmation(BaseModel):
    reviewer: str
    comment: str | None = None
    accepted_change_ids: list[str] | None = None  # None => all
