"""Phase 1: structured facts seed into SQL idempotently and with evidence."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.app.core.errors import ConfigError
from backend.app.knowledge.kb_seed import fact_counts, seed_company_facts
from backend.app.tools import facts

FACTS_DIR = Path(__file__).resolve().parents[3] / "demo_data" / "structured_facts"
COMPANY = "NIMBUS-001"
CRORE = 1e7


@pytest.fixture
def seeded(db_session):
    seed_company_facts(db_session, facts_dir=FACTS_DIR)
    db_session.flush()
    return db_session


def test_seed_is_idempotent(db_session):
    first = seed_company_facts(db_session, facts_dir=FACTS_DIR)
    counts_once = fact_counts(db_session, COMPANY)
    second = seed_company_facts(db_session, facts_dir=FACTS_DIR)
    assert first == second
    assert fact_counts(db_session, COMPANY) == counts_once
    assert counts_once == {"financials": 3, "certificates": 5, "projects": 10, "people": 10,
                           "risk_positions": 10, "fact_evidence": 62}


def test_financials_in_rupees_with_spans(seeded):
    fins = facts.get_financials(seeded, COMPANY)
    assert [f.fiscal_year for f in fins] == ["FY2022-23", "FY2023-24", "FY2024-25"]
    assert [round(f.revenue_inr / CRORE, 2) for f in fins] == [46.0, 52.0, 58.0]
    assert all(f.source and f.source.doc_id.startswith("KB-FIN-") and f.source.page == 2 for f in fins)
    assert "4,600.00 lakh" in fins[0].source.text_span


def test_company_is_small_mse(seeded):
    company = facts.get_company(seeded, COMPANY)
    assert company.is_mse and company.msme_category == "small"
    assert company.incorporation_date == date(2011, 6, 14)
    assert company.source.doc_id == "KB-REG-001"


def test_certificates_status_and_expiry(seeded):
    certs = {c.standard: c for c in facts.get_certificates(seeded, COMPANY)}
    assert certs["ISO27001"].expiry_date == date(2026, 11, 10)
    assert certs["ISO27001"].status.value == "held"
    assert certs["CMMI3"].status.value == "held"
    assert certs["ISO20000"].status.value == "not_held"


def test_project_eligible_value_never_uses_uncertified_total(seeded):
    projects = {p.project_id: p for p in facts.get_projects(seeded, COMPANY)}
    assert projects["PRJ-001"].eligible_value_inr == pytest.approx(24.60 * CRORE)
    assert projects["PRJ-002"].eligible_value_inr == pytest.approx(26.10 * CRORE)
    # PRJ-005: Rs 38 Cr consortium contract, 45% share not certified by the client.
    assert projects["PRJ-005"].eligible_value_inr is None
    assert projects["PRJ-005"].contract_value_inr == pytest.approx(38.0 * CRORE)
    assert projects["PRJ-005"].consortium_share_pct == 45.0
    assert projects["PRJ-006"].status == "ongoing"


def test_people_masked_and_hr_validity(seeded):
    people = {p.person_id: p for p in facts.get_people(seeded, COMPANY)}
    assert all("masked" in p.name for p in people.values())
    cism = next(c for c in people["NDS-E105"].certifications if c.standard == "CISM")
    assert cism.valid is False and cism.expiry_date == date(2026, 6, 30)
    assert people["NDS-E102"].available_from == date(2026, 12, 1)


def test_risk_thresholds(seeded):
    risks = {r.category: r for r in facts.get_risk_positions(seeded, COMPANY)}
    assert risks["performance_guarantee"].within_policy_max == 3.0
    assert risks["payment_terms"].within_policy_max == 45.0
    assert risks["termination_for_convenience"].higher_is_worse is False


def test_company_id_mismatch_rejected(db_session):
    with pytest.raises(ConfigError):
        seed_company_facts(db_session, "SOMEONE-ELSE", facts_dir=FACTS_DIR)


def test_seeded_strings_fit_column_lengths(seeded):
    """SQLite ignores VARCHAR(n); Postgres rejects overflow. Check it here so the
    SQLite test run catches what a Postgres deploy would fail on."""
    from sqlalchemy import String, select

    from backend.app.db import models as m

    for model in (m.Company, m.Financial, m.Certificate, m.Project, m.Person, m.RiskPosition,
                  m.FactEvidence):
        limited = [c for c in model.__table__.columns
                   if isinstance(c.type, String) and c.type.length]
        for row in seeded.scalars(select(model)).all():
            for col in limited:
                value = getattr(row, col.key)
                assert value is None or len(value) <= col.type.length, (
                    f"{model.__tablename__}.{col.key} ({col.type.length}) <- {len(value)} chars")
