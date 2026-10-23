"""Company KB queries."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    Certificate,
    Company,
    Financial,
    KbChunk,
    KbDocument,
    Person,
    Project,
    RiskPosition,
)

FACT_TABLES: dict[str, Any] = {
    "financials": Financial, "certificates": Certificate, "projects": Project,
    "people": Person, "risk_positions": RiskPosition,
}


def get_company(session: Session, company_id: str) -> Company | None:
    return session.get(Company, company_id)


def list_documents(session: Session, company_id: str, *, doc_type: str | None = None,
                   q: str | None = None) -> list[KbDocument]:
    stmt = select(KbDocument).where(KbDocument.company_id == company_id)
    if doc_type:
        stmt = stmt.where(KbDocument.doc_type == doc_type)
    if q:
        stmt = stmt.where(or_(KbDocument.filename.ilike(f"%{q}%"), KbDocument.doc_id.ilike(f"%{q}%")))
    return list(session.scalars(stmt.order_by(KbDocument.doc_type, KbDocument.filename)).all())


def counts(session: Session, company_id: str) -> dict[str, Any]:
    docs = session.scalar(select(func.count()).select_from(KbDocument)
                          .where(KbDocument.company_id == company_id)) or 0
    chunks = session.scalar(select(func.count()).select_from(KbChunk)
                            .where(KbChunk.company_id == company_id)) or 0
    by_type = dict(session.execute(select(KbDocument.doc_type, func.count())
                                   .where(KbDocument.company_id == company_id)
                                   .group_by(KbDocument.doc_type)).all())
    facts = {name: session.scalar(select(func.count()).select_from(model)
                                  .where(model.company_id == company_id)) or 0
             for name, model in FACT_TABLES.items()}
    return {"documents": docs, "chunks": chunks,
            "by_type": {str(k or "unknown"): v for k, v in by_type.items()}, "facts": facts}


def _row_dict(row) -> dict[str, Any]:
    out = {}
    for col in row.__table__.columns:
        v = getattr(row, col.name)
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        out[col.name] = v
    return out


def list_facts(session: Session, company_id: str, kind: str) -> list[dict[str, Any]]:
    if kind == "company":
        c = get_company(session, company_id)
        return [_row_dict(c)] if c else []
    model = FACT_TABLES[kind]
    return [_row_dict(r) for r in session.scalars(select(model).where(model.company_id == company_id)).all()]
