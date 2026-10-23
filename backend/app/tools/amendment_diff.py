"""Deterministic corrigendum diffing and incremental invalidation."""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from backend.app.ops.langsmith import summarize_sections, traceable
from backend.app.schemas.amendments import (
    AmendmentChange,
    AmendmentDiff,
    ChangeKind,
    ChangeType,
)
from backend.app.schemas.documents import ParsedSection, SourceSpan
from backend.app.schemas.requirements import KeyFacts


def _source(section: dict[str, Any] | ParsedSection, version: int) -> SourceSpan:
    data = section if isinstance(section, dict) else section.model_dump()
    return SourceSpan(doc_id=str(data["doc_id"]), page=data.get("page_start"),
                      section_path=data.get("section_path"), text_span=str(data.get("text", ""))[:400],
                      tender_version=version)


def invalidation_for(change: AmendmentChange | dict[str, Any]) -> list[str]:
    """Return check keys affected by one direct change."""
    field = str(change.field if isinstance(change, AmendmentChange) else change.get("field") or "").lower()
    category = change.change_type if isinstance(change, AmendmentChange) else change.get("change_type")
    keys: set[str] = set()
    if any(token in field for token in ("submission", "deadline", "validity", "certificate")):
        keys.update({"key_facts", "certificate_validity", "personnel_certifications", "calendar"})
    if any(token in field for token in ("turnover", "experience", "consortium", "project", "eligibility")):
        keys.update({"financial_eligibility", "project_eligibility"})
    if any(token in field for token in ("payment", "pbg", "penalty", "liability", "commercial")):
        keys.add("commercial_risk")
    if any(token in field for token in ("engineer", "personnel", "manpower", "staff")):
        keys.add("personnel")
    if category in (ChangeType.clause_added, ChangeType.clause_deleted,
                    ChangeType.clause_replaced, ChangeType.eligibility_change):
        keys.add("requirements")
    return sorted(keys or {"requirements"})


def _classify(old: str, new: str, field: str) -> ChangeType:
    f = field.lower()
    if any(t in f for t in ("date", "deadline", "submission", "opening", "presentation")):
        return ChangeType.date_change
    if any(t in f for t in ("value", "amount", "pct", "percent", "days", "engineers", "payment")):
        return ChangeType.value_change
    if any(t in f for t in ("eligibility", "experience", "certificate", "consortium")):
        return ChangeType.eligibility_change
    if any(t in f for t in ("payment", "pbg", "penalty", "liability")):
        return ChangeType.commercial_change
    return ChangeType.clause_replaced


def diff_sections(base: Sequence[dict[str, Any] | ParsedSection],
                  amended: Sequence[dict[str, Any] | ParsedSection], *,
                  amendment_id: str, tender_id: str, base_version: int,
                  target_version: int) -> AmendmentDiff:
    """Compare sectionized versions while preserving page-citable sources."""
    old_map = {str((s if isinstance(s, dict) else s.model_dump())["section_id"]): s for s in base}
    new_map = {str((s if isinstance(s, dict) else s.model_dump())["section_id"]): s for s in amended}
    changes: list[AmendmentChange] = []
    for section_id in sorted(set(old_map) | set(new_map)):
        old = old_map.get(section_id)
        new = new_map.get(section_id)
        old_data = old if isinstance(old, dict) else old.model_dump() if old else {}
        new_data = new if isinstance(new, dict) else new.model_dump() if new else {}
        old_text, new_text = str(old_data.get("text", "")), str(new_data.get("text", ""))
        if old is not None and new is not None and old_text == new_text:
            continue
        if old is None:
            kind, field, summary = ChangeType.clause_added, section_id, "Section added"
        elif new is None:
            kind, field, summary = ChangeType.clause_deleted, section_id, "Section removed"
        else:
            field = str(new_data.get("section_path") or section_id)
            kind, summary = _classify(old_text, new_text, field), "Section text changed"
        source_section = new if new is not None else old
        assert source_section is not None
        change = AmendmentChange(
            change_id=f"{amendment_id}-{len(changes) + 1:02d}", change_type=kind,
            clause_ref=section_id, field=field, old_value=old_text or None,
            new_value=new_text or None, old_source=_source(old, base_version) if old else None,
            new_source=_source(source_section, target_version), summary=summary,
        )
        change.downstream_impacts = invalidation_for(change)
        changes.append(change)
    invalidated = sorted({key for change in changes for key in change.downstream_impacts})
    return AmendmentDiff(
        amendment_id=amendment_id, tender_id=tender_id, base_version=base_version,
        target_version=target_version, changes=changes, invalidated_checks=invalidated,
        reusable_checks=[] if changes else ["all"], generated_at=datetime.now(UTC),
    )


def diff_change_records(records: list[dict[str, Any]], *, amendment_id: str,
                        tender_id: str, base_version: int, target_version: int) -> AmendmentDiff:
    """Convert parser output into the stable amendment contract.

    Parsers may provide richer references than section diffing can infer.  Keeping
    this adapter separate lets PDF/OCR extractors evolve without changing impact
    evaluation or persistence.
    """
    type_map = {
        "added": ChangeType.clause_added, "changed": ChangeType.other,
        "removed": ChangeType.clause_deleted, "superseded": ChangeType.clause_replaced,
        "clarified": ChangeType.clarification, "eligibility_change": ChangeType.eligibility_change,
        "commercial_change": ChangeType.commercial_change,
    }
    changes: list[AmendmentChange] = []
    for record in records:
        kind = type_map.get(str(record.get("type", "changed")), ChangeType.other)
        if str(record.get("type", "changed")) == "changed":
            kind = _classify(str(record.get("old", "")), str(record.get("new", "")),
                             str(record.get("field", "")))
        affects = [str(item) for item in record.get("affects", [])]
        change = AmendmentChange(
            change_id=str(record["change_id"]), change_type=kind,
            clause_ref=record.get("new_ref") or record.get("old_ref"),
            field=record.get("field"), old_value=str(record["old"]) if "old" in record else None,
            new_value=str(record["new"]) if "new" in record else None,
            new_source=SourceSpan(doc_id=str(record.get("new_ref_file", "corrigendum")),
                                  page=record.get("new_ref_page"),
                                  text_span=str(record.get("new", record.get("field", ""))),
                                  tender_version=target_version),
            affected_requirement_ids=affects,
            summary=str(record.get("eligibility_effect") or record.get("field", "")),
        )
        change.downstream_impacts = invalidation_for(change)
        changes.append(change)
    return AmendmentDiff(
        amendment_id=amendment_id, tender_id=tender_id, base_version=base_version,
        target_version=target_version, changes=changes,
        invalidated_checks=sorted({i for c in changes for i in c.downstream_impacts}),
        generated_at=datetime.now(UTC),
    )


def apply_amendments(base_sections: Sequence[dict[str, Any] | ParsedSection],
                     amendment_sections: Sequence[dict[str, Any] | ParsedSection]
                     ) -> list[dict[str, Any] | ParsedSection]:
    """Overlay amended sections on the base version without mutating either input."""
    merged: dict[str, dict[str, Any] | ParsedSection] = {
        str((s if isinstance(s, dict) else s.model_dump())["section_id"]): s for s in base_sections
    }
    for section in amendment_sections:
        data = section if isinstance(section, dict) else section.model_dump()
        merged[str(data["section_id"])] = section
    return [merged[key] for key in sorted(merged)]


@traceable(name="compare_versions", run_type="chain")
def compare_versions(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    """Contract-shaped comparison of two analysed versions: score and recommendation,
    requirements whose verdict changed, and contract risks whose level changed.

    Inputs: {"version", "assessment", "compliance", "risks"} (+ "amendments" and
    "derived_impacts" on the newer side). Verdicts are compared, not whole records:
    every v2 record differs from v1 at least in its version number.
    """
    def score(data: dict[str, Any]) -> dict[str, Any]:
        assessment = data.get("assessment") or {}
        return {"version": data.get("version"), "score": assessment.get("score"),
                "recommendation": assessment.get("recommendation"),
                "hard_gate_failures": assessment.get("hard_gate_failures", [])}

    def by_id(items: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
        return {str(i.get(key)): i for i in items or []}

    before, after = by_id(v1.get("compliance", []), "requirement_id"), by_id(v2.get("compliance", []),
                                                                           "requirement_id")
    changed: list[dict[str, Any]] = []
    for rid in sorted(set(before) | set(after)):
        b, a = before.get(rid), after.get(rid)
        if (b or {}).get("status") != (a or {}).get("status"):
            changed.append({"requirement_id": rid, "hard_gate": bool((a or b or {}).get("hard_gate")),
                            "before": {"status": b.get("status"), "summary": b.get("summary")} if b else None,
                            "after": {"status": a.get("status"), "summary": a.get("summary")} if a else None})
    rb, ra = by_id(v1.get("risks", []), "category"), by_id(v2.get("risks", []), "category")
    risk_changes = [{"category": c, "before": (rb.get(c) or {}).get("level"), "after": (ra.get(c) or {}).get("level"),
                     "tender_value": (ra.get(c) or rb.get(c) or {}).get("tender_value")}
                    for c in sorted(set(rb) | set(ra))
                    if (rb.get(c) or {}).get("level") != (ra.get(c) or {}).get("level")]
    return {"a": score(v1), "b": score(v2), "changed_items": changed, "risk_changes": risk_changes,
            "amendments": v2.get("amendments", []), "derived_impacts": v2.get("derived_impacts", [])}

# --------------------------------------------------------------------------- corrigendum tables
# field -> checks it invalidates (PQ check names from agents/prequalification.py, plus
# key_facts / commercial_risk / calendar / submission_checklist / manpower / requirements).
FIELD_IMPACTS: dict[str, list[str]] = {
    "bid_submission_end": ["key_facts", "certifications", "company_age", "personnel", "emd", "calendar"],
    "tech_bid_opening": ["key_facts", "calendar"],
    "technical_presentation": ["key_facts", "calendar"],
    "pbg_pct": ["key_facts", "commercial_risk"],
    "sla_penalty_cap_pct": ["key_facts", "commercial_risk"],
    "payment_days": ["key_facts", "commercial_risk"],
    "consortium_experience_value_rule": ["similar_work"],
    "certificate_versions": ["certifications"],
    "iso_renewal_in_progress": ["certifications"],
    "physical_emd_submission": ["submission_checklist"],
    "emd_validity": ["emd"],
    "min_l2_network_engineers": ["manpower"],
    "certin_declaration": ["requirements"],
    "limitation_of_liability": [],
}

# Ordered: the first matching rule names the field.
_FIELD_RULES: list[tuple[str, str]] = [
    # specific provisions first: many rows mention the deadline in passing
    (r"cert-in", "certin_declaration"),
    (r"\brenewal\b|audit completion", "iso_renewal_in_progress"),
    (r"27001:2013|certificates issued under", "certificate_versions"),
    (r"emd bank guarantee|physical submission|sealed envelope", "physical_emd_submission"),
    (r"emd validity|emd shall be valid", "emd_validity"),
    (r"online bid submission", "bid_submission_end"),
    (r"opening of (?:pq|pre-?qualification)", "tech_bid_opening"),
    (r"technical presentation", "technical_presentation"),
    (r"performance bank guarantee", "pbg_pct"),
    (r"sla penalty", "sla_penalty_cap_pct"),
    (r"payment", "payment_days"),
    (r"consortium", "consortium_experience_value_rule"),
    (r"limitation of liability", "limitation_of_liability"),
    (r"network engineer", "min_l2_network_engineers"),
]
_NUM = re.compile(r"\d+(?:\.\d+)?")
_DATE_RX = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})(?:\s+at\s+(\d{1,2}):(\d{2}))?")


def infer_field(*texts: str) -> str:
    blob = " ".join(texts).lower()
    for pattern, field in _FIELD_RULES:
        if re.search(pattern, blob):
            return field
    return re.sub(r"[^a-z0-9]+", "_", blob[:40]).strip("_") or "provision"


def _norm_value(field: str, text: str) -> str | None:
    """Comparable value of a provision: ISO date-time, percentage, days or count."""
    if not text:
        return None
    if field in ("bid_submission_end", "tech_bid_opening", "technical_presentation"):
        m = _DATE_RX.search(text)
        if not m:
            return None
        d, mo, y, hh, mm = m.groups()
        iso = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        if field == "technical_presentation":
            return f"week of {iso}"
        return f"{iso}T{int(hh):02d}:{mm}" if hh else iso
    patterns = {"pbg_pct": r"(\d+(?:\.\d+)?)\s*%", "sla_penalty_cap_pct": r"capped at\s+(\d+(?:\.\d+)?)\s*%",
                "payment_days": r"within\s+(\d+)\s+days", "min_l2_network_engineers": r"minimum\s+(\d+)"}
    if field in patterns:
        m = re.search(patterns[field], text, re.IGNORECASE)
        return m.group(1) if m else None
    return None


def _part_a_kind(existing: str, amended: str) -> ChangeKind:
    e, a = existing.strip().lower(), amended.strip().lower()
    if not e or e in {"-", "–", "nil", "new"}:
        return "added"
    if a.startswith("deleted"):
        return "removed"
    if re.fullmatch(r"no change\.?\s*(as per rfp\.?)?", a):
        return "no_change"
    if a.startswith("no change") or "clarification added" in e or "no change in the requirement" in e:
        return "clarified"
    return "changed" if set(_NUM.findall(e)) != set(_NUM.findall(a)) else "superseded"


_TYPE_FOR_KIND = {"added": ChangeType.clause_added, "removed": ChangeType.clause_deleted,
                  "superseded": ChangeType.clause_replaced, "clarified": ChangeType.clarification,
                  "no_change": ChangeType.other}


def _corrigendum_number(rows_text: str) -> int:
    m = re.search(r"corrigendum\s+no\.?\s*(\d+)", rows_text, re.IGNORECASE)
    return int(m.group(1)) if m else 1


@traceable(name="corrigendum_changes", run_type="parser", process_inputs=summarize_sections)
def changes_from_corrigendum(rows: list[dict[str, Any]], *, doc_id: str, amendment_id: str,
                             tender_id: str, base_version: int, target_version: int,
                             first_page_text: str = "") -> AmendmentDiff:
    """Typed changes from Part A (amendments) and binding Part B (pre-bid) responses.

    Part A rows are all kept (including `no_change`, so reviewers see the buyer said
    so). Part B rows are kept only when they add a binding clarification: responses
    that just point to Part A or say "As per RFP" are not new changes.
    """
    n = _corrigendum_number(first_page_text)
    changes: list[AmendmentChange] = []
    for row in rows:
        page = row.get("page")
        kind: ChangeKind
        if row["part"] == "A":
            existing, amended, ref = row["existing"], row["amended"], row["reference"]
            kind = _part_a_kind(existing, amended)
            field = infer_field(existing, amended) if kind != "no_change" else infer_field(existing, ref)
            change_id = f"C{n}-{row['sl']:02d}"
            old_text, new_text = existing, amended
        else:
            response = row["response"]
            r = response.strip().lower()
            # Pointers to Part A and confirmations of the existing terms are not new changes.
            if re.search(r"see part a|as per rfp|as per clause|no change", r):
                continue
            kind, ref = "clarified", row["reference"]
            field = infer_field(row["query"], response)
            change_id = f"C{n}-PB{row['sl']:02d}"
            old_text, new_text = row["query"], response
        old_value, new_value = _norm_value(field, old_text), _norm_value(field, new_text)
        change_type = _TYPE_FOR_KIND.get(kind) or (
            ChangeType.date_change if field in ("bid_submission_end", "tech_bid_opening", "technical_presentation")
            else ChangeType.value_change if old_value or new_value else ChangeType.clause_replaced)
        change = AmendmentChange(
            change_id=change_id, change_type=change_type, kind=kind, part=row["part"], clause_ref=ref,
            field=field, old_value=old_value or (old_text or None), new_value=new_value or (new_text or None),
            new_source=SourceSpan(doc_id=doc_id, page=page, section_path=f"Corrigendum No. {n}, Part "
                                  f"{row['part']}, item {row['sl']}", text_span=new_text[:400],
                                  tender_version=target_version),
            summary=(f"{field}: {old_value} -> {new_value}" if old_value and new_value and old_value != new_value
                     else f"{kind}: {new_text[:160]}"),
        )
        change.downstream_impacts = list(FIELD_IMPACTS.get(field, ["requirements"]))
        changes.append(change)
    invalidated = sorted({k for c in changes if c.kind != "no_change" for k in c.downstream_impacts})
    return AmendmentDiff(amendment_id=amendment_id, tender_id=tender_id, base_version=base_version,
                         target_version=target_version, changes=changes, invalidated_checks=invalidated,
                         generated_at=datetime.now(UTC))


def apply_changes_to_key_facts(key_facts: KeyFacts, changes: list[AmendmentChange]) -> KeyFacts:
    """Overlay amended provisions on key facts. Each amended text is re-read with the
    sourced key-fact extractor, so a new value carries the corrigendum's citation."""
    from backend.app.agents.key_facts import extract_key_facts_deterministic

    data = key_facts.model_dump()
    facts = {f["name"]: f for f in data.get("facts", [])}
    for change in changes:
        if change.kind not in ("changed", "clarified", "superseded") or change.part != "A":
            continue
        src = change.new_source
        found = extract_key_facts_deterministic(key_facts.tender_id, key_facts.tender_version, [{
            "text": src.text_span, "doc_id": src.doc_id, "page_start": src.page,
            "section_path": src.section_path, "tender_version": src.tender_version}])
        for fact in found.facts:
            if fact.name in ("reference_no", "evaluation_method"):
                continue
            data[fact.name] = getattr(found, fact.name)
            facts[fact.name] = fact.model_dump()
    data["facts"] = list(facts.values())
    data["missing"] = [m for m in data.get("missing", []) if data.get(m) is None]
    return KeyFacts.model_validate(data)
