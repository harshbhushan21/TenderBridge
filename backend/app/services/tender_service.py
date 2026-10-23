"""Tender workspace lifecycle (create, status). The API layer (Phase 5) builds on this."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.ops.audit import audit
from backend.app.ops.langsmith import traceable
from backend.app.schemas.documents import TenderStatus


def create_tender(session: Session, title: str, *, buyer: str | None = None,
                  reference_no: str | None = None, company_id: str | None = None,
                  analysis_mode: str | None = None, tender_id: str | None = None,
                  actor: str = "system") -> m.Tender:
    """Create a tender workspace with an effective version 1 (files arrive next)."""
    settings = get_settings()
    tender = m.Tender(tender_id=tender_id or m.new_id("TDR"), title=title, buyer=buyer,
                      reference_no=reference_no, company_id=company_id or settings.default_company_id,
                      status=TenderStatus.created.value, current_version=1,
                      analysis_mode=analysis_mode or settings.analysis_mode, created_by=actor)
    session.add(tender)
    session.add(m.TenderVersion(tender_id=tender.tender_id, version=1, status="effective",
                                confirmed_by=actor, note="original tender pack"))
    session.flush()
    audit(actor, "tender.created", tender_id=tender.tender_id, version=1, session=session,
          title=title, reference_no=reference_no)
    return tender


# --------------------------------------------------------------------------- views
def _latest_gate1(session: Session, tender_id: str, version: int) -> m.ReviewRow | None:
    from backend.app.db.repositories.analysis import gate1_reviews
    rows = gate1_reviews(session, tender_id, version)
    return rows[0] if rows else None


def tender_view(session: Session, tender: m.Tender) -> dict:
    """camelCase TenderView (docs/api_contract.md), derived from files, runs and reviews."""
    from backend.app.db.repositories.analysis import latest_assessment_row, latest_run
    from backend.app.ingestion.upload_service import tender_ingestion_status
    from backend.app.tools.facts import get_key_facts

    version = tender.current_version
    ingest = tender_ingestion_status(session, tender.tender_id, version)
    files = ingest["files"]
    ingestion_status = ("ready_for_analysis" if ingest["ready"] else
                        "failed" if files and all(f["status"] == "failed" for f in files) else "ingesting")
    run = latest_run(session, tender.tender_id, version)
    analysis_status = "not_started"
    if run is not None:
        analysis_status = {"queued": "running", "running": "running", "awaiting_human": "awaiting_human",
                           "completed": "completed", "failed": "failed", "cancelled": "failed"}.get(
                               run.status, "running")
    assessment = latest_assessment_row(session, tender.tender_id, version)
    review = _latest_gate1(session, tender.tender_id, version)
    approval = review.status if review is not None else "pending"
    status = tender.status
    if run is not None and tender.status not in ("bid_approved", "no_bid_approved", "amendment_pending",
                                                 "reanalysis_required"):
        status = {"running": "analyzing", "awaiting_human": "awaiting_bid_decision",
                  "failed": "failed"}.get(analysis_status, status)
    key_facts = get_key_facts(session, tender.tender_id, version)
    return {
        "tenderId": tender.tender_id, "title": tender.title, "buyer": tender.buyer,
        "referenceNo": tender.reference_no, "status": status, "currentVersion": version,
        "analysisMode": tender.analysis_mode, "ingestionStatus": ingestion_status,
        "analysisStatus": analysis_status, "latestRunId": run.run_id if run else None,
        "latestAssessment": {
            "version": assessment.version, "recommendation": assessment.recommendation,
            "score": assessment.score,
            "hardGateFailures": (assessment.data or {}).get("hard_gate_failures", []),
        } if assessment is not None else None,
        "approvalStatus": approval,
        "amendmentPending": tender.status == "amendment_pending",
        "submissionDeadline": key_facts.submission_deadline.isoformat()
        if key_facts and key_facts.submission_deadline else None,
        "createdAt": tender.created_at.isoformat() if tender.created_at else None,
    }


# --------------------------------------------------------------------------- analysis
def start_analysis(session: Session, tender_id: str, *, version: int | None = None,
                   analysis_mode: str | None = None, actor: str = "system",
                   mode: str = "full_analysis") -> dict:
    """Start the graph for a tender version. Upload != analyze: only when ingestion is ready."""
    from backend.app.agents.runner import start_run
    from backend.app.core.errors import ConflictError, InvalidStateError
    from backend.app.db.repositories.analysis import latest_run
    from backend.app.ingestion.upload_service import tender_ingestion_status

    tender = session.get(m.Tender, tender_id)
    if tender is None:
        from backend.app.core.errors import NotFoundError
        raise NotFoundError(f"tender '{tender_id}' not found")
    version = version or tender.current_version
    if version != tender.current_version:
        raise ConflictError("analysis runs only on the current tender version",
                            details={"requested": version, "current": tender.current_version})
    if not tender_ingestion_status(session, tender_id, version)["ready"]:
        raise InvalidStateError("tender is not ready for analysis: wait for every file to be indexed",
                                details={"status": tender.status})
    active = latest_run(session, tender_id, version)
    if active is not None and active.status in ("queued", "running", "resuming"):
        raise ConflictError("an analysis is already running for this version",
                            details={"run_id": active.run_id})
    tender.status = TenderStatus.analyzing.value
    session.commit()  # the runner writes from its own thread/session
    result = start_run(tender_id, version=version, analysis_mode=analysis_mode or tender.analysis_mode, mode=mode)
    audit(actor, "analysis.requested", tender_id=tender_id, version=version,
          run_id=result["analysis_run_id"], mode=mode)
    return result


@traceable(name="gate1_decision", run_type="chain")
def decide_gate1(session: Session, tender_id: str, decision: dict, *, user_id: str, role: str) -> dict:
    """Record a version-bound Gate 1 decision and resume the paused run.

    Only bid_manager/admin may decide; a refused attempt is audited in its own
    transaction so the record survives the request's rollback.
    """
    from backend.app.agents.runner import resume_run
    from backend.app.core.errors import ConflictError, InvalidStateError, NotFoundError
    from backend.app.core.security import APPROVER_ROLES, CurrentUser
    from backend.app.db.repositories.analysis import latest_run
    from backend.app.schemas.assessment import GateDecision

    tender = session.get(m.Tender, tender_id)
    if tender is None:
        raise NotFoundError(f"tender '{tender_id}' not found")
    gate = GateDecision.model_validate({**decision, "reviewer": user_id})
    user = CurrentUser(user_id=user_id, role=role)
    if role not in APPROVER_ROLES:
        audit(user_id, "gate1.denied", tender_id=tender_id, version=gate.tender_version,
              role=role, requested_action=gate.action)
        user.require_approver()  # raises PermissionDenied (403)
    if gate.tender_version != tender.current_version:
        raise ConflictError("decision is for a superseded tender version",
                            details={"decision_version": gate.tender_version, "current": tender.current_version})
    run = latest_run(session, tender_id, gate.tender_version)
    if run is None or run.status != "awaiting_human":
        raise InvalidStateError("no analysis is waiting for a Gate 1 decision",
                                details={"run_status": run.status if run else None})
    status = {"approve_bid": "approved", "no_bid": "rejected", "defer": "pending"}[gate.action]
    if gate.action != "defer":
        # Claim the paused run atomically: of two near-simultaneous decisions only one resumes it.
        from sqlalchemy import update
        result: Any = session.execute(update(m.AnalysisRun).where(
            m.AnalysisRun.run_id == run.run_id, m.AnalysisRun.status == "awaiting_human")
            .values(status="resuming"))
        claimed = result.rowcount
        if claimed != 1:
            raise ConflictError("this Gate 1 decision was already recorded", details={"run_id": run.run_id})
    session.add(m.ReviewRow(tender_id=tender_id, version=gate.tender_version, run_id=run.run_id, gate="gate1",
                            action=gate.action, status=status, reviewer=user_id, comment=gate.comment,
                            data=gate.model_dump(mode="json")))
    if gate.action == "approve_bid":
        tender.status = TenderStatus.bid_approved.value
    elif gate.action == "no_bid":
        tender.status = TenderStatus.no_bid_approved.value
    audit(user_id, f"gate1.{gate.action}", tender_id=tender_id, version=gate.tender_version,
          run_id=run.run_id, session=session, comment=gate.comment, role=role)
    session.commit()
    if gate.action != "defer":  # a deferral keeps the run paused at Gate 1
        resume_run(run.run_id, gate.model_dump(mode="json"))
    return {"status": "resuming" if gate.action != "defer" else "deferred", "approval_status": status,
            "run_id": run.run_id}
