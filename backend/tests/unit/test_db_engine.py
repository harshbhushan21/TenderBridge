"""Phase 1: the storage layer works the same on SQLite and Postgres + pgvector."""
from __future__ import annotations

import pytest

from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.db.engine import check_db


def test_check_db_reports_dialect():
    info = check_db()
    assert info["ok"] is True
    if get_settings().is_postgres:
        assert info["dialect"] == "postgresql" and info["pgvector"] is True
    else:
        assert info["dialect"] == "sqlite"


def test_embedding_round_trip(db_session):
    dim = get_settings().embedding_dim
    db_session.add(m.Company(company_id="T-EMB", name="Embedding test"))
    db_session.add(m.KbDocument(doc_id="T-EMB-DOC", company_id="T-EMB", filename="x.pdf",
                                file_sha256="0" * 64))
    vector = [i / dim for i in range(dim)]
    db_session.add(m.KbChunk(chunk_id="T-EMB-C1", doc_id="T-EMB-DOC", company_id="T-EMB",
                             text="sample", embedding=vector, embedding_model="test"))
    db_session.flush()
    db_session.expire_all()
    chunk = db_session.get(m.KbChunk, "T-EMB-C1")
    assert len(chunk.embedding) == dim
    assert chunk.embedding[10] == pytest.approx(vector[10], rel=1e-5)


@pytest.mark.skipif(not get_settings().is_postgres, reason="pgvector operators are Postgres-only")
def test_pgvector_distance_operator(db_session):
    from sqlalchemy import text

    distance = db_session.execute(text("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector")).scalar()
    assert distance == pytest.approx(1.0)
