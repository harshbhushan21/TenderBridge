"""Deterministic citation validation performed before semantic review."""
from __future__ import annotations

from typing import Any

from backend.app.schemas.documents import SourceSpan


def verify_citation(citation: SourceSpan | dict[str, Any], evidence_text: str) -> tuple[bool, str]:
    span = citation if isinstance(citation, SourceSpan) else SourceSpan.model_validate(citation)
    if not span.doc_id:
        return False, "citation has no document id"
    if span.page is not None and span.page < 1:
        return False, "citation page must be positive"
    if not span.text_span.strip():
        return False, "citation has no supporting text"
    if evidence_text and span.text_span.strip() not in evidence_text:
        return False, "citation text is not present in the supplied evidence"
    return True, "citation verified"


def verify_citations(claim: dict[str, Any], evidence: str) -> list[str]:
    errors: list[str] = []
    for index, citation in enumerate(claim.get("citations") or [], 1):
        valid, reason = verify_citation(citation, evidence)
        if not valid:
            errors.append(f"citation {index}: {reason}")
    if not claim.get("citations"):
        errors.append("claim has no citations")
    return errors
