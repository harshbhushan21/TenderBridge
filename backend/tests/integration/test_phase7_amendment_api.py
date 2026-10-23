"""Phase 7 (API half): the corrigendum lifecycle over HTTP on the same tender.

v1 analysed and approved -> corrigendum uploaded -> typed diff -> analyst cannot confirm ->
bid manager confirms -> impact re-analysis -> 78.80 NO_BID -> versions and comparison.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db.engine import session_scope
from backend.app.ingestion.kb_ingest import ingest_company_kb
from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "demo_data"
ORIGINAL = DATA / "tender/TDR-001/original"
V1_FILES = ("notice.pdf", "main_rfp.pdf", "annexures.pdf", "price_schedule_boq.xlsx")
GOLD_IDS = {c["change_id"] for c in json.loads(
    (DATA / "evaluation/corrigendum_diff_gold.json").read_text(encoding="utf-8"))["changes"]}
MANAGER = {"X-User": "bid.manager@nimbus.example", "X-Role": "bid_manager"}
ANALYST = {"X-User": "analyst@nimbus.example", "X-Role": "analyst"}


def _wait(client, tender_id, run_id, statuses, timeout=180):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        status = client.get(f"/tenders/{tender_id}/runs/{run_id}").json()["status"]
        if status in statuses:
            return status
        time.sleep(0.25)
    raise TimeoutError(run_id)


@pytest.fixture(scope="module")
def flow():
    with session_scope() as s:
        company = seed_company_facts(s, facts_dir=DATA / "structured_facts")["company_id"]
        ingest_company_kb(s, company, kb_dir=DATA / "company_kb", facts_dir=DATA / "structured_facts",
                          manifest_path=DATA / "demo_config/company_manifest.json")
    with TestClient(create_app()) as c:
        tid = c.post("/tenders", json={"title": "DSDC O&M (amendment API test)"}, headers=MANAGER).json()["tenderId"]
        c.post(f"/tenders/{tid}/files", headers=MANAGER,
               files=[("files", (n, (ORIGINAL / n).read_bytes())) for n in V1_FILES])
        run1 = c.post(f"/tenders/{tid}/run", json={}, headers=MANAGER).json()["analysis_run_id"]
        _wait(c, tid, run1, {"awaiting_human"})
        c.post(f"/tenders/{tid}/decision", json={"tender_version": 1, "action": "approve_bid"}, headers=MANAGER)
        _wait(c, tid, run1, {"completed"})
        up = c.post(f"/tenders/{tid}/amendments", headers=MANAGER,
                    files={"file": ("corrigendum.pdf", (ORIGINAL / "corrigendum.pdf").read_bytes())})
        yield {"client": c, "id": tid, "upload": up, "run1": run1}


def test_upload_processes_into_typed_diff(flow):
    c, tid, up = flow["client"], flow["id"], flow["upload"]
    assert up.status_code == 202 and up.json()["target_version"] == 2
    aid = up.json()["amendment_id"]
    diff = c.get(f"/tenders/{tid}/amendments/{aid}/diff").json()
    assert diff["status"] == "diff_ready"
    assert GOLD_IDS <= {ch["change_id"] for ch in diff["changes"]}
    view = c.get(f"/tenders/{tid}").json()
    assert view["amendmentPending"] is True and view["currentVersion"] == 1


def test_second_amendment_refused_while_one_is_pending(flow):
    c, tid = flow["client"], flow["id"]
    r = c.post(f"/tenders/{tid}/amendments", headers=MANAGER,
               files={"file": ("again.pdf", (ORIGINAL / "corrigendum.pdf").read_bytes())})
    assert r.status_code == 409


def test_confirm_analyst_refused_then_manager_confirms(flow):
    c, tid = flow["client"], flow["id"]
    aid = flow["upload"].json()["amendment_id"]
    denied = c.post(f"/tenders/{tid}/amendments/{aid}/confirm", json={}, headers=ANALYST)
    assert denied.status_code == 403
    assert "amendment.confirm_denied" in [e["action"] for e in c.get(f"/tenders/{tid}/audit").json()["items"]]
    ok = c.post(f"/tenders/{tid}/amendments/{aid}/confirm", json={"comment": "Corrigendum No. 1"}, headers=MANAGER)
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"tender_version": 2, "status": "reanalysis_required", "superseded_reviews": 1,
                         "stale_drafts": 0}
    # A late v1 decision is now refused: it belongs to a superseded version.
    late = c.post(f"/tenders/{tid}/decision", json={"tender_version": 1, "action": "approve_bid"}, headers=MANAGER)
    assert late.status_code == 409


def test_reanalyse_gives_no_bid_and_versions_compare(flow):
    c, tid = flow["client"], flow["id"]
    started = c.post(f"/tenders/{tid}/reanalyse", json={"mode": "impact"}, headers=MANAGER)
    assert started.status_code == 202 and started.json()["tender_version"] == 2
    assert _wait(c, tid, started.json()["analysis_run_id"], {"awaiting_human", "failed"}) == "awaiting_human"
    a = c.get(f"/tenders/{tid}/assessment").json()
    assert (a["score"], a["recommendation"], a["hard_gate_failures"]) == (78.8, "NO_BID", ["REQ-PQ-06"])
    assert c.get(f"/tenders/{tid}/key-facts").json()["submission_deadline"].startswith("2026-11-20T15:00")

    versions = {v["version"]: v for v in c.get(f"/tenders/{tid}/versions").json()["versions"]}
    assert versions[1]["status"] == "superseded" and versions[1]["assessment"]["approval_status"] == "superseded"
    assert versions[1]["assessment"]["score"] == pytest.approx(77.34, abs=0.01)
    assert versions[2]["status"] == "effective" and versions[2]["assessment"]["recommendation"] == "NO_BID"

    cmp = c.get(f"/tenders/{tid}/compare", params={"a": 1, "b": 2}).json()
    hard = [(x["requirement_id"], x["before"]["status"], x["after"]["status"])
            for x in cmp["changed_items"] if x["hard_gate"]]
    assert hard == [("REQ-PQ-06", "meets", "gap")]
    assert {r["category"] for r in cmp["risk_changes"]} == {"performance_guarantee", "payment_terms",
                                                            "sla_penalty_cap"}

    decided = c.post(f"/tenders/{tid}/decision", json={"tender_version": 2, "action": "no_bid",
                                                       "comment": "ISO 27001 expires before the new deadline"},
                     headers=MANAGER)
    assert decided.status_code == 200 and decided.json()["approval_status"] == "rejected"
    assert c.get(f"/tenders/{tid}").json()["status"] == "no_bid_approved"
