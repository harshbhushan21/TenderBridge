"""Cited response drafting (after Gate 1) and version-bound Gate 2 review routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.agents.persistence import load_drafts
from backend.app.core.errors import NotFoundError
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.db import models as m
from backend.app.db.engine import db_dependency
from backend.app.db.repositories.analysis import latest_drafting_run, run_to_dict
from backend.app.db.repositories.tenders import get_tender
from backend.app.services.tender_service import decide_gate2, start_drafting

router = APIRouter(tags=["drafts"])


class DraftReviewBody(BaseModel):
    action: str
    comment: str | None = None
    edited_markdown: str | None = None


@router.get("/tenders/{tender_id}/drafts")
def list_drafts(tender_id: str, version: int | None = None,
                session: Session = Depends(db_dependency)) -> dict[str, Any]:
    """Section drafts of the latest drafting run for the version, with verifier reports."""
    chosen = version or get_tender(session, tender_id).current_version
    run = latest_drafting_run(session, tender_id, chosen)
    return {"version": chosen, "run": run_to_dict(run) if run else None,
            "items": load_drafts(session, tender_id, chosen) if run else []}


@router.post("/tenders/{tender_id}/drafts", status_code=202)
def create_drafts(tender_id: str, session: Session = Depends(db_dependency),
                  user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return start_drafting(session, tender_id, actor=user.user_id, role=user.role)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    row = session.get(m.SectionDraftRow, draft_id)
    if row is None:
        raise NotFoundError(f"draft '{draft_id}' not found")
    return next(d for d in load_drafts(session, row.tender_id, row.version, row.run_id) if d["draft_id"] == draft_id)


@router.post("/drafts/{draft_id}/review")
def review_draft(draft_id: str, body: DraftReviewBody, session: Session = Depends(db_dependency),
                 user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Gate 2: approve / edit / reject / request_changes (bid_manager or admin; refusals audited)."""
    return decide_gate2(session, draft_id, body.model_dump(), user_id=user.user_id, role=user.role)
