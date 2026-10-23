"""Format retrieved evidence for a prompt with stable source IDs (S1..Sn)."""
from __future__ import annotations

from backend.app.schemas.documents import RetrievedChunk


def source_label(chunk: RetrievedChunk) -> str:
    name = chunk.metadata.get("filename") or chunk.doc_id
    page = f" p.{chunk.page}" if chunk.page is not None else ""
    section = f" | {chunk.section_path}" if chunk.section_path else ""
    return f"{name}{page}{section}"


def build_context(chunks: list[RetrievedChunk], *, max_chars: int = 12000, use_parent: bool = True) -> str:
    """Each block is "[S<n>] <file> p.<page> | <section>" then its text. The model must
    cite these IDs; the citation verifier maps them back to the chunk's source span."""
    blocks: list[str] = []
    used = 0
    for i, c in enumerate(chunks, start=1):
        body = (c.parent_text if use_parent and c.parent_text else c.text).strip()
        block = f"[S{i}] {source_label(c)}\n{body}"
        if used + len(block) > max_chars:
            remaining = max_chars - used - len(f"[S{i}] {source_label(c)}\n") - 3
            if remaining < 200:
                break
            block = f"[S{i}] {source_label(c)}\n{body[:remaining]}..."
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks)
