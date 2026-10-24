"""Cited response drafting and version-bound Gate 2 review routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.agents.persistence import load_drafts
from backend.app.agents.runner import resume_run
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.db import models as m
from backend.app.db.engine import db_dependency
from backend.app.db.repositories.tenders import get_tender
from backend.app.schemas.assessment import DraftReview
from backend.app.services.tender_service import start_drafting

router = APIRouter(tags=["drafts"])


class DraftStart(BaseModel):
    version: int | None = None


@router.get("/tenders/{tender_id}/drafts")
def list_drafts(tender_id: str, version: int | None = None,
                session: Session = Depends(db_dependency)) -> dict[str, Any]:
    tender = get_tender(session, tender_id)
    chosen = version or tender.current_version
    return {"items": load_drafts(session, tender_id, chosen)}


@router.post("/tenders/{tender_id}/drafts", status_code=202)
def create_drafts(tender_id: str, body: DraftStart | None = None,
                  session: Session = Depends(db_dependency),
                  user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return start_drafting(session, tender_id, actor=user.user_id, role=user.role)


@router.post("/drafts/{draft_id}/review")
def review_draft(draft_id: str, body: DraftReview,
                 session: Session = Depends(db_dependency),
                 user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    draft = session.get(m.SectionDraftRow, draft_id)
    if draft is None:
        from backend.app.core.errors import NotFoundError
        raise NotFoundError(f"draft '{draft_id}' not found")
    if user.role not in {"bid_manager", "admin"}:
        user.require_approver()
    run = session.get(m.AnalysisRun, draft.run_id)
    if run is None or run.status != "awaiting_human":
        from backend.app.core.errors import InvalidStateError
        raise InvalidStateError("draft run is not waiting for Gate 2")
    review = body.model_dump(mode="json")
    session.add(m.ReviewRow(
        tender_id=draft.tender_id, version=draft.version, run_id=draft.run_id,
        gate="gate2", target_id=draft_id, action=body.action,
        status="approved" if body.action == "approve" else "pending",
        reviewer=user.user_id, comment=body.comment, data=review,
    ))
    draft.status = "approved" if body.action == "approve" else body.action
    if body.edited_markdown:
        draft.data = {**draft.data, "body_markdown": body.edited_markdown}
    session.commit()
    resume_run(draft.run_id, {
        "section_key": draft.section_key, **review,
    })
    return {"status": "resuming"}
