"""Phase 8 review fixes: vectors from another embedder are ignored and repaired, and manifest
permission changes reach the index even when the file is unchanged."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.ingestion.kb_ingest import ingest_company_kb
from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.retrieval.embeddings import get_embedder
from backend.app.retrieval.filters import SearchFilters
from backend.app.retrieval.vector import vector_search
from backend.app.schemas.documents import Scope
from backend.scripts.reembed import reembed, stale_counts

DATA = Path(__file__).resolve().parents[3] / "demo_data"
MANIFEST = DATA / "demo_config/company_manifest.json"


def _ingest(manifest: Path = MANIFEST) -> tuple[str, dict]:
    with session_scope() as s:
        company = seed_company_facts(s, facts_dir=DATA / "structured_facts")["company_id"]
        report = ingest_company_kb(s, company, kb_dir=DATA / "company_kb", facts_dir=DATA / "structured_facts",
                                   manifest_path=manifest)
    return company, report


def test_foreign_vectors_are_ignored_then_reembedded():
    company, _ = _ingest()
    with session_scope() as s:
        chunk = s.scalars(select(m.KbChunk).where(m.KbChunk.company_id == company,
                                                  m.KbChunk.is_parent.is_(False))).first()
        assert chunk is not None
        chunk_id, vector = chunk.chunk_id, list(chunk.embedding)
        chunk.embedding_model = "some-other-model"  # as if written before a provider switch
    assert stale_counts(get_embedder().name)["kb_chunks"] >= 1
    with session_scope() as s:
        f = SearchFilters(scope=Scope.kb, company_id=company, role="bid_manager")
        hits = vector_search(s, f, vector, k=50)  # its own vector: it would rank first if compared
        assert chunk_id not in {r.chunk_id for r, _ in hits}
    report = reembed()
    assert report["stale_after"] == {"kb_chunks": 0, "tender_chunks": 0}
    with session_scope() as s:
        assert s.get(m.KbChunk, chunk_id).embedding_model == get_embedder().name
        hits = vector_search(s, SearchFilters(scope=Scope.kb, company_id=company, role="bid_manager"), vector, k=5)
        assert hits[0][0].chunk_id == chunk_id


def test_manifest_role_change_reindexes_unchanged_file(tmp_path):
    company, first = _ingest()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next(d for d in manifest["documents"] if d["doc_id"] == "KB-CO-001")
    entry["allowed_roles"] = ["bid_manager"]  # narrowed: analysts must lose access
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")
    _, report = _ingest(changed)
    assert report["indexed"] == 1 and report["skipped"] == first["documents"] - 1
    with session_scope() as s:
        roles = {tuple(c.allowed_roles) for c in s.scalars(select(m.KbChunk).where(m.KbChunk.doc_id == "KB-CO-001"))}
    assert roles == {("bid_manager",)}
    _, restored = _ingest()  # back to the checked-in manifest for the other tests
    assert restored["indexed"] == 1
