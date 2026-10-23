"""Regression tests for Phase 2 review fixes, driven by eligibility_gold.json.

Tests (the evaluator) may read gold labels; the agent graph never does.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from backend.app.agents.nodes.core import bid_score
from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.schemas.documents import SourceSpan
from backend.app.schemas.eligibility import (
    DocumentPresenceRule,
    EligibilityStatus,
    PersonnelRule,
    SimilarWorkBranch,
    SimilarWorkRule,
)
from backend.app.tools import facts
from backend.app.tools.personnel_rules import check_personnel
from backend.app.tools.project_rules import check_similar_work
from backend.app.tools.registration_rules import check_registration
from backend.app.tools.rule_parser import parse_requirement

ROOT = Path(__file__).resolve().parents[3]
GOLD = json.loads((ROOT / "demo_data/evaluation/eligibility_gold.json").read_text(encoding="utf-8"))
COMPANY = "NIMBUS-001"
CRORE = 10_000_000
V1, V2 = date(2026, 11, 6), date(2026, 11, 20)


@pytest.fixture
def seeded(db_session):
    seed_company_facts(db_session, facts_dir=ROOT / "demo_data" / "structured_facts")
    db_session.flush()
    return db_session


def _state_for(scenario: str) -> dict:
    """Build graph state from the gold verdicts, exactly as route/eligibility nodes would."""
    data = GOLD["scenarios"][scenario]
    ba = data["bid_assessment"]
    span = SourceSpan(doc_id="TDR-001", page=1)
    compliance = [{
        "requirement_id": it["requirement_id"], "tender_id": "TDR-001", "tender_version": 1,
        "category": "eligibility", "hard_gate": bool(it.get("hard_gate")),
        "status": it["expected_verdict"], "summary": it["criterion"],
        "tender_source": span.model_dump(mode="json"),
    } for it in data["items"]]
    risks = [{
        "risk_id": f"R{i}", "requirement_id": r["requirement_id"], "tender_id": "TDR-001",
        "tender_version": 1, "category": r["clause_type"], "level": r["verdict"],
        "tender_value": r["tender_term"], "policy_value": r["policy"], "summary": r["clause_type"],
    } for i, r in enumerate(ba["risk_register"])]
    static = {k: ba["factors"][k] for k in ("strategic_fit", "technical_capability", "delivery_capacity")}
    return {"tender_id": "TDR-001", "tender_version": 1, "analysis_run_id": f"run-{scenario}",
            "compliance": compliance, "risks": risks, "static_scores": static}


@pytest.mark.parametrize("scenario", ["S-v1", "S-v2", "S-X1"])
def test_bid_score_node_reproduces_gold(scenario):
    ba = GOLD["scenarios"][scenario]["bid_assessment"]
    out = bid_score(_state_for(scenario))["assessment"]
    factors = {c["key"]: c["raw_score"] for c in out["criteria"]}
    assert factors["eligibility_confidence"] == pytest.approx(ba["factors"]["eligibility_confidence"], abs=0.01)
    assert factors["commercial_risk"] == pytest.approx(ba["factors"]["commercial_risk"], abs=0.01)
    assert out["score"] == pytest.approx(ba["weighted_score"], abs=0.01)
    assert out["recommendation"] == ba["recommendation"]


def test_v1_needs_action_hard_gate_is_a_condition_not_a_failure():
    out = bid_score(_state_for("S-v1"))["assessment"]
    assert out["hard_gate_failures"] == []
    assert out["recommendation"] == "BID_WITH_CONDITIONS"
    assert any("Approval needed" in c for c in out["conditions"])  # CEO, uncapped liability


def test_v2_iso_gap_forces_no_bid_despite_higher_score():
    out = bid_score(_state_for("S-v2"))["assessment"]
    assert out["hard_gate_failures"] == ["REQ-ELG-009"]
    assert out["score"] > bid_score(_state_for("S-v1"))["assessment"]["score"]


def test_similar_work_never_counts_consortium_total(seeded):
    rule = SimilarWorkRule(
        branches=[SimilarWorkBranch(count=3, min_value_inr=15.36 * CRORE),
                  SimilarWorkBranch(count=2, min_value_inr=23.04 * CRORE),
                  SimilarWorkBranch(count=1, min_value_inr=30.72 * CRORE)],
        reference_date=V1, required_scope_tags=["data_centre", "noc_24x7"])
    result = check_similar_work(facts.get_projects(seeded, COMPANY), rule)
    branches = {b["branch"]: b for b in next(c.value for c in result.calculations
                                             if c.label == "branch results")}
    # Gold: (a) pending PRJ-005 (45% share = 17.10 >= 15.36); (b) meets; (c) gap, no pending.
    assert branches["a"]["pending_human"] == ["PRJ-005"] and branches["a"]["verdict"] == "needs_human"
    assert branches["b"]["pending_human"] == [] and branches["b"]["verdict"] == "meets"
    assert branches["c"]["pending_human"] == [] and branches["c"]["verdict"] == "gap"
    assert result.status is EligibilityStatus.meets


def test_project_manager_rolling_off_before_takeover_still_meets(seeded):
    people = facts.get_people(seeded, COMPANY)
    rule = PersonnelRule(role="Project Manager", any_of_certifications=["PMP"], as_of=V1)
    assert check_personnel(people, rule).status is EligibilityStatus.meets
    late = rule.model_copy(update={"available_by": date(2026, 11, 15)})  # before NDS-E102 frees up
    assert check_personnel(people, late).status is EligibilityStatus.gap


@pytest.mark.parametrize("deadline", [V1, V2])
def test_security_lead_substitution_from_hr_tracker(seeded, deadline):
    people = facts.get_people(seeded, COMPANY)
    result = check_personnel(people, PersonnelRule(role="Security Lead", min_years=8,
                                                   any_of_certifications=["CISM", "CISSP"], as_of=deadline))
    assert result.status is EligibilityStatus.meets_with_substitution
    assert "NDS-E110" in result.actions[0] and "NDS-E105" in result.actions[0]


def test_document_rules_match_gold_verdicts(seeded):
    company = facts.get_company(seeded, COMPANY)
    maf = DocumentPresenceRule(document_type="oem_maf", tender_specific=True)
    office = DocumentPresenceRule(document_type="local_office", undertaking_acceptable=True)
    assert check_registration(company, set(), maf).status is EligibilityStatus.needs_action
    assert check_registration(company, set(), office).status is EligibilityStatus.meets_with_undertaking
    assert check_registration(company, set(), DocumentPresenceRule(document_type="x")).status \
        is EligibilityStatus.gap


def test_rule_parser_word_numbers_and_multiple_standards():
    similar = parse_requirement("three similar works of Rs. 15.36 Cr within the last seven (7) years")
    assert similar["window"]["years"] == 7
    assert parse_requirement("works completed within five years, two similar works of Rs. 10 Cr")[
        "window"]["years"] == 5
    cert = parse_requirement("Valid ISO 9001:2015 and ISO/IEC 27001:2022 certificates")
    assert cert["standards"] == ["ISO9001", "ISO27001"]
