"""Generate versioned export files from persisted analysis results.

Writes under `storage/exports/<tender_id>/v<version>/` and records `ExportRow`s.
Never submits, uploads or emails anything (principle 10).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import AuditLog, ExportRow, ReviewRow, Tender, new_id
from backend.app.exports.audit_json import write_audit_json
from backend.app.exports.compliance_xlsx import write_compliance_xlsx, write_eligibility_xlsx
from backend.app.exports.dates_ics import write_dates_ics
from backend.app.exports.draft_docx import write_draft_docx, write_no_bid_docx
from backend.app.schemas.assessment import ApprovalStatus, BidAssessment, Recommendation, SectionDraft
from backend.app.schemas.eligibility import ComplianceItem, RiskItem
from backend.app.schemas.requirements import KeyFacts, Requirement

log = get_logger(__name__)
M = TypeVar("M", bound=BaseModel)

ALL_KINDS = ("compliance_xlsx", "eligibility_xlsx", "draft_docx", "dates_ics", "audit_json", "no_bid_docx")
FILENAMES = {
    "compliance_xlsx": "compliance_matrix.xlsx",
    "eligibility_xlsx": "eligibility_risk.xlsx",
    "draft_docx": "draft_response.docx",
    "dates_ics": "key_dates.ics",
    "audit_json": "audit.json",
    "no_bid_docx": "bid_no_bid_report.docx",
}
MEDIA_TYPES = {
    "compliance_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "eligibility_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "draft_docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "no_bid_docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "dates_ics": "text/calendar",
    "audit_json": "application/json",
}


def export_dir(tender_id: str, version: int) -> Path:
    d = get_settings().exports_dir / tender_id / f"v{version}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def export_path(tender_id: str, version: int, kind: str) -> Path:
    return export_dir(tender_id, version) / FILENAMES[kind]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _coerce(items: Any, model: type[M]) -> list[M]:
    out: list[M] = []
    for it in items or []:
        if isinstance(it, model):
            out.append(it)
        elif isinstance(it, BaseModel):
            out.append(model.model_validate(it.model_dump()))
        elif isinstance(it, dict):
            out.append(model.model_validate(it.get("data", it) if "data" in it and isinstance(it["data"], dict) else it))
        elif hasattr(it, "data") and isinstance(it.data, dict):
            out.append(model.model_validate(it.data))
    return out


def _coerce_one(item: Any, model: type[M]) -> M | None:
    res = _coerce([item] if item is not None else [], model)
    return res[0] if res else None


def _load(session: Session, tender_id: str, version: int, run_id: str | None) -> dict[str, Any]:
    data: dict[str, Any] = {"requirements": [], "compliance": [], "risks": [], "assessment": None,
                            "drafts": [], "key_facts": None}
    try:
        from backend.app.agents import persistence as p
        data["requirements"] = _coerce(p.load_requirements(session, tender_id, version, run_id), Requirement)
        data["compliance"] = _coerce(p.load_compliance(session, tender_id, version, run_id), ComplianceItem)
        data["risks"] = _coerce(p.load_risks(session, tender_id, version, run_id), RiskItem)
        data["assessment"] = _coerce_one(p.load_assessment(session, tender_id, version, run_id), BidAssessment)
        data["drafts"] = _coerce(p.load_drafts(session, tender_id, version, run_id), SectionDraft)
    except Exception as exc:  # loaders unavailable or no run yet
        log.warning("export: persistence loaders failed: %s", exc)
    try:
        from backend.app.tools.facts import get_key_facts
        data["key_facts"] = _coerce_one(get_key_facts(session, tender_id, version), KeyFacts)
    except Exception as exc:
        log.warning("export: key facts unavailable: %s", exc)
    return data


def _gate1(session: Session, tender_id: str, version: int) -> ReviewRow | None:
    return session.execute(
        select(ReviewRow).where(ReviewRow.tender_id == tender_id, ReviewRow.version == version,
                                ReviewRow.gate == "gate1").order_by(ReviewRow.id.desc())
    ).scalars().first()


def _audit_payload(session: Session, tender_id: str, version: int, data: dict[str, Any]) -> dict:
    rows = session.execute(
        select(AuditLog).where(AuditLog.tender_id == tender_id).order_by(AuditLog.id)
    ).scalars().all()
    reviews = session.execute(
        select(ReviewRow).where(ReviewRow.tender_id == tender_id).order_by(ReviewRow.id)
    ).scalars().all()
    a: BidAssessment | None = data["assessment"]
    return {
        "assessment": a.model_dump(mode="json") if a else None,
        "requirement_count": len(data["requirements"]),
        "compliance": [c.model_dump(mode="json") for c in data["compliance"]],
        "risks": [r.model_dump(mode="json") for r in data["risks"]],
        "key_facts": data["key_facts"].model_dump(mode="json") if data["key_facts"] else None,
        "reviews": [{"version": r.version, "gate": r.gate, "action": r.action, "status": r.status,
                     "reviewer": r.reviewer, "comment": r.comment, "target_id": r.target_id,
                     "created_at": r.created_at.isoformat() if r.created_at else None} for r in reviews],
        "audit_log": [{"ts": r.ts.isoformat() if r.ts else None, "actor": r.actor, "action": r.action,
                       "version": r.version, "run_id": r.run_id, "target": r.target, "detail": r.detail}
                      for r in rows],
    }


def export_outputs(session: Session, tender_id: str, version: int, run_id: str | None = None, *,
                   kinds: list[str] | tuple[str, ...] | None = None) -> list[dict]:
    """Write the requested exports; silently skip kinds whose preconditions are unmet."""
    kinds = list(kinds or ALL_KINDS)
    data = _load(session, tender_id, version, run_id)
    tender = session.get(Tender, tender_id)
    analysis_mode = (tender.analysis_mode if tender else None) or get_settings().analysis_mode
    a: BidAssessment | None = data["assessment"]
    run_id = run_id or (a.analysis_run_id if a else None)
    g1 = _gate1(session, tender_id, version)
    results: list[dict] = []

    for kind in kinds:
        if kind not in FILENAMES:
            continue
        path = export_path(tender_id, version, kind)
        try:
            if kind == "compliance_xlsx":
                if not data["requirements"]:
                    continue
                write_compliance_xlsx(path, tender_id=tender_id, version=version,
                                      requirements=data["requirements"], compliance=data["compliance"],
                                      risks=data["risks"], key_facts=data["key_facts"],
                                      analysis_mode=analysis_mode)
            elif kind == "eligibility_xlsx":
                if not data["compliance"]:
                    continue
                write_eligibility_xlsx(path, tender_id=tender_id, version=version,
                                       compliance=data["compliance"], risks=data["risks"],
                                       assessment=a, analysis_mode=analysis_mode)
            elif kind == "draft_docx":
                approved = [d for d in data["drafts"] if d.status == ApprovalStatus.approved]
                if not approved:
                    continue
                write_draft_docx(path, tender_id=tender_id, version=version, drafts=approved, assessment=a)
            elif kind == "dates_ics":
                if not data["key_facts"]:
                    continue
                write_dates_ics(path, data["key_facts"])
            elif kind == "audit_json":
                write_audit_json(path, tender_id=tender_id, version=version, run_id=run_id,
                                 payload=_audit_payload(session, tender_id, version, data))
            elif kind == "no_bid_docx":
                is_no_bid = (a is not None and a.recommendation == Recommendation.NO_BID) or \
                            (g1 is not None and g1.action == "no_bid")
                if not (a and is_no_bid):
                    continue
                report = {
                    "summary": a.narrative,
                    "reviewer": g1.reviewer if g1 else None,
                    "decision": g1.action if g1 else None,
                    "comment": g1.comment if g1 else None,
                    "risks": [r.summary for r in data["risks"] if getattr(r.level, "value", r.level) != "within_policy"],
                }
                write_no_bid_docx(path, assessment=a, report=report)
        except Exception as exc:
            log.exception("export %s failed: %s", kind, exc)
            results.append({"export_id": None, "kind": kind, "path": None, "error": str(exc)})
            continue

        row = ExportRow(export_id=new_id("EXP"), tender_id=tender_id, version=version, run_id=run_id,
                        kind=kind, path=str(path), sha256=_sha256(path))
        session.add(row)
        session.flush()
        results.append({"export_id": row.export_id, "kind": kind, "path": str(path),
                        "version": version, "sha256": row.sha256})
    return results


def latest_export(session: Session, tender_id: str, version: int, kind: str) -> ExportRow | None:
    return session.execute(
        select(ExportRow).where(ExportRow.tender_id == tender_id, ExportRow.version == version,
                                ExportRow.kind == kind).order_by(ExportRow.created_at.desc())
    ).scalars().first()
