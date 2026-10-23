from backend.app.agents.subgraphs.amendment_impact import classify_impacts, reusable_checks
from backend.app.schemas.amendments import AmendmentChange, ChangeType
from backend.app.schemas.documents import SourceSpan
from backend.app.tools.amendment_diff import (
    apply_amendments,
    diff_change_records,
    invalidation_for,
)


def _change(field: str) -> AmendmentChange:
    return AmendmentChange(
        change_id="C1-01", change_type=ChangeType.date_change, field=field,
        new_source=SourceSpan(doc_id="corrigendum.pdf", tender_version=2),
    )


def test_structured_corrigendum_records_preserve_ids_and_types():
    diff = diff_change_records(
        [{"change_id": "C1-01", "type": "changed", "field": "bid_submission_end",
          "old": "2026-11-06", "new": "2026-11-20"}],
        amendment_id="AMD-1", tender_id="TDR-001", base_version=1, target_version=2,
    )
    assert [c.change_id for c in diff.changes] == ["C1-01"]
    assert diff.changes[0].change_type == ChangeType.date_change
    assert "calendar" in diff.invalidated_checks


def test_apply_amendments_overlays_without_mutating_base():
    base = [{"section_id": "a", "text": "old"}, {"section_id": "b", "text": "keep"}]
    amended = [{"section_id": "a", "text": "new"}]
    result = apply_amendments(base, amended)
    assert result == [{"section_id": "a", "text": "new"}, {"section_id": "b", "text": "keep"}]
    assert base[0]["text"] == "old"


def test_impact_classification_and_reuse():
    change = _change("submission_deadline")
    impacts = classify_impacts([change], {"REQ-1"})
    assert any(item.check_key == "calendar" for item in impacts["derived_impacts"])
    assert reusable_checks({"calendar", "commercial_risk", "personnel"}, {"calendar"}) == [
        "commercial_risk", "personnel"
    ]
    assert "certificate_validity" in invalidation_for(change)
