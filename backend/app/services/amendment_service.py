"""Corrigendum lifecycle: upload -> process (typed diff) -> preview -> confirm -> new version.

The corrigendum is tender content for the next version; it never touches the
company KB. Processing runs in its own sessions (call it after the upload is
committed); confirmation is the human step that makes the new version effective.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.agents.subgraphs.amendment_impact import classify_impacts
from backend.app.core.errors import ConflictError, InvalidStateError, NotFoundError
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.db.repositories.amendments import get_amendment, pending_amendment
from backend.app.ingestion.corrigendum_parser import parse_corrigendum_tables
from backend.app.ingestion.tender_ingest import load_effective_sections, load_sections_for_doc
from backend.app.ingestion.upload_service import process_tender_file, save_tender_upload
from backend.app.ops.audit import audit
from backend.app.ops.events import emit_event
from backend.app.schemas.amendments import AmendmentConfirmation, AmendmentDiff, AmendmentStatus
from backend.app.schemas.documents import TenderStatus
from backend.app.tools.amendment_diff import changes_from_corrigendum, diff_sections


def upload_amendment(session: Session, tender_id: str, filename: str, data: bytes,
                     *, actor: str = "system") -> dict[str, Any]:
    """Store a corrigendum for the next version. Call `process_amendment` after committing."""
    tender = session.get(m.Tender, tender_id)
    if tender is None:
        raise NotFoundError(f"tender '{tender_id}' not found")
    if pending_amendment(session, tender_id) is not None:
        raise ConflictError("another amendment is still awaiting confirmation")
    base_version = tender.current_version
    target_version = base_version + 1
    amendment = m.AmendmentRow(amendment_id=m.new_id("AMD"), tender_id=tender_id, base_version=base_version,
                               target_version=target_version, status=AmendmentStatus.uploaded.value)
    session.add(amendment)
    session.flush()
    file = save_tender_upload(session, tender_id, filename, data, doc_role="corrigendum",
                              version=target_version, amendment_id=amendment.amendment_id, actor=actor)
    amendment.doc_id = file.doc_id
    tender.status = TenderStatus.amendment_pending.value
    audit(actor, "amendment.uploaded", tender_id=tender_id, version=target_version,
          target=amendment.amendment_id, session=session, filename=filename)
    session.flush()
    return {"amendment_id": amendment.amendment_id, "doc_id": file.doc_id, "status": amendment.status,
            "base_version": base_version, "target_version": target_version}


def process_amendment(amendment_id: str, *, actor: str = "system") -> str:
    """Parse the corrigendum and build its typed diff. Opens its own sessions."""
    with session_scope() as s:
        a = s.get(m.AmendmentRow, amendment_id)
        if a is None:
            raise NotFoundError(f"amendment '{amendment_id}' not found")
        if a.status not in (AmendmentStatus.uploaded.value, AmendmentStatus.failed.value):
            return a.status
        a.status = AmendmentStatus.parsed.value
        tender_id, doc_id, base, target = a.tender_id, a.doc_id, a.base_version, a.target_version
    file_status = process_tender_file(doc_id) if doc_id else "failed"
    with session_scope() as s:
        a = s.get(m.AmendmentRow, amendment_id)
        assert a is not None
        tf = s.get(m.TenderFile, doc_id) if doc_id else None
        if file_status != "indexed" or tf is None or doc_id is None:
            a.status = AmendmentStatus.failed.value
            detail = tf.status_detail if tf else "no document"
            emit_event(run_id=None, tender_id=tender_id, version=target, event="amendment_diff_ready",
                       status="failed", message=detail, payload={"amendment_id": amendment_id})
            return a.status
        rows = parse_corrigendum_tables(Path(tf.storage_path)) if tf.filename.lower().endswith(".pdf") else []
        sections = load_sections_for_doc(s, doc_id)
        first_page = next((sec.text for sec in sections), "")
        if rows:
            diff = changes_from_corrigendum(rows, doc_id=doc_id, amendment_id=amendment_id, tender_id=tender_id,
                                            base_version=base, target_version=target,
                                            first_page_text=f"{tf.filename} {first_page}")
        else:  # no amendment table: fall back to a section-level comparison
            diff = diff_sections(load_effective_sections(s, tender_id, base), sections,
                                 amendment_id=amendment_id, tender_id=tender_id, base_version=base,
                                 target_version=target)
            diff.warnings.append("No amendment table found; showing section-level differences.")
        a.diff = diff.model_dump(mode="json")
        a.status = AmendmentStatus.diff_ready.value
        audit(actor, "amendment.diff_ready", tender_id=tender_id, version=target, target=amendment_id,
              session=s, changes=len(diff.changes))
    emit_event(run_id=None, tender_id=tender_id, version=target, event="amendment_diff_ready",
               status="diff_ready", payload={"amendment_id": amendment_id, "changes": len(diff.changes)})
    return AmendmentStatus.diff_ready.value


def preview_amendment(session: Session, tender_id: str, amendment_id: str) -> AmendmentDiff:
    amendment = get_amendment(session, tender_id, amendment_id)
    if amendment.status in (AmendmentStatus.uploaded.value, AmendmentStatus.parsed.value):
        raise InvalidStateError("the amendment is still being processed", details={"status": amendment.status})
    if amendment.status == AmendmentStatus.failed.value or not amendment.diff:
        raise InvalidStateError("the amendment could not be processed", details={"status": amendment.status})
    return AmendmentDiff.model_validate(amendment.diff)


def confirm_amendment(session: Session, tender_id: str, amendment_id: str,
                      confirmation: AmendmentConfirmation) -> dict[str, Any]:
    """Make the amended version effective: supersede the base version's Gate 1 decisions and
    drafts, record the changes, and require re-analysis."""
    amendment = get_amendment(session, tender_id, amendment_id)
    if amendment.status != AmendmentStatus.diff_ready.value:
        raise InvalidStateError("amendment must have a diff preview before confirmation",
                                details={"status": amendment.status})
    diff = AmendmentDiff.model_validate(amendment.diff or {})
    accepted = set(confirmation.accepted_change_ids or [c.change_id for c in diff.changes])
    if not accepted.issuperset(c.change_id for c in diff.changes):
        raise ConflictError("all published changes must be accepted: a corrigendum is binding as issued")
    tender = session.get(m.Tender, tender_id)
    if tender is None or tender.current_version != amendment.base_version:
        raise ConflictError("amendment base version is no longer current")

    base, target = amendment.base_version, amendment.target_version
    session.execute(update(m.TenderVersion).where(m.TenderVersion.tender_id == tender_id,
                                                  m.TenderVersion.version == base).values(status="superseded"))
    session.add(m.TenderVersion(tender_id=tender_id, version=target, parent_version=base,
                                amendment_id=amendment_id, status="effective", confirmed_by=confirmation.reviewer,
                                confirmed_at=datetime.now(UTC), note=confirmation.comment))
    for change in diff.changes:
        session.add(m.AmendmentChangeRow(amendment_id=amendment_id, change_id=change.change_id,
                                         change_type=change.change_type.value, clause_ref=change.clause_ref,
                                         field=change.field, old_value=change.old_value,
                                         new_value=change.new_value, accepted=True,
                                         data=change.model_dump(mode="json")))

    # Every live Gate 1 decision on the base version is superseded (approved, pending or rejected).
    live = (m.ReviewRow.tender_id == tender_id) & (m.ReviewRow.version == base) & \
        (m.ReviewRow.gate == "gate1") & (m.ReviewRow.status != "superseded")
    superseded = session.scalar(select(func.count()).select_from(m.ReviewRow).where(live)) or 0
    session.execute(update(m.ReviewRow).where(live).values(status="superseded"))
    stale_q = (m.SectionDraftRow.tender_id == tender_id) & (m.SectionDraftRow.version == base) & \
        (m.SectionDraftRow.stale.is_(False))
    stale = session.scalar(select(func.count()).select_from(m.SectionDraftRow).where(stale_q)) or 0
    session.execute(update(m.SectionDraftRow).where(stale_q).values(stale=True, status="superseded"))

    requirement_ids = set(session.scalars(select(m.RequirementRow.requirement_id).where(
        m.RequirementRow.tender_id == tender_id, m.RequirementRow.version == base)).all())
    diff.derived_impacts = classify_impacts(diff.changes, requirement_ids)["derived_impacts"]
    amendment.diff = diff.model_dump(mode="json")
    amendment.status = AmendmentStatus.confirmed.value
    amendment.confirmed_by = confirmation.reviewer
    amendment.confirmed_at = datetime.now(UTC)
    amendment.comment = confirmation.comment
    tender.current_version = target
    tender.status = TenderStatus.reanalysis_required.value
    audit(confirmation.reviewer, "amendment.confirmed", tender_id=tender_id, version=target,
          target=amendment_id, session=session, superseded_reviews=superseded, stale_drafts=stale)
    return {"tender_version": target, "status": TenderStatus.reanalysis_required.value,
            "superseded_reviews": superseded, "stale_drafts": stale}


def compare_tender_versions(session: Session, tender_id: str, a: int, b: int) -> dict[str, Any]:
    """Compare the latest analysis of two versions (for GET /tenders/{id}/compare)."""
    from backend.app.agents.persistence import load_assessment, load_compliance, load_risks
    from backend.app.db.repositories.amendments import confirmed_for_version
    from backend.app.db.repositories.analysis import latest_run
    from backend.app.tools.amendment_diff import compare_versions

    def side(version: int) -> dict[str, Any]:
        run = latest_run(session, tender_id, version, completed_only=True)
        if run is None:
            raise InvalidStateError(f"version {version} has not been analysed yet")
        return {"version": version, "assessment": load_assessment(session, tender_id, version, run.run_id),
                "compliance": load_compliance(session, tender_id, version, run.run_id),
                "risks": load_risks(session, tender_id, version, run.run_id)}

    older, newer = side(a), side(b)
    amendments = [x for x in confirmed_for_version(session, tender_id, max(a, b)) if x.target_version > min(a, b)]
    newer["amendments"] = [c for x in amendments for c in (x.diff or {}).get("changes", [])]
    newer["derived_impacts"] = [d for x in amendments for d in (x.diff or {}).get("derived_impacts", [])]
    return compare_versions(older, newer)
