"""Phase 2 deterministic rule and scoring acceptance tests."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.schemas.assessment import HardGateResult
from backend.app.schemas.eligibility import (
    CertificationRule,
    EligibilityStatus,
    PersonnelRule,
    SimilarWorkBranch,
    SimilarWorkRule,
)
from backend.app.schemas.requirements import KeyFacts
from backend.app.tools.bid_scoring import score_bid
from backend.app.tools.certificate_rules import check_certification
from backend.app.tools.commercial_rules import assess_commercial_risk
from backend.app.tools.date_normalization import fiscal_year_key, parse_money, to_inr
from backend.app.tools.facts import (
    get_certificates,
    get_company,
    get_people,
    get_projects,
    get_risk_positions,
)
from backend.app.tools.personnel_rules import check_personnel
from backend.app.tools.project_rules import check_similar_work
from backend.app.tools.registration_rules import check_registration
from backend.app.tools.rule_parser import parse_requirement


@pytest.fixture
def seeded(db_session):
    seed_company_facts(
        db_session,
        facts_dir=Path(__file__).resolve().parents[3] / "demo_data" / "structured_facts",
    )
    db_session.flush()
    return db_session

COMPANY = "NIMBUS-001"
CRORE = 10_000_000


def test_money_and_fiscal_year_normalization() -> None:
    assert to_inr(4_600, "lakh") == 46 * CRORE
    assert parse_money("Rs. 45 Crore").crore == 45
    assert fiscal_year_key("FY2022-23") == 2023
    assert fiscal_year_key("2024-25") == 2025


def test_rule_parser_extracts_mse_and_or_branches() -> None:
    turnover = parse_requirement(
        "Average turnover shall be Rs. 55 Crore, relaxed to Rs. 45 Crore for MSEs "
        "during FY2022-23, FY2023-24 and FY2024-25."
    )
    assert turnover["logic"] == "OR"
    assert turnover["mse_relaxation"] is True
    assert turnover["branches"][1]["threshold"] == 45
    similar = parse_requirement(
        "Three similar works of at least Rs. 15.36 Cr OR two of Rs. 23.04 Cr "
        "OR one of Rs. 30.72 Cr within seven years."
    )
    assert similar["logic"] == "OR"
    assert len(similar["branches"]) == 3


def test_turnover_and_certificate_v1_v2(seeded) -> None:
    from backend.app.schemas.eligibility import TurnoverRule
    from backend.app.tools.facts import get_company, get_financials
    from backend.app.tools.financial_rules import check_turnover

    company = get_company(seeded, COMPANY)
    result = check_turnover(
        get_financials(seeded, COMPANY),
        TurnoverRule(general_threshold_inr=55 * CRORE, mse_threshold_inr=45 * CRORE,
                     mse_relaxation_allowed=True, n_years=3),
        company,
    )
    assert result.status is EligibilityStatus.meets
    assert "Would fail the general threshold" in result.summary

    certs = get_certificates(seeded, COMPANY)
    v1 = KeyFacts(tender_id="TDR-001", tender_version=1,
                  submission_deadline=datetime(2026, 11, 6, 15, tzinfo=UTC))
    v2 = v1.model_copy(update={"tender_version": 2,
                               "submission_deadline": datetime(2026, 11, 20, 15, tzinfo=UTC)})
    rule = CertificationRule(standard="ISO27001", display_name="ISO/IEC 27001")
    assert check_certification(certs, rule, v1).status is EligibilityStatus.meets
    assert check_certification(certs, rule, v2).status is EligibilityStatus.gap


def test_similar_work_uses_certified_share_and_or_branch(seeded) -> None:
    projects = get_projects(seeded, COMPANY)
    rule = SimilarWorkRule(
        branches=[
            SimilarWorkBranch(count=3, min_value_inr=15.36 * CRORE),
            SimilarWorkBranch(count=2, min_value_inr=23.04 * CRORE),
            SimilarWorkBranch(count=1, min_value_inr=30.72 * CRORE),
        ],
        reference_date=date(2026, 11, 6),
        required_scope_tags=["data_centre", "noc_24x7"],
    )
    result = check_similar_work(projects, rule)
    assert result.status is EligibilityStatus.meets
    branches = next(c.value for c in result.calculations if c.label == "branch results")
    assert branches[1]["verdict"] == "meets"
    assert "PRJ-005" in branches[0]["pending_human"]
    assert not any(c["project_id"] == "PRJ-004" and c["in_window"] for c in result.candidates)
    assert not any(c["project_id"] == "PRJ-009" and c["similar"] for c in result.candidates)


def test_personnel_and_registration_rules(seeded) -> None:
    people = get_people(seeded, COMPANY)
    result = check_personnel(people, PersonnelRule(role="Security Lead", min_years=8,
                                                   any_of_certifications=["CISM", "CISSP"],
                                                   as_of=date(2026, 11, 6)))
    # Gold REQ-PER-004: NDS-E105's CISM lapsed, NDS-E110 (alternate) substitutes.
    assert result.status is EligibilityStatus.meets_with_substitution
    assert any(c["person_id"] == "NDS-E110" and c["qualified"] for c in result.candidates)
    company = get_company(seeded, COMPANY)
    assert check_registration(company).status is EligibilityStatus.meets


def test_commercial_policy_and_exact_v1_v2_scores(seeded) -> None:
    positions = {p.category: p for p in get_risk_positions(seeded, COMPANY)}
    assert assess_commercial_risk("performance_guarantee", 5, positions["performance_guarantee"])["level"] == "review"
    assert assess_commercial_risk("payment_terms", 45, positions["payment_terms"])["level"] == "within_policy"
    gates = [HardGateResult(requirement_id="REQ-ELG-009", label="ISO", status="meets", passed=True,
                            summary="valid")]
    factors = {"strategic_fit": 85, "technical_capability": 72.52,
               "eligibility_confidence": 97.31, "commercial_risk": 50, "delivery_capacity": 85}
    v1 = score_bid(tender_id="TDR-001", tender_version=1, analysis_run_id="run-1",
                   factors=factors, hard_gates=gates, conditions=["CEO approval"])
    assert v1.score == 77.34
    assert v1.recommendation.value == "BID_WITH_CONDITIONS"
    v2 = score_bid(tender_id="TDR-001", tender_version=2, analysis_run_id="run-2",
                   factors={**factors, "eligibility_confidence": 89.62, "commercial_risk": 65},
                   hard_gates=[gates[0].model_copy(update={"passed": False, "status": "gap"})])
    assert v2.score == 78.8
    assert v2.recommendation.value == "NO_BID"
