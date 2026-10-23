"""Tender workspace lifecycle (create, status). The API layer (Phase 5) builds on this."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.ops.audit import audit
from backend.app.schemas.documents import TenderStatus


def create_tender(session: Session, title: str, *, buyer: str | None = None,
                  reference_no: str | None = None, company_id: str | None = None,
                  analysis_mode: str | None = None, tender_id: str | None = None,
                  actor: str = "system") -> m.Tender:
    """Create a tender workspace with an effective version 1 (files arrive next)."""
    settings = get_settings()
    tender = m.Tender(tender_id=tender_id or m.new_id("TDR"), title=title, buyer=buyer,
                      reference_no=reference_no, company_id=company_id or settings.default_company_id,
                      status=TenderStatus.created.value, current_version=1,
                      analysis_mode=analysis_mode or settings.analysis_mode, created_by=actor)
    session.add(tender)
    session.add(m.TenderVersion(tender_id=tender.tender_id, version=1, status="effective",
                                confirmed_by=actor, note="original tender pack"))
    session.flush()
    audit(actor, "tender.created", tender_id=tender.tender_id, version=1, session=session,
          title=title, reference_no=reference_no)
    return tender
