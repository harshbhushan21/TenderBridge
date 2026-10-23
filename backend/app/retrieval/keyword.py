"""Keyword (lexical) ranking with BM25 over the pre-filtered candidates.

Filters (scope, tender/version, role, reuse, quarantine) run in SQL first; BM25
then ranks the remaining child chunks in Python. This gives identical results
on SQLite and Postgres and weights rare terms properly (Postgres `ts_rank_cd`
has no IDF, which cost ~15 points of recall@6 on the gold set). At our scale
(< ~1,000 chunks per scope) this is fast; the Postgres GIN full-text index is
kept for a SQL pre-filter if the corpus grows (docs/decisions.md D16).
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from backend.app.retrieval.embeddings import tokenize
from backend.app.retrieval.filters import SearchFilters, candidate_query, visible

_SPLIT = re.compile(r"[-/.]")


def _stem(token: str) -> str:
    """Light plural folding so 'pages' matches 'page'."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def terms(text: str) -> list[str]:
    """BM25 terms: tokens plus the parts of hyphenated/slashed tokens, plural-folded."""
    out: list[str] = []
    for tok in tokenize(text):
        out.append(_stem(tok))
        parts = [p for p in _SPLIT.split(tok) if p]
        if len(parts) > 1:
            out.extend(_stem(p) for p in parts)
    return out


def load_candidates(session: Session, f: SearchFilters) -> list[Any]:
    """Visible, searchable chunks for the filters (role filter applied before ranking)."""
    return [r for r in session.scalars(candidate_query(session, f)).all() if visible(r, f)]


def bm25_search(session: Session, f: SearchFilters, query: str, *, k: int = 30,
                rows: list[Any] | None = None) -> list[tuple[Any, float]]:
    """Top-k (row, score) by BM25. Pass `rows` to reuse an already loaded candidate set."""
    from rank_bm25 import BM25Okapi

    candidates = rows if rows is not None else load_candidates(session, f)
    if not candidates:
        return []
    corpus = [terms(f"{r.section_path or ''} {r.text}") for r in candidates]
    scores = BM25Okapi(corpus).get_scores(terms(query))
    ranked = sorted(zip(candidates, scores, strict=True), key=lambda x: x[1], reverse=True)
    return [(r, float(s)) for r, s in ranked[:k] if s > 0]
