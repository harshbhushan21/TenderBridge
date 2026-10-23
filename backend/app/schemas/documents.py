"""Document, provenance and retrieval schemas."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IngestionStatus(str, Enum):
    uploaded = "uploaded"
    validating = "validating"
    parsing = "parsing"
    indexed = "indexed"
    failed = "failed"
    quarantined = "quarantined"


class TenderStatus(str, Enum):
    created = "created"
    ingesting = "ingesting"
    ready_for_analysis = "ready_for_analysis"
    analyzing = "analyzing"
    awaiting_bid_decision = "awaiting_bid_decision"
    bid_approved = "bid_approved"
    no_bid_approved = "no_bid_approved"
    drafting = "drafting"
    awaiting_draft_review = "awaiting_draft_review"
    exported = "exported"
    amendment_pending = "amendment_pending"
    reanalysis_required = "reanalysis_required"
    reanalyzing = "reanalyzing"
    failed = "failed"


class Scope(str, Enum):
    tender = "tender"
    kb = "kb"


class TenderDocRole(str, Enum):
    """Classification of a tender pack file."""
    notice = "notice"
    main_rfp = "main_rfp"
    annexures = "annexures"
    boq = "boq"
    corrigendum = "corrigendum"
    clarification = "clarification"
    other = "other"


class SourceSpan(BaseModel):
    """Immutable pointer to supporting evidence (principle 7)."""
    model_config = ConfigDict(frozen=True)

    doc_id: str
    page: int | None = None
    section_path: str | None = None
    text_span: str = ""  # verbatim supporting text (trimmed)
    char_start: int | None = None
    char_end: int | None = None
    file_sha256: str | None = None
    scope: Scope = Scope.tender
    tender_version: int | None = None
    sheet: str | None = None  # for XLSX
    cell: str | None = None

    def short(self) -> str:
        loc = f"p.{self.page}" if self.page is not None else (f"{self.sheet}!{self.cell}" if self.sheet else "")
        return f"{self.doc_id} {loc}".strip()


class DocumentMeta(BaseModel):
    doc_id: str
    filename: str
    scope: Scope
    file_sha256: str
    mime_type: str | None = None
    size_bytes: int = 0
    doc_type: str | None = None  # kb folder category or TenderDocRole value
    tender_id: str | None = None
    company_id: str | None = None
    version: int = 1
    allowed_roles: list[str] = Field(default_factory=lambda: ["all"])
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = "internal"
    approved_for_reuse: bool = False
    source_kind: str = "upload"  # upload | seed | demo_data
    synthetic: bool = True
    live_subset: bool = False
    status: IngestionStatus = IngestionStatus.uploaded
    page_count: int | None = None
    storage_path: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class TableBlock(BaseModel):
    caption: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    page: int | None = None


class ParsedSection(BaseModel):
    """A heading-delimited section of a parsed document."""
    section_id: str
    doc_id: str
    title: str
    section_path: str  # e.g. "Section 3 > 3.2 Pre-Qualification"
    level: int = 1
    page_start: int | None = None
    page_end: int | None = None
    text: str = ""
    tables: list[TableBlock] = Field(default_factory=list)
    parent_id: str | None = None
    flags: list[str] = Field(default_factory=list)  # e.g. "ocr", "suspicious_hidden_text"


class ParsedPage(BaseModel):
    page: int
    text: str
    ocr: bool = False
    hidden_spans: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    doc_id: str
    filename: str
    file_sha256: str
    parser: str  # docling | pymupdf | pypdf | docx | xlsx | text
    pages: list[ParsedPage] = Field(default_factory=list)
    sections: list[ParsedSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


class BoqItem(BaseModel):
    sheet: str
    row: int
    item_no: str | None = None
    description: str = ""
    unit: str | None = None
    quantity: float | None = None
    rate: float | None = None
    amount: float | None = None
    cells: dict[str, Any] = Field(default_factory=dict)


class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    parent_id: str | None = None
    text: str
    page: int | None = None
    section_path: str | None = None
    token_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    score: float
    scope: Scope
    page: int | None = None
    section_path: str | None = None
    parent_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_span(self, max_len: int = 400) -> SourceSpan:
        return SourceSpan(
            doc_id=self.doc_id, page=self.page, section_path=self.section_path,
            text_span=self.text[:max_len], scope=self.scope,
            tender_version=self.metadata.get("version"),
        )


class GuardrailFlag(BaseModel):
    kind: Literal["prompt_injection", "hidden_text", "pii", "malware_suspect", "poisoned_kb",
                  "unsupported_claim", "budget", "other"]
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    doc_id: str | None = None
    page: int | None = None
    excerpt: str = ""
    detail: str = ""
    quarantined: bool = False
    created_at: datetime | None = None
