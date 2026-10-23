"""Read back ingested tender content for the analysis graph."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import models as m
from backend.app.schemas.documents import BoqItem, ParsedSection, TableBlock


def _to_section(row: m.TenderSection) -> ParsedSection:
    return ParsedSection(section_id=row.section_id, doc_id=row.doc_id, title=row.title,
                         section_path=row.section_path, level=row.level, page_start=row.page_start,
                         page_end=row.page_end, text=row.text, parent_id=row.parent_id,
                         tables=[TableBlock.model_validate(t) for t in row.tables or []],
                         flags=list(row.flags or []))


def load_effective_sections(session: Session, tender_id: str, version: int, *,
                            include_quarantined: bool = False) -> list[ParsedSection]:
    """Sections from indexed files introduced at or before `version`, in document order.

    Quarantined sections are excluded unless asked for (their text is already
    stripped of the hostile spans, but they stay out of agent prompts by default).
    """
    stmt = (select(m.TenderSection).join(m.TenderFile, m.TenderFile.doc_id == m.TenderSection.doc_id)
            .where(m.TenderSection.tender_id == tender_id, m.TenderSection.version <= version,
                   m.TenderFile.status == "indexed")
            .order_by(m.TenderFile.version, m.TenderFile.created_at, m.TenderSection.section_id))
    if not include_quarantined:
        stmt = stmt.where(m.TenderSection.quarantined.is_(False))
    return [_to_section(r) for r in session.scalars(stmt)]


def load_sections_for_doc(session: Session, doc_id: str) -> list[ParsedSection]:
    rows = session.scalars(select(m.TenderSection).where(m.TenderSection.doc_id == doc_id)
                           .order_by(m.TenderSection.section_id))
    return [_to_section(r) for r in rows]


def load_boq_items(session: Session, tender_id: str, version: int) -> list[BoqItem]:
    rows = session.scalars(select(m.BoqItemRow).where(m.BoqItemRow.tender_id == tender_id,
                                                      m.BoqItemRow.version <= version)
                           .order_by(m.BoqItemRow.sheet, m.BoqItemRow.row))
    return [BoqItem(sheet=r.sheet, row=r.row, item_no=r.item_no, description=r.description, unit=r.unit,
                    quantity=r.quantity, rate=r.rate, amount=r.amount, cells=dict(r.cells or {}))
            for r in rows]
