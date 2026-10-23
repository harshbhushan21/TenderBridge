"""Tender file upload and processing: save -> validate -> parse -> scan -> section -> index.

Uploading never starts analysis (principle 2). Each step commits in its own
short transaction and emits a `file_status` event, so the UI can show
per-file progress and the work can run in a background thread.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import FileRejected, NotFoundError
from backend.app.core.logging import get_logger
from backend.app.core.security import ensure_within, safe_filename
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.guardrails.file_security import DEFAULT_TENDER_EXTS, validate_upload
from backend.app.guardrails.injection import scan_pdf_hidden_text
from backend.app.ingestion.document_classifier import classify_tender_file
from backend.app.ingestion.docx_parser import parse_docx, parse_text_file
from backend.app.ingestion.kb_ingest import QUARANTINE_FLAG, scan_sections
from backend.app.ingestion.pdf_parser import parse_pdf
from backend.app.ingestion.sectionizer import sectionize
from backend.app.ingestion.xlsx_parser import parse_xlsx
from backend.app.ops.audit import audit
from backend.app.ops.events import emit_event
from backend.app.ops.metrics import record_guardrail
from backend.app.retrieval.chunker import chunk_sections
from backend.app.retrieval.indexer import index_tender_chunks
from backend.app.schemas.documents import (
    BoqItem,
    GuardrailFlag,
    IngestionStatus,
    ParsedDocument,
    TenderDocRole,
    TenderStatus,
)

log = get_logger(__name__)
TENDER_EXTS = DEFAULT_TENDER_EXTS - {"zip"}  # ZIP packs: unpack client-side for now
_DONE = {IngestionStatus.indexed.value}


def _emit(tf: m.TenderFile, message: str | None = None) -> None:
    emit_event(run_id=None, tender_id=tf.tender_id, version=tf.version, event="file_status",
               status=tf.status, message=message or tf.status_detail,
               payload={"doc_id": tf.doc_id, "filename": tf.filename, "doc_role": tf.doc_role})


def save_tender_upload(session: Session, tender_id: str, filename: str, data: bytes, *,
                       doc_role: str | None = None, version: int = 1, amendment_id: str | None = None,
                       actor: str = "system") -> m.TenderFile:
    """Validate and store an uploaded file. Re-uploading identical bytes returns the existing file."""
    tender = session.get(m.Tender, tender_id)
    if tender is None:
        raise NotFoundError(f"tender '{tender_id}' not found")
    role = doc_role or classify_tender_file(filename).value
    if role == TenderDocRole.corrigendum.value and amendment_id is None:
        raise FileRejected("a corrigendum must be uploaded as an amendment to the tender, "
                           "not with the original pack")
    info = validate_upload(filename, data, allowed=TENDER_EXTS)
    existing = session.scalar(select(m.TenderFile).where(m.TenderFile.tender_id == tender_id,
                                                         m.TenderFile.file_sha256 == info["sha256"]))
    if existing is not None:
        return existing

    name = safe_filename(filename)
    folder = get_settings().uploads_dir / tender_id / f"v{version}"
    target = ensure_within(get_settings().uploads_dir, folder / f"{info['sha256'][:12]}_{name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    tf = m.TenderFile(doc_id=m.new_id("DOC"), tender_id=tender_id, version=version, filename=name,
                      doc_role=role, file_sha256=info["sha256"],
                      mime_type=info["mime"], size_bytes=info["size"], status=IngestionStatus.uploaded.value,
                      storage_path=str(target), amendment_id=amendment_id, flags=[])
    session.add(tf)
    if tender.status in (TenderStatus.created.value, TenderStatus.ready_for_analysis.value) and not amendment_id:
        tender.status = TenderStatus.ingesting.value
    session.flush()
    audit(actor, "tender.file_uploaded", tender_id=tender_id, version=version, session=session,
          target=tf.doc_id, filename=name, sha256=info["sha256"])
    return tf


def _parse(path: Path, doc_id: str) -> tuple[ParsedDocument, list[BoqItem]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path, doc_id), []
    if suffix == ".docx":
        return parse_docx(path, doc_id), []
    if suffix == ".xlsx":
        return parse_xlsx(path, doc_id)
    return parse_text_file(path, doc_id), []


def _set_status(doc_id: str, status: IngestionStatus, detail: str | None = None, **fields: Any) -> m.TenderFile:
    with session_scope() as s:
        tf = s.get(m.TenderFile, doc_id)
        if tf is None:
            raise NotFoundError(f"tender file '{doc_id}' not found")
        tf.status = status.value
        tf.status_detail = detail
        for key, value in fields.items():
            setattr(tf, key, value)
        s.flush()
        s.expunge(tf)
    _emit(tf, detail)
    return tf


def process_tender_file(doc_id: str) -> str:
    """Run the ingestion pipeline for one uploaded file; returns its final status.

    Opens its own sessions, so it can run in a background thread.
    """
    with session_scope() as s:
        tf = s.get(m.TenderFile, doc_id)
        if tf is None:
            raise NotFoundError(f"tender file '{doc_id}' not found")
        tender_id, version, path, amendment_id = tf.tender_id, tf.version, Path(tf.storage_path), tf.amendment_id
    try:
        _set_status(doc_id, IngestionStatus.validating)
        validate_upload(path.name, path.read_bytes(), allowed=TENDER_EXTS)
        _set_status(doc_id, IngestionStatus.parsing)
        parsed, boq = _parse(path, doc_id)

        first_text = parsed.pages[0].text if parsed.pages else ""
        role = classify_tender_file(path.name, first_text)
        if role is TenderDocRole.corrigendum and amendment_id is None:
            # Caught by content even if renamed: amendments have their own path (Phase 6).
            return _set_status(doc_id, IngestionStatus.failed,
                               "This file is a corrigendum. Upload it as an amendment to the tender, "
                               "not with the original pack.", doc_role=role.value).status

        sections = sectionize(parsed)
        flags: list[GuardrailFlag] = scan_pdf_hidden_text(path, doc_id=doc_id) if path.suffix.lower() == ".pdf" \
            else []
        hidden_by_page = {p.page: p.hidden_spans for p in parsed.pages if p.hidden_spans}
        flags += scan_sections(sections, hidden_by_page, doc_id)
        quarantined = {s.section_id for s in sections if QUARANTINE_FLAG in s.flags}

        parsed_dir = get_settings().parsed_dir / tender_id
        parsed_dir.mkdir(parents=True, exist_ok=True)
        parsed_path = parsed_dir / f"{doc_id}.json"
        parsed_path.write_text(parsed.model_dump_json(), encoding="utf-8")

        with session_scope() as s:
            s.execute(delete(m.TenderSection).where(m.TenderSection.doc_id == doc_id))
            s.execute(delete(m.BoqItemRow).where(m.BoqItemRow.doc_id == doc_id))
            for sec in sections:
                s.add(m.TenderSection(
                    section_id=sec.section_id, tender_id=tender_id, version=version, doc_id=doc_id,
                    parent_id=sec.parent_id, title=sec.title, section_path=sec.section_path,
                    level=sec.level, page_start=sec.page_start, page_end=sec.page_end, text=sec.text,
                    tables=[t.model_dump() for t in sec.tables], flags=sec.flags,
                    quarantined=sec.section_id in quarantined))
            for item in boq:
                s.add(m.BoqItemRow(tender_id=tender_id, version=version, doc_id=doc_id, sheet=item.sheet,
                                   row=item.row, item_no=item.item_no, description=item.description,
                                   unit=item.unit, quantity=item.quantity, rate=item.rate,
                                   amount=item.amount, cells=item.cells))
            chunks = chunk_sections(sections, prefix=f"{doc_id}::")
            index_tender_chunks(s, tender_id, version, doc_id, chunks, quarantined_sections=quarantined)
            for flag in flags:
                record_guardrail(flag, tender_id=tender_id, session=s)
            tf = s.get(m.TenderFile, doc_id)
            assert tf is not None
            tf.doc_role = role.value if tf.doc_role in (None, "", TenderDocRole.other.value) else tf.doc_role
            tf.page_count = len(parsed.pages)
            tf.parser = parsed.parser
            tf.parsed_path = str(parsed_path)
            tf.flags = sorted({f.kind for f in flags} | ({"ocr"} if any(p.ocr for p in parsed.pages) else set()))
            detail = f"{len(sections)} sections, {len(chunks)} chunks"
            if boq:
                detail += f", {len(boq)} BoQ rows"
            if quarantined:
                detail += f", {len(quarantined)} section(s) with quarantined content"
            if parsed.warnings:
                detail += f"; warnings: {'; '.join(parsed.warnings)[:300]}"
        _set_status(doc_id, IngestionStatus.indexed, detail)
        _refresh_tender_status(tender_id)
        return IngestionStatus.indexed.value
    except Exception as exc:
        log.warning("tender file %s failed: %s", doc_id, exc)
        _set_status(doc_id, IngestionStatus.failed, f"{type(exc).__name__}: {str(exc)[:300]}")
        _refresh_tender_status(tender_id)
        return IngestionStatus.failed.value


def process_pending_files(tender_id: str) -> dict[str, str]:
    """Process every uploaded-but-unprocessed file of a tender (synchronously)."""
    with session_scope() as s:
        pending = [tf.doc_id for tf in s.scalars(select(m.TenderFile).where(
            m.TenderFile.tender_id == tender_id, m.TenderFile.status == IngestionStatus.uploaded.value))]
    return {doc_id: process_tender_file(doc_id) for doc_id in pending}


def tender_ingestion_status(session: Session, tender_id: str, version: int | None = None) -> dict[str, Any]:
    """Per-file progress and whether the tender is ready for analysis."""
    q = select(m.TenderFile).where(m.TenderFile.tender_id == tender_id, m.TenderFile.amendment_id.is_(None))
    if version is not None:
        q = q.where(m.TenderFile.version <= version)
    files = list(session.scalars(q.order_by(m.TenderFile.created_at)))
    tender = session.get(m.Tender, tender_id)
    ready = bool(files) and all(f.status in _DONE for f in files)
    return {
        "tender_id": tender_id,
        "status": tender.status if tender else None,
        "ready": ready,
        "files": [{"doc_id": f.doc_id, "filename": f.filename, "doc_role": f.doc_role, "status": f.status,
                   "status_detail": f.status_detail, "page_count": f.page_count, "flags": f.flags or [],
                   "version": f.version} for f in files],
    }


def _refresh_tender_status(tender_id: str) -> None:
    with session_scope() as s:
        tender = s.get(m.Tender, tender_id)
        if tender is None or tender.status not in (TenderStatus.created.value, TenderStatus.ingesting.value,
                                                   TenderStatus.ready_for_analysis.value):
            return  # analysis and amendment states belong to later phases
        ready = tender_ingestion_status(s, tender_id)["ready"]
        # A failed file keeps the tender in `ingesting` until it is replaced or removed.
        tender.status = TenderStatus.ready_for_analysis.value if ready else TenderStatus.ingesting.value
