"""Durable persistence for graph outputs and resumable analysis runs."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.db import models as m


def thread_id_for(run_id: str) -> str:
    """LangGraph checkpoint thread for a run (one place, so stored and used ids match)."""
    return f"tb-{run_id}"


def upsert_run(session: Session, state: dict[str, Any], *, status: str,
               error: str | None = None) -> m.AnalysisRun:
    run = session.get(m.AnalysisRun, state["analysis_run_id"])
    if run is None:
        run = m.AnalysisRun(
            run_id=state["analysis_run_id"], tender_id=state["tender_id"],
            version=state["tender_version"], thread_id=thread_id_for(state["analysis_run_id"]),
            mode=state.get("mode", "full_analysis"),
            analysis_mode=state.get("analysis_mode", "focused"),
            previous_run_id=state.get("previous_run_id"),
        )
        session.add(run)
    run.status = status
    run.current_node = state.get("current_node")
    run.error = error
    run.usage = {**(run.usage or {}), **(state.get("usage") or {}),
                 "node_timings": state.get("node_timings") or {}}
    if state.get("runner_host"):  # which machine's server executes it (see recover_interrupted_runs)
        run.usage["runner_host"] = state["runner_host"]
    if status in {"completed", "failed", "cancelled"}:
        from datetime import UTC, datetime
        run.finished_at = datetime.now(UTC)
    session.flush()
    return run


def persist_state(session: Session, state: dict[str, Any]) -> None:
    """Replace the run-owned result rows atomically and retain auditability."""
    run_id = state["analysis_run_id"]
    tender_id = state["tender_id"]
    version = state["tender_version"]
    upsert_run(session, state, status=state.get("run_status", "running"))

    session.execute(delete(m.RequirementRow).where(
        m.RequirementRow.tender_id == tender_id, m.RequirementRow.version == version))
    for item in state.get("requirements", []):
        session.add(m.RequirementRow(
            requirement_id=item["requirement_id"], tender_id=tender_id, version=version,
            analysis_run_id=run_id, clause_ref=item.get("clause_ref"),
            category=item.get("category", "other"), mandatory=item.get("mandatory", True),
            hard_gate=item.get("hard_gate", False), text=item.get("text", ""), data=item))

    session.execute(delete(m.ComplianceItemRow).where(m.ComplianceItemRow.run_id == run_id))
    for item in state.get("compliance", []):
        session.add(m.ComplianceItemRow(
            tender_id=tender_id, version=version, run_id=run_id,
            requirement_id=item["requirement_id"], status=item.get("status", "needs_human"),
            data=item))
    session.execute(delete(m.RiskItemRow).where(m.RiskItemRow.run_id == run_id))
    for item in state.get("risks", []):
        session.add(m.RiskItemRow(
            tender_id=tender_id, version=version, run_id=run_id,
            risk_id=item["risk_id"], level=item.get("level", "review"), data=item))

    if state.get("key_facts"):
        row = session.scalar(select(m.KeyFactsRow).where(
            m.KeyFactsRow.tender_id == tender_id, m.KeyFactsRow.version == version))
        if row is None:
            row = m.KeyFactsRow(tender_id=tender_id, version=version, data=state["key_facts"])
            session.add(row)
        else:
            row.data = state["key_facts"]

    assessment = state.get("assessment")
    if assessment:
        session.add(m.BidAssessmentRow(
            tender_id=tender_id, version=version, run_id=run_id,
            score=assessment.get("score", 0), recommendation=assessment.get("recommendation", "NO_BID"),
            data=assessment))


def persist_drafts(session: Session, state: dict[str, Any]) -> None:
    """A drafting run owns only its run row and its section drafts (the analysis rows are untouched)."""
    run_id = state["analysis_run_id"]
    upsert_run(session, state, status=state.get("run_status", "running"))
    session.execute(delete(m.SectionDraftRow).where(m.SectionDraftRow.run_id == run_id))
    reports = {r.get("draft_id"): r for r in state.get("verifier_reports", [])}
    for draft in state.get("drafts", []):
        session.add(m.SectionDraftRow(
            draft_id=draft["draft_id"], tender_id=state["tender_id"], version=state["tender_version"],
            run_id=run_id, section_key=draft["section_key"], status=draft.get("status", "pending"),
            stale=draft.get("stale", False), revision=draft.get("revision", 0), data=draft,
            verifier=reports.get(draft["draft_id"])))
    session.flush()


def _rows(session: Session, model: type[Any], tender_id: str, version: int,
          run_id: str | None) -> list[Any]:
    q = select(model).where(model.tender_id == tender_id, model.version == version)
    if run_id is not None and hasattr(model, "run_id"):
        q = q.where(model.run_id == run_id)
    return list(session.scalars(q.order_by(model.id)).all())


def load_requirements(session: Session, tender_id: str, version: int,
                      run_id: str | None = None) -> list[dict[str, Any]]:
    return [r.data for r in _rows(session, m.RequirementRow, tender_id, version, run_id)]


def load_compliance(session: Session, tender_id: str, version: int,
                    run_id: str | None = None) -> list[dict[str, Any]]:
    return [r.data for r in _rows(session, m.ComplianceItemRow, tender_id, version, run_id)]


def load_risks(session: Session, tender_id: str, version: int,
               run_id: str | None = None) -> list[dict[str, Any]]:
    return [r.data for r in _rows(session, m.RiskItemRow, tender_id, version, run_id)]


def load_assessment(session: Session, tender_id: str, version: int,
                    run_id: str | None = None) -> dict[str, Any] | None:
    rows = _rows(session, m.BidAssessmentRow, tender_id, version, run_id)
    return rows[-1].data if rows else None


def load_drafts(session: Session, tender_id: str, version: int,
                run_id: str | None = None) -> list[dict[str, Any]]:
    """Drafts of `run_id`, else of the latest drafting run for the version, with verifier report."""
    if run_id is None:
        from backend.app.db.repositories.analysis import latest_drafting_run
        run = latest_drafting_run(session, tender_id, version)
        if run is None:
            return []
        run_id = run.run_id
    q = select(m.SectionDraftRow).where(m.SectionDraftRow.tender_id == tender_id,
                                        m.SectionDraftRow.version == version,
                                        m.SectionDraftRow.run_id == run_id)
    return [{**r.data, "status": r.status, "stale": r.stale, "verifier": r.verifier, "run_id": r.run_id}
            for r in session.scalars(q.order_by(m.SectionDraftRow.created_at)).all()]
