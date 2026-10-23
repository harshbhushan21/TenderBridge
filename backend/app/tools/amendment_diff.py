"""Deterministic corrigendum diffing and incremental invalidation."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from backend.app.schemas.amendments import (
    AmendmentChange,
    AmendmentDiff,
    ChangeType,
)
from backend.app.schemas.documents import ParsedSection, SourceSpan


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


def compare_versions(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    """Build the contract-shaped version comparison from persisted results."""
    def score(data: dict[str, Any]) -> dict[str, Any]:
        assessment = data.get("assessment") or {}
        return {"version": data.get("version"), "score": assessment.get("score"),
                "recommendation": assessment.get("recommendation"),
                "hard_gate_failures": assessment.get("hard_gate_failures", [])}
    before = {r.get("requirement_id"): r for r in v1.get("requirements", [])}
    after = {r.get("requirement_id"): r for r in v2.get("requirements", [])}
    changed: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed.append({"requirement_id": key, "before": before.get(key), "after": after.get(key)})
    return {"a": score(v1), "b": score(v2), "changed_items": changed,
            "amendments": v2.get("amendments", []),
            "derived_impacts": v2.get("derived_impacts", [])}
