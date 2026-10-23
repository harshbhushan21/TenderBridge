"""Run the Phase 4 demo case through Gate 1."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from backend.app.agents.runner import get_run, start_run
from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.db.engine import session_scope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("CASE-1",))
    args = parser.parse_args()
    if args.case != "CASE-1":
        raise ValueError(f"unsupported demo case: {args.case}")

    _ensure_demo_case()
    result = start_run("TDR-001", version=1, analysis_mode="focused")
    print(json.dumps(result, indent=2))
    run_id = result["analysis_run_id"]
    for _ in range(120):
        run = get_run(run_id)
        if run and run["status"] in {"awaiting_human", "completed", "failed", "cancelled"}:
            print(json.dumps(run, indent=2))
            return
        time.sleep(0.25)
    raise TimeoutError(f"demo run '{run_id}' did not reach Gate 1 in time")


def _ensure_demo_case() -> None:
    """Materialize the checked-in extracted fixture when no tender was uploaded."""
    settings = get_settings()
    fixture = settings.project_root / "demo_data/tender/TDR-001/extracted/tender_sections.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    with session_scope() as session:
        tender = session.get(m.Tender, "TDR-001")
        if tender is None:
            tender = m.Tender(tender_id="TDR-001", title="Phase 4 demo tender",
                             company_id=settings.default_company_id, status="ready_for_analysis",
                             current_version=1, analysis_mode="focused")
            session.add(tender)
            session.add(m.TenderVersion(tender_id="TDR-001", version=1, status="effective"))
        for document in payload.get("documents", []):
            rel = Path("demo_data/tender/TDR-001") / document["file"]
            path = settings.project_root / rel
            if not path.exists():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            doc_id = f"DEMO-{digest[:12]}"
            if session.get(m.TenderFile, doc_id) is None:
                session.add(m.TenderFile(
                    doc_id=doc_id, tender_id="TDR-001", version=1,
                    filename=path.name, doc_role="main_rfp",
                    file_sha256=digest, mime_type="application/pdf",
                    size_bytes=path.stat().st_size, page_count=document.get("pages"),
                    status="indexed", storage_path=str(path), flags=[],
                ))
            for section in document.get("sections", []):
                if session.get(m.TenderSection, section["section_id"]) is None:
                    session.add(m.TenderSection(
                        section_id=section["section_id"], tender_id="TDR-001", version=1,
                        doc_id=doc_id, title=section.get("heading", ""),
                        section_path=section.get("heading", ""),
                        level=section.get("level", 1), page_start=section.get("page_start"),
                        page_end=section.get("page_end"), text=section.get("text", ""),
                        tables=[], flags=[], quarantined=False,
                    ))


if __name__ == "__main__":
    main()
