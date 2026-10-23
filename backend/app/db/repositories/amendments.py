"""Amendment queries."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import NotFoundError
from backend.app.db.models import AmendmentChangeRow, AmendmentRow


def get_amendment(session: Session, tender_id: str, amendment_id: str) -> AmendmentRow:
    a = session.get(AmendmentRow, amendment_id)
    if a is None or a.tender_id != tender_id:
        raise NotFoundError(f"amendment '{amendment_id}' not found for tender '{tender_id}'")
    return a


def list_amendments(session: Session, tender_id: str) -> list[AmendmentRow]:
    return list(session.scalars(select(AmendmentRow).where(AmendmentRow.tender_id == tender_id)
                                .order_by(AmendmentRow.created_at)).all())


def confirmed_for_version(session: Session, tender_id: str, version: int) -> list[AmendmentRow]:
    return list(session.scalars(select(AmendmentRow).where(
        AmendmentRow.tender_id == tender_id, AmendmentRow.target_version <= version,
        AmendmentRow.status == "confirmed").order_by(AmendmentRow.target_version)).all())


def pending_amendment(session: Session, tender_id: str) -> AmendmentRow | None:
    return session.scalars(select(AmendmentRow).where(
        AmendmentRow.tender_id == tender_id,
        AmendmentRow.status.in_(("uploaded", "parsed", "diff_ready")))
        .order_by(AmendmentRow.created_at.desc())).first()


def changes(session: Session, amendment_id: str) -> list[AmendmentChangeRow]:
    return list(session.scalars(select(AmendmentChangeRow)
                                .where(AmendmentChangeRow.amendment_id == amendment_id)).all())
