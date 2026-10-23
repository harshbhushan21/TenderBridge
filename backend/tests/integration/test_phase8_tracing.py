"""Phase 8: LangSmith instrumentation, trace hierarchy and redaction, without a LangSmith account.

A recording client replaces the network calls of the real `langsmith.Client` (`_create_run`,
`_update_run`), so the payloads checked here are exactly what would be sent, after the
client-level redaction.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import langsmith as ls
import pytest
from langchain_core.tracers.langchain import wait_for_all_tracers

from backend.app.agents.runner import _futures, resume_run, start_run
from backend.app.ops import langsmith as tracing
from backend.app.schemas.documents import RetrievedChunk, Scope
from backend.scripts.run_demo_case import prepare_v1, wait_for_gate

DATA = Path(__file__).resolve().parents[3] / "demo_data"
TENDER = "TDR-TRACE"
REVIEWER = "reviewer.person@nimbus.example"


class RecordingClient(ls.Client):
    def __init__(self) -> None:
        super().__init__(api_key="lsv2_test_not_a_real_key_0000", api_url="http://127.0.0.1:9",
                         auto_batch_tracing=False, hide_inputs=tracing.redact_for_trace,
                         hide_outputs=tracing.redact_for_trace, hide_metadata=tracing.redact_for_trace)
        self.recorded: dict[str, dict[str, Any]] = {}
        self._rec_lock = threading.Lock()

    def _create_run(self, run_create: dict, **_: Any) -> None:  # type: ignore[override]
        with self._rec_lock:
            self.recorded.setdefault(str(run_create["id"]), {}).update(run_create)

    def _update_run(self, run_update: dict, **_: Any) -> None:  # type: ignore[override]
        with self._rec_lock:
            self.recorded.setdefault(str(run_update["id"]), {}).update(
                {k: v for k, v in run_update.items() if v is not None})


@pytest.fixture
def recorder():
    client = RecordingClient()
    ls.configure(client=client, enabled=True, project_name="tenderbridge-test")
    tracing._configured = True
    try:
        yield client
    finally:
        ls.configure(enabled=False)
        tracing._configured = None


def _named(client: RecordingClient, name: str) -> list[dict[str, Any]]:
    return [r for r in client.recorded.values() if r.get("name") == name]


def _ancestry(client: RecordingClient, run: dict[str, Any]) -> list[str]:
    names, parent = [], run.get("parent_run_id")
    while parent:
        node = client.recorded[str(parent)]
        names.append(node["name"])
        parent = node.get("parent_run_id")
    return names


def _metadata(run: dict[str, Any]) -> dict[str, Any]:
    return (run.get("extra") or {}).get("metadata") or {}


@pytest.fixture(scope="module")
def tender_ready():
    prepare_v1(TENDER, data_dir=DATA)


# --------------------------------------------------------------------------- redaction
def test_redact_masks_pii_secrets_and_handles():
    out = tracing.redact_for_trace({
        "email": "a.person@example.com", "text": "Call +91 9876543210, PAN ABCDE1234F",
        "groq": "gsk_" + "a" * 40, "hf": "hf_" + "b" * 30, "api_key": "anything", "session": object(),
        "input_tokens": 12, "long": "x" * (tracing.MAX_TRACE_TEXT + 50),
    })
    flat = json.dumps(out)
    for leaked in ("a.person@example.com", "9876543210", "ABCDE1234F", "gsk_aaaa", "hf_bbbb", "anything"):
        assert leaked not in flat
    assert "session" not in out and out["input_tokens"] == 12  # token counts are not secrets
    assert out["long"].endswith("chars truncated]")


def test_retriever_output_withholds_restricted_kb_text():
    open_chunk = RetrievedChunk(chunk_id="a", doc_id="KB-1", text="public text", score=1.0, scope=Scope.kb,
                                page=1, metadata={"allowed_roles": ["all"]})
    secret = RetrievedChunk(chunk_id="b", doc_id="KB-LEG-001", text="walk-away liability position",
                            score=0.5, scope=Scope.kb, page=2, metadata={"allowed_roles": ["bid_manager"]})
    docs = tracing.retrieval_outputs([open_chunk, secret])["documents"]
    assert docs[0]["page_content"] == "public text"
    assert "walk-away" not in docs[1]["page_content"] and docs[1]["page_content"].startswith("[RESTRICTED")


def test_tracing_stays_off_without_a_key(monkeypatch):
    from backend.app.core.config import get_settings
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    get_settings.cache_clear()
    tracing._configured = None
    try:
        settings = get_settings()
        if settings.langsmith_api_key or settings.langchain_api_key:
            pytest.skip("a LangSmith key is configured in .env on this machine")
        assert tracing.configure_tracing() is False
    finally:
        get_settings.cache_clear()
        tracing._configured = None
        ls.configure(enabled=False)


# --------------------------------------------------------------------------- hierarchy
def test_analysis_and_gate1_resume_trace_tree(recorder, tender_ready):
    @tracing.traceable(name="caller")
    def caller() -> dict[str, Any]:
        return start_run(TENDER, version=1)

    started = caller()  # the run executes in a worker thread; its trace must stay under `caller`
    run = wait_for_gate(started["analysis_run_id"])
    assert run["status"] == "awaiting_human"
    resume_run(run["run_id"], {"tender_version": 1, "action": "approve_bid", "reviewer": REVIEWER,
                               "comment": f"approved, contact {REVIEWER}"})
    _futures[run["run_id"]].result(timeout=120)
    wait_for_all_tracers()

    analysis = _named(recorder, "analysis_run")
    resume = _named(recorder, "gate1_resume")
    assert len(analysis) == 1 and len(resume) == 1
    assert _ancestry(recorder, analysis[0]) == ["caller"]  # parent survives the thread hop
    assert _metadata(analysis[0])["thread_id"] == _metadata(resume[0])["thread_id"]  # one LangSmith thread
    assert _metadata(analysis[0])["tender_id"] == TENDER

    # graph -> node -> tool / retriever, all inside the analysis
    for name, parents in {"tenderbridge_graph": ["analysis_run"],
                          "eligibility_and_risk": ["tenderbridge_graph", "analysis_run"],
                          "score_bid": ["bid_score", "tenderbridge_graph", "analysis_run"],
                          "check_turnover": ["evaluate_pq", "eligibility_and_risk"]}.items():
        runs = _named(recorder, name)
        assert runs, name
        assert _ancestry(recorder, runs[0])[:len(parents)] == parents, name
    retrievers = [r for r in recorder.recorded.values() if r.get("run_type") == "retriever"]
    assert retrievers and all("eligibility_and_risk" in _ancestry(recorder, r) for r in retrievers)
    assert "documents" in retrievers[0]["outputs"]

    # outputs summarise the run instead of shipping the whole state
    assert analysis[0]["outputs"]["recommendation"] == "BID_WITH_CONDITIONS"
    assert analysis[0]["inputs"]["sections"] > 0 and "text" not in json.dumps(analysis[0]["inputs"])
    assert resume[0]["outputs"]["run_status"] == "completed"
    assert resume[0]["inputs"]["gate1_decision"]["action"] == "approve_bid"

    # nothing personal or secret left the process
    payload = json.dumps(list(recorder.recorded.values()), default=str)
    assert REVIEWER not in payload and "lsv2_test_not_a_real_key" not in payload


def test_no_runs_recorded_when_tracing_disabled(tender_ready):
    client = RecordingClient()
    ls.configure(client=client, enabled=False)
    tracing._configured = None
    try:
        run = wait_for_gate(start_run(TENDER, version=1)["analysis_run_id"])
        assert run["status"] == "awaiting_human"
        wait_for_all_tracers()
        assert client.recorded == {}
    finally:
        ls.configure(enabled=False)
        tracing._configured = None
