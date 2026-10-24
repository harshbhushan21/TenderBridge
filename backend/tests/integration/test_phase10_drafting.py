"""Phase 10: cited drafting after Gate 1, verified claims, Gate 2 review and the draft DOCX.

Offline (fake models) the draft is extractive: sentences taken from approved KB passages, each
cited to its passage, so every claim must verify. Drafting runs on the persisted analysis.
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from docx import Document
from fastapi.testclient import TestClient

from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.ingestion.kb_ingest import ingest_company_kb
from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.main import create_app

DATA = Path(__file__).resolve().parents[3] / "demo_data"
ORIGINAL = DATA / "tender/TDR-001/original"
MANAGER = {"X-User": "bid.manager@nimbus.example", "X-Role": "bid_manager"}
ANALYST = {"X-User": "analyst@nimbus.example", "X-Role": "analyst"}
FILES = ("notice.pdf", "main_rfp.pdf", "annexures.pdf", "price_schedule_boq.xlsx")
ANALYSIS_NODES = {"shred_requirements", "eligibility_and_risk", "bid_score", "gate1_review"}


def _wait(c: TestClient, tid: str, run_id: str, statuses: set[str]) -> str:
    end = time.monotonic() + 180
    while time.monotonic() < end:
        status = c.get(f"/tenders/{tid}/runs/{run_id}").json()["status"]
        if status in statuses:
            return status
        time.sleep(0.2)
    raise TimeoutError(run_id)


def _new_tender(c: TestClient, title: str) -> tuple[str, str]:
    tid = c.post("/tenders", json={"title": title}, headers=MANAGER).json()["tenderId"]
    c.post(f"/tenders/{tid}/files", headers=MANAGER, files=[("files", (n, (ORIGINAL / n).read_bytes())) for n in FILES])
    run = c.post(f"/tenders/{tid}/run", json={}, headers=MANAGER).json()["analysis_run_id"]
    _wait(c, tid, run, {"awaiting_human"})
    return tid, run


def _draft_run(c: TestClient, tid: str) -> str:
    started = c.post(f"/tenders/{tid}/drafts", headers=MANAGER)
    assert started.status_code == 202, started.text
    run = started.json()["analysis_run_id"]
    assert _wait(c, tid, run, {"awaiting_human", "failed"}) == "awaiting_human"
    return run


@pytest.fixture(scope="module")
def client():
    with session_scope() as s:
        company = seed_company_facts(s, facts_dir=DATA / "structured_facts")["company_id"]
        ingest_company_kb(s, company, kb_dir=DATA / "company_kb", facts_dir=DATA / "structured_facts",
                          manifest_path=DATA / "demo_config/company_manifest.json")
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="module")
def approved(client):
    tid, run = _new_tender(client, "Drafting test")
    assert client.post(f"/tenders/{tid}/drafts", headers=MANAGER).status_code == 409  # Gate 1 still open
    client.post(f"/tenders/{tid}/decision", json={"tender_version": 1, "action": "approve_bid"}, headers=MANAGER)
    _wait(client, tid, run, {"completed"})
    return tid, run


def test_drafting_needs_an_approver(client, approved):
    tid, _ = approved
    assert client.post(f"/tenders/{tid}/drafts", headers=ANALYST).status_code == 403
    assert "drafting.denied" in [e["action"] for e in client.get(f"/tenders/{tid}/audit").json()["items"]]


def test_cited_draft_verified_waits_at_gate2_without_reanalysis(client, approved):
    tid, analysis_run = approved
    run = _draft_run(client, tid)
    assert client.post(f"/tenders/{tid}/drafts", headers=MANAGER).status_code == 409  # one draft at a time
    view = client.get(f"/tenders/{tid}").json()
    assert (view["status"], view["draftStatus"], view["latestRunId"]) == ("awaiting_draft_review", "awaiting_review",
                                                                         analysis_run)  # analysis results unchanged
    assert client.get(f"/tenders/{tid}/assessment").json()["score"] == pytest.approx(77.34, abs=0.01)
    with session_scope() as s:
        nodes = {e.node for e in s.query(m.RunEvent).filter_by(run_id=run, event="node_completed")}
    assert {"plan_response", "write_sections", "verify_claims"} <= nodes and not nodes & ANALYSIS_NODES

    body = client.get(f"/tenders/{tid}/drafts").json()
    assert body["run"]["status"] == "awaiting_human"
    draft = body["items"][0]
    assert draft["status"] == "pending" and draft["claims"] and "[1]" in draft["body_markdown"]
    assert all(c["citations"] and c["citations"][0]["doc_id"].startswith("KB-") for c in draft["claims"])
    report = draft["verifier"]
    assert report["passed"] and all(v["verdict"] in ("supported", "conditional") for v in report["verdicts"])
    assert draft["generated_by"].startswith("extractive")

    # Analysts may read the draft but not decide it; the refusal is audited.
    denied = client.post(f"/drafts/{draft['draft_id']}/review", json={"action": "approve"}, headers=ANALYST)
    assert denied.status_code == 403
    assert "gate2.denied" in [e["action"] for e in client.get(f"/tenders/{tid}/audit").json()["items"]]

    ok = client.post(f"/drafts/{draft['draft_id']}/review", json={"action": "approve", "comment": "Good"},
                     headers=MANAGER)
    assert ok.status_code == 200, ok.text
    again = client.post(f"/drafts/{draft['draft_id']}/review", json={"action": "approve"}, headers=MANAGER)
    assert again.status_code == 409  # one decision resumes the run
    assert _wait(client, tid, run, {"completed", "failed"}) == "completed"
    assert client.get(f"/tenders/{tid}/drafts").json()["items"][0]["status"] == "approved"
    assert client.get(f"/tenders/{tid}").json()["status"] == "bid_approved"

    docx = client.get(f"/tenders/{tid}/exports/draft_docx", headers=MANAGER)
    assert docx.status_code == 200
    text = "\n".join(p.text for p in Document(io.BytesIO(docx.content)).paragraphs)
    assert "Tender version: v1" in text and draft["claims"][0]["text"][:40] in text and "[1] KB-" in text


def test_request_changes_redrafts_then_edit_approves(client, approved):
    tid, _ = approved
    run = _draft_run(client, tid)
    first = client.get(f"/tenders/{tid}/drafts").json()["items"][0]
    client.post(f"/drafts/{first['draft_id']}/review", headers=MANAGER,
                json={"action": "request_changes", "comment": "Mention the DR drills"})
    assert _wait(client, tid, run, {"awaiting_human"}) == "awaiting_human"
    second = client.get(f"/tenders/{tid}/drafts").json()["items"][0]
    assert second["revision"] == first["revision"] + 1 and second["status"] == "pending"
    edited = "Nimbus will run the DSDC with an onsite 24x7 team."
    client.post(f"/drafts/{second['draft_id']}/review", headers=MANAGER,
                json={"action": "edit", "edited_markdown": edited})
    assert _wait(client, tid, run, {"completed"}) == "completed"
    final = client.get(f"/tenders/{tid}/drafts").json()["items"][0]
    assert final["status"] == "approved" and final["body_markdown"] == edited and final["human_edited"]


def test_no_bid_decision_writes_the_no_bid_report(client):
    from backend.app.agents.checkpoint import get_checkpointer
    from backend.app.agents.graph import build_graph

    tid, run = _new_tender(client, "No-bid route test")
    client.post(f"/tenders/{tid}/decision", json={"tender_version": 1, "action": "no_bid"}, headers=MANAGER)
    _wait(client, tid, run, {"completed"})
    with session_scope() as s:
        nodes = {e.node for e in s.query(m.RunEvent).filter_by(run_id=run, event="node_completed")}
    assert "write_no_bid_report" in nodes
    state = build_graph(checkpointer=get_checkpointer()).get_state(
        {"configurable": {"thread_id": f"tb-{run}"}}).values
    assert state["no_bid_report"]["version"] == 1
    assert client.post(f"/tenders/{tid}/drafts", headers=MANAGER).status_code == 409  # no bid, no draft
