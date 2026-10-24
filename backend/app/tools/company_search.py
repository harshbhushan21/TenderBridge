"""Company-KB retrieval tool. Role and reuse filters are enforced before ranking."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.errors import ToolError
from backend.app.core.security import role_can_read
from backend.app.schemas.documents import RetrievedChunk, Scope


def search_company_kb(session: Session, company_id: str, query: str, *, k: int = 6,
                      role: str = "bid_manager", approved_only: bool = False,
                      doc_types: list[str] | None = None, candidates: Any = None) -> list[RetrievedChunk]:
    if not company_id:
        raise ToolError("search_company_kb requires company_id")
    if not query or not query.strip():
        return []
    from backend.app.retrieval.hybrid import hybrid_search

    results = hybrid_search(session, Scope.kb, query, k=k, company_id=company_id, role=role,
                            doc_types=doc_types, approved_only=approved_only, candidates=candidates)
    out = []
    for r in results:
        md = r.metadata or {}
        if md.get("company_id", company_id) != company_id:
            continue
        if not role_can_read(role, md.get("allowed_roles")):
            continue
        if approved_only and md.get("approved_for_reuse") is False:
            continue
        out.append(r)
    return out
