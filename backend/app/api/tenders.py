"""Tender lifecycle routes for v1: create, upload, ingest, analyze, events, results, Gate 1.

Amendment/version routes are added in Phase 7, draft routes in Phase 11.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from backend.app.agents.persistence import load_assessment, load_compliance, load_requirements, load_risks
from backend.app.agents.runner import get_run
from backend.app.core.errors import FileRejected, NotFoundError
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.db import models as m
from backend.app.db.engine import db_dependency, session_scope
from backend.app.db.repositories.analysis import latest_run
from backend.app.db.repositories.tenders import get_file, get_tender, list_tenders
from backend.app.ingestion.upload_service import (
    process_pending_files,
    save_tender_upload,
    tender_ingestion_status,
)
from backend.app.ops.audit import list_audit
from backend.app.ops.events import list_events, open_subscription
from backend.app.schemas.documents import ParsedDocument
from backend.app.services.tender_service import create_tender, decide_gate1, start_analysis, tender_view
from backend.app.tools.facts import get_key_facts

router = APIRouter(prefix="/tenders", tags=["tenders"])
KEEPALIVE_S = 15


class TenderCreate(BaseModel):
    title: str
    buyer: str | None = None
    reference_no: str | None = None
    analysis_mode: str | None = None


class RunRequest(BaseModel):
    version: int | None = None
    analysis_mode: str | None = None


def _version(session: Session, tender_id: str, version: int | None) -> int:
    return version or get_tender(session, tender_id).current_version


def _result_run_id(session: Session, tender_id: str, version: int) -> str | None:
    run = latest_run(session, tender_id, version, completed_only=True)
    return run.run_id if run else None


# --------------------------------------------------------------------------- workspace
@router.post("", status_code=201)
def create(body: TenderCreate, session: Session = Depends(db_dependency),
           user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    tender = create_tender(session, body.title, buyer=body.buyer, reference_no=body.reference_no,
                           analysis_mode=body.analysis_mode, actor=user.user_id)
    return tender_view(session, tender)


@router.get("")
def list_all(session: Session = Depends(db_dependency)) -> dict[str, Any]:
    return {"items": [tender_view(session, t) for t in list_tenders(session)]}


@router.get("/{tender_id}")
def get_one(tender_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    return tender_view(session, get_tender(session, tender_id))


# --------------------------------------------------------------------------- files
@router.post("/{tender_id}/files")
async def upload(tender_id: str, background: BackgroundTasks, files: list[UploadFile] = File(...),
                 doc_role: str | None = Form(None), session: Session = Depends(db_dependency),
                 user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Original tender pack only. A corrigendum goes through the amendments route (Phase 7)."""
    get_tender(session, tender_id)
    accepted, rejected = [], []
    for upload_file in files:
        data = await upload_file.read()
        name = upload_file.filename or "upload"
        try:
            tf = save_tender_upload(session, tender_id, name, data, doc_role=doc_role, actor=user.user_id)
            accepted.append({"doc_id": tf.doc_id, "filename": tf.filename, "doc_role": tf.doc_role,
                             "status": tf.status})
        except FileRejected as exc:
            rejected.append({"filename": name, "error": exc.message, "details": exc.details})
    if not accepted:
        raise FileRejected("no file was accepted", details={"rejected": rejected})
    session.commit()  # processing runs after the response, in its own sessions
    background.add_task(process_pending_files, tender_id)
    return {"files": accepted, "rejected": rejected}


@router.get("/{tender_id}/ingestion")
def ingestion(tender_id: str, version: int | None = None, session: Session = Depends(db_dependency)
              ) -> dict[str, Any]:
    get_tender(session, tender_id)
    return tender_ingestion_status(session, tender_id, version)


@router.get("/{tender_id}/files/{doc_id}/pages/{page}")
def page_text(tender_id: str, doc_id: str, page: int, session: Session = Depends(db_dependency)
              ) -> dict[str, Any]:
    """Evidence viewer: the parsed text of one page (hidden spans already removed)."""
    tf = get_file(session, tender_id, doc_id)
    if not tf.parsed_path or not Path(tf.parsed_path).exists():
        raise NotFoundError("file has not been parsed yet")
    parsed = ParsedDocument.model_validate_json(Path(tf.parsed_path).read_text(encoding="utf-8"))
    match = next((p for p in parsed.pages if p.page == page), None)
    if match is None:
        raise NotFoundError(f"page {page} not found", details={"pages": len(parsed.pages)})
    return {"doc_id": doc_id, "page": page, "text": match.text, "ocr": match.ocr, "flags": tf.flags or []}


@router.get("/{tender_id}/files/{doc_id}/download")
def download(tender_id: str, doc_id: str, session: Session = Depends(db_dependency)) -> FileResponse:
    tf = get_file(session, tender_id, doc_id)
    return FileResponse(tf.storage_path, filename=tf.filename, media_type=tf.mime_type or None)


# --------------------------------------------------------------------------- analysis
@router.post("/{tender_id}/run", status_code=202)
def run(tender_id: str, body: RunRequest | None = None, session: Session = Depends(db_dependency),
        user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    body = body or RunRequest()
    return start_analysis(session, tender_id, version=body.version, analysis_mode=body.analysis_mode,
                          actor=user.user_id)


@router.get("/{tender_id}/runs/{run_id}")
def run_status(tender_id: str, run_id: str) -> dict[str, Any]:
    info = get_run(run_id)
    if info is None or info["tender_id"] != tender_id:
        raise NotFoundError(f"run '{run_id}' not found for tender '{tender_id}'")
    return info


@router.get("/{tender_id}/events", response_model=None)
async def events(request: Request, tender_id: str, run_id: str | None = None, after_id: int = 0,
                 format: str | None = Query(None, pattern="^(json)?$"), follow: bool = True) -> Any:
    """Server-Sent Events: replays persisted events after `after_id`, then streams live ones
    (reconnect with the last id seen). `follow=false` replays and closes; `?format=json`
    returns the persisted list (polling fallback)."""
    if format == "json":
        with session_scope() as s:
            return {"items": list_events(s, run_id, after_id, tender_id=tender_id)}

    async def stream():
        queue, close = open_subscription(run_id or tender_id)  # subscribe first, then replay: no gap
        last = after_id
        try:
            with session_scope() as s:
                backlog = list_events(s, run_id, after_id, tender_id=tender_id)
            for ev in backlog:
                last = max(last, ev["id"] or 0)
                yield {"id": str(ev["id"]), "event": ev["event"], "data": json.dumps(ev)}
            while follow and not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield {"comment": "keep-alive"}
                    continue
                if ev.get("id") is not None and ev["id"] <= last:
                    continue
                last = ev.get("id") or last
                yield {"id": str(ev.get("id") or ""), "event": ev["event"], "data": json.dumps(ev)}
        finally:
            close()

    return EventSourceResponse(stream())


# --------------------------------------------------------------------------- results
@router.get("/{tender_id}/requirements")
def requirements(tender_id: str, version: int | None = None, category: str | None = None,
                 mandatory: bool | None = None, hard_gate: bool | None = None, q: str | None = None,
                 session: Session = Depends(db_dependency)) -> dict[str, Any]:
    v = _version(session, tender_id, version)
    items = load_requirements(session, tender_id, v)
    if category:
        items = [i for i in items if i.get("category") == category]
    if mandatory is not None:
        items = [i for i in items if bool(i.get("mandatory")) is mandatory]
    if hard_gate is not None:
        items = [i for i in items if bool(i.get("hard_gate")) is hard_gate]
    if q:
        items = [i for i in items if q.lower() in str(i.get("text", "")).lower()]
    return {"version": v, "analysis_mode": get_tender(session, tender_id).analysis_mode, "items": items}


@router.get("/{tender_id}/key-facts")
def key_facts(tender_id: str, version: int | None = None, session: Session = Depends(db_dependency)
              ) -> dict[str, Any]:
    kf = get_key_facts(session, tender_id, _version(session, tender_id, version))
    if kf is None:
        raise NotFoundError("key facts are not available until the analysis has run")
    return kf.model_dump(mode="json")


@router.get("/{tender_id}/compliance")
def compliance(tender_id: str, version: int | None = None, session: Session = Depends(db_dependency)
               ) -> dict[str, Any]:
    v = _version(session, tender_id, version)
    run_id = _result_run_id(session, tender_id, v)
    return {"version": v, "run_id": run_id,
            "items": load_compliance(session, tender_id, v, run_id) if run_id else []}


@router.get("/{tender_id}/risks")
def risks(tender_id: str, version: int | None = None, session: Session = Depends(db_dependency)
          ) -> dict[str, Any]:
    v = _version(session, tender_id, version)
    run_id = _result_run_id(session, tender_id, v)
    return {"version": v, "run_id": run_id,
            "items": load_risks(session, tender_id, v, run_id) if run_id else []}


@router.get("/{tender_id}/assessment")
def assessment(tender_id: str, version: int | None = None, session: Session = Depends(db_dependency)
               ) -> dict[str, Any]:
    v = _version(session, tender_id, version)
    run_id = _result_run_id(session, tender_id, v)
    data = load_assessment(session, tender_id, v, run_id) if run_id else None
    if data is None:
        raise NotFoundError("no assessment yet: run the analysis first")
    view = tender_view(session, get_tender(session, tender_id))
    return {**data, "approval_status": view["approvalStatus"]}


@router.post("/{tender_id}/decision")
def decision(tender_id: str, body: dict[str, Any], session: Session = Depends(db_dependency),
             user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Gate 1: bid_manager/admin only, bound to the current tender version, audited."""
    return decide_gate1(session, tender_id, body, user_id=user.user_id, role=user.role)


@router.get("/{tender_id}/audit")
def audit_trail(tender_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    get_tender(session, tender_id)
    return {"items": list_audit(session, tender_id)}


@router.get("/{tender_id}/guardrails")
def guardrails(tender_id: str, session: Session = Depends(db_dependency)) -> dict[str, Any]:
    from backend.app.ops.metrics import guardrail_to_dict

    rows = session.scalars(select(m.GuardrailEvent).where(m.GuardrailEvent.tender_id == tender_id)
                           .order_by(m.GuardrailEvent.id)).all()
    return {"items": [guardrail_to_dict(r) for r in rows]}
