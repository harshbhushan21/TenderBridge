"""Background analysis runner with durable run state and Gate 1 resume support."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from backend.app.agents.checkpoint import get_checkpointer
from backend.app.agents.graph import build_graph
from backend.app.agents.persistence import persist_state, upsert_run
from backend.app.core.config import get_settings
from backend.app.db.engine import session_scope
from backend.app.db.repositories.analysis import run_to_dict
from backend.app.db.repositories.tenders import get_tender
from backend.app.ingestion.tender_ingest import load_effective_sections
from backend.app.llm.budget import bind_budget, new_budget
from backend.app.ops.audit import audit
from backend.app.ops.events import emit_event

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tenderbridge-run")
_futures: dict[str, Future] = {}
_lock = threading.Lock()


def _thread_id(run_id: str) -> str:
    return f"tb-{run_id}"


def _execute(state: dict[str, Any], *, resume: dict[str, Any] | None = None) -> None:
    run_id = state["analysis_run_id"]
    budget = new_budget(run_id)
    token = bind_budget(budget)
    try:
        with session_scope() as session:
            upsert_run(session, state, status="running")
            audit("agent:runner", "analysis.started", tender_id=state["tender_id"],
                  version=state["tender_version"], run_id=run_id, session=session)
        emit_event(run_id=run_id, tender_id=state["tender_id"], version=state["tender_version"],
                   event="run_started", status="running")
        with session_scope() as session:
            compiled = build_graph(checkpointer=get_checkpointer())
            config = {"configurable": {"thread_id": _thread_id(run_id)}}
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
            status = "awaiting_human" if result.get("gate1_decision") is None else "completed"
            result["run_status"] = status
            persist_state(session, result)
            audit("agent:runner", f"analysis.{status}", tender_id=state["tender_id"],
                  version=state["tender_version"], run_id=run_id, session=session)
        emit_event(run_id=run_id, tender_id=state["tender_id"], version=state["tender_version"],
                   event="run_completed", status=status,
                   payload={"assessment": result.get("assessment")})
    except Exception as exc:
        with session_scope() as session:
            upsert_run(session, state, status="failed", error=str(exc))
        emit_event(run_id=run_id, tender_id=state["tender_id"],
                   version=state["tender_version"], event="run_failed",
                   status="failed", message=str(exc))
        raise
    finally:
        from backend.app.llm.budget import _current
        _current.reset(token)


def start_run(tender_id: str, *, version: int | None = None,
              analysis_mode: str | None = None, mode: str = "full_analysis") -> dict[str, Any]:
    with session_scope() as session:
        tender = get_tender(session, tender_id)
        chosen_version = version or tender.current_version
        sections = load_effective_sections(session, tender_id, chosen_version)
        if not sections:
            raise ValueError("tender has no indexed sections")
        run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        state: dict[str, Any] = {
            "tender_id": tender_id, "tender_version": chosen_version,
            "analysis_run_id": run_id, "company_id": get_settings().default_company_id,
            "mode": mode, "analysis_mode": analysis_mode or tender.analysis_mode,
            "sections": [s.model_dump(mode="json") for s in sections],
            "flags": [], "raw_requirements": [], "requirements": [], "compliance": [],
            "risks": [], "errors": [],
        }
        upsert_run(session, state, status="queued")
    future = _executor.submit(_execute, state)
    with _lock:
        _futures[run_id] = future
    return {"analysis_run_id": run_id, "thread_id": _thread_id(run_id),
            "tender_version": chosen_version}


def resume_run(run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
    from backend.app.db.models import AnalysisRun
    with session_scope() as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise ValueError(f"analysis run '{run_id}' not found")
        state = {"analysis_run_id": run_id, "tender_id": run.tender_id,
                 "tender_version": run.version, "gate1_decision": decision}
    future = _executor.submit(_execute, state, resume=decision)
    with _lock:
        _futures[run_id] = future
    return {"analysis_run_id": run_id, "status": "resuming"}


def cancel_run(run_id: str) -> bool:
    from backend.app.llm.budget import cancel_run as cancel_budget
    future = _futures.get(run_id)
    return cancel_budget(run_id) or (future.cancel() if future is not None else False)


def get_run(run_id: str) -> dict[str, Any] | None:
    from backend.app.db.models import AnalysisRun
    with session_scope() as session:
        row = session.get(AnalysisRun, run_id)
        return run_to_dict(row) if row else None
