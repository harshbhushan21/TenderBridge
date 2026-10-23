"""Phase 4: the graph runs a freshly uploaded v1 tender to Gate 1 and reproduces the gold
assessment; Gate 1 pauses and resumes from a durable checkpoint.

Gold files are read here (the evaluator); the pipeline never reads them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.agents import checkpoint
from backend.app.agents.graph import build_graph
from backend.app.agents.persistence import load_assessment, load_compliance, load_risks, thread_id_for
from backend.app.agents.runner import _futures, get_run, resume_run, start_run
from backend.app.db.engine import session_scope
from backend.app.llm import routing
from backend.scripts.run_demo_case import prepare_v1, wait_for_gate

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "demo_data"
GOLD = json.loads((DATA / "evaluation/eligibility_gold.json").read_text(encoding="utf-8"))["scenarios"]["S-v1"]
KEY_FACTS_GOLD = {f["name"]: f for f in json.loads(
    (DATA / "evaluation/key_facts_gold.json").read_text(encoding="utf-8"))["facts"]}
TENDER = "TDR-001"


@pytest.fixture(scope="module")
def paused_run():
    prepare_v1(TENDER, data_dir=DATA)
    started = start_run(TENDER, version=1, analysis_mode="focused")
    run = wait_for_gate(started["analysis_run_id"])
    assert run["status"] == "awaiting_human", run
    with session_scope() as s:
        return {
            "run": run,
            "assessment": load_assessment(s, TENDER, 1, run["run_id"]),
            "compliance": load_compliance(s, TENDER, 1, run["run_id"]),
            "risks": load_risks(s, TENDER, 1, run["run_id"]),
        }


def test_case1_reproduces_gold_score_and_recommendation(paused_run):
    gold = GOLD["bid_assessment"]
    a = paused_run["assessment"]
    assert a["score"] == pytest.approx(gold["weighted_score"], abs=0.01)
    assert a["recommendation"] == gold["recommendation"] == "BID_WITH_CONDITIONS"
    factors = {c["key"]: c["raw_score"] for c in a["criteria"]}
    for key, value in gold["factors"].items():
        assert factors[key] == pytest.approx(value, abs=0.01), key
    assert a["hard_gate_failures"] == []


# Gold labels hard gates by section: PQ rows by number, the single-entity clause
# under 2.1, and the EMD row (PQ-12) under clause 2.10.
_GOLD_SECTION = {"2.1.2": "2.1 Eligible Bidders", "PQ-12": "2.10 EMD"}


def _gold_gate(clause_ref: str) -> dict:
    want = _GOLD_SECTION.get(clause_ref, clause_ref)
    for item in GOLD["items"]:
        if item.get("hard_gate") and want in item["tender_evidence"].get("section", ""):
            return item
    raise AssertionError(f"no gold hard gate for {clause_ref}")


def test_every_hard_gate_matches_gold(paused_run):
    gates = [c for c in paused_run["compliance"] if c["hard_gate"]]
    assert len(gates) == sum(1 for i in GOLD["items"] if i.get("hard_gate")) == 13
    for gate in gates:
        clause = gate["requirement_id"].removeprefix("REQ-")
        assert gate["status"] == _gold_gate(clause)["expected_verdict"], clause


def test_risk_register_matches_gold(paused_run):
    ours = {r["category"]: r["level"] for r in paused_run["risks"]}
    gold = {r["clause_type"]: r["verdict"] for r in GOLD["bid_assessment"]["risk_register"]}
    assert ours == gold


def test_key_facts_are_sourced_and_match_gold(paused_run):
    with session_scope() as s:
        from backend.app.tools.facts import get_key_facts
        kf = get_key_facts(s, TENDER, 1)
    assert kf is not None
    assert kf.submission_deadline.strftime("%Y-%m-%dT%H:%M") == KEY_FACTS_GOLD["bid_submission_end"]["value_v1"]
    assert kf.prebid_meeting.strftime("%Y-%m-%dT%H:%M") == KEY_FACTS_GOLD["prebid_meeting"]["value_v1"]
    assert kf.emd.amount_inr == 7_680_000 and kf.pbg_percent == 5.0
    assert kf.evaluation_method == KEY_FACTS_GOLD["evaluation_method"]["value_v1"]
    assert all(f.source and f.source.page for f in kf.facts)


def test_unchecked_requirements_are_not_risks(paused_run):
    assert len(paused_run["risks"]) == 9  # contract clauses only, not every unchecked sentence


def test_thread_id_stored_matches_checkpoint(paused_run):
    assert paused_run["run"]["thread_id"] == thread_id_for(paused_run["run"]["run_id"])


def test_gate1_resumes_after_restart(paused_run):
    run_id = paused_run["run"]["run_id"]
    checkpoint.get_checkpointer.cache_clear()  # simulate a restart: new saver, same durable store
    resume_run(run_id, {"action": "approve_bid", "tender_version": 1, "reviewer": "bid.manager@nimbus.example"})
    _futures[run_id].result(timeout=120)
    assert get_run(run_id)["status"] == "completed"


def test_graph_applies_amendments_before_routing():
    edges = set(build_graph().builder.edges)
    assert ("extract_key_facts", "reconcile_corrigenda") in edges
    assert ("reconcile_corrigenda", "route_requirements") in edges
    assert ("extract_key_facts", "route_requirements") not in edges


def test_routing_reads_plan_and_stays_offline_in_fake_mode(monkeypatch):
    assert routing.resolve("write_sections").model.startswith("fake:")
    monkeypatch.setattr(routing, "model_for_tier", lambda tier: "groq:openai/gpt-oss-120b")
    monkeypatch.setattr(routing, "get_routing_config", lambda: routing.RoutingConfig(
        routing={"write_sections": {"primary": "gemini-3-flash"},
                 "route_requirements": {"primary": "keyword rules",
                                        "fallback": "groq/openai/gpt-oss-20b (10-15 items per call)"}}))
    assert routing.resolve("write_sections").model == "google_genai:gemini-3-flash"
    assert routing.resolve("route_requirements").model == "groq:openai/gpt-oss-20b"
