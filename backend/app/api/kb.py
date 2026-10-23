"""Company knowledge-base routes: status, documents, facts, search, ingest."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import ValidationFailed
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.db.engine import db_dependency, session_scope
from backend.app.db.repositories import kb as kb_repo
from backend.app.knowledge.freshness import kb_status
from backend.app.ops.audit import audit
from backend.app.tools.company_search import search_company_kb

router = APIRouter(prefix="/kb", tags=["knowledge base"])
FACT_KINDS = ("company", "financials", "certificates", "projects", "people", "risk_positions")


def _company() -> str:
    return get_settings().default_company_id


@router.get("/status")
def status(session: Session = Depends(db_dependency)) -> dict[str, Any]:
    return kb_status(session, _company())


@router.get("/documents")
def documents(doc_type: str | None = None, q: str | None = None, session: Session = Depends(db_dependency),
              user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    rows = kb_repo.list_documents(session, _company(), doc_type=doc_type, q=q)
    return {"items": [{"doc_id": d.doc_id, "filename": d.filename, "doc_type": d.doc_type,
                       "page_count": d.page_count, "status": d.status, "sensitivity": d.sensitivity,
                       "approved_for_reuse": d.approved_for_reuse, "live_subset": d.live_subset,
                       "title": (d.meta or {}).get("title")}
                      for d in rows if user.can_read(d.allowed_roles)]}


@router.get("/facts/{kind}")
def facts(kind: str, session: Session = Depends(db_dependency),
          user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    if kind not in FACT_KINDS:
        raise ValidationFailed(f"unknown fact kind '{kind}'", details={"allowed": list(FACT_KINDS)})
    if kind == "risk_positions" and not user.can_read(["bid_manager", "legal"]):
        user.require_approver()  # commercial risk policy is not for analysts
    return {"items": kb_repo.list_facts(session, _company(), kind)}


@router.get("/search")
def search(q: str = Query(..., min_length=2), k: int = Query(6, ge=1, le=20),
           session: Session = Depends(db_dependency), user: CurrentUser = Depends(get_current_user)
           ) -> dict[str, Any]:
    results = search_company_kb(session, _company(), q, k=k, role=user.role)
    return {"items": [r.model_dump(mode="json") for r in results]}


def _ingest(force: bool, actor: str) -> None:
    from backend.app.ingestion.kb_ingest import ingest_company_kb
    from backend.app.knowledge.kb_seed import seed_company_facts

    with session_scope() as s:
        company_id = seed_company_facts(s)["company_id"]
        report = ingest_company_kb(s, company_id, force=force)
    audit(actor, "kb.ingested", indexed=report["indexed"], skipped=report["skipped"],
          failed=len(report["failed"]))


@router.post("/ingest")
def ingest(background: BackgroundTasks, body: dict[str, Any] | None = None,
           user: CurrentUser = Depends(get_current_user)) -> dict[str, str]:
    user.require("admin")
    background.add_task(_ingest, bool((body or {}).get("force")), user.user_id)
    return {"job": "started"}
