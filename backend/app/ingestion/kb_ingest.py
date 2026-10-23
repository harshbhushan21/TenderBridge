"""One-time, hash-idempotent ingestion of the company knowledge base.

Driven by `demo_config/company_manifest.json` (doc ids, types, roles,
sensitivity). Every document is parsed, PII-masked, scanned for injected
instructions, sectioned and indexed into `kb_chunks`. Unchanged files (same
SHA-256) are skipped, so the KB is never re-embedded per tender.
Structured facts are seeded separately (knowledge/kb_seed.py) and not embedded.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import ConfigError, FileRejected
from backend.app.core.logging import get_logger
from backend.app.db import models as m
from backend.app.guardrails.file_security import validate_upload
from backend.app.guardrails.injection import scan_pdf_hidden_text, scan_text, strip_quarantined
from backend.app.guardrails.pii import mask_pii
from backend.app.ingestion.document_classifier import classify_kb_file
from backend.app.ingestion.docx_parser import parse_docx
from backend.app.ingestion.file_validator import KB_EXTS
from backend.app.ingestion.pdf_parser import parse_pdf
from backend.app.ingestion.sectionizer import sectionize
from backend.app.ops.metrics import record_guardrail
from backend.app.retrieval.chunker import chunk_sections
from backend.app.retrieval.indexer import delete_doc_chunks, index_kb_chunks
from backend.app.schemas.documents import GuardrailFlag, ParsedDocument, ParsedSection, Scope

log = get_logger(__name__)
QUARANTINE_FLAG = "quarantined_content"
_DOC_REUSE = re.compile(r"approved\s+for\s+reuse\s*\|\s*(yes|partial|no)", re.IGNORECASE)


def _name_masks(facts_dir: Path) -> dict[str, str]:
    """Real names from the HR facts -> masked labels, so CVs index without PII."""
    path = facts_dir / "personnel.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["name"]: r.get("name_masked") or r["employee_id"]
                for r in csv.DictReader(fh) if r.get("name")}


def mask_text(text: str, names: dict[str, str]) -> str:
    for name, masked in names.items():
        text = text.replace(name, masked)
    return mask_pii(text)


def parse_any(path: Path, doc_id: str) -> ParsedDocument:
    if path.suffix.lower() == ".docx":
        return parse_docx(path, doc_id)
    if path.suffix.lower() == ".pdf":
        return parse_pdf(path, doc_id)
    raise FileRejected(f"unsupported knowledge-base file type: {path.suffix}")


def scan_sections(sections: list[ParsedSection], hidden_by_page: dict[int, list[str]],
                  doc_id: str) -> list[GuardrailFlag]:
    """Quarantine injected instructions inside sections (text is untrusted data)."""
    flags: list[GuardrailFlag] = []
    for sec in sections:
        found = scan_text(sec.text, doc_id=doc_id, page=sec.page_start)
        hidden = [t for p in range(sec.page_start or 0, (sec.page_end or 0) + 1)
                  for t in hidden_by_page.get(p, [])]
        if hidden:
            found += [GuardrailFlag(kind="hidden_text", severity="high", doc_id=doc_id, page=sec.page_start,
                                    excerpt=" ".join(hidden)[:500], detail="hidden spans removed by parser",
                                    quarantined=True)]
            if "hidden_text_removed" not in sec.flags:
                sec.flags.append("hidden_text_removed")
        quarantined = [f for f in found if f.quarantined]
        if quarantined:
            sec.text = strip_quarantined(sec.text, quarantined)
            if QUARANTINE_FLAG not in sec.flags:
                sec.flags.append(QUARANTINE_FLAG)
        flags += found
    return flags


def reuse_approvals(sections: list[ParsedSection], default: bool) -> tuple[bool, dict[str, bool]]:
    """Per-section reuse approval for past proposals.

    "Approved for reuse | Yes" -> every section unless marked NOT approved;
    "Partial" -> only sections explicitly "(approved for reuse)"; "No" -> none.
    """
    doc_level = None
    for sec in sections:
        match = _DOC_REUSE.search(sec.text)
        if match:
            doc_level = match.group(1).lower()
            break
    if doc_level is None:
        return default, {}
    approvals: dict[str, bool] = {}
    for sec in sections:
        title = sec.title.lower()
        if "not approved for reuse" in title or "(internal)" in title:
            approvals[sec.section_id] = False
        elif "approved for reuse" in title:
            approvals[sec.section_id] = True
        else:
            approvals[sec.section_id] = doc_level == "yes"
    return doc_level != "no", approvals


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise ConfigError("company manifest missing", details={"path": str(manifest_path)})
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def ingest_company_kb(session: Session, company_id: str | None = None, *, kb_dir: Path | None = None,
                      manifest_path: Path | None = None, facts_dir: Path | None = None,
                      force: bool = False) -> dict[str, Any]:
    """Ingest every manifest document. Returns counts; safe to re-run.

    A company document carrying hidden or critical injected instructions is
    quarantined as a whole and not indexed: certification answers must keep
    coming from the facts tables, never from a poisoned brochure.
    """
    settings = get_settings()
    kb_dir = Path(kb_dir or settings.company_kb_dir)
    manifest = _load_manifest(Path(manifest_path or settings.demo_config_dir / "company_manifest.json"))
    company_id = company_id or manifest.get("company_id") or settings.default_company_id
    company = session.get(m.Company, company_id)
    if company is None:
        company = m.Company(company_id=company_id, name=manifest.get("company_name", company_id))
        session.add(company)
    company.kb_status = "ingesting"
    session.flush()

    names = _name_masks(Path(facts_dir or settings.structured_facts_dir))
    report: dict[str, Any] = {"company_id": company_id, "documents": 0, "indexed": 0, "skipped": 0,
                              "failed": [], "quarantined": [], "chunks": 0, "quarantined_sections": 0,
                              "guardrail_flags": 0}
    parsed_dir = settings.parsed_dir / "kb"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    for entry in manifest.get("documents", []):
        report["documents"] += 1
        doc_id, rel = entry["doc_id"], entry["file_path"]
        path = kb_dir / rel
        try:
            if not path.exists():
                raise FileRejected("file listed in manifest is missing", details={"path": rel})
            info = validate_upload(path.name, path.read_bytes(), allowed=KB_EXTS)
            row = session.get(m.KbDocument, doc_id)
            if row is not None and row.file_sha256 == info["sha256"] and row.status in ("indexed", "quarantined") \
                    and not force:
                report["skipped"] += 1
                continue
            if row is None:
                row = m.KbDocument(doc_id=doc_id, company_id=company_id, filename=path.name,
                                   file_sha256=info["sha256"])
                session.add(row)

            parsed = parse_any(path, doc_id)
            for page in parsed.pages:
                page.text = mask_text(page.text, names)
            hidden_by_page = {p.page: p.hidden_spans for p in parsed.pages if p.hidden_spans}
            sections = sectionize(parsed)
            flags = scan_pdf_hidden_text(path, doc_id=doc_id) if path.suffix.lower() == ".pdf" else []
            flags += scan_sections(sections, hidden_by_page, doc_id)
            for flag in flags:
                record_guardrail(flag, session=session)
            # Hidden text has no business in a company document; with a critical
            # injection it is poisoning. Either way the document is not indexed.
            poisoned = any(f.severity == "critical" or f.kind == "hidden_text" for f in flags)
            doc_type = entry.get("document_type") or classify_kb_file(rel)
            approved, section_approvals = reuse_approvals(sections, default=True)

            row.company_id = company_id
            row.filename = path.name
            row.rel_path = rel
            row.file_sha256 = info["sha256"]
            row.doc_type = doc_type
            row.mime_type = info["mime"]
            row.size_bytes = info["size"]
            row.page_count = len(parsed.pages)
            row.allowed_roles = list(entry.get("allowed_roles") or ["all"])
            row.sensitivity = entry.get("sensitivity", "internal")
            row.approved_for_reuse = approved
            row.synthetic = bool(entry.get("synthetic", True))
            row.live_subset = bool(entry.get("live_subset", False))
            row.storage_path = str(path)
            row.meta = {k: entry.get(k) for k in ("title", "version", "document_date", "project_id",
                                                  "employee_id", "client", "verification_status")
                        if entry.get(k) is not None}
            row.meta.update({"parser": parsed.parser, "warnings": parsed.warnings,
                             "guardrail_flags": len(flags)})
            parsed_path = parsed_dir / f"{doc_id}.json"
            parsed_path.write_text(parsed.model_dump_json(), encoding="utf-8")
            row.parsed_path = str(parsed_path)
            if poisoned:
                delete_doc_chunks(session, Scope.kb, doc_id)
                row.status = "quarantined"
                row.meta["quarantine_reason"] = "hidden or injected instructions found; not indexed"
                report["quarantined"].append({"doc_id": doc_id, "file": rel})
                report["guardrail_flags"] += len(flags)
                session.flush()
                continue

            chunks = chunk_sections(sections, prefix=f"{doc_id}::")
            report["chunks"] += index_kb_chunks(session, company_id, row, chunks,
                                                approved_sections=section_approvals)
            row.status = "indexed"
            report["indexed"] += 1
            report["quarantined_sections"] += sum(QUARANTINE_FLAG in s.flags for s in sections)
            report["guardrail_flags"] += len(flags)
            session.flush()
        except Exception as exc:  # one bad file must not stop the KB
            log.warning("kb ingest failed for %s: %s", doc_id, exc)
            report["failed"].append({"doc_id": doc_id, "file": rel, "error": str(exc)[:300]})
            existing = session.get(m.KbDocument, doc_id)
            if existing is not None:
                existing.status = "failed"
                existing.meta = {**(existing.meta or {}), "error": str(exc)[:300]}

    usable = report["indexed"] + report["skipped"]
    company.kb_status = "ready" if usable else "failed"  # partial failures surface as warnings
    company.kb_report = report
    session.flush()
    log.info("company KB ingested", extra={k: v for k, v in report.items() if k != "failed"})
    return report
