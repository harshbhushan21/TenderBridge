"""Process health, dependency readiness and non-secret settings."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.db.engine import check_db, session_scope
from backend.app.llm.factory import llm_status
from backend.app.retrieval.embeddings import get_embedder

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, Any]:
    """Ready only when the database answers and the demo data is present."""
    from backend.app.db.models import Company

    settings = get_settings()
    db = check_db()
    kb = "unknown"
    if db.get("ok"):
        with session_scope() as s:
            company = s.get(Company, settings.default_company_id)
            kb = company.kb_status if company else "empty"
    embedder = get_embedder()
    demo = {"exists": settings.demo_data_dir.exists(), "path": str(settings.demo_data_dir)}
    return {"ready": bool(db.get("ok")) and demo["exists"], "db": db, "llm": llm_status(),
            "embeddings": {"name": embedder.name, "dim": embedder.dim}, "demo_data": demo,
            "kb": {"status": kb}}


@router.get("/settings")
def settings_view() -> dict[str, Any]:
    s = get_settings()
    return {"analysis_mode": s.analysis_mode, "demo_mode": s.demo_mode,
            "llm": {"fast": s.llm_fast, "strong": s.llm_strong},
            "embedding_provider": s.embedding_provider, "max_cost_usd": s.max_cost_usd,
            "max_llm_calls": s.max_llm_calls, "company_id": s.default_company_id}
