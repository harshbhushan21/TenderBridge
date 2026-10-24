"""Background analysis runner with durable run state and Gate 1 resume support."""
from __future__ import annotations

import socket
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from backend.app.agents.checkpoint import get_checkpointer
from backend.app.agents.graph import build_graph
from backend.app.agents.persistence import load_compliance, persist_state, thread_id_for, upsert_run
from backend.app.core.config import get_settings
from backend.app.db.engine import session_scope
from backend.app.db.repositories.amendments import confirmed_for_version
from backend.app.db.repositories.analysis import latest_run, run_to_dict
from backend.app.db.repositories.tenders import get_tender
from backend.app.ingestion.tender_ingest import load_effective_sections
from backend.app.llm.budget import bind_budget, new_budget
from backend.app.ops.audit import audit
from backend.app.ops.events import emit_event
from backend.app.ops.langsmith import configure_tracing, continue_trace, current_parent_headers, traceable

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tenderbridge-run")
RUNNER_HOST = socket.gethostname()  # several laptops may share one (cloud) database
_futures: dict[str, Future] = {}
_lock = threading.Lock()


def _thread_id(run_id: str) -> str:
    return thread_id_for(run_id)


def _track(run_id: str, future: Future) -> None:
    with _lock:
        _futures[run_id] = future

    def done(_: Future) -> None:
        from backend.app.llm.budget import release_budget
        with _lock:
            if _futures.get(run_id) is future:
                _futures.pop(run_id, None)
        release_budget(run_id)

    future.add_done_callback(done)


def is_active(run_id: str) -> bool:
    with _lock:
        future = _futures.get(run_id)
    return future is not None and not future.done()


def _trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """The graph state carries every section's text; the trace keeps what identifies the run."""
    state, resume = inputs.get("state") or {}, inputs.get("resume")
    return {"tender_id": state.get("tender_id"), "tender_version": state.get("tender_version"),
            "analysis_run_id": state.get("analysis_run_id"), "mode": state.get("mode"),
            "sections": len(state.get("sections") or []),
            "amendment_changes": len(state.get("amendment_changes") or []),
            "gate1_decision": {k: (resume or {}).get(k) for k in ("action", "tender_version", "comment")}
            if resume else None}


def _trace_outputs(result: dict[str, Any]) -> dict[str, Any]:
    assessment = result.get("assessment") or {}
    return {"run_status": result.get("run_status"), "score": assessment.get("score"),
            "recommendation": assessment.get("recommendation"),
            "hard_gate_failures": assessment.get("hard_gate_failures"),
            "requirements": len(result.get("requirements") or []),
            "compliance_items": len(result.get("compliance") or []), "usage": result.get("usage")}


@traceable(name="analysis_run", run_type="chain", process_inputs=_trace_inputs, process_outputs=_trace_outputs)
def _run_graph(state: dict[str, Any], resume: dict[str, Any] | None, budget: Any) -> dict[str, Any]:
    run_id = state["analysis_run_id"]
    meta = {"tender_id": state["tender_id"], "tender_version": state["tender_version"],
            "analysis_run_id": run_id, "mode": state.get("mode"), "thread_id": _thread_id(run_id)}
    compiled = build_graph(checkpointer=get_checkpointer())
    config: dict[str, Any] = {"configurable": {"thread_id": _thread_id(run_id)}, "metadata": meta,
                              "run_name": "tenderbridge_graph", "tags": ["tenderbridge", f"v{state['tender_version']}"]}
    if resume is not None:
        from langgraph.types import Command
        result = compiled.invoke(Command(resume=resume), config=config)
    else:
        result = compiled.invoke(state, config=config)
    checkpoint_state = compiled.get_state(config)
    if checkpoint_state and checkpoint_state.values:
        result = {**checkpoint_state.values, **result}
    result.pop("_session", None)
    result["usage"] = budget.snapshot()
    next_nodes = set(checkpoint_state.next if checkpoint_state else ())
    result["run_status"] = "awaiting_human" if (
        result.get("gate1_decision") is None
        or result.get("gate2_pending")
        or "gate2_review" in next_nodes
    ) else "completed"
    return result



def _execute(state: dict[str, Any], *, resume: dict[str, Any] | None = None,
             parent: dict[str, str] | None = None) -> None:
    # Tracing is configured by the caller (start_run/resume_run), never here: langsmith.configure
    # also sets a context variable, which would stick to this pooled worker thread.
    with continue_trace(parent):
        _execute_traced(state, resume=resume)


def _execute_traced(state: dict[str, Any], *, resume: dict[str, Any] | None = None) -> None:
    run_id = state["analysis_run_id"]
    budget = new_budget(run_id, usage=state.get("usage"))  # a resume continues the pre-Gate 1 totals
    token = bind_budget(budget)
    try:
        with session_scope() as session:
            upsert_run(session, state, status="running")
            audit("agent:runner", "analysis.started", tender_id=state["tender_id"],
                  version=state["tender_version"], run_id=run_id, session=session)
        emit_event(run_id=run_id, tender_id=state["tender_id"], version=state["tender_version"],
                   event="run_started", status="running")
        result = _run_graph(state, resume, budget, langsmith_extra={
            "name": "gate1_resume" if resume is not None else "analysis_run",
            "metadata": {"tender_id": state["tender_id"], "tender_version": state["tender_version"],
                         "analysis_run_id": run_id, "mode": state.get("mode"), "thread_id": _thread_id(run_id)},
            "tags": ["tenderbridge", "gate1" if resume is not None else "analysis"]})
        status = result["run_status"]
        with session_scope() as session:
            persist_state(session, result)
            audit("agent:runner", f"analysis.{status}", tender_id=state["tender_id"],
                  version=state["tender_version"], run_id=run_id, session=session)
        emit_event(run_id=run_id, tender_id=state["tender_id"], version=state["tender_version"],
                   event="run_completed", status=status,
                   payload={"assessment": result.get("assessment")})
    except Exception as exc:
        status = "cancelled" if budget.cancelled else "failed"
        with session_scope() as session:
            upsert_run(session, {**state, "usage": budget.snapshot()}, status=status, error=str(exc))
        emit_event(run_id=run_id, tender_id=state["tender_id"],
                   version=state["tender_version"], event="run_failed",
                   status=status, message=str(exc))
        raise
    finally:
        from backend.app.llm.budget import _current
        _current.reset(token)


def start_run(tender_id: str, *, version: int | None = None,
              analysis_mode: str | None = None, mode: str = "full_analysis",
              previous_run_id: str | None = None,
              scoring_factors: dict[str, float] | None = None,
              drafting_requested: bool = False,
              gate1_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    configure_tracing()  # idempotent; CLI entry points reach the runner without the API lifespan
    with session_scope() as session:
        tender = get_tender(session, tender_id)
        chosen_version = version or tender.current_version
        sections = load_effective_sections(session, tender_id, chosen_version)
        if not sections:
            raise ValueError("tender has no indexed sections")
        run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        # Every confirmed amendment up to this version applies, in any mode; impact mode
        # also gets the base version's results so unaffected checks can be reused.
        amendment_state: dict[str, Any] = {"amendment_changes": [
            change for a in confirmed_for_version(session, tender_id, chosen_version)
            for change in (a.diff or {}).get("changes", [])]}
        if mode == "impact" and chosen_version > 1:
            base = latest_run(session, tender_id, chosen_version - 1, completed_only=True)
            if base is not None:
                amendment_state["previous_compliance"] = load_compliance(
                    session, tender_id, chosen_version - 1, base.run_id)
                amendment_state["previous_version"] = chosen_version - 1
                previous_run_id = previous_run_id or base.run_id
        state: dict[str, Any] = {
            "tender_id": tender_id, "tender_version": chosen_version,
            "analysis_run_id": run_id, "company_id": get_settings().default_company_id,
            "mode": mode, "analysis_mode": analysis_mode or tender.analysis_mode,
            "previous_run_id": previous_run_id,
            "scoring_factors": scoring_factors or {},
            "drafting_requested": drafting_requested,
            "gate1_decision": gate1_decision,
            **amendment_state,
            "sections": [s.model_dump(mode="json") for s in sections],
            "flags": [], "raw_requirements": [], "requirements": [], "compliance": [],
            "risks": [], "errors": [], "runner_host": RUNNER_HOST,
        }
        upsert_run(session, state, status="queued")
    _track(run_id, _executor.submit(_execute, state, parent=current_parent_headers()))
    return {"analysis_run_id": run_id, "thread_id": _thread_id(run_id),
            "tender_version": chosen_version}


def resume_run(run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    from backend.app.db.models import AnalysisRun
    configure_tracing()
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run '{run_id}' not found")
        state = {"analysis_run_id": run_id, "tender_id": run.tender_id,
                 "tender_version": run.version, "gate1_decision": decision, "runner_host": RUNNER_HOST,
                 "usage": {k: v for k, v in (run.usage or {}).items() if k not in ("node_timings", "runner_host")}}
    _track(run_id, _executor.submit(_execute, state, resume=decision, parent=current_parent_headers()))
    return {"analysis_run_id": run_id, "status": "resuming"}


def cancel_run(run_id: str) -> bool:
    """Stop a queued or running analysis; False if it is not running in this process."""
    from backend.app.llm.budget import cancel_run as cancel_budget
    with _lock:
        future = _futures.get(run_id)
    if future is None or future.done():
        return False
    return future.cancel() or cancel_budget(run_id)


def recover_interrupted_runs() -> list[str]:
    """Runs left queued/running/resuming by a stopped server can never finish: mark them failed so
    the tender can be analysed again. Runs paused at Gate 1 are untouched (the checkpoint resumes
    them). Only runs started on this machine are touched: with a shared database, another
    laptop's live runs are not ours to fail (runs from before owners were recorded are)."""
    from sqlalchemy import select

    from backend.app.db.models import AnalysisRun
    recovered: list[str] = []
    with session_scope() as session:
        for run in session.scalars(select(AnalysisRun).where(
                AnalysisRun.status.in_(("queued", "running", "resuming")))):
            owner = (run.usage or {}).get("runner_host")
            if is_active(run.run_id) or (owner and owner != RUNNER_HOST):
                continue
            upsert_run(session, {"analysis_run_id": run.run_id, "tender_id": run.tender_id,
                                 "tender_version": run.version}, status="failed",
                       error="interrupted by a server restart; start the analysis again")
            recovered.append(run.run_id)
    return recovered


def get_run(run_id: str) -> dict[str, Any] | None:
    from backend.app.db.models import AnalysisRun
    with session_scope() as session:
        row = session.get(AnalysisRun, run_id)
        return run_to_dict(row) if row else None
