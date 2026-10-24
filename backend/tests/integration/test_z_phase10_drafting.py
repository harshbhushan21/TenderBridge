"""Phase 10: cited drafting pauses at and resumes through Gate 2."""
from __future__ import annotations

from pathlib import Path

from backend.app.agents.runner import _futures, get_run, resume_run, start_run
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.db.repositories.analysis import latest_run
from backend.app.schemas.assessment import GateDecision
from backend.app.services.tender_service import start_drafting
from backend.scripts.run_demo_case import prepare_v1, wait_for_gate

DATA = Path(__file__).resolve().parents[3] / "demo_data"
TENDER = "TDR-010"


def test_cited_draft_waits_at_gate2_and_resumes():
    prepare_v1(TENDER, data_dir=DATA)
    first = start_run(TENDER, version=1, analysis_mode="focused")
    gate1 = wait_for_gate(first["analysis_run_id"])
    assert gate1["status"] == "awaiting_human"

    with session_scope() as session:
        decision = GateDecision(
            tender_version=1, action="approve_bid", reviewer="bid.manager@nimbus.example"
        )
        from backend.app.services.tender_service import decide_gate1
        decide_gate1(
            session, TENDER, decision.model_dump(mode="json"),
            user_id=decision.reviewer, role="bid_manager",
        )
    _futures[first["analysis_run_id"]].result(timeout=120)

    with session_scope() as session:
        started = start_drafting(session, TENDER, actor="bid.manager@nimbus.example",
                                 role="bid_manager")
    gate2 = wait_for_gate(started["analysis_run_id"])
    assert gate2["status"] == "awaiting_human", gate2
    with session_scope() as session:
        run = latest_run(session, TENDER, 1)
        assert run is not None
        drafts = session.query(m.SectionDraftRow).filter_by(run_id=run.run_id).all()
    assert drafts
    if drafts[0].data["claims"]:
        assert drafts[0].data["claims"][0]["citations"]

    resume_run(started["analysis_run_id"], {
        "section_key": drafts[0].section_key, "action": "approve",
        "reviewer": "bid.manager@nimbus.example",
    })
    _futures[started["analysis_run_id"]].result(timeout=120)
    assert get_run(started["analysis_run_id"])["status"] == "completed"
