"""Read-only access to structured company facts and tender facts.

SQL is the authority for numeric eligibility (principle 5). All queries are
parameterised via the ORM; `query_facts` only exposes allow-listed views.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import ToolError
from backend.app.db import models as m
from backend.app.schemas.documents import SourceSpan
from backend.app.schemas.eligibility import (CertificateRecord, CertificateStatus, CompanyProfile,
                                             FinancialRecord, PersonCert, PersonRecord,
                                             ProjectRecord, RiskPositionRecord)
from backend.app.schemas.requirements import KeyFacts, Requirement
from backend.app.tools.date_normalization import fiscal_year_key


def _span(src: dict | None) -> SourceSpan | None:
    if not src:
        return None
    try:
        return SourceSpan.model_validate(src)
    except Exception:
        doc = src.get("doc_id") if isinstance(src, dict) else None
        return SourceSpan(doc_id=str(doc or "unknown"), scope="kb")


def get_company(session: Session, company_id: str) -> CompanyProfile | None:
    row = session.get(m.Company, company_id)
    if row is None:
        return None
    profile = dict(row.profile or {})
    profile.setdefault("company_id", row.company_id)
    profile.setdefault("name", row.name)
    profile["is_mse"] = bool(profile.get("is_mse", row.is_mse))
    try:
        return CompanyProfile.model_validate(profile)
    except Exception:
        return CompanyProfile(company_id=row.company_id, name=row.name, is_mse=row.is_mse,
                              extra=profile)


def get_financials(session: Session, company_id: str,
                   fiscal_years: list[str] | None = None) -> list[FinancialRecord]:
    rows = session.scalars(select(m.Financial).where(m.Financial.company_id == company_id)).all()
    out = [FinancialRecord(company_id=r.company_id, fiscal_year=r.fiscal_year,
                           revenue_inr=r.revenue_inr, net_worth_inr=r.net_worth_inr,
                           profit_after_tax_inr=r.profit_after_tax_inr, audited=r.audited,
                           ca_certified=r.ca_certified, source=_span(r.source)) for r in rows]
    if fiscal_years:
        wanted = {fiscal_year_key(f) for f in fiscal_years}
        out = [f for f in out if fiscal_year_key(f.fiscal_year) in wanted]
    return sorted(out, key=lambda f: fiscal_year_key(f.fiscal_year))


def get_certificates(session: Session, company_id: str) -> list[CertificateRecord]:
    rows = session.scalars(select(m.Certificate).where(m.Certificate.company_id == company_id)).all()
    out = []
    for r in rows:
        try:
            status = CertificateStatus(r.status)
        except ValueError:
            status = CertificateStatus.held
        out.append(CertificateRecord(
            company_id=r.company_id, cert_id=r.cert_id, name=r.name, standard=r.standard,
            scope=r.scope, certificate_no=r.certificate_no, issuer=r.issuer,
            issue_date=r.issue_date, expiry_date=r.expiry_date, status=status,
            source=_span(r.source)))
    return out


def get_projects(session: Session, company_id: str) -> list[ProjectRecord]:
    rows = session.scalars(select(m.Project).where(m.Project.company_id == company_id)).all()
    return [ProjectRecord(
        company_id=r.company_id, project_id=r.project_id, name=r.name, client=r.client,
        client_type=r.client_type, scope_tags=list(r.scope_tags or []),
        description=r.description or "", contract_value_inr=r.contract_value_inr,
        eligible_value_inr=r.eligible_value_inr, start_date=r.start_date,
        completion_date=r.completion_date,
        status=r.status if r.status in ("completed", "ongoing", "terminated") else "completed",
        completion_certificate=r.completion_certificate,
        consortium_share_pct=r.consortium_share_pct, source=_span(r.source)) for r in rows]


def get_people(session: Session, company_id: str) -> list[PersonRecord]:
    rows = session.scalars(select(m.Person).where(m.Person.company_id == company_id)).all()
    out = []
    for r in rows:
        certs = []
        for c in r.certifications or []:
            try:
                certs.append(PersonCert.model_validate(c) if isinstance(c, dict) else PersonCert(name=str(c)))
            except Exception:
                continue
        out.append(PersonRecord(
            company_id=r.company_id, person_id=r.person_id, name=r.name, role=r.role,
            years_experience=r.years_experience or 0, qualifications=list(r.qualifications or []),
            certifications=certs, available=r.available, available_from=r.available_from,
            source=_span(r.source)))
    return out


def get_risk_positions(session: Session, company_id: str) -> list[RiskPositionRecord]:
    rows = session.scalars(select(m.RiskPosition).where(m.RiskPosition.company_id == company_id)).all()
    return [RiskPositionRecord(
        company_id=r.company_id, category=r.category, policy=r.policy or "",
        within_policy_max=r.within_policy_max, review_max=r.review_max,
        higher_is_worse=r.higher_is_worse, unit=r.unit, approver=r.approver,
        extra=dict(r.extra or {}), source=_span(r.source)) for r in rows]


def get_key_facts(session: Session, tender_id: str, version: int) -> KeyFacts | None:
    row = session.scalar(select(m.KeyFactsRow).where(m.KeyFactsRow.tender_id == tender_id,
                                                     m.KeyFactsRow.version == version))
    return KeyFacts.model_validate(row.data) if row else None


def save_key_facts(session: Session, key_facts: KeyFacts) -> None:
    """Upsert key facts for (tender, version). Not exposed to agents as a tool."""
    row = session.scalar(select(m.KeyFactsRow).where(
        m.KeyFactsRow.tender_id == key_facts.tender_id,
        m.KeyFactsRow.version == key_facts.tender_version))
    data = key_facts.model_dump(mode="json")
    if row:
        row.data = data
    else:
        session.add(m.KeyFactsRow(tender_id=key_facts.tender_id, version=key_facts.tender_version,
                                  data=data))
    session.flush()


def get_requirement(session: Session, tender_id: str, version: int,
                    requirement_id: str) -> Requirement | None:
    row = session.scalar(
        select(m.RequirementRow)
        .where(m.RequirementRow.tender_id == tender_id, m.RequirementRow.version == version,
               m.RequirementRow.requirement_id == requirement_id)
        .order_by(m.RequirementRow.id.desc()))
    return Requirement.model_validate(row.data) if row else None


# --------------------------------------------------------------------------- #
# Allow-listed parameterised views (for ask_tender / UI)                       #
# --------------------------------------------------------------------------- #
_VIEW_FILTERS: dict[str, set[str]] = {
    "financials": {"fiscal_year"},
    "certificates": {"standard", "status"},
    "projects": {"client_type", "status", "scope_tag", "min_eligible_value_inr"},
    "people": {"role", "available"},
    "risk_positions": {"category"},
    "company": set(),
}


def query_facts(session: Session, view: str, company_id: str, **filters: Any) -> list[dict]:
    if view not in _VIEW_FILTERS:
        raise ToolError(f"view '{view}' is not allowed", details={"allowed": sorted(_VIEW_FILTERS)})
    bad = set(filters) - _VIEW_FILTERS[view]
    if bad:
        raise ToolError(f"unsupported filters for {view}: {sorted(bad)}")
    if view == "company":
        c = get_company(session, company_id)
        return [c.model_dump(mode="json")] if c else []
    loader = {"financials": get_financials, "certificates": get_certificates,
              "projects": get_projects, "people": get_people,
              "risk_positions": get_risk_positions}[view]
    records = loader(session, company_id)
    out = []
    for r in records:
        d = r.model_dump(mode="json")
        ok = True
        for k, v in filters.items():
            if v is None:
                continue
            if k == "scope_tag":
                ok = v in d.get("scope_tags", [])
            elif k == "min_eligible_value_inr":
                ok = (d.get("eligible_value_inr") or 0) >= float(v)
            elif k == "role":
                ok = str(v).lower() in str(d.get("role", "")).lower()
            elif k == "fiscal_year":
                ok = fiscal_year_key(d["fiscal_year"]) == fiscal_year_key(str(v))
            else:
                ok = str(d.get(k)).lower() == str(v).lower()
            if not ok:
                break
        if ok:
            out.append(d)
    return out
