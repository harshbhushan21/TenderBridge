"""Write chunks (with embeddings) into the isolated tender and company indexes."""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.db import models as m
from backend.app.ops.langsmith import traceable
from backend.app.retrieval.embeddings import get_embedder
from backend.app.schemas.documents import ChunkRecord, Scope


def embedding_text(chunk: ChunkRecord) -> str:
    """Children are embedded with their section path so headings inform the vector."""
    return f"{chunk.section_path}\n{chunk.text}" if chunk.section_path else chunk.text


Vectors = tuple[dict[str, list[float]], str]


@traceable(name="embed_chunks", run_type="embedding",
           process_inputs=lambda d: {"chunks": len(d.get("chunks") or [])},
           process_outputs=lambda out: {"vectors": len(out[0]), "embedding_model": out[1]})
def embed_chunks(chunks: list[ChunkRecord]) -> Vectors:
    """Embed child chunks. Call before opening a write transaction: a local model can take
    longer than SQLite's lock timeout, and other writers would fail meanwhile."""
    embedder = get_embedder()
    children = [c for c in chunks if not c.metadata.get("is_parent")]
    vectors = embedder.embed_documents([embedding_text(c) for c in children]) if children else []
    return {c.chunk_id: v for c, v in zip(children, vectors, strict=True)}, embedder.name


def delete_doc_chunks(session: Session, scope: Scope, doc_id: str) -> None:
    model: Any = m.TenderChunk if scope is Scope.tender else m.KbChunk
    session.execute(delete(model).where(model.doc_id == doc_id))


def index_tender_chunks(session: Session, tender_id: str, version: int, doc_id: str,
                        chunks: list[ChunkRecord], *, quarantined_sections: set[str] | None = None,
                        vectors: Vectors | None = None) -> int:
    """Replace a tender file's chunks. Parents are stored but only children are embedded."""
    by_id, model_name = vectors or embed_chunks(chunks)
    delete_doc_chunks(session, Scope.tender, doc_id)
    quarantined_sections = quarantined_sections or set()
    for c in chunks:
        session.add(m.TenderChunk(
            chunk_id=c.chunk_id, tender_id=tender_id, version=version, doc_id=doc_id,
            section_id=c.metadata.get("section_id"), parent_id=c.parent_id,
            is_parent=bool(c.metadata.get("is_parent")), text=c.text, page=c.page,
            section_path=c.section_path, token_count=c.token_count,
            quarantined=c.metadata.get("section_id") in quarantined_sections,
            embedding=by_id.get(c.chunk_id), embedding_model=model_name if c.chunk_id in by_id else None,
            meta={**c.metadata, "tender_id": tender_id, "version": version}))
    session.flush()
    return len(chunks)


def index_kb_chunks(session: Session, company_id: str, kb_doc: m.KbDocument, chunks: list[ChunkRecord],
                    *, approved_sections: dict[str, bool] | None = None) -> int:
    """Replace a KB document's chunks, copying its access metadata onto every chunk."""
    vectors, model_name = embed_chunks(chunks)
    delete_doc_chunks(session, Scope.kb, kb_doc.doc_id)
    approved_sections = approved_sections or {}
    for c in chunks:
        section_id = c.metadata.get("section_id")
        approved = approved_sections.get(section_id, kb_doc.approved_for_reuse) if section_id \
            else kb_doc.approved_for_reuse
        session.add(m.KbChunk(
            chunk_id=c.chunk_id, doc_id=kb_doc.doc_id, company_id=company_id, parent_id=c.parent_id,
            is_parent=bool(c.metadata.get("is_parent")), text=c.text, page=c.page,
            section_path=c.section_path, doc_type=kb_doc.doc_type,
            allowed_roles=list(kb_doc.allowed_roles or ["all"]), approved_for_reuse=approved,
            token_count=c.token_count, embedding=vectors.get(c.chunk_id),
            embedding_model=model_name if c.chunk_id in vectors else None,
            meta={**c.metadata, "company_id": company_id, "filename": kb_doc.filename,
                  "rel_path": kb_doc.rel_path, "live_subset": kb_doc.live_subset}))
    session.flush()
    return len(chunks)
