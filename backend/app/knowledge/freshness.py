"""Knowledge-base status and credential freshness (expiring certificates)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db import models as m
from backend.app.db.repositories import kb as kb_repo
from backend.app.tools.facts import get_certificates, get_people


def expiring_credentials(session: Session, company_id: str, within_days: int = 90,
                         as_of: date | None = None) -> list[dict[str, Any]]:
    """Company certificates and staff certifications expiring within the window (or expired)."""
    as_of = as_of or date.today()
    horizon = as_of + timedelta(days=within_days)
    out: list[dict[str, Any]] = []
    for cert in get_certificates(session, company_id):
        if cert.expiry_date and cert.expiry_date <= horizon and cert.status.value != "not_held":
            out.append({"kind": "company_certificate", "id": cert.cert_id, "name": cert.name,
                        "expiry_date": cert.expiry_date.isoformat(),
                        "days_left": (cert.expiry_date - as_of).days,
                        "source": cert.source.short() if cert.source else None})
    for person in get_people(session, company_id):
        for pc in person.certifications:
            if pc.expiry_date and pc.expiry_date <= horizon:
                out.append({"kind": "staff_certification", "id": person.person_id, "name": pc.name,
                            "expiry_date": pc.expiry_date.isoformat(),
                            "days_left": (pc.expiry_date - as_of).days,
                            "source": person.source.short() if person.source else None})
    return sorted(out, key=lambda x: x["days_left"])


def kb_status(session: Session, company_id: str, as_of: date | None = None) -> dict[str, Any]:
    """Payload for GET /kb/status (docs/api_contract.md)."""
    company = session.get(m.Company, company_id)
    counts = kb_repo.counts(session, company_id)
    expiring = expiring_credentials(session, company_id, as_of=as_of)
    report = (company.kb_report if company else {}) or {}
    warnings = [f"{e['name']} ({e['id']}) expires {e['expiry_date']}" if e["days_left"] >= 0
                else f"{e['name']} ({e['id']}) expired {e['expiry_date']}" for e in expiring
                if e["kind"] == "company_certificate"]
    warnings += [f"KB file failed to ingest: {f['file']}" for f in report.get("failed", [])]
    return {"company_id": company_id, "name": company.name if company else None,
            "status": company.kb_status if company else "empty",
            "documents": counts["documents"], "chunks": counts["chunks"], "by_type": counts["by_type"],
            "facts": counts["facts"], "expiring": expiring, "warnings": warnings,
            "quarantined_sections": report.get("quarantined_sections", 0)}
