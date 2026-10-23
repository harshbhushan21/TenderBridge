"""Phase 6: Corrigendum No. 1 on the same tender -> typed diff, new version, impact
re-analysis (78.80 NO_BID), superseded v1 approval, KB untouched.

Gold files are read here (the evaluator); the pipeline never reads them.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.agents.persistence import load_assessment, load_compliance, load_risks
from backend.app.agents.runner import _futures, start_run
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.db.repositories.analysis import latest_run
from backend.app.ingestion.tender_ingest import load_effective_sections
from backend.app.services.tender_service import decide_gate1
from backend.app.tools.facts import get_key_facts
from backend.scripts.run_demo_case import prepare_v1, prepare_v2, wait_for_gate

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "demo_data"
SCENARIOS = json.loads((DATA / "evaluation/eligibility_gold.json").read_text(encoding="utf-8"))["scenarios"]
DIFF_GOLD = json.loads((DATA / "evaluation/corrigendum_diff_gold.json").read_text(encoding="utf-8"))
TENDER = "TDR-C2"  # its own tender, independent of the other test modules
_GOLD_SECTION = {"2.1.2": "2.1 Eligible Bidders", "PQ-12": "2.10 EMD"}


def _kb_fingerprint() -> tuple[int, object]:
    with session_scope() as s:
        return (s.scalar(select(func.count()).select_from(m.KbChunk)) or 0,
                s.scalar(select(func.max(m.KbDocument.updated_at))))


@pytest.fixture(scope="module")
def world():
    prepare_v1(TENDER, data_dir=DATA)
    v1 = wait_for_gate(start_run(TENDER, version=1)["analysis_run_id"])
    with session_scope() as s:  # bid manager approves v1 at Gate 1
        decide_gate1(s, TENDER, {"tender_version": 1, "action": "approve_bid"},
                     user_id="bid.manager@nimbus.example", role="bid_manager")
    _futures[v1["run_id"]].result(timeout=120)
    kb_before = _kb_fingerprint()
    amendment_id = prepare_v2(TENDER, data_dir=DATA)
    kb_after = _kb_fingerprint()
    v2 = wait_for_gate(start_run(TENDER, version=2, mode="impact")["analysis_run_id"])
    with session_scope() as s:
        return {
            "amendment": s.get(m.AmendmentRow, amendment_id).diff,
            "kb": (kb_before, kb_after), "v1_run": v1["run_id"], "v2_run": v2["run_id"],
            "v2_status": v2["status"],
            "v2_assessment": load_assessment(s, TENDER, 2, v2["run_id"]),
            "v2_compliance": load_compliance(s, TENDER, 2, v2["run_id"]),
            "v2_risks": load_risks(s, TENDER, 2, v2["run_id"]),
        }


def test_typed_diff_matches_gold(world):
    ours = {c["change_id"]: c for c in world["amendment"]["changes"]}
    for gold in DIFF_GOLD["changes"]:
        got = ours.get(gold["change_id"])
        assert got is not None, gold["change_id"]
        assert (got["kind"], got["field"]) == (gold["type"], gold["field"]), gold["change_id"]
        if "old" in gold:
            assert str(got["old_value"]) == str(gold["old"]), gold["change_id"]
        if "new" in gold:
            assert str(got["new_value"]) == str(gold["new"]), gold["change_id"]
    part_a = [c for c in world["amendment"]["changes"] if c["part"] == "A"]
    assert len(part_a) == 13  # every Part A row, including the explicit "no change"


def test_v2_reproduces_gold_score_and_no_bid(world):
    gold = SCENARIOS["S-v2"]["bid_assessment"]
    a = world["v2_assessment"]
    assert world["v2_status"] == "awaiting_human"
    assert a["score"] == pytest.approx(gold["weighted_score"], abs=0.01)
    assert a["recommendation"] == gold["recommendation"] == "NO_BID"
    factors = {c["key"]: c["raw_score"] for c in a["criteria"]}
    for key, value in gold["factors"].items():
        assert factors[key] == pytest.approx(value, abs=0.01), key
    assert a["hard_gate_failures"] == ["REQ-PQ-06"]


def test_v2_hard_gates_match_gold(world):
    items = SCENARIOS["S-v2"]["items"]
    for gate in (c for c in world["v2_compliance"] if c["hard_gate"]):
        clause = gate["requirement_id"].removeprefix("REQ-")
        want = _GOLD_SECTION.get(clause, clause)
        gold = next(i for i in items if i.get("hard_gate") and want in i["tender_evidence"].get("section", ""))
        assert gate["status"] == gold["expected_verdict"], clause


def test_iso_gate_cites_new_deadline(world):
    iso = next(c for c in world["v2_compliance"] if c["requirement_id"] == "REQ-PQ-06")
    trace = " ".join(str(x["value"]) for x in iso["rule_result"]["calculations"])
    assert "2026-11-10" in trace and "2026-11-20" in trace


def test_v2_risk_register_matches_gold(world):
    gold = {r["clause_type"]: r["verdict"] for r in SCENARIOS["S-v2"]["bid_assessment"]["risk_register"]}
    assert {r["category"]: r["level"] for r in world["v2_risks"]} == gold


def test_amended_key_dates_cite_the_corrigendum(world):
    with session_scope() as s:
        kf = get_key_facts(s, TENDER, 2)
        corr = s.scalar(select(m.TenderFile).where(m.TenderFile.tender_id == TENDER,
                                                   m.TenderFile.doc_role == "corrigendum"))
    expected = DIFF_GOLD["calendar_expected"]["v2"]
    assert kf.submission_deadline.strftime("%Y-%m-%dT%H:%M") == expected["bid_submission_end"]
    assert kf.bid_opening.strftime("%Y-%m-%dT%H:%M") == expected["tech_bid_opening"]
    assert kf.prebid_meeting.strftime("%Y-%m-%dT%H:%M") == expected["prebid_meeting"]
    assert (kf.pbg_percent, kf.penalty_cap_percent) == (3.0, 10.0)
    assert kf.source_for("submission_deadline").doc_id == corr.doc_id


def test_only_affected_checks_rerun(world):
    gates = {c["requirement_id"]: c for c in world["v2_compliance"] if c["hard_gate"]}
    rerun = {rid for rid, c in gates.items() if not c.get("reused_from_version")}
    reused = {rid for rid, c in gates.items() if c.get("reused_from_version") == 1}
    assert {"REQ-PQ-06", "REQ-PQ-05", "REQ-PQ-01", "REQ-PQ-12"} <= rerun  # deadline / consortium rule
    assert {"REQ-PQ-02", "REQ-PQ-03", "REQ-PQ-04", "REQ-PQ-07"} <= reused  # untouched financials, staff
    assert rerun | reused == set(gates)


def test_consortium_rule_applied_in_v2(world):
    pq05 = next(c for c in world["v2_compliance"] if c["requirement_id"] == "REQ-PQ-05")
    branches = next(x["value"] for x in pq05["rule_result"]["calculations"] if x["label"] == "branch results")
    assert branches[0]["pending_human"] == [] and branches[0]["verdict"] == "gap"  # PRJ-005 no longer pending
    assert pq05["status"] == "meets"  # still met through branch (b)


def test_v1_approval_superseded_and_version_rolled(world):
    with session_scope() as s:
        tender = s.get(m.Tender, TENDER)
        reviews = s.scalars(select(m.ReviewRow).where(m.ReviewRow.tender_id == TENDER,
                                                      m.ReviewRow.version == 1)).all()
        versions = {v.version: v.status for v in s.scalars(select(m.TenderVersion)
                                                          .where(m.TenderVersion.tender_id == TENDER))}
        v1_sections = load_effective_sections(s, TENDER, 1)
        corr = s.scalar(select(m.TenderFile).where(m.TenderFile.tender_id == TENDER,
                                                   m.TenderFile.doc_role == "corrigendum"))
        v1_result = load_assessment(s, TENDER, 1, latest_run(s, TENDER, 1, completed_only=True).run_id)
    assert tender.current_version == 2
    assert versions == {1: "superseded", 2: "effective"}
    assert reviews and all(r.status == "superseded" for r in reviews)
    assert corr.doc_id not in {sec.doc_id for sec in v1_sections}  # the corrigendum never leaks into v1
    assert v1_result["score"] == pytest.approx(77.34, abs=0.01)  # v1 history is kept unchanged


def test_kb_not_reembedded(world):
    before, after = world["kb"]
    assert before == after and before[0] > 0


def test_impact_run_links_to_v1(world):
    with session_scope() as s:
        run = s.get(m.AnalysisRun, world["v2_run"])
    assert run.mode == "impact" and run.previous_run_id == world["v1_run"]
    assert isinstance(run.started_at, datetime)


def test_version_comparison_shows_what_moved(world):
    from backend.app.services.amendment_service import compare_tender_versions

    with session_scope() as s:
        cmp = compare_tender_versions(s, TENDER, 1, 2)
    assert (cmp["a"]["recommendation"], cmp["b"]["recommendation"]) == ("BID_WITH_CONDITIONS", "NO_BID")
    hard = [c for c in cmp["changed_items"] if c["hard_gate"]]
    assert [(c["requirement_id"], c["before"]["status"], c["after"]["status"]) for c in hard] == [
        ("REQ-PQ-06", "meets", "gap")]
    assert {r["category"] for r in cmp["risk_changes"]} == {"performance_guarantee", "payment_terms",
                                                            "sla_penalty_cap"}
    assert len(cmp["amendments"]) >= 14
