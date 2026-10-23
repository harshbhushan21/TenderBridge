"""Run a demo case end to end from the command line, up to the Gate 1 pause.

Usage: uv run python dev.py demo-cli CASE-1

Prepares whatever is missing through the real pipeline (idempotent): seeds
company facts, ingests the KB, creates tender TDR-001 and uploads the four v1
files (never the corrigendum). It does not read the evaluation gold files or
the reference extraction.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from backend.app.agents.runner import get_run, start_run
from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.db.engine import init_db, session_scope
from backend.app.ingestion.kb_ingest import ingest_company_kb
from backend.app.ingestion.upload_service import (
    process_pending_files,
    save_tender_upload,
    tender_ingestion_status,
)
from backend.app.knowledge.kb_seed import seed_company_facts
from backend.app.schemas.amendments import AmendmentConfirmation, AmendmentStatus
from backend.app.services.amendment_service import (
    confirm_amendment,
    process_amendment,
    upload_amendment,
)
from backend.app.services.tender_service import create_tender

DEMO_TENDER = "TDR-001"
V1_FILES = ("notice.pdf", "main_rfp.pdf", "annexures.pdf", "price_schedule_boq.xlsx")


def prepare_v1(tender_id: str = DEMO_TENDER, *, data_dir: Path | None = None) -> None:
    """Facts, KB and the v1 tender pack, created only if missing."""
    data = Path(data_dir or get_settings().demo_data_dir)
    init_db()
    with session_scope() as session:
        company_id = seed_company_facts(session, facts_dir=data / "structured_facts")["company_id"]
        company = session.get(m.Company, company_id)
        if company is None or company.kb_status != "ready":
            ingest_company_kb(session, company_id, kb_dir=data / "company_kb",
                              manifest_path=data / "demo_config" / "company_manifest.json",
                              facts_dir=data / "structured_facts")
        if session.get(m.Tender, tender_id) is None:
            create_tender(session, "Selection of MSP for O&M of Deccan State Data Centre (simulated)",
                          buyer="DSEDC (fictional)", reference_no="DSEDC/DSDC-MSP/2026/014",
                          tender_id=tender_id, actor="demo-cli")
        folder = data / "tender" / DEMO_TENDER / "original"
        for name in V1_FILES:
            save_tender_upload(session, tender_id, name, (folder / name).read_bytes(), actor="demo-cli")
    process_pending_files(tender_id)
    with session_scope() as session:
        state = tender_ingestion_status(session, tender_id)
    if not state["ready"]:
        raise SystemExit(f"tender {tender_id} is not ready for analysis: {json.dumps(state['files'], indent=2)}")


def prepare_v2(tender_id: str = DEMO_TENDER, *, data_dir: Path | None = None) -> str:
    """v1 plus the corrigendum, uploaded, processed and confirmed (the KB is not touched)."""
    from sqlalchemy import select

    prepare_v1(tender_id, data_dir=data_dir)
    data = Path(data_dir or get_settings().demo_data_dir)
    with session_scope() as session:
        existing = session.scalar(select(m.AmendmentRow).where(m.AmendmentRow.tender_id == tender_id,
                                                               m.AmendmentRow.target_version == 2))
        if existing is None:
            amendment_id = upload_amendment(
                session, tender_id, "corrigendum.pdf",
                (data / "tender" / DEMO_TENDER / "original" / "corrigendum.pdf").read_bytes(),
                actor="demo-cli")["amendment_id"]
        else:
            amendment_id = existing.amendment_id
    process_amendment(amendment_id, actor="demo-cli")
    with session_scope() as session:
        amendment = session.get(m.AmendmentRow, amendment_id)
        if amendment is not None and amendment.status == AmendmentStatus.diff_ready.value:
            confirm_amendment(session, tender_id, amendment_id, AmendmentConfirmation(
                reviewer="bid.manager@nimbus.example", comment="Corrigendum No. 1 confirmed (demo)"))
    return amendment_id


def wait_for_gate(run_id: str, timeout_s: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        run = get_run(run_id)
        if run and run["status"] in {"awaiting_human", "completed", "failed", "cancelled"}:
            return run
        time.sleep(0.25)
    raise TimeoutError(f"run {run_id} did not reach Gate 1 within {timeout_s:.0f}s")


def summary(run: dict) -> dict:
    from backend.app.agents.persistence import load_assessment, load_compliance

    with session_scope() as session:
        assessment = load_assessment(session, run["tender_id"], run["version"], run["run_id"]) or {}
        compliance = load_compliance(session, run["tender_id"], run["version"], run["run_id"])
    gates = [c for c in compliance if c.get("hard_gate")]
    from backend.app.tools.facts import get_key_facts
    with session_scope() as session:
        kf = get_key_facts(session, run["tender_id"], run["version"])
    failed = [g for g in gates if g["status"] == "gap"]
    return {
        "tender_version": run["version"],
        "submission_deadline": kf.submission_deadline.isoformat() if kf and kf.submission_deadline else None,
        "rerun_checks": sorted(g["requirement_id"] for g in gates if not g.get("reused_from_version")),
        "reused_checks": sorted(g["requirement_id"] for g in gates if g.get("reused_from_version")),
        "failed_gate_evidence": [{"requirement": g["requirement_id"], "summary": g["summary"],
                                  "calculations": [c["value"] for c in (g.get("rule_result") or {}).get(
                                      "calculations", [])]} for g in failed],
        "run_id": run["run_id"], "status": run["status"], "error": run.get("error"),
        "score": assessment.get("score"), "recommendation": assessment.get("recommendation"),
        "factors": {c["key"]: c["raw_score"] for c in assessment.get("criteria", [])},
        "hard_gate_failures": assessment.get("hard_gate_failures"),
        "hard_gates": {g["tender_source"]["text_span"][:60]: g["status"] for g in gates},
        "conditions": assessment.get("conditions"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=("CASE-1", "CASE-2"))
    args = parser.parse_args()
    if args.case == "CASE-1":
        prepare_v1()
        started = start_run(DEMO_TENDER, version=1, analysis_mode="focused")
        print(json.dumps(summary(wait_for_gate(started["analysis_run_id"])), indent=2))
    else:
        prepare_v1()
        with session_scope() as session:
            from backend.app.db.repositories.analysis import latest_run
            has_v1 = latest_run(session, DEMO_TENDER, 1, completed_only=True) is not None
        if not has_v1:  # impact mode needs the v1 results as its baseline
            wait_for_gate(start_run(DEMO_TENDER, version=1, analysis_mode="focused")["analysis_run_id"])
        prepare_v2()
        started = start_run(DEMO_TENDER, version=2, mode="impact", analysis_mode="focused")
        print(json.dumps(summary(wait_for_gate(started["analysis_run_id"])), indent=2))


if __name__ == "__main__":
    main()
