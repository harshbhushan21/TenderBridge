"""Re-embed chunks whose vectors came from a different embedder (e.g. hash -> BAAI/bge-m3).

Usage: uv run python dev.py reembed [--dry-run]

Non-destructive: chunk text, ids, sections and permissions are untouched; only `embedding` and
`embedding_model` are rewritten, batch by batch, with vectors computed outside each write.
Safe to stop and re-run: finished batches are committed and skipped next time.
"""
from __future__ import annotations

import argparse
import time
from typing import Any

from sqlalchemy import func, or_, select

from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.retrieval.embeddings import get_embedder
from backend.app.retrieval.indexer import embedding_text
from backend.app.schemas.documents import ChunkRecord

BATCH = 64


def _stale(model: Any, name: str) -> Any:
    return (model.is_parent.is_(False),
            or_(model.embedding.is_(None), model.embedding_model.is_(None), model.embedding_model != name))


def stale_counts(name: str) -> dict[str, int]:
    with session_scope() as s:
        return {model.__tablename__: s.scalar(select(func.count()).select_from(model).where(*_stale(model, name))) or 0
                for model in (m.KbChunk, m.TenderChunk)}


def reembed(*, dry_run: bool = False) -> dict[str, Any]:
    embedder = get_embedder()
    before = stale_counts(embedder.name)
    report: dict[str, Any] = {"embedder": embedder.name, "dim": embedder.dim, "stale_before": before}
    if dry_run:
        return report
    started = time.perf_counter()
    for model in (m.KbChunk, m.TenderChunk):
        while True:
            with session_scope() as s:
                batch = [(r.chunk_id, embedding_text(ChunkRecord(chunk_id=r.chunk_id, doc_id=r.doc_id, text=r.text,
                                                                 section_path=r.section_path)))
                         for r in s.scalars(select(model).where(*_stale(model, embedder.name))
                                            .order_by(model.chunk_id).limit(BATCH))]
            if not batch:
                break
            vectors = embedder.embed_documents([text for _, text in batch])  # no transaction open
            with session_scope() as s:
                for (chunk_id, _), vector in zip(batch, vectors, strict=True):
                    row = s.get(model, chunk_id)
                    if row is not None:
                        row.embedding, row.embedding_model = vector, embedder.name
    report["stale_after"] = stale_counts(embedder.name)
    report["seconds"] = round(time.perf_counter() - started, 1)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="only count stale chunks")
    print(reembed(dry_run=parser.parse_args().dry_run))


if __name__ == "__main__":
    main()
