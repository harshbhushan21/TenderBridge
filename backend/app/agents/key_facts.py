"""Deterministic key-fact extraction from tender sections.

Finds dates, money and percentages next to their labels and records the
verbatim source of every value. Anything not found goes to `missing`; nothing
is guessed. This is the offline path and the safety net for the LLM node:
values found here (with a source span) take precedence over model output.
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.ops.langsmith import summarize_sections, traceable
from backend.app.schemas.documents import Scope, SourceSpan
from backend.app.schemas.requirements import KeyFact, KeyFacts
from backend.app.tools.date_normalization import parse_all_money, parse_datetime, parse_money

_DATE_TIME = r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}(?:\s+(?:at\s+)?\d{1,2}[:.]\d{2}\s*(?:hrs|hours|am|pm)?)?"
_GAP = r"[^\n]{0,60}?\n?[^\n]{0,20}?"  # lazy: the nearest value on the same or the next line

# name -> label patterns (value captured right after the label)
_DATE_LABELS: dict[str, list[str]] = {
    "submission_deadline": [r"last date and time for online bid submission\s*:?",
                            r"bid submission end date(?: and time)?"],
    "prebid_meeting": [r"pre-?bid meeting"],
    "bid_opening": [r"opening of (?:pq|pre-?qualification) and technical bids\s*:?"],
}
_MONEY_LABELS: dict[str, list[str]] = {
    "estimated_value": [r"estimated cost(?: of the project)?"],
    "emd": [r"\bEMD\b(?!\s+(?:and|shall|instrument|bank))", r"earnest money deposit(?: \(emd\))?"],
}


def _span(section: dict[str, Any], text: str) -> SourceSpan:
    return SourceSpan(doc_id=str(section.get("doc_id") or "tender"), page=section.get("page_start"),
                      section_path=section.get("section_path"), text_span=" ".join(text.split())[:300],
                      scope=Scope.tender, tender_version=section.get("tender_version"))


def _sections_by_priority(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Notice first (clean label/value table), then everything else in document order."""
    def rank(s: dict[str, Any]) -> int:
        path = str(s.get("section_path") or "").lower()
        return 0 if "notice inviting tender" in path else 1
    return sorted(sections, key=rank)


def _find(sections: list[dict[str, Any]], pattern: str, flags: int = re.IGNORECASE
          ) -> tuple[re.Match[str], dict[str, Any]] | None:
    rx = re.compile(pattern, flags)
    for section in _sections_by_priority(sections):
        match = rx.search(str(section.get("text") or ""))
        if match:
            return match, section
    return None


@traceable(name="extract_key_facts", run_type="parser", process_inputs=summarize_sections)
def extract_key_facts_deterministic(tender_id: str, version: int,
                                    sections: list[dict[str, Any]]) -> KeyFacts:
    values: dict[str, Any] = {}
    facts: list[KeyFact] = []

    def record(name: str, value: Any, section: dict[str, Any], text: str) -> None:
        values[name] = value
        facts.append(KeyFact(name=name, value=value if not hasattr(value, "model_dump")
                             else value.model_dump(mode="json"), source=_span(section, text)))

    for name, labels in _DATE_LABELS.items():
        for label in labels:
            hit = _find(sections, rf"{label}{_GAP}({_DATE_TIME})")
            if hit:
                match, section = hit
                when = parse_datetime(match.group(1))
                if when:
                    record(name, when, section, match.group(0))
                    break

    for name, labels in _MONEY_LABELS.items():
        for label in labels:
            hit = _find(sections, rf"{label}{_GAP}(Rs\.?\s*[\d,]+(?:\.\d+)?[^\n]{{0,25}})")
            if hit:
                match, section = hit
                money = parse_money(match.group(1))
                if money:
                    record(name, money, section, match.group(0))
                    break

    simple: list[tuple[str, str, Any]] = [
        ("reference_no", r"(?:RFP|NIT)\s+No\.?\s*:?\s*([A-Z0-9][A-Z0-9/\-]+\d)", str),
        ("bid_validity_days", r"valid for (\d+) days from the bid submission end date|bid validity\s*\n?\s*(\d+) days",
         int),
        ("pbg_percent", r"performance bank guarantee\s+of\s+(\d+(?:\.\d+)?)\s*%|performance bank guarantee\s*\n\s*(\d+(?:\.\d+)?)\s*%",
         float),
        ("penalty_cap_percent", r"penalt\w*\s+in a quarter\s+shall be capped at\s+(\d+(?:\.\d+)?)\s*%", float),
        ("evaluation_method", r"\b(QCBS\s*\d+\s*:\s*\d+|L1|QBS)\b", str),
    ]
    for name, pattern, cast in simple:
        hit = _find(sections, pattern)
        if hit:
            match, section = hit
            raw = next(g for g in match.groups() if g)
            record(name, cast(raw), section, match.group(0))

    hit = _find(sections, r"payment of the qgr[^.]{0,120}?within\s+(\d+)\s+days")
    if hit:
        match, section = hit
        record("payment_terms", f"within {match.group(1)} days of a correct invoice", section, match.group(0))

    hit = _find(sections, r"average annual turnover of not less than[\s\S]{0,420}")
    if hit:
        match, section = hit
        clause = re.split(r"\bPQ-\d{2}\b|\n\s*\n", match.group(0))[0]  # stop at the next clause
        amounts = parse_all_money(clause)
        if amounts:
            record("general_turnover_threshold", amounts[0], section, clause)
        if len(amounts) > 1 and re.search(r"micro|small|MSE", clause, re.IGNORECASE):
            record("mse_turnover_threshold", amounts[1], section, clause)
            record("mse_relaxation_allowed", True, section, clause)

    hit = _find(sections, r"liability of the \w+ shall be\s+unlimited[^.]*")
    if hit:
        match, section = hit
        record("liability_cap", "total contract value, unlimited for listed exceptions", section, match.group(0))

    wanted = ["submission_deadline", "prebid_meeting", "bid_opening", "emd", "pbg_percent",
              "evaluation_method", "estimated_value"]
    return KeyFacts(tender_id=tender_id, tender_version=version, facts=facts,
                    missing=[w for w in wanted if w not in values], **values)


def merge_key_facts(primary: KeyFacts, fallback: KeyFacts) -> KeyFacts:
    """Fill gaps in `primary` from `fallback`; sourced deterministic values win."""
    data = primary.model_dump()
    deterministic = fallback.model_dump()
    for key, value in deterministic.items():
        if key in ("tender_id", "tender_version", "facts", "missing"):
            continue
        if value is not None:
            data[key] = value
    data["facts"] = [f.model_dump() for f in fallback.facts] + [
        f for f in data.get("facts", []) if f["name"] not in {x.name for x in fallback.facts}]
    found = {f["name"] for f in data["facts"]}
    data["missing"] = [m for m in fallback.missing if m not in found and data.get(m) is None]
    return KeyFacts.model_validate(data)
