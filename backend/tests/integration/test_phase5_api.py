"""Phase 5: the full v1 lifecycle over HTTP (upload -> analyze -> Gate 1 -> exports).

Uses the real app, fake LLMs and the demo data. Gold files are read only to
check results.
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
GOLD = json.loads((DATA / "evaluation/eligibility_gold.json").read_text(encoding="utf-8"))["scenarios"]["S-v1"]
MANAGER = {"X-User": "bid.manager@nimbus.example", "X-Role": "bid_manager"}
ANALYST = {"X-User": "analyst@nimbus.example", "X-Role": "analyst"}


def _wait(client: TestClient, tender_id: str, run_id: str, statuses: set[str], timeout: float = 180) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        run = client.get(f"/tenders/{tender_id}/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.25)
    raise TimeoutError(f"run {run_id} never reached {statuses}")


@pytest.fixture(scope="module")
def client():
    with session_scope() as s:
        company = seed_company_facts(s, facts_dir=DATA / "structured_facts")["company_id"]
        ingest_company_kb(s, company, kb_dir=DATA / "company_kb", facts_dir=DATA / "structured_facts",
                          manifest_path=DATA / "demo_config/company_manifest.json")
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="module")
def tender(client):
    """A v1 tender uploaded through the API and analysed to the Gate 1 pause."""
    created = client.post("/tenders", json={"title": "DSDC O&M (API test)"}, headers=MANAGER)
    assert created.status_code == 201, created.text
    tender_id = created.json()["tenderId"]
    files = [("files", (name, (ORIGINAL / name).read_bytes())) for name in V1_FILES]
    up = client.post(f"/tenders/{tender_id}/files", files=files, headers=MANAGER)
    assert up.status_code == 200, up.text
    assert client.get(f"/tenders/{tender_id}/ingestion").json()["ready"]  # background processing done
    started = client.post(f"/tenders/{tender_id}/run", json={}, headers=MANAGER)
    assert started.status_code == 202, started.text
    run_id = started.json()["analysis_run_id"]
    _wait(client, tender_id, run_id, {"awaiting_human", "failed"})
    return {"id": tender_id, "run_id": run_id}


# --------------------------------------------------------------------------- basics
def test_health_ready_settings(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["ready"] is True and ready["db"]["ok"] is True
    assert client.get("/settings").json()["company_id"] == "NIMBUS-001"


def test_errors_use_contract_shape(client):
    r = client.get("/tenders/TDR-NOPE")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


def test_kb_routes_and_role_filter(client):
    status = client.get("/kb/status").json()
    assert status["documents"] == 52 and status["status"] == "ready"
    q = {"q": "standard position on uncapped liability"}
    as_analyst = client.get("/kb/search", params=q, headers=ANALYST).json()["items"]
    as_manager = client.get("/kb/search", params=q, headers=MANAGER).json()["items"]
    assert "KB-LEG-001" not in {i["doc_id"] for i in as_analyst}
    assert "KB-LEG-001" in {i["doc_id"] for i in as_manager}
    assert client.get("/kb/facts/risk_positions", headers=ANALYST).status_code == 403
    assert len(client.get("/kb/facts/financials", headers=MANAGER).json()["items"]) == 3


# --------------------------------------------------------------------------- upload rules
def test_corrigendum_rejected_on_original_pack(client):
    tid = client.post("/tenders", json={"title": "guard"}, headers=MANAGER).json()["tenderId"]
    r = client.post(f"/tenders/{tid}/files", files=[("files", ("corrigendum.pdf",
                                                               (ORIGINAL / "corrigendum.pdf").read_bytes()))],
                    headers=MANAGER)
    assert r.status_code == 400 and r.json()["error"] == "file_rejected"


def test_analyze_refused_before_ingestion_is_ready(client):
    tid = client.post("/tenders", json={"title": "empty"}, headers=MANAGER).json()["tenderId"]
    r = client.post(f"/tenders/{tid}/run", json={}, headers=MANAGER)
    assert r.status_code == 409 and r.json()["error"] == "invalid_state"


# --------------------------------------------------------------------------- v1 analysis
def test_tender_view_after_analysis(client, tender):
    view = client.get(f"/tenders/{tender['id']}").json()
    assert view["status"] == "awaiting_bid_decision" and view["analysisStatus"] == "awaiting_human"
    assert view["ingestionStatus"] == "ready_for_analysis" and view["approvalStatus"] == "pending"
    assert view["latestAssessment"]["score"] == pytest.approx(77.34, abs=0.01)
    assert view["submissionDeadline"].startswith("2026-11-06T15:00")


def test_assessment_and_results(client, tender):
    tid = tender["id"]
    a = client.get(f"/tenders/{tid}/assessment").json()
    assert a["score"] == pytest.approx(GOLD["bid_assessment"]["weighted_score"], abs=0.01)
    assert a["recommendation"] == "BID_WITH_CONDITIONS" and a["approval_status"] == "pending"
    gates = client.get(f"/tenders/{tid}/requirements", params={"hard_gate": True}).json()["items"]
    assert len(gates) == 13
    assert len(client.get(f"/tenders/{tid}/risks").json()["items"]) == 9
    compliance = client.get(f"/tenders/{tid}/compliance").json()["items"]
    assert {c["status"] for c in compliance if c["hard_gate"]} == {"meets", "meets_with_undertaking",
                                                                   "needs_action"}
    assert client.get(f"/tenders/{tid}/key-facts").json()["emd"]["amount_inr"] == 7_680_000


def test_evidence_viewer_page_text(client, tender):
    files = client.get(f"/tenders/{tender['id']}/ingestion").json()["files"]
    rfp = next(f for f in files if f["doc_role"] == "main_rfp")
    page = client.get(f"/tenders/{tender['id']}/files/{rfp['doc_id']}/pages/7").json()
    assert "Rs. 15.36 Crore" in page["text"]


def test_events_json_and_sse_replay(client, tender):
    tid, run_id = tender["id"], tender["run_id"]
    items = client.get(f"/tenders/{tid}/events", params={"run_id": run_id, "format": "json"}).json()["items"]
    kinds = [e["event"] for e in items]
    assert kinds[0] == "run_started" and "human_review_required" in kinds
    with client.stream("GET", f"/tenders/{tid}/events",
                       params={"run_id": run_id, "follow": False, "after_id": items[2]["id"]}) as r:
        body = r.read().decode()
    assert body.count("event: ") == len(items) - 3  # replays only events after `after_id`


# --------------------------------------------------------------------------- Gate 1
def test_gate1_analyst_refused_and_audited(client, tender):
    tid = tender["id"]
    r = client.post(f"/tenders/{tid}/decision", json={"tender_version": 1, "action": "approve_bid"},
                    headers=ANALYST)
    assert r.status_code == 403 and r.json()["error"] == "permission_denied"
    actions = [e["action"] for e in client.get(f"/tenders/{tid}/audit").json()["items"]]
    assert "gate1.denied" in actions


def test_gate1_wrong_version_conflicts(client, tender):
    r = client.post(f"/tenders/{tender['id']}/decision", json={"tender_version": 2, "action": "approve_bid"},
                    headers=MANAGER)
    assert r.status_code == 409


def test_gate1_approval_resumes_and_completes(client, tender):
    tid, run_id = tender["id"], tender["run_id"]
    r = client.post(f"/tenders/{tid}/decision", headers=MANAGER,
                    json={"tender_version": 1, "action": "approve_bid", "comment": "CEO approval obtained"})
    assert r.status_code == 200, r.text
    assert r.json()["approval_status"] == "approved"
    assert _wait(client, tid, run_id, {"completed", "failed"})["status"] == "completed"
    view = client.get(f"/tenders/{tid}").json()
    assert view["status"] == "bid_approved" and view["approvalStatus"] == "approved"
    audit = client.get(f"/tenders/{tid}/audit").json()["items"]
    entry = next(e for e in audit if e["action"] == "gate1.approve_bid")
    assert entry["actor"] == MANAGER["X-User"] and entry["version"] == 1


# --------------------------------------------------------------------------- exports and ops
def test_exports_download(client, tender):
    tid = tender["id"]
    xlsx = client.get(f"/tenders/{tid}/exports/compliance_xlsx", headers=MANAGER)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    ics = client.get(f"/tenders/{tid}/exports/dates_ics", headers=MANAGER)
    assert ics.status_code == 200 and b"BEGIN:VCALENDAR" in ics.content
    kinds = {e["kind"] for e in client.get(f"/tenders/{tid}/exports").json()["items"]}
    assert {"compliance_xlsx", "dates_ics"} <= kinds


def test_ops_metrics_and_runs(client, tender):
    metrics = client.get("/ops/metrics", params={"run_id": tender["run_id"]}).json()
    assert metrics["latency_ms_by_node"] and "bid_score" in metrics["latency_ms_by_node"]
    runs = client.get("/ops/runs", params={"tender_id": tender["id"]}).json()["items"]
    assert runs[0]["run_id"] == tender["run_id"]
