"""Company facts, machine-checkable eligibility rules and compliance results."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from backend.app.schemas.documents import SourceSpan


# --------------------------------------------------------------------------- #
# Status vocabularies                                                          #
# --------------------------------------------------------------------------- #
class EligibilityStatus(str, Enum):
    meets = "meets"
    meets_with_undertaking = "meets_with_undertaking"
    meets_with_substitution = "meets_with_substitution"
    needs_action = "needs_action"
    partial = "partial"
    needs_human = "needs_human"
    gap = "gap"

    @property
    def passing(self) -> bool:
        return self in (EligibilityStatus.meets, EligibilityStatus.meets_with_undertaking,
                        EligibilityStatus.meets_with_substitution)


class RiskLevel(str, Enum):
    within_policy = "within_policy"
    review = "review"
    escalate = "escalate"


# --------------------------------------------------------------------------- #
# Company fact records (SQL is the authority — principle 5)                    #
# --------------------------------------------------------------------------- #
class CompanyProfile(BaseModel):
    company_id: str
    name: str
    is_mse: bool = False
    udyam_number: str | None = None
    msme_category: str | None = None  # micro | small | medium
    incorporation_date: date | None = None
    gstin: str | None = None
    pan: str | None = None
    authorised_signatory: str | None = None
    blacklisted: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)
    source: SourceSpan | None = None


class FinancialRecord(BaseModel):
    company_id: str
    fiscal_year: str                 # "FY2023-24"
    revenue_inr: float               # canonical rupees
    net_worth_inr: float | None = None
    profit_after_tax_inr: float | None = None
    audited: bool = True
    ca_certified: bool = False
    source: SourceSpan | None = None


class CertificateStatus(str, Enum):
    held = "held"
    expired = "expired"
    not_held = "not_held"
    in_progress = "in_progress"     # audit in progress — NOT valid (clarification 9)
    suspended = "suspended"


class CertificateRecord(BaseModel):
    company_id: str
    cert_id: str
    name: str                        # "ISO/IEC 27001:2022"
    standard: str | None = None      # normalized key e.g. "ISO27001"
    scope: str | None = None
    certificate_no: str | None = None
    issuer: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    status: CertificateStatus = CertificateStatus.held
    source: SourceSpan | None = None


class ProjectRecord(BaseModel):
    company_id: str
    project_id: str                  # "PRJ-005"
    name: str
    client: str | None = None
    client_type: str | None = None   # central_govt | state_govt | psu | private
    scope_tags: list[str] = Field(default_factory=list)  # ["data_centre_om", "noc_24x7"]
    description: str = ""
    contract_value_inr: float | None = None
    eligible_value_inr: float | None = None  # certified eligible share — use this, not total
    start_date: date | None = None
    completion_date: date | None = None
    status: Literal["completed", "ongoing", "terminated"] = "completed"
    completion_certificate: bool = False
    consortium_share_pct: float | None = None
    source: SourceSpan | None = None


class PersonCert(BaseModel):
    name: str
    standard: str | None = None
    expiry_date: date | None = None
    valid: bool | None = None        # HR tracker verdict wins over CV text


class PersonRecord(BaseModel):
    company_id: str
    person_id: str                   # "NDS-E105"
    name: str
    role: str
    years_experience: float = 0
    qualifications: list[str] = Field(default_factory=list)
    certifications: list[PersonCert] = Field(default_factory=list)
    available: bool = True
    available_from: date | None = None
    source: SourceSpan | None = None


class RiskPositionRecord(BaseModel):
    company_id: str
    category: str                    # payment_terms | pbg | penalty_cap | liability_cap | ld ...
    policy: str                      # human-readable approved position
    within_policy_max: float | None = None
    review_max: float | None = None  # above => escalate
    higher_is_worse: bool = True
    unit: str = "percent"
    approver: str | None = None      # "CFO", "CEO"
    extra: dict[str, Any] = Field(default_factory=dict)
    source: SourceSpan | None = None


# --------------------------------------------------------------------------- #
# Machine-checkable eligibility rules                                          #
# --------------------------------------------------------------------------- #
class TurnoverRule(BaseModel):
    kind: Literal["turnover"] = "turnover"
    general_threshold_inr: float
    mse_threshold_inr: float | None = None   # applies only if mse_relaxation_allowed
    mse_relaxation_allowed: bool = False
    fiscal_years: list[str] = Field(default_factory=list)  # empty => latest n_years
    n_years: int = 3
    aggregation: Literal["average", "each_year", "any_year", "sum"] = "average"


class NetWorthRule(BaseModel):
    kind: Literal["net_worth"] = "net_worth"
    min_inr: float = 0.0
    strictly_positive: bool = True
    fiscal_years: list[str] = Field(default_factory=list)
    n_years: int = 1


class SimilarWorkBranch(BaseModel):
    count: int                       # number of projects
    min_value_inr: float             # each project at least this eligible value


class SimilarWorkRule(BaseModel):
    kind: Literal["similar_work"] = "similar_work"
    branches: list[SimilarWorkBranch]        # OR of branches
    window_years: int = 7
    reference_date: date | None = None       # window counted back from this (bid deadline)
    required_scope_tags: list[str] = Field(default_factory=list)  # any-of
    client_types: list[str] = Field(default_factory=list)          # empty => any
    require_completion_certificate: bool = True
    allow_ongoing: bool = False


class CertificationRule(BaseModel):
    kind: Literal["certification"] = "certification"
    standard: str                    # normalized "ISO27001"
    display_name: str = ""
    required_scope_keywords: list[str] = Field(default_factory=list)
    valid_on: Literal["submission_deadline", "bid_opening", "date"] = "submission_deadline"
    valid_on_date: date | None = None
    accept_in_progress: bool = False


class PersonnelRule(BaseModel):
    kind: Literal["personnel"] = "personnel"
    role: str
    count: int = 1
    min_years: float = 0
    required_certifications: list[str] = Field(default_factory=list)  # all-of standards
    any_of_certifications: list[str] = Field(default_factory=list)
    required_qualifications: list[str] = Field(default_factory=list)
    as_of: date | None = None


class DocumentPresenceRule(BaseModel):
    kind: Literal["document"] = "document"
    document_type: str               # "udyam", "oem_maf", "no_blacklisting_declaration"
    tender_specific: bool = False    # e.g. MAF must be issued for this tender
    undertaking_acceptable: bool = False


EligibilityRule = Annotated[
    TurnoverRule | NetWorthRule | SimilarWorkRule | CertificationRule | PersonnelRule | DocumentPresenceRule,
    Field(discriminator="kind"),
]


class RuleEnvelope(BaseModel):
    """Wrapper so a rule can be parsed from JSON stored on a Requirement."""
    rule: EligibilityRule


# --------------------------------------------------------------------------- #
# Results                                                                      #
# --------------------------------------------------------------------------- #
class Calculation(BaseModel):
    label: str
    value: Any
    unit: str | None = None


class RuleResult(BaseModel):
    """Output of every deterministic rule tool."""
    rule_kind: str
    status: EligibilityStatus
    summary: str
    calculations: list[Calculation] = Field(default_factory=list)
    evidence: list[SourceSpan] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)          # what the bid team must do
    needs_human_reason: str | None = None
    unknowns: list[str] = Field(default_factory=list)


class ComplianceItem(BaseModel):
    requirement_id: str
    tender_id: str
    tender_version: int
    category: str
    mandatory: bool = True
    hard_gate: bool = False
    status: EligibilityStatus
    summary: str
    rule_result: RuleResult | None = None
    tender_source: SourceSpan
    company_evidence: list[SourceSpan] = Field(default_factory=list)
    owner: str | None = None
    actions: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    checked_by: Literal["rule", "llm", "human"] = "rule"
    reused_from_version: int | None = None  # incremental re-analysis


class RiskItem(BaseModel):
    risk_id: str
    requirement_id: str | None = None
    tender_id: str
    tender_version: int
    category: str
    level: RiskLevel
    tender_value: str
    policy_value: str
    summary: str
    approver: str | None = None
    approval_status: Literal["pending", "approved", "rejected", "not_required"] = "not_required"
    source: SourceSpan | None = None
    reused_from_version: int | None = None
