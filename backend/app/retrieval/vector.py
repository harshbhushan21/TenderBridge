"""Vector ranking: pgvector cosine distance in SQL, or cosine in Python on SQLite."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Float, cast, literal
from sqlalchemy.orm import Session

from backend.app.retrieval.embeddings import cosine, get_embedder
from backend.app.retrieval.filters import SearchFilters, candidate_query, is_postgres, visible


def vector_search(session: Session, f: SearchFilters, query_vector: list[float], *, k: int = 30,
                  rows: list[Any] | None = None) -> list[tuple[Any, float]]:
    """Top-k (row, similarity) with similarity = 1 - cosine distance.

    Only vectors made by the current embedder are compared: after a provider switch, rows
    not yet re-embedded (`dev.py reembed`) are ranked by keywords only, never by a
    meaningless cross-model cosine.
    """
    model = f.model
    current = get_embedder().name
    if is_postgres(session):
        from pgvector.sqlalchemy import Vector

        qvec = cast(literal(query_vector, Vector(len(query_vector))), Vector(len(query_vector)))
        distance = model.embedding.op("<=>", return_type=Float)(qvec)
        stmt = candidate_query(session, f).where(model.embedding.isnot(None), model.embedding_model == current) \
            .add_columns(distance).order_by(distance).limit(k)
        return [(row, 1.0 - float(d)) for row, d in session.execute(stmt).all() if visible(row, f)]

    candidates = rows if rows is not None else [
        r for r in session.scalars(candidate_query(session, f)).all() if visible(r, f)]
    scored = [(r, cosine(query_vector, r.embedding)) for r in candidates
              if r.embedding and r.embedding_model == current]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
