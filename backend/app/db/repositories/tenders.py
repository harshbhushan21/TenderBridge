"""Tender, version and file queries."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.errors import NotFoundError
from backend.app.db.models import Tender, TenderFile, TenderVersion


def get_tender(session: Session, tender_id: str) -> Tender:
    t = session.get(Tender, tender_id)
    if t is None:
        raise NotFoundError(f"tender '{tender_id}' not found")
    return t


def list_tenders(session: Session) -> list[Tender]:
    return list(session.scalars(select(Tender).order_by(Tender.created_at.desc())).all())


def count_tenders(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Tender)) or 0


def list_versions(session: Session, tender_id: str) -> list[TenderVersion]:
    return list(session.scalars(select(TenderVersion).where(TenderVersion.tender_id == tender_id)
                                .order_by(TenderVersion.version)).all())


def get_version(session: Session, tender_id: str, version: int) -> TenderVersion | None:
    return session.scalar(select(TenderVersion).where(TenderVersion.tender_id == tender_id,
                                                      TenderVersion.version == version))


def list_files(session: Session, tender_id: str, version: int | None = None) -> list[TenderFile]:
    q = select(TenderFile).where(TenderFile.tender_id == tender_id)
    if version is not None:
        q = q.where(TenderFile.version <= version)
    return list(session.scalars(q.order_by(TenderFile.created_at)).all())


def get_file(session: Session, tender_id: str, doc_id: str) -> TenderFile:
    f = session.get(TenderFile, doc_id)
    if f is None or f.tender_id != tender_id:
        raise NotFoundError(f"file '{doc_id}' not found for tender '{tender_id}'")
    return f
