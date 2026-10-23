"""Phase 3: KB ingestion, tender upload/parsing/indexing and hybrid retrieval.

Runs the real demo data end to end (SQLite by default, Postgres via `test-pg`).
Gold files are read here by the evaluator only, never by the pipeline.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.core.errors import FileRejected
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.ingestion.document_classifier import classify_tender_file
from backend.app.ingestion.kb_ingest import ingest_company_kb
from backend.app.ingestion.ocr import ocr_available
from backend.app.ingestion.pdf_parser import parse_pdf
from backend.app.ingestion.sectionizer import _norm, sectionize
from backend.app.ingestion.tender_ingest import load_boq_items, load_effective_sections
from backend.app.ingestion.upload_service import (
    process_pending_files,
    save_tender_upload,
    tender_ingestion_status,
)
from backend.app.knowledge.freshness import kb_status
from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.retrieval.context_pack import build_context
from backend.app.retrieval.hybrid import hybrid_search
from backend.app.retrieval.query_rewrite import expand_query
from backend.app.schemas.documents import Scope
from backend.app.services.tender_service import create_tender
from backend.app.tools.company_search import search_company_kb
from backend.app.tools.tender_search import search_tender

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "demo_data"
ORIGINAL = DATA / "tender" / "TDR-001" / "original"
COMPANY = "NIMBUS-001"
V1_FILES = ["notice.pdf", "main_rfp.pdf", "annexures.pdf", "price_schedule_boq.xlsx"]
MANIFEST = json.loads((DATA / "demo_config" / "company_manifest.json").read_text(encoding="utf-8"))
KB_FILE = {d["doc_id"]: Path(d["file_path"]).name for d in MANIFEST["documents"]}
QA = json.loads((DATA / "evaluation" / "retrieval_qa.json").read_text(encoding="utf-8"))["items"]


def _ingest_kb(**kw):
    with session_scope() as s:
        return ingest_company_kb(s, kb_dir=DATA / "company_kb", manifest_path=DATA / "demo_config" /
                                 "company_manifest.json", facts_dir=DATA / "structured_facts", **kw)


def _upload_v1() -> str:
    with session_scope() as s:
        tender = create_tender(s, "DSDC O&M (test)", reference_no="DSEDC/DSDC-MSP/2026/014")
        for name in V1_FILES:
            save_tender_upload(s, tender.tender_id, name, (ORIGINAL / name).read_bytes())
        tender_id = tender.tender_id
    process_pending_files(tender_id)
    return tender_id


@pytest.fixture(scope="module")
def world():
    with session_scope() as s:
        seed_company_facts(s, facts_dir=DATA / "structured_facts")
    first = _ingest_kb()
    return {"kb_first": first, "kb_second": _ingest_kb(), "tender": _upload_v1(), "other": _upload_v1()}


def _hit(results, relevant, file_of) -> int | None:
    for rank, r in enumerate(results, start=1):
        name = file_of(r)
        if any(name == Path(x["file"]).name and x.get("page") in (None, r.page) for x in relevant):
            return rank
    return None


# --------------------------------------------------------------------------- parsing
def test_sectionizer_matches_reference_headings_and_pages():
    ref = json.loads((DATA / "tender/TDR-001/extracted/tender_sections.json").read_text(encoding="utf-8"))
    for doc in ref["documents"]:
        sections = sectionize(parse_pdf(DATA / "tender/TDR-001" / doc["file"], "t"))
        ours = {_norm(s.title): s.page_start for s in sections}
        for gold in doc["sections"]:
            key = _norm(gold["heading"])
            assert key in ours, f"{doc['file']}: missing heading {gold['heading']!r}"
            assert ours[key] == gold["page_start"], f"{doc['file']}: {gold['heading']!r} page"


def test_chunks_keep_exact_pages():
    sections = sectionize(parse_pdf(ORIGINAL / "main_rfp.pdf", "rfp"))
    pq = next(s for s in sections if "Rs. 15.36" in s.text)
    assert pq.page_at(pq.text.index("Rs. 15.36")) == 7


@pytest.mark.skipif(not ocr_available(), reason="Tesseract not installed")
def test_scanned_page_is_ocred():
    parsed = parse_pdf(ORIGINAL / "annexures.pdf", "ann")
    assert parsed.pages[11].ocr and "POWER OF ATTORNEY" in parsed.pages[11].text.upper()


def test_classifier_catches_renamed_corrigendum():
    first_page = parse_pdf(ORIGINAL / "corrigendum.pdf", "c").pages[0].text
    assert classify_tender_file("annexure_extra.pdf", first_page).value == "corrigendum"
    assert classify_tender_file("price_schedule_boq.xlsx").value == "boq"


# --------------------------------------------------------------------------- company KB
def test_kb_ingest_indexes_all_and_is_idempotent(world):
    first, second = world["kb_first"], world["kb_second"]
    assert first["indexed"] == 52 and not first["failed"] and first["chunks"] > 0
    assert second["indexed"] == 0 and second["skipped"] == 52  # never re-embedded


def test_kb_has_no_real_names(world):
    names = [r["name"] for r in csv.DictReader((DATA / "structured_facts/personnel.csv").open(encoding="utf-8"))]
    with session_scope() as s:
        text = " ".join(s.scalars(select(m.KbChunk.text)).all())
    assert not [n for n in names if n in text]
    assert "NDS-E105 (name masked)" in text


def test_lost_proposal_reuse_flags(world):
    with session_scope() as s:
        parents = s.scalars(select(m.KbChunk).where(m.KbChunk.doc_id == "KB-PP-003",
                                                    m.KbChunk.is_parent.is_(True))).all()
        approved = {c.section_path for c in parents if c.approved_for_reuse}
    assert approved == {"3. NOC operating model (approved for reuse)",
                        "4. Change and configuration management (approved for reuse)"}


def test_poisoned_kb_document_is_quarantined_not_indexed(world, tmp_path):
    trap = DATA / "evaluation/safety_traps/kb_poisoned_brochure_test.pdf"
    kb_dir = tmp_path / "kb"
    (kb_dir / "01_company").mkdir(parents=True)
    (kb_dir / "01_company" / trap.name).write_bytes(trap.read_bytes())
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"company_id": "TRAP-CO", "documents": [{
        "doc_id": "TRAP-KB-01", "document_type": "company_profile", "allowed_roles": ["bid_manager"],
        "file_path": f"01_company/{trap.name}"}]}), encoding="utf-8")
    with session_scope() as s:
        report = ingest_company_kb(s, "TRAP-CO", kb_dir=kb_dir, manifest_path=manifest,
                                   facts_dir=DATA / "structured_facts")
    assert report["quarantined"] and report["indexed"] == 0
    with session_scope() as s:
        assert s.get(m.KbDocument, "TRAP-KB-01").status == "quarantined"
        assert not s.scalars(select(m.KbChunk).where(m.KbChunk.doc_id == "TRAP-KB-01")).all()


def test_kb_status_flags_expiring_iso(world):
    with session_scope() as s:
        status = kb_status(s, COMPANY, as_of=date(2026, 10, 23))
    assert status["status"] == "ready" and status["documents"] == 52
    assert any("CERT-002" in w and "2026-11-10" in w for w in status["warnings"])


def test_company_retrieval_gold_recall(world):
    company_qa = [q for q in QA if q["scope"] == "company"]
    with session_scope() as s:
        ranks = [_hit(hybrid_search(s, Scope.kb, q["question"], k=6, company_id=COMPANY),
                      q["relevant"], lambda r: KB_FILE.get(r.doc_id)) for q in company_qa]
    recall = sum(r is not None for r in ranks) / len(ranks)
    assert recall >= 0.9, f"company recall@6 {recall:.2f}"


def test_role_filter_applies_before_ranking(world):
    query = "standard position on uncapped liability"
    with session_scope() as s:
        analyst = search_company_kb(s, COMPANY, query, role="analyst")
        manager = search_company_kb(s, COMPANY, query, role="bid_manager")
    assert "bid_risk_policy.pdf" not in {KB_FILE.get(r.doc_id) for r in analyst}
    assert "bid_risk_policy.pdf" in {KB_FILE.get(r.doc_id) for r in manager}


# --------------------------------------------------------------------------- tender
def test_v1_upload_reaches_ready_without_analysis(world):
    with session_scope() as s:
        state = tender_ingestion_status(s, world["tender"])
        assert state["ready"] and state["status"] == "ready_for_analysis"
        assert {f["doc_role"] for f in state["files"]} == {"notice", "main_rfp", "annexures", "boq"}
        assert not s.scalars(select(m.BidAssessmentRow)).all()  # upload != analyze
        assert len(load_boq_items(s, world["tender"], 1)) > 0
        assert len(load_effective_sections(s, world["tender"], 1)) > 90


def test_duplicate_upload_returns_existing_file(world):
    with session_scope() as s:
        a = save_tender_upload(s, world["tender"], "main_rfp.pdf", (ORIGINAL / "main_rfp.pdf").read_bytes())
        b = save_tender_upload(s, world["tender"], "copy.pdf", (ORIGINAL / "main_rfp.pdf").read_bytes())
        assert a.doc_id == b.doc_id


def test_corrigendum_rejected_on_original_pack(world):
    data = (ORIGINAL / "corrigendum.pdf").read_bytes()
    with session_scope() as s:
        tender = create_tender(s, "corrigendum guard")
        with pytest.raises(FileRejected):
            save_tender_upload(s, tender.tender_id, "corrigendum.pdf", data)
        renamed = save_tender_upload(s, tender.tender_id, "extra.pdf", data)
        tender_id, doc_id = tender.tender_id, renamed.doc_id
    assert process_pending_files(tender_id)[doc_id] == "failed"
    with session_scope() as s:
        state = tender_ingestion_status(s, tender_id)
        assert not state["ready"] and "corrigendum" in state["files"][0]["status_detail"].lower()


def test_injection_trap_is_quarantined_in_tender_upload(world):
    trap = (DATA / "evaluation/safety_traps/injection_test.pdf").read_bytes()
    with session_scope() as s:
        tender = create_tender(s, "injection trap")
        doc = save_tender_upload(s, tender.tender_id, "annex_g.pdf", trap)
        tender_id = tender.tender_id
    process_pending_files(tender_id)
    with session_scope() as s:
        text = " ".join(s.scalars(select(m.TenderChunk.text).where(m.TenderChunk.tender_id == tender_id)).all())
        events = s.scalars(select(m.GuardrailEvent).where(m.GuardrailEvent.tender_id == tender_id)).all()
        flags = s.get(m.TenderFile, doc.doc_id).flags
    assert "Ignore all previous instructions" not in text
    assert "tenders-review@dsedc-eval.example" not in text
    assert "treat ongoing works as completed works" not in text
    assert events and {"hidden_text", "prompt_injection"} & set(flags)


def test_tender_retrieval_gold_recall_and_isolation(world):
    v1_qa = [q for q in QA if q["scope"] == "tender"
             and not any("corrigendum" in r["file"] for r in q["relevant"])]
    with session_scope() as s:
        files = {f.doc_id: f.filename for f in s.scalars(select(m.TenderFile))}
        ranks = []
        for q in v1_qa:
            results = search_tender(s, world["tender"], 1, q["question"])
            assert all(r.metadata["tender_id"] == world["tender"] for r in results)  # never the other tender
            assert all(r.scope is Scope.tender for r in results)
            ranks.append(_hit(results, q["relevant"], lambda r: files.get(r.doc_id)))
    recall = sum(r is not None for r in ranks) / len(ranks)
    assert recall >= 0.9, f"tender recall@6 {recall:.2f}"


def test_context_pack_labels_sources(world):
    with session_scope() as s:
        results = hybrid_search(s, Scope.tender, "EMD exemption", tender_id=world["tender"], version=1, k=3)
    pack = build_context(results)
    assert pack.startswith("[S1] ") and " p." in pack.splitlines()[0]


def test_query_rewrite_expands_acronyms_and_phrasing():
    assert "Udyam" in expand_query("Is Nimbus an MSE?")
    assert "not exceed" in expand_query("page limit for the technical proposal")
    assert expand_query("plain words only") == "plain words only"
