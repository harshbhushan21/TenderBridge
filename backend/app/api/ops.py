"""AgentOps routes: run metrics, guardrail events, runs, cancellation."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.runner import cancel_run
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.db import models as m
from backend.app.db.engine import db_dependency
from backend.app.db.repositories.analysis import list_runs, run_to_dict
from backend.app.ops.audit import audit
from backend.app.ops.metrics import guardrail_to_dict, run_metrics

router = APIRouter(prefix="/ops", tags=["agentops"])


@router.get("/metrics")
def metrics(run_id: str | None = None, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    return run_metrics(session, run_id)


@router.get("/guardrails")
def guardrails(tender_id: str | None = None, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    q = select(m.GuardrailEvent)
    if tender_id:
        q = q.where(m.GuardrailEvent.tender_id == tender_id)
    return {"items": [guardrail_to_dict(r) for r in session.scalars(q.order_by(m.GuardrailEvent.id.desc())
                                                                      .limit(500))]}


@router.get("/runs")
def runs(tender_id: str | None = None, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    return {"items": [run_to_dict(r) for r in list_runs(session, tender_id)]}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, user: CurrentUser = Depends(get_current_user)) -> dict[str, bool]:
    user.require_approver()
    cancelled = cancel_run(run_id)
    audit(user.user_id, "run.cancel", run_id=run_id, cancelled=cancelled)
    return {"cancelled": cancelled}
