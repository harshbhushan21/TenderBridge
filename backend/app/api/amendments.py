"""Amendment and version routes: corrigendum upload -> diff preview -> confirm -> re-analyse,
plus version history and comparison (docs/api_contract.md, Phase 7)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.errors import ValidationFailed
from backend.app.core.security import APPROVER_ROLES, CurrentUser, get_current_user
from backend.app.db import models as m
from backend.app.db.engine import db_dependency
from backend.app.db.repositories.amendments import get_amendment, list_amendments
from backend.app.db.repositories.analysis import gate1_reviews, latest_assessment_row, latest_run
from backend.app.db.repositories.tenders import get_tender, list_versions
from backend.app.ops.audit import audit
from backend.app.schemas.amendments import AmendmentConfirmation
from backend.app.services.amendment_service import (
    compare_tender_versions,
    confirm_amendment,
    preview_amendment,
    process_amendment,
    upload_amendment,
)
from backend.app.services.tender_service import start_analysis

router = APIRouter(prefix="/tenders", tags=["amendments and versions"])


class ConfirmBody(BaseModel):
    comment: str | None = None
    accepted_change_ids: list[str] | None = None


class ReanalyseBody(BaseModel):
    version: int | None = None
    mode: str = "impact"


def _summary(a: m.AmendmentRow) -> dict[str, Any]:
    return {"amendment_id": a.amendment_id, "status": a.status, "base_version": a.base_version,
            "target_version": a.target_version, "doc_id": a.doc_id,
            "changes": len((a.diff or {}).get("changes", [])),
            "confirmed_by": a.confirmed_by, "created_at": a.created_at.isoformat() if a.created_at else None}


@router.post("/{tender_id}/amendments", status_code=202)
async def upload(tender_id: str, background: BackgroundTasks, file: UploadFile = File(...),
                 session: Session = Depends(db_dependency), user: CurrentUser = Depends(get_current_user)
                 ) -> dict[str, Any]:
    """Upload a corrigendum to the same tender. Parsing and the typed diff run after the response."""
    result = upload_amendment(session, tender_id, file.filename or "corrigendum.pdf", await file.read(),
                              actor=user.user_id)
    session.commit()
    background.add_task(process_amendment, result["amendment_id"], actor=user.user_id)
    return result


@router.get("/{tender_id}/amendments")
def amendments(tender_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    get_tender(session, tender_id)
    return {"items": [_summary(a) for a in list_amendments(session, tender_id)]}


@router.get("/{tender_id}/amendments/{amendment_id}/diff")
def diff(tender_id: str, amendment_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    """Typed changes (409 while the corrigendum is still being processed)."""
    status = get_amendment(session, tender_id, amendment_id).status
    return {**preview_amendment(session, tender_id, amendment_id).model_dump(mode="json"), "status": status}


@router.post("/{tender_id}/amendments/{amendment_id}/confirm")
def confirm(tender_id: str, amendment_id: str, body: ConfirmBody | None = None,
            session: Session = Depends(db_dependency), user: CurrentUser = Depends(get_current_user)
            ) -> dict[str, Any]:
    """Make the amended version effective (bid_manager/admin; refusals are audited)."""
    body = body or ConfirmBody()
    if user.role not in APPROVER_ROLES:
        audit(user.user_id, "amendment.confirm_denied", tender_id=tender_id, target=amendment_id, role=user.role)
        user.require_approver()
    result = confirm_amendment(session, tender_id, amendment_id, AmendmentConfirmation(
        reviewer=user.user_id, comment=body.comment, accepted_change_ids=body.accepted_change_ids))
    return result


@router.post("/{tender_id}/reanalyse", status_code=202)
def reanalyse(tender_id: str, body: ReanalyseBody | None = None, session: Session = Depends(db_dependency),
              user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Re-analyse the current version; `impact` reuses checks no amendment touched."""
    body = body or ReanalyseBody()
    if body.mode not in ("impact", "full_analysis"):
        raise ValidationFailed("mode must be 'impact' or 'full_analysis'")
    return start_analysis(session, tender_id, version=body.version, actor=user.user_id, mode=body.mode)


@router.get("/{tender_id}/versions")
def versions(tender_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    tender = get_tender(session, tender_id)
    out = []
    for v in list_versions(session, tender_id):
        row = latest_assessment_row(session, tender_id, v.version)
        review = next(iter(gate1_reviews(session, tender_id, v.version)), None)
        run = latest_run(session, tender_id, v.version)
        out.append({"version": v.version, "status": v.status, "amendment_id": v.amendment_id,
                    "confirmed_by": v.confirmed_by,
                    "confirmed_at": v.confirmed_at.isoformat() if v.confirmed_at else None,
                    "run_id": run.run_id if run else None, "run_status": run.status if run else None,
                    "assessment": {"score": row.score, "recommendation": row.recommendation,
                                   "approval_status": review.status if review else "pending"} if row else None})
    return {"current_version": tender.current_version, "versions": out}


@router.get("/{tender_id}/compare")
def compare(tender_id: str, a: int, b: int, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    get_tender(session, tender_id)
    return compare_tender_versions(session, tender_id, a, b)
