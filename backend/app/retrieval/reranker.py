"""Optional cross-encoder rerank (RERANKER=bge-reranker-v2-m3). No-op by default
or when the model cannot load, so retrieval never fails because of it."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.schemas.documents import RetrievedChunk

log = get_logger(__name__)


@lru_cache
def _model() -> Any:
    name = get_settings().reranker.strip()
    if not name or name == "none":
        return None
    try:
        from FlagEmbedding import FlagReranker

        return FlagReranker(name if "/" in name else f"BAAI/{name}", use_fp16=False)
    except Exception as exc:  # optional heavy dependency or model download
        log.warning("reranker %s unavailable (%s); keeping fused order", name, exc)
        return None


def rerank(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    model = _model()
    if model is None or not chunks:
        return chunks
    scores = model.compute_score([[query, c.text] for c in chunks])
    scores = scores if isinstance(scores, list) else [scores]
    for c, s in zip(chunks, scores, strict=True):
        c.metadata["rerank_score"] = float(s)
    return sorted(chunks, key=lambda c: c.metadata["rerank_score"], reverse=True)
