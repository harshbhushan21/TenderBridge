"""Claim verification: deterministic checks first, an optional semantic model last.

A claim is only as good as the evidence passed in. The checks never read expected
labels or fixture notes; they compare the claim text with the cited evidence text.
Verdicts: ``supported``, ``conditional`` (true only under a stated condition),
``unsupported`` (evidence does not establish it) and ``contradicted`` (evidence
says the opposite). Anything but supported/conditional must be struck or rewritten.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.guardrails.citation_verifier import verify_citations
from backend.app.ops.langsmith import traceable

Verdict = Literal["supported", "conditional", "unsupported", "contradicted"]
STRUCK: frozenset[str] = frozenset({"unsupported", "contradicted"})

_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                 "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}
_NEGATION = re.compile(r"\b(not held|expired|has lapsed|lapsed on|withdrawn|revoked|suspended|"
                       r"not (?:been )?(?:performed|obtained|issued|applied)|no level \d|not yet)\b", re.I)
_BOUNDED_VALIDITY = re.compile(r"\b(valid until|valid till|valid up ?to|expires? on|expiry date)\b", re.I)
_OPEN_ENDED = re.compile(r"\b(throughout|for the (?:entire|whole)|remain valid|at all times)\b", re.I)
# Qualifiers that change what is promised; evidence has to say the same thing.
_STRONG = ("bid-specific", "tender-specific", "guarantee", "exclusive", "unlimited")
_EXCEPTION = re.compile(r"\b(unless|subject to|except where|provided that)\b", re.I)
_STOP = frozenset("a an and are as at be by for from has have in is it its of on or our the to we will with "
                  "this that all any per each been which who".split())


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Verdict = "unsupported"
    reason: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    semantic_reviewed: bool = False


def _values(text: str) -> set[str]:
    """Numbers, percentages and dates; spelled-out counts become digits ("three" -> "3")."""
    words = " ".join(_NUMBER_WORDS.get(w.lower(), w) for w in re.findall(r"[\w.%₹/-]+", text))
    return {v.replace(",", "") for v in re.findall(r"\d+(?:[.,]\d+)*%?", words)}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2}


@traceable(name="verify_claim", run_type="chain")
def verify_claim(claim: dict[str, Any], evidence: str) -> ClaimVerdict:
    claim_id = str(claim.get("claim_id", "unknown"))
    claim_text = str(claim.get("text") or claim.get("claim") or "")
    citations = [{**c, "text_span": c.get("text_span") or c.get("span", "")}
                 for c in claim.get("citations") or claim.get("evidence") or []]
    evidence = evidence or " ".join(str(c["text_span"]) for c in citations)

    def verdict(v: Verdict, reason: str) -> ClaimVerdict:
        return ClaimVerdict(claim_id=claim_id, verdict=v, reason=reason, citations=citations)

    citation_errors = verify_citations({"citations": citations}, evidence)
    if citation_errors:
        return verdict("unsupported", "; ".join(citation_errors))
    negation = _NEGATION.search(evidence)
    if negation and negation.group(0).lower() not in claim_text.lower():  # a claim may report the negation
        return verdict("contradicted", f"evidence states '{negation.group(0)}'")
    if _OPEN_ENDED.search(claim_text) and _BOUNDED_VALIDITY.search(evidence):
        return verdict("contradicted", "claim asserts open-ended validity; evidence gives an expiry")
    missing = _values(claim_text) - _values(evidence)
    if missing and _EXCEPTION.search(evidence):
        return verdict("conditional", f"evidence sets a different value ({', '.join(sorted(missing))} not "
                                      f"stated) but allows the contract to override it")
    if missing:
        return verdict("unsupported", f"values not in evidence: {', '.join(sorted(missing))}")
    lower_claim, lower_evidence = claim_text.lower(), evidence.lower()
    strong = [q for q in _STRONG if q in lower_claim and q not in lower_evidence]
    if strong:
        return verdict("unsupported", f"evidence does not say: {', '.join(strong)}")
    words = _content_words(claim_text)
    overlap = len(words & _content_words(evidence)) / max(len(words), 1)
    if overlap < 0.25:
        return verdict("unsupported", f"evidence does not mention the claim (overlap {overlap:.0%})")
    if claim.get("conditional") or _EXCEPTION.search(evidence):
        return verdict("conditional", "evidence holds only under a stated condition")
    return verdict("supported", "citation, values and wording verified against evidence")


def verify_claims(claims: list[dict[str, Any]], evidence_by_doc: dict[str, str]) -> list[ClaimVerdict]:
    results: list[ClaimVerdict] = []
    for claim in claims:
        evidence = " ".join(evidence_by_doc.get(str(c.get("doc_id", "")), "") for c in claim.get("citations", []))
        results.append(verify_claim(claim, evidence))
    return results
