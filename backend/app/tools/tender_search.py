"""Tender-scoped retrieval tool. Always filtered by tender_id + version (never another tender)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.errors import ToolError
from backend.app.schemas.documents import RetrievedChunk, Scope


def search_tender(session: Session, tender_id: str, version: int, query: str, *, k: int = 6,
                  role: str = "bid_manager") -> list[RetrievedChunk]:
    if not tender_id:
        raise ToolError("search_tender requires tender_id")
    if not query or not query.strip():
        return []
    from backend.app.retrieval.hybrid import hybrid_search

    results = hybrid_search(session, Scope.tender, query, k=k, tender_id=tender_id,
                            version=version, role=role)
    # defence in depth: drop anything not belonging to this tender
    return [r for r in results
            if r.metadata.get("tender_id", tender_id) == tender_id
            and (r.metadata.get("version") is None or int(r.metadata["version"]) <= int(version))]
