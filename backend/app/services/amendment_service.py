"""Corrigendum lifecycle: upload, preview, confirmation, and version rollover."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.subgraphs.amendment_impact import classify_impacts
from backend.app.core.errors import ConflictError, InvalidStateError, NotFoundError
from backend.app.db import models as m
from backend.app.db.repositories.amendments import get_amendment
from backend.app.ingestion.tender_ingest import load_effective_sections
from backend.app.ingestion.upload_service import process_tender_file, save_tender_upload
from backend.app.ops.audit import audit
from backend.app.schemas.amendments import (
    AmendmentConfirmation,
    AmendmentDiff,
    AmendmentStatus,
)
from backend.app.schemas.documents import TenderStatus
from backend.app.tools.amendment_diff import diff_sections


def upload_amendment(session: Session, tender_id: str, filename: str, data: bytes,
                     *, actor: str = "system") -> dict[str, Any]:
    tender = session.get(m.Tender, tender_id)
    if tender is None:
        raise NotFoundError(f"tender '{tender_id}' not found")
    base_version = tender.current_version
    target_version = base_version + 1
    amendment_id = m.new_id("AMD")
    amendment = m.AmendmentRow(amendment_id=amendment_id, tender_id=tender_id,
                               base_version=base_version, target_version=target_version,
                               status=AmendmentStatus.uploaded.value)
    session.add(amendment)
    session.flush()
    file = save_tender_upload(session, tender_id, filename, data, doc_role="corrigendum",
                               version=target_version, amendment_id=amendment_id, actor=actor)
    amendment.doc_id = file.doc_id
    tender.status = TenderStatus.amendment_pending.value
    audit(actor, "amendment.uploaded", tender_id=tender_id, version=target_version,
          target=amendment_id, session=session, filename=filename)
    session.flush()
    return {"amendment_id": amendment_id, "doc_id": file.doc_id,
            "status": amendment.status, "target_version": target_version}


def preview_amendment(session: Session, tender_id: str, amendment_id: str,
                      *, actor: str = "system") -> AmendmentDiff:
    amendment = get_amendment(session, tender_id, amendment_id)
    if not amendment.doc_id:
        raise InvalidStateError("amendment has no uploaded document")
    process_tender_file(amendment.doc_id)
    base = load_effective_sections(session, tender_id, amendment.base_version)
    amended = load_effective_sections(session, tender_id, amendment.target_version)
    diff = diff_sections(base, amended, amendment_id=amendment_id, tender_id=tender_id,
                         base_version=amendment.base_version, target_version=amendment.target_version)
    amendment.diff = diff.model_dump(mode="json")
    amendment.status = AmendmentStatus.diff_ready.value
    audit(actor, "amendment.diff_ready", tender_id=tender_id, version=amendment.target_version,
          target=amendment_id, session=session, changes=len(diff.changes))
    return diff


def confirm_amendment(session: Session, tender_id: str, amendment_id: str,
                      confirmation: AmendmentConfirmation) -> dict[str, Any]:
    amendment = get_amendment(session, tender_id, amendment_id)
    if amendment.status != AmendmentStatus.diff_ready.value:
        raise InvalidStateError("amendment must have a diff preview before confirmation")
    diff = AmendmentDiff.model_validate(amendment.diff or {})
    accepted = set(confirmation.accepted_change_ids or [c.change_id for c in diff.changes])
    if not accepted.issuperset(c.change_id for c in diff.changes):
        raise ConflictError("all amendment changes must be accepted for version rollover")
    tender = session.get(m.Tender, tender_id)
    if tender is None or tender.current_version != amendment.base_version:
        raise ConflictError("amendment base version is no longer current")
    old_version = session.scalar(select(m.TenderVersion).where(
        m.TenderVersion.tender_id == tender_id, m.TenderVersion.version == amendment.base_version))
    if old_version:
        old_version.status = "superseded"
    session.add(m.TenderVersion(
        tender_id=tender_id, version=amendment.target_version, parent_version=amendment.base_version,
        amendment_id=amendment_id, status="effective", confirmed_by=confirmation.reviewer,
        confirmed_at=datetime.now(UTC), note=confirmation.comment,
    ))
    amendment.status = AmendmentStatus.confirmed.value
    amendment.confirmed_by = confirmation.reviewer
    amendment.confirmed_at = datetime.now(UTC)
    amendment.comment = confirmation.comment
    for change in diff.changes:
        session.add(m.AmendmentChangeRow(
            amendment_id=amendment_id, change_id=change.change_id,
            change_type=change.change_type.value, clause_ref=change.clause_ref,
            field=change.field, old_value=change.old_value, new_value=change.new_value,
            accepted=True, data=change.model_dump(mode="json"),
        ))
    for review in session.scalars(select(m.ReviewRow).where(
            m.ReviewRow.tender_id == tender_id, m.ReviewRow.version == amendment.base_version,
            m.ReviewRow.gate == "gate1", m.ReviewRow.status == "approved")).all():
        review.status = "superseded"
    for draft in session.scalars(select(m.SectionDraftRow).where(
            m.SectionDraftRow.tender_id == tender_id, m.SectionDraftRow.version == amendment.base_version,
            m.SectionDraftRow.stale.is_(False))).all():
        draft.stale = True
        draft.status = "superseded"
    tender.current_version = amendment.target_version
    tender.status = TenderStatus.reanalysis_required.value
    requirement_ids = {r.requirement_id for r in session.scalars(select(m.RequirementRow).where(
        m.RequirementRow.tender_id == tender_id, m.RequirementRow.version == amendment.base_version)).all()}
    impacts = classify_impacts(diff.changes, requirement_ids)
    diff.derived_impacts = impacts["derived_impacts"]
    diff.reusable_checks = sorted(set(diff.reusable_checks) - set(diff.invalidated_checks))
    amendment.diff = diff.model_dump(mode="json")
    audit(confirmation.reviewer, "amendment.confirmed", tender_id=tender_id,
          version=amendment.target_version, target=amendment_id, session=session)
    return {"tender_version": amendment.target_version, "status": "reanalysis_required",
            "superseded_reviews": len([r for r in session.identity_map.values() if isinstance(r, m.ReviewRow)
                                       and r.status == "superseded"]),
            "stale_drafts": len([d for d in session.identity_map.values() if isinstance(d, m.SectionDraftRow)
                                 and d.stale])}
