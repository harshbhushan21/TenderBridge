"""Phase 8 review fixes in the runner: restart recovery, one resume per Gate 1 decision,
usage carried across the resume, unpriced LLM calls reported as unknown cost."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.agents import runner
from backend.app.agents.runner import _futures, recover_interrupted_runs, start_run
from backend.app.core.errors import ConflictError
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.llm.budget import estimate_cost, new_budget
from backend.app.services.tender_service import decide_gate1
from backend.scripts.run_demo_case import prepare_v1, wait_for_gate

DATA = Path(__file__).resolve().parents[3] / "demo_data"
TENDER = "TDR-RUNNER"
MANAGER = {"user_id": "bid.manager@nimbus.example", "role": "bid_manager"}


def test_restart_marks_orphaned_runs_failed_but_keeps_gate1_pauses():
    prepare_v1(TENDER, data_dir=DATA)
    with session_scope() as s:
        for run_id, status in (("RUN-ORPHAN", "running"), ("RUN-PAUSED", "awaiting_human")):
            s.add(m.AnalysisRun(run_id=run_id, tender_id=TENDER, version=1, thread_id=f"t-{run_id}",
                                status=status, mode="full_analysis", analysis_mode="focused"))
    assert "RUN-ORPHAN" in recover_interrupted_runs()
    with session_scope() as s:
        assert s.get(m.AnalysisRun, "RUN-ORPHAN").status == "failed"
        assert "restart" in s.get(m.AnalysisRun, "RUN-ORPHAN").error
        assert s.get(m.AnalysisRun, "RUN-PAUSED").status == "awaiting_human"
        s.delete(s.get(m.AnalysisRun, "RUN-PAUSED"))  # not a real paused graph


def test_second_concurrent_gate1_decision_is_refused(monkeypatch):
    prepare_v1(TENDER, data_dir=DATA)
    run = wait_for_gate(start_run(TENDER, version=1)["analysis_run_id"])
    assert run["status"] == "awaiting_human"
    resumes: list[str] = []
    monkeypatch.setattr(runner, "resume_run", lambda run_id, decision: resumes.append(run_id))

    decision = {"tender_version": 1, "action": "approve_bid"}
    with session_scope() as s:
        decide_gate1(s, TENDER, decision, **MANAGER)
    # A second request that read the run before the first committed still sees `awaiting_human`.
    stale = m.AnalysisRun(run_id=run["run_id"], tender_id=TENDER, version=1, status="awaiting_human")
    monkeypatch.setattr("backend.app.db.repositories.analysis.latest_run", lambda *a, **k: stale)
    with session_scope() as s, pytest.raises(ConflictError):
        decide_gate1(s, TENDER, decision, **MANAGER)
    assert resumes == [run["run_id"]]
    _futures.pop(run["run_id"], None)


def test_budget_resumes_from_previous_usage_and_counts_unpriced_calls():
    b = new_budget("RUN-X", usage={"calls": 3, "input_tokens": 100, "output_tokens": 40, "cost_usd": 0.5,
                                   "unpriced_calls": 1, "per_node": {"shred": {"calls": 3}}})
    b.record("write_sections", 10, 5, None)  # model without a configured price
    snap = b.snapshot()
    assert (snap["calls"], snap["input_tokens"], snap["unpriced_calls"], snap["cost_usd"]) == (4, 110, 2, 0.5)
    assert estimate_cost("groq:openai/gpt-oss-20b", 1000, 1000, {}) is None
    assert estimate_cost("groq:openai/gpt-oss-20b", 1_000_000, 0,
                         {"openai/gpt-oss-20b": {"input": 0.1, "output": 0.5}}) == pytest.approx(0.1)
