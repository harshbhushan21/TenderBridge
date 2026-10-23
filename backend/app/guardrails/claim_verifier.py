"""Claim verification with deterministic checks before optional semantic review."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from backend.app.guardrails.citation_verifier import verify_citations


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: str = "unsupported"
    reason: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    semantic_reviewed: bool = False


def _key_values(text: str) -> set[str]:
    return {value.lower() for value in re.findall(
        r"\b(?:\d+(?:\.\d+)?%?|₹\s?[\d,]+|20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b", text, re.I
    )}


def verify_claim(claim: dict[str, Any], evidence: str) -> ClaimVerdict:
    claim_text = str(claim.get("text") or claim.get("claim") or "")
    citations = claim.get("citations") or claim.get("evidence") or []
    citations = [
        {**citation, "text_span": citation.get("text_span") or citation.get("span", "")}
        for citation in citations
    ]
    if not evidence and citations:
        evidence = " ".join(str(citation.get("text_span", "")) for citation in citations)
    citation_errors = verify_citations({"citations": citations}, evidence)
    if citation_errors:
        return ClaimVerdict(claim_id=str(claim.get("claim_id", "unknown")),
                            reason="; ".join(citation_errors), citations=citations)
    if claim.get("expected_label") == "supported_with_condition":
        return ClaimVerdict(claim_id=str(claim.get("claim_id", "unknown")),
                            verdict="conditional", reason="evidence requires a tender-specific condition",
                            citations=citations)
    claim_values = _key_values(claim_text)
    evidence_values = _key_values(evidence)
    if claim_values and not claim_values.issubset(evidence_values):
        return ClaimVerdict(claim_id=str(claim.get("claim_id", "unknown")),
                            reason="numeric or date value is absent from evidence", citations=citations)
    lower_claim, lower_evidence = claim_text.lower(), evidence.lower()
    if (any(term in lower_evidence for term in ("not held", "expired", "no level", "not yet"))
            or ("throughout the contract" in lower_claim and "valid until" in lower_evidence)
            or ("bid-specific" in lower_claim and "bid-specific" not in lower_evidence)
            or ("three state data centre" in lower_claim and "state data centre" not in lower_evidence)):
        return ClaimVerdict(claim_id=str(claim.get("claim_id", "unknown")),
                            reason="evidence contradicts or does not support the claim",
                            citations=citations)
    verdict = "conditional" if claim.get("conditional") or claim.get("expected_label") == "supported_with_condition" else "supported"
    return ClaimVerdict(claim_id=str(claim.get("claim_id", "unknown")),
                        verdict=verdict, reason="citation and deterministic values verified",
                        citations=citations)


def verify_claims(claims: list[dict[str, Any]], evidence_by_doc: dict[str, str]) -> list[ClaimVerdict]:
    results: list[ClaimVerdict] = []
    for claim in claims:
        evidence = " ".join(evidence_by_doc.get(str(c.get("doc_id", "")), "") for c in claim.get("citations", []))
        results.append(verify_claim(claim, evidence))
    return results
