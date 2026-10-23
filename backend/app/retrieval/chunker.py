"""Parent/child chunking of sections.

Children (~250 tokens) are what retrieval scores; parents (whole sections, or
~1,200-token slices of long ones) are what the LLM reads. Each chunk keeps the
page it starts on and its section path, so every hit is citable.
"""
from __future__ import annotations

import re

from backend.app.ingestion.hashes import short_hash
from backend.app.schemas.documents import ChunkRecord, ParsedSection

TOKENS_PER_WORD = 1.3   # rough English estimate; avoids a tokenizer download
PARENT_TOKENS = 1200
_WORD = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    return int(len(_WORD.findall(text)) * TOKENS_PER_WORD)


def _windows(text: str, max_tokens: int, overlap_tokens: int) -> list[tuple[int, str]]:
    """Split text into word windows; returns (char_offset, text) pairs."""
    words = list(_WORD.finditer(text))
    if not words:
        return []
    size = max(1, int(max_tokens / TOKENS_PER_WORD))
    step = max(1, size - int(overlap_tokens / TOKENS_PER_WORD))
    out = []
    for start in range(0, len(words), step):
        chunk = words[start:start + size]
        out.append((chunk[0].start(), text[chunk[0].start():chunk[-1].end()]))
        if start + size >= len(words):
            break
    return out


def chunk_sections(sections: list[ParsedSection], *, child_tokens: int = 250,
                   overlap: int = 40, prefix: str = "") -> list[ChunkRecord]:
    """Return parent chunks (metadata.is_parent=True) followed by their children."""
    out: list[ChunkRecord] = []
    for sec in sections:
        if not sec.text.strip():
            continue
        parents = _windows(sec.text, PARENT_TOKENS, 0) if estimate_tokens(sec.text) > PARENT_TOKENS \
            else [(0, sec.text)]
        for p_index, (p_offset, p_text) in enumerate(parents):
            parent_id = f"{prefix}{sec.section_id}::p{p_index}::{short_hash(p_text, 6)}"
            base_meta = {"section_id": sec.section_id, "section_title": sec.title,
                         "flags": list(sec.flags)}
            out.append(ChunkRecord(chunk_id=parent_id, doc_id=sec.doc_id, text=p_text,
                                   page=sec.page_at(p_offset), section_path=sec.section_path,
                                   token_count=estimate_tokens(p_text),
                                   metadata={**base_meta, "is_parent": True}))
            for c_index, (c_offset, c_text) in enumerate(_windows(p_text, child_tokens, overlap)):
                out.append(ChunkRecord(
                    chunk_id=f"{parent_id}::c{c_index}", doc_id=sec.doc_id, parent_id=parent_id,
                    text=c_text, page=sec.page_at(p_offset + c_offset),
                    section_path=sec.section_path, token_count=estimate_tokens(c_text),
                    metadata={**base_meta, "is_parent": False}))
    return out
