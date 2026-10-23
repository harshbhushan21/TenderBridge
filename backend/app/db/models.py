"""ORM models. One durable store for facts, chunks, work state and audit.

Embeddings use pgvector on PostgreSQL and a JSON list on SQLite (searched in
Python) so the system runs with zero setup.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from backend.app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


class EmbeddingType(TypeDecorator):
    """pgvector `vector(dim)` on Postgres, JSON elsewhere."""
    impl = JSON
    cache_ok = True

    def __init__(self, dim: int | None = None, *a, **kw):
        super().__init__(*a, **kw)
        self.dim = dim or get_settings().embedding_dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# =========================================================================== #
# Company KB                                                                  #
# =========================================================================== #
class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    company_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_mse: Mapped[bool] = mapped_column(Boolean, default=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # CompanyProfile dump
    kb_status: Mapped[str] = mapped_column(String(32), default="empty")  # empty|ingesting|ready|failed
    kb_report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class KbDocument(Base, TimestampMixin):
    __tablename__ = "kb_documents"
    __table_args__ = (UniqueConstraint("company_id", "file_sha256", name="uq_kb_doc_hash"),)
    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    rel_path: Mapped[str | None] = mapped_column(String(512))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str | None] = mapped_column(String(64), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer)
    allowed_roles: Mapped[list[Any]] = mapped_column(JSON, default=lambda: ["all"])
    sensitivity: Mapped[str] = mapped_column(String(32), default="internal")
    approved_for_reuse: Mapped[bool] = mapped_column(Boolean, default=False)
    source_kind: Mapped[str] = mapped_column(String(32), default="demo_data")
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    live_subset: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    parsed_path: Mapped[str | None] = mapped_column(String(1024))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    chunks: Mapped[list[KbChunk]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    chunk_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("kb_documents.doc_id", ondelete="CASCADE"), index=True)
    company_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(80), index=True)
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(512))
    doc_type: Mapped[str | None] = mapped_column(String(64), index=True)
    allowed_roles: Mapped[list[Any]] = mapped_column(JSON, default=lambda: ["all"])
    approved_for_reuse: Mapped[bool] = mapped_column(Boolean, default=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(EmbeddingType(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class Financial(Base):
    __tablename__ = "financials"
    __table_args__ = (UniqueConstraint("company_id", "fiscal_year", name="uq_fin_fy"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    fiscal_year: Mapped[str] = mapped_column(String(16))
    revenue_inr: Mapped[float] = mapped_column(Float)
    net_worth_inr: Mapped[float | None] = mapped_column(Float)
    profit_after_tax_inr: Mapped[float | None] = mapped_column(Float)
    audited: Mapped[bool] = mapped_column(Boolean, default=True)
    ca_certified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Certificate(Base):
    __tablename__ = "certificates"
    cert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    standard: Mapped[str | None] = mapped_column(String(64), index=True)
    scope: Mapped[str | None] = mapped_column(Text)
    certificate_no: Mapped[str | None] = mapped_column(String(128))
    issuer: Mapped[str | None] = mapped_column(String(255))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="held")
    source: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Project(Base):
    __tablename__ = "projects"
    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    name: Mapped[str] = mapped_column(String(512))
    client: Mapped[str | None] = mapped_column(String(255))
    client_type: Mapped[str | None] = mapped_column(String(64))
    scope_tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    contract_value_inr: Mapped[float | None] = mapped_column(Float)
    eligible_value_inr: Mapped[float | None] = mapped_column(Float)
    start_date: Mapped[date | None] = mapped_column(Date)
    completion_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    completion_certificate: Mapped[bool] = mapped_column(Boolean, default=False)
    consortium_share_pct: Mapped[float | None] = mapped_column(Float)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Person(Base):
    __tablename__ = "people"
    person_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(255), index=True)
    years_experience: Mapped[float] = mapped_column(Float, default=0)
    qualifications: Mapped[list[Any]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[Any]] = mapped_column(JSON, default=list)  # PersonCert dumps
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    available_from: Mapped[date | None] = mapped_column(Date)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RiskPosition(Base):
    __tablename__ = "risk_positions"
    __table_args__ = (UniqueConstraint("company_id", "category", name="uq_risk_cat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.company_id"), index=True)
    category: Mapped[str] = mapped_column(String(64))
    policy: Mapped[str] = mapped_column(Text, default="")
    within_policy_max: Mapped[float | None] = mapped_column(Float)
    review_max: Mapped[float | None] = mapped_column(Float)
    higher_is_worse: Mapped[bool] = mapped_column(Boolean, default=True)
    unit: Mapped[str] = mapped_column(String(32), default="percent")
    approver: Mapped[str | None] = mapped_column(String(64))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class FactEvidence(Base):
    """Links any seeded fact to the source document span that supports it."""
    __tablename__ = "fact_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(64), index=True)
    fact_table: Mapped[str] = mapped_column(String(64))
    fact_key: Mapped[str] = mapped_column(String(128), index=True)
    doc_id: Mapped[str | None] = mapped_column(String(64))
    page: Mapped[int | None] = mapped_column(Integer)
    text_span: Mapped[str | None] = mapped_column(Text)
    validated: Mapped[str] = mapped_column(String(32), default="unvalidated")  # unvalidated|matched|mismatch|missing
    detail: Mapped[str | None] = mapped_column(Text)


# =========================================================================== #
# Tender                                                                      #
# =========================================================================== #
class Tender(Base, TimestampMixin):
    __tablename__ = "tenders"
    tender_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    buyer: Mapped[str | None] = mapped_column(String(255))
    reference_no: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[str] = mapped_column(String(64), default="NIMBUS-001")
    status: Mapped[str] = mapped_column(String(32), default="created")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    analysis_mode: Mapped[str] = mapped_column(String(16), default="focused")
    created_by: Mapped[str | None] = mapped_column(String(255))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TenderVersion(Base):
    __tablename__ = "tender_versions"
    __table_args__ = (UniqueConstraint("tender_id", "version", name="uq_tender_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(Integer)
    amendment_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft|effective|superseded
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class TenderFile(Base, TimestampMixin):
    __tablename__ = "tender_files"
    __table_args__ = (UniqueConstraint("tender_id", "file_sha256", name="uq_tender_file_hash"),)
    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # version that introduced this file
    filename: Mapped[str] = mapped_column(String(255))
    doc_role: Mapped[str] = mapped_column(String(32), default="other")  # TenderDocRole
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    status_detail: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(String(1024))
    parsed_path: Mapped[str | None] = mapped_column(String(1024))
    parser: Mapped[str | None] = mapped_column(String(32))
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    amendment_id: Mapped[str | None] = mapped_column(String(64))


class TenderSection(Base):
    __tablename__ = "tender_sections"
    section_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(96))
    title: Mapped[str] = mapped_column(String(512))
    section_path: Mapped[str] = mapped_column(String(1024))
    level: Mapped[int] = mapped_column(Integer, default=1)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    tables: Mapped[list[Any]] = mapped_column(JSON, default=list)
    flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)


class TenderChunk(Base):
    __tablename__ = "tender_chunks"
    chunk_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    section_id: Mapped[str | None] = mapped_column(String(96))
    parent_id: Mapped[str | None] = mapped_column(String(96))
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(1024))
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding = mapped_column(EmbeddingType(), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BoqItemRow(Base):
    __tablename__ = "boq_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    doc_id: Mapped[str] = mapped_column(String(64))
    sheet: Mapped[str] = mapped_column(String(128))
    row: Mapped[int] = mapped_column(Integer)
    item_no: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[float | None] = mapped_column(Float)
    rate: Mapped[float | None] = mapped_column(Float)
    amount: Mapped[float | None] = mapped_column(Float)
    cells: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RequirementRow(Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("tender_id", "version", "requirement_id", name="uq_req_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requirement_id: Mapped[str] = mapped_column(String(64), index=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(64))
    clause_ref: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(64), index=True)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    hard_gate: Mapped[bool] = mapped_column(Boolean, default=False)
    text: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)  # full Requirement dump


class KeyFactsRow(Base):
    __tablename__ = "key_facts"
    __table_args__ = (UniqueConstraint("tender_id", "version", name="uq_keyfacts_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)  # KeyFacts dump
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AmendmentRow(Base, TimestampMixin):
    __tablename__ = "amendments"
    amendment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[str | None] = mapped_column(String(64))
    base_version: Mapped[int] = mapped_column(Integer)
    target_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")  # AmendmentStatus
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON)            # AmendmentDiff dump
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)


class AmendmentChangeRow(Base):
    __tablename__ = "amendment_changes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amendment_id: Mapped[str] = mapped_column(ForeignKey("amendments.amendment_id", ondelete="CASCADE"), index=True)
    change_id: Mapped[str] = mapped_column(String(64))
    change_type: Mapped[str] = mapped_column(String(64))
    clause_ref: Mapped[str | None] = mapped_column(String(64))
    field: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)  # AmendmentChange dump


# =========================================================================== #
# Analysis                                                                    #
# =========================================================================== #
class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(16), default="full_analysis")  # full_analysis|impact
    analysis_mode: Mapped[str] = mapped_column(String(16), default="focused")
    previous_run_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")  # queued|running|awaiting_human|completed|failed|cancelled
    current_node: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    replay: Mapped[bool] = mapped_column(Boolean, default=False)  # labelled replay run
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    """Persisted SSE events so the UI can recover after disconnect."""
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    tender_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(64))
    node: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComplianceItemRow(Base):
    __tablename__ = "compliance_items"
    __table_args__ = (Index("ix_compliance_tv", "tender_id", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    requirement_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)  # ComplianceItem dump


class RiskItemRow(Base):
    __tablename__ = "risk_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    risk_id: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class BidAssessmentRow(Base):
    __tablename__ = "bid_assessments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[float] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(32))
    approval_status: Mapped[str] = mapped_column(String(32), default="pending")
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewRow(Base):
    """Gate 1 and Gate 2 human decisions — version-bound."""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(64))
    gate: Mapped[str] = mapped_column(String(16))  # gate1|gate2|amendment
    target_id: Mapped[str | None] = mapped_column(String(64))  # draft_id / amendment_id
    action: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="approved")  # ApprovalStatus
    reviewer: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResponsePlanRow(Base):
    __tablename__ = "response_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)


class SectionDraftRow(Base, TimestampMixin):
    __tablename__ = "section_drafts"
    draft_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str] = mapped_column(String(64))
    section_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    verifier: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ExportRow(Base):
    __tablename__ = "exports"
    export_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tender_id: Mapped[str] = mapped_column(ForeignKey("tenders.tender_id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))  # compliance_xlsx|eligibility_xlsx|draft_docx|dates_ics|audit_json|no_bid_report
    path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# =========================================================================== #
# Ops                                                                         #
# =========================================================================== #
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255))  # user id or "agent:<node>"
    action: Mapped[str] = mapped_column(String(128))
    tender_id: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[int | None] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GuardrailEvent(Base):
    __tablename__ = "guardrail_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    tender_id: Mapped[str | None] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    doc_id: Mapped[str | None] = mapped_column(String(64))
    page: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class ModelUsage(Base):
    __tablename__ = "model_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    node: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    tier: Mapped[str] = mapped_column(String(16))  # fast|strong|embedding
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
