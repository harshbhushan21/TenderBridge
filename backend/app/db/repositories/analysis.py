"""Analysis-run and result queries (read side)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AnalysisRun, BidAssessmentRow, ExportRow, ReviewRow, SectionDraftRow


def latest_run(session: Session, tender_id: str, version: int | None = None,
               *, completed_only: bool = False) -> AnalysisRun | None:
    q = select(AnalysisRun).where(AnalysisRun.tender_id == tender_id)
    if version is not None:
        q = q.where(AnalysisRun.version == version)
    if completed_only:
        q = q.where(AnalysisRun.status.in_(("completed", "awaiting_human")))
    return session.scalars(q.order_by(AnalysisRun.started_at.desc(), AnalysisRun.run_id.desc())).first()


def list_runs(session: Session, tender_id: str | None = None, limit: int = 100) -> list[AnalysisRun]:
    q = select(AnalysisRun)
    if tender_id:
        q = q.where(AnalysisRun.tender_id == tender_id)
    return list(session.scalars(q.order_by(AnalysisRun.started_at.desc()).limit(limit)).all())


def run_to_dict(r: AnalysisRun) -> dict:
    return {"run_id": r.run_id, "tender_id": r.tender_id, "version": r.version,
            "thread_id": r.thread_id, "status": r.status, "current_node": r.current_node,
            "mode": r.mode, "analysis_mode": r.analysis_mode, "previous_run_id": r.previous_run_id,
            "error": r.error, "usage": r.usage or {}, "replay": r.replay,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


def latest_assessment_row(session: Session, tender_id: str, version: int | None = None
                          ) -> BidAssessmentRow | None:
    q = select(BidAssessmentRow).where(BidAssessmentRow.tender_id == tender_id)
    if version is not None:
        q = q.where(BidAssessmentRow.version == version)
    return session.scalars(q.order_by(BidAssessmentRow.created_at.desc(),
                                      BidAssessmentRow.id.desc())).first()


def gate1_reviews(session: Session, tender_id: str, version: int | None = None) -> list[ReviewRow]:
    q = select(ReviewRow).where(ReviewRow.tender_id == tender_id, ReviewRow.gate == "gate1")
    if version is not None:
        q = q.where(ReviewRow.version == version)
    return list(session.scalars(q.order_by(ReviewRow.created_at.desc())).all())


def draft_rows(session: Session, tender_id: str, version: int | None = None) -> list[SectionDraftRow]:
    q = select(SectionDraftRow).where(SectionDraftRow.tender_id == tender_id)
    if version is not None:
        q = q.where(SectionDraftRow.version == version)
    return list(session.scalars(q.order_by(SectionDraftRow.created_at)).all())


def list_exports(session: Session, tender_id: str, version: int | None = None) -> list[ExportRow]:
    q = select(ExportRow).where(ExportRow.tender_id == tender_id)
    if version is not None:
        q = q.where(ExportRow.version == version)
    return list(session.scalars(q.order_by(ExportRow.created_at.desc())).all())


def latest_export(session: Session, tender_id: str, version: int, kind: str) -> ExportRow | None:
    return session.scalars(select(ExportRow).where(ExportRow.tender_id == tender_id,
                                                   ExportRow.version == version,
                                                   ExportRow.kind == kind)
                           .order_by(ExportRow.created_at.desc())).first()
