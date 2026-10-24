"""Hybrid retrieval: filters -> acronym expansion -> keyword top-30 + vector top-30 -> RRF (k=60)
-> optional rerank -> best child per parent -> parent text for the LLM.

Tender and company scopes are separate indexes and are never searched together.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.db import models as m
from backend.app.ops.langsmith import retrieval_outputs, traceable
from backend.app.retrieval.embeddings import get_embedder
from backend.app.retrieval.filters import SearchFilters, is_postgres
from backend.app.retrieval.keyword import Candidates, bm25_search, prepare_candidates
from backend.app.retrieval.query_rewrite import expand_query
from backend.app.retrieval.reranker import rerank
from backend.app.retrieval.vector import vector_search
from backend.app.schemas.documents import RetrievedChunk, Scope

RRF_K = 60
CANDIDATES = 30


def rrf(*rankings: list[str], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def _metadata(row: Any, f: SearchFilters) -> dict[str, Any]:
    md = dict(row.meta or {})
    md.update({"parent_id": row.parent_id, "doc_id": row.doc_id})
    if f.scope is Scope.tender:
        md.update({"tender_id": row.tender_id, "version": row.version, "section_id": row.section_id})
    else:
        md.update({"company_id": row.company_id, "allowed_roles": list(row.allowed_roles or []),
                   "approved_for_reuse": row.approved_for_reuse, "doc_type": row.doc_type})
    return md


@traceable(name="hybrid_search", run_type="retriever", process_outputs=retrieval_outputs)
def hybrid_search(session: Session, scope: Scope, query: str, *, k: int = 6, tender_id: str | None = None,
                  version: int | None = None, company_id: str | None = None, role: str = "bid_manager",
                  doc_types: list[str] | None = None, approved_only: bool = False,
                  candidates: Candidates | None = None) -> list[RetrievedChunk]:
    """Return up to k results, one per parent section, best first.

    `candidates` (from `prepare_candidates` with the same filters) skips reloading and
    re-indexing the corpus when many queries run against one scope.
    """
    f = SearchFilters(scope=scope, tender_id=tender_id, version=version, company_id=company_id,
                      role=role, doc_types=doc_types, approved_only=approved_only)
    f.validate()
    if candidates is not None and candidates.filters != f:
        raise ValueError("prepared candidates were built for different filters")
    if not query or not query.strip():
        return []

    prepared = candidates or prepare_candidates(session, f)  # role filter applied before any ranking
    rows = prepared.rows
    expanded = expand_query(query)
    lexical = bm25_search(session, f, expanded, k=CANDIDATES, prepared=prepared)
    # Postgres ranks vectors in SQL with pgvector; SQLite reuses the loaded rows.
    semantic = vector_search(session, f, get_embedder().embed_query(expanded), k=CANDIDATES,
                             rows=None if is_postgres(session) else rows)

    by_id: dict[str, Any] = {r.chunk_id: r for r, _ in lexical + semantic}
    fused = rrf([r.chunk_id for r, _ in lexical], [r.chunk_id for r, _ in semantic])
    lex_scores = {r.chunk_id: s for r, s in lexical}
    vec_scores = {r.chunk_id: s for r, s in semantic}

    results: list[RetrievedChunk] = []
    for chunk_id, score in sorted(fused.items(), key=lambda x: x[1], reverse=True):
        row = by_id[chunk_id]
        md = _metadata(row, f)
        md.update({"keyword_score": lex_scores.get(chunk_id), "vector_score": vec_scores.get(chunk_id)})
        results.append(RetrievedChunk(chunk_id=chunk_id, doc_id=row.doc_id, text=row.text, score=score,
                                      scope=scope, page=row.page, section_path=row.section_path,
                                      metadata=md))
    results = rerank(query, results[: max(k * 4, CANDIDATES)])

    # One result per parent section, then attach the parent text for context.
    seen: set[str] = set()
    picked: list[RetrievedChunk] = []
    for r in results:
        key = r.metadata.get("parent_id") or r.chunk_id
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= k:
            break
    model: Any = m.TenderChunk if scope is Scope.tender else m.KbChunk
    parent_ids = [p.metadata["parent_id"] for p in picked if p.metadata.get("parent_id")]
    parents = {p.chunk_id: p.text for p in session.query(model).filter(model.chunk_id.in_(parent_ids))} \
        if parent_ids else {}
    for p in picked:
        p.parent_text = parents.get(p.metadata.get("parent_id") or "")
    return picked
