"""Seed structured company facts from `demo_data/structured_facts/` into SQL.

SQL is the authority for numeric eligibility, so these rows are what the rule
engine reads. Seeding is idempotent: rows are upserted by their natural key
and evidence rows are rebuilt, so running it twice leaves identical counts.

Each fact keeps a `source` SourceSpan (doc, page, verbatim span) and the full
source row in `raw`, so columns without a dedicated ORM field (for example the
infrastructure-services turnover used by PQ-04) stay available to the rules.
Fact files are never embedded as RAG chunks.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import ConfigError
from backend.app.core.logging import get_logger
from backend.app.db import models as m
from backend.app.schemas.documents import Scope, SourceSpan
from backend.app.tools.certificate_rules import normalize_standard
from backend.app.tools.date_normalization import to_inr

log = get_logger(__name__)

FACT_FILES = ("company.json", "financials.csv", "certifications.csv", "projects.csv",
              "personnel.csv", "risk_positions.json")

# certifications.csv status -> CertificateStatus. "valid_expiring" is still held;
# expiry against the bid deadline is decided by the certificate rule, not here.
_CERT_STATUS = {"valid": "held", "valid_expiring": "held", "expired": "expired",
                "not_held": "not_held", "in_progress": "in_progress", "suspended": "suspended"}

# Risk-position numeric thresholds by clause type: (within_policy_max, review_max,
# higher_is_worse, unit, threshold key in numeric_thresholds). For clauses where a
# lower value is worse (notice periods) `within_policy_max` holds the minimum.
_RISK_THRESHOLDS: dict[str, tuple[str | None, float | None, bool, str]] = {
    "limitation_of_liability": ("liability_cap_multiple_max", None, True, "x_contract_value"),
    "performance_guarantee": ("pbg_pct_standard_max", 10.0, True, "percent"),
    "payment_terms": ("payment_days_max", None, True, "days"),
    "sla_penalty_cap": ("sla_penalty_cap_pct_max", None, True, "percent"),
    "liquidated_damages": ("ld_cap_pct_max", None, True, "percent"),
    "termination_for_convenience": ("termination_notice_days_min", None, False, "days"),
}

_AVAILABLE_FROM = re.compile(r"from\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Small parsing helpers                                                        #
# --------------------------------------------------------------------------- #
def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _str(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _float(value: str | None) -> float | None:
    value = _str(value)
    return float(value.replace(",", "")) if value is not None else None


def _int(value: str | None) -> int | None:
    value = _str(value)
    return int(float(value)) if value is not None else None


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "yes", "1", "y"}


def _date(value: str | None) -> date | None:
    value = _str(value)
    return date.fromisoformat(value) if value else None


def _crore(value: str | None) -> float | None:
    v = _float(value)
    return to_inr(v, "crore") if v is not None else None


def _span(doc_id: str | None, page: Any = None, text: str | None = None) -> dict[str, Any] | None:
    if not doc_id:
        return None
    page_no = _int(str(page)) if page not in (None, "") else None
    return SourceSpan(doc_id=doc_id, page=page_no, text_span=(text or "").strip(),
                      scope=Scope.kb).model_dump(mode="json")


def _evidence_span(ev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ev:
        return None
    return _span(ev.get("doc_id"), ev.get("page"), ev.get("span"))


def _fy_label(value: str) -> str:
    value = value.strip()
    return value if value.upper().startswith("FY") else f"FY{value}"


def _available_from(text: str | None) -> date | None:
    """First "from YYYY-MM-DD" in the availability note (None = available now)."""
    match = _AVAILABLE_FROM.search(text or "")
    return date.fromisoformat(match.group(1)) if match else None


def _project_tags(row: dict[str, str]) -> list[str]:
    """Factual tags only. Whether a project counts as "similar work" is decided
    by the project rule / similarity judge (Phase 2), not by the seed."""
    tags: list[str] = []
    if (_int(row.get("racks")) or 0) > 0:
        tags.append("data_centre")
    if _bool(row.get("noc_24x7")):
        tags.append("noc_24x7")
    if sector := _str(row.get("sector")):
        tags.append(f"sector:{sector}")
    if scope := _str(row.get("scope_type")):
        tags.append("scope:" + re.sub(r"[^a-z0-9]+", "_", scope.lower()).strip("_"))
    return tags


def _client_type(raw: str | None) -> str | None:
    """Map the descriptive client type to the schema's coarse vocabulary."""
    t = (raw or "").lower()
    if not t:
        return None
    if "central government" in t:
        return "central_govt"
    if "urban local body" in t or "municipal" in t:
        return "local_govt"
    if "state government" in t:
        return "state_govt"
    if "port trust" in t or "psu" in t or "public sector" in t:
        return "psu"
    if "bank" in t:
        return "bank"
    if "private" in t:
        return "private"
    return "other"


# --------------------------------------------------------------------------- #
# Upsert helpers                                                               #
# --------------------------------------------------------------------------- #
class _Evidence:
    """Collects fact_evidence rows; rebuilt on every seed for idempotency."""

    def __init__(self, company_id: str):
        self.company_id = company_id
        self.rows: list[m.FactEvidence] = []

    def add(self, table: str, key: str, span: dict[str, Any] | None) -> None:
        if not span:
            return
        self.rows.append(m.FactEvidence(
            company_id=self.company_id, fact_table=table, fact_key=key,
            doc_id=span.get("doc_id"), page=span.get("page"),
            text_span=span.get("text_span") or None))


def _seed_company(session: Session, data: dict[str, Any], ev: _Evidence) -> m.Company:
    company_id = data["company_id"]
    msme = data.get("msme") or {}
    ids = data.get("identifiers") or {}
    signatory = data.get("authorised_signatory") or {}
    declarations = data.get("declarations") or {}
    source = _evidence_span(data.get("incorporation_evidence"))
    is_mse = bool(msme.get("valid")) and str(msme.get("udyam_classification", "")).lower() in {
        "micro", "small", "medium"}
    profile = {
        "company_id": company_id,
        "name": data.get("name", company_id),
        "is_mse": is_mse,
        "udyam_number": ids.get("udyam"),
        "msme_category": (msme.get("udyam_classification") or "").lower() or None,
        "incorporation_date": data.get("incorporation_date"),
        "gstin": ids.get("gstin"),
        "pan": ids.get("pan"),
        "authorised_signatory": signatory.get("name"),
        "blacklisted": not bool((declarations.get("non_blacklisted") or {}).get("value", True)),
        "extra": {k: v for k, v in data.items() if k not in {"company_id", "name"}},
        "source": source,
    }
    row = session.get(m.Company, company_id)
    if row is None:
        row = m.Company(company_id=company_id, name=profile["name"])
        session.add(row)
    row.name = profile["name"]
    row.is_mse = is_mse
    row.profile = profile

    ev.add("companies", "incorporation_date", source)
    ev.add("companies", "msme", _evidence_span(msme.get("evidence")))
    ev.add("companies", "office_in_deccan_state", _evidence_span(data.get("office_evidence")))
    ev.add("companies", "tech_staff_on_payroll", _evidence_span(data.get("tech_staff_evidence")))
    ev.add("companies", "authorised_signatory", _evidence_span(signatory.get("evidence")))
    for name, decl in declarations.items():
        ev.add("companies", f"declaration:{name}", _evidence_span((decl or {}).get("evidence")))
    for oem in data.get("oem_partnerships") or []:
        ev.add("companies", f"oem:{oem.get('oem')}", _evidence_span(oem.get("evidence")))
    return row


def _seed_financials(session: Session, company_id: str, rows: list[dict[str, str]],
                     ev: _Evidence) -> int:
    for r in rows:
        fy = _fy_label(r["financial_year"])
        source = _span(r.get("source_doc_id"), r.get("page"), r.get("span"))
        row = session.scalar(select(m.Financial).where(m.Financial.company_id == company_id,
                                                      m.Financial.fiscal_year == fy))
        if row is None:
            row = m.Financial(company_id=company_id, fiscal_year=fy, revenue_inr=0.0)
            session.add(row)
        row.revenue_inr = _crore(r.get("revenue_inr_cr")) or 0.0
        row.net_worth_inr = _crore(r.get("net_worth_inr_cr"))
        row.profit_after_tax_inr = _crore(r.get("profit_inr_cr"))
        row.audited = _bool(r.get("audited_flag"))
        row.ca_certified = bool(_str(r.get("infra_source_doc_id")))
        row.source = source
        row.raw = dict(r)
        ev.add("financials", f"{fy}:revenue", source)
        ev.add("financials", f"{fy}:net_worth",
               _span(r.get("source_doc_id"), r.get("net_worth_page"), r.get("net_worth_span")))
        ev.add("financials", f"{fy}:infra_services_revenue",
               _span(r.get("infra_source_doc_id"), r.get("infra_page")))
    return len(rows)


def _seed_certificates(session: Session, company_id: str, rows: list[dict[str, str]],
                       ev: _Evidence) -> int:
    for r in rows:
        source = _span(r.get("source_doc_id"), r.get("page"), r.get("span"))
        standard = normalize_standard(" ".join(filter(None, [r.get("standard"), r.get("level")])))
        row = session.get(m.Certificate, r["cert_id"])
        if row is None:
            row = m.Certificate(cert_id=r["cert_id"], company_id=company_id, name=r["name"])
            session.add(row)
        row.company_id = company_id
        row.name = r["name"]
        row.standard = standard or None
        row.scope = _str(r.get("scope"))
        row.certificate_no = _str(r.get("certificate_no"))
        row.issuer = _str(r.get("issuer"))
        row.issue_date = _date(r.get("valid_from"))
        row.expiry_date = _date(r.get("valid_to"))
        row.status = _CERT_STATUS.get((r.get("status") or "").strip().lower(), "held")
        row.source = source
        row.raw = dict(r)
        ev.add("certificates", r["cert_id"], source)
    return len(rows)


def _seed_projects(session: Session, company_id: str, rows: list[dict[str, str]],
                   ev: _Evidence) -> int:
    for r in rows:
        source = _span(r.get("evidence_doc_id"), r.get("evidence_page"), r.get("evidence_span"))
        status = (r.get("completion_status") or "completed").strip().lower()
        row = session.get(m.Project, r["project_id"])
        if row is None:
            row = m.Project(project_id=r["project_id"], company_id=company_id, name=r["name"])
            session.add(row)
        row.company_id = company_id
        row.name = r["name"]
        row.client = _str(r.get("client"))
        row.client_type = _client_type(r.get("client_type"))
        row.scope_tags = _project_tags(r)
        row.description = _str(r.get("scope_summary")) or ""
        unit = _str(r.get("value_unit")) or "crore"
        value = _float(r.get("contract_value"))
        row.contract_value_inr = to_inr(value, unit) if value is not None else None
        # Eligible value is the bidder's own share, and only when the client has
        # certified it. An uncertified consortium share (PRJ-005) stays None, so
        # total contract value can never satisfy a similar-work threshold.
        certified = _crore(r.get("client_certified_bidder_value_inr_cr"))
        if certified is None and _bool(r.get("share_certified_by_client")):
            certified = _crore(r.get("bidder_share_value_inr_cr"))
        row.eligible_value_inr = certified
        row.start_date = _date(r.get("start_date"))
        row.completion_date = _date(r.get("end_date"))
        row.status = status if status in {"completed", "ongoing", "terminated"} else "completed"
        row.completion_certificate = bool(_str(r.get("completion_certificate_doc_id")))
        share = _float(r.get("bidder_share_pct"))
        row.consortium_share_pct = share if share is not None and share < 100 else None
        row.source = source
        row.raw = dict(r)
        ev.add("projects", r["project_id"], source)
    return len(rows)


def _seed_people(session: Session, company_id: str, rows: list[dict[str, str]],
                 ev: _Evidence) -> int:
    for r in rows:
        source = _span(r.get("cv_doc_id"), r.get("evidence_page"))
        certs = []
        for c in json.loads(r.get("certifications") or "[]"):
            status = (c.get("status") or "").lower()
            certs.append({
                "name": c["name"],
                "standard": normalize_standard(c["name"]) or None,
                "expiry_date": c.get("valid_to"),
                # HR tracker verdict (cert_validity_source_doc_id) wins over CV text.
                "valid": status in {"valid", "no_expiry"} if status else None,
            })
        availability = _str(r.get("availability")) or ""
        row = session.get(m.Person, r["employee_id"])
        if row is None:
            row = m.Person(person_id=r["employee_id"], company_id=company_id,
                           name=r["employee_id"], role=r["role"])
            session.add(row)
        row.company_id = company_id
        # Personal names stay out of the facts store; the masked label is enough
        # for eligibility and keeps PII out of prompts and traces by default.
        row.name = _str(r.get("name_masked")) or r["employee_id"]
        row.role = r["role"]
        row.years_experience = _float(r.get("years_experience")) or 0.0
        row.qualifications = [q.strip() for q in (r.get("degrees") or "").split(", ") if q.strip()]
        row.certifications = certs
        row.available = availability.lower().startswith("available")
        row.available_from = _available_from(availability)
        row.source = source
        row.raw = {k: v for k, v in r.items() if k != "name"}
        ev.add("people", r["employee_id"], source)
        ev.add("people", f"{r['employee_id']}:certifications",
               _span(r.get("cert_validity_source_doc_id"), r.get("cert_validity_page")))
    return len(rows)


def _seed_risk_positions(session: Session, company_id: str, data: dict[str, Any],
                         ev: _Evidence) -> int:
    thresholds = data.get("numeric_thresholds") or {}
    positions = data.get("positions") or []
    for p in positions:
        category = p["clause_type"]
        key, review_max, higher_is_worse, unit = _RISK_THRESHOLDS.get(category, (None, None, True, "text"))
        source = _span(p.get("policy_doc_id"), p.get("page"), p.get("span"))
        row = session.scalar(select(m.RiskPosition).where(m.RiskPosition.company_id == company_id,
                                                         m.RiskPosition.category == category))
        if row is None:
            row = m.RiskPosition(company_id=company_id, category=category)
            session.add(row)
        row.policy = p.get("standard_position") or ""
        row.within_policy_max = float(thresholds[key]) if key and key in thresholds else None
        row.review_max = review_max
        row.higher_is_worse = higher_is_worse
        row.unit = unit
        row.approver = p.get("owner")  # short role; the full approval rule goes in extra
        row.extra = {k: p.get(k) for k in ("approval_required", "negotiation_threshold",
                                          "deal_breaker", "policy_source") if p.get(k) is not None}
        if not higher_is_worse:
            row.extra["threshold_is_minimum"] = True
        row.source = source
        ev.add("risk_positions", category, source)
    return len(positions)


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #
def seed_company_facts(session: Session, company_id: str | None = None, *,
                       facts_dir: Path | None = None) -> dict[str, Any]:
    """Upsert every structured fact file for one company. Idempotent.

    `company_id` defaults to the id in `company.json`; when given it must match.
    Returns per-table counts.
    """
    facts_dir = Path(facts_dir or get_settings().structured_facts_dir)
    missing = [f for f in FACT_FILES if not (facts_dir / f).exists()]
    if missing:
        raise ConfigError("structured facts missing", details={"dir": str(facts_dir),
                                                               "missing": missing})

    company_data = _read_json(facts_dir / "company.json")
    file_company = company_data["company_id"]
    if company_id and company_id != file_company:
        raise ConfigError("company_id does not match company.json",
                          details={"requested": company_id, "file": file_company})
    company_id = file_company

    ev = _Evidence(company_id)
    _seed_company(session, company_data, ev)
    session.flush()
    counts = {
        "financials": _seed_financials(session, company_id, _read_csv(facts_dir / "financials.csv"), ev),
        "certificates": _seed_certificates(session, company_id,
                                           _read_csv(facts_dir / "certifications.csv"), ev),
        "projects": _seed_projects(session, company_id, _read_csv(facts_dir / "projects.csv"), ev),
        "people": _seed_people(session, company_id, _read_csv(facts_dir / "personnel.csv"), ev),
        "risk_positions": _seed_risk_positions(session, company_id,
                                               _read_json(facts_dir / "risk_positions.json"), ev),
    }
    session.execute(delete(m.FactEvidence).where(m.FactEvidence.company_id == company_id))
    session.add_all(ev.rows)
    session.flush()
    counts["fact_evidence"] = len(ev.rows)
    log.info("seeded company facts", extra={"company_id": company_id, **counts})
    return {"company_id": company_id, **counts}


def fact_counts(session: Session, company_id: str) -> dict[str, int]:
    """Row counts per fact table for one company (used by tests and kb_status)."""
    tables: dict[str, Any] = {"financials": m.Financial, "certificates": m.Certificate, "projects": m.Project,
              "people": m.Person, "risk_positions": m.RiskPosition, "fact_evidence": m.FactEvidence}
    return {name: session.scalar(select(func.count()).select_from(model)
                                 .where(model.company_id == company_id)) or 0
            for name, model in tables.items()}
