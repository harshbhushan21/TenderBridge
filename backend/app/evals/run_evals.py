"""Phase 8 evaluation harness: runs the real pipeline on TDR-001 and scores it against the gold files.

Usage: `uv run python dev.py evals` (fresh, isolated database under storage/evals/ every time).
Running this module directly uses whatever DATABASE_URL is configured; the evaluation tender
EVAL-TDR-001 is created there if missing. Gold files are read only here, after the pipeline ran.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.app.agents.runner import get_run, start_run
from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.evals.evaluators import basename, evaluate_claims, evaluate_requirements, evaluate_retrieval
from backend.app.guardrails.claim_verifier import verify_claim
from backend.app.guardrails.injection import scan_pdf_hidden_text
from backend.app.ingestion.kb_ingest import scan_sections
from backend.app.ingestion.pdf_parser import parse_pdf
from backend.app.ingestion.sectionizer import sectionize
from backend.app.ops.langsmith import configure_tracing, traceable
from backend.app.retrieval.hybrid import hybrid_search
from backend.app.schemas.documents import Scope

TENDER = "EVAL-TDR-001"
# Which guardrail evidence proves each injection trap was caught (traps_manifest.json).
_TRAP_FILES = {"TRAP-INJ-01": "injection_test.pdf", "TRAP-INJ-02": "injection_test.pdf",
               "TRAP-INJ-03": "injection_test.pdf", "TRAP-KB-01": "kb_poisoned_brochure_test.pdf"}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _analyse() -> dict[str, Any]:
    """v1 to Gate 1, then Corrigendum No. 1 and the impact re-analysis of v2."""
    from backend.scripts.run_demo_case import prepare_v1, prepare_v2, wait_for_gate

    data = get_settings().demo_data_dir
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    prepare_v1(TENDER, data_dir=data)
    timings["ingest_v1_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    v1 = wait_for_gate(start_run(TENDER, version=1)["analysis_run_id"]) or {}
    timings["analyse_v1_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    prepare_v2(TENDER, data_dir=data)
    timings["corrigendum_s"] = round(time.perf_counter() - t0, 2)
    t0 = time.perf_counter()
    v2 = wait_for_gate(start_run(TENDER, version=2, mode="impact")["analysis_run_id"]) or {}
    timings["analyse_v2_impact_s"] = round(time.perf_counter() - t0, 2)
    return {"runs": {1: get_run(str(v1.get("run_id"))), 2: get_run(str(v2.get("run_id")))}, "timings": timings}


def _requirements(gold: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with session_scope() as s:
        files = {f.doc_id: f.filename for f in s.scalars(select(m.TenderFile).where(m.TenderFile.tender_id == TENDER))}
        for version in (1, 2):
            rows = [r.data for r in s.scalars(select(m.RequirementRow).where(
                m.RequirementRow.tender_id == TENDER, m.RequirementRow.version == version))]
            out[f"v{version}"] = {
                "live_subset": evaluate_requirements(gold, rows, files, version=version, live_only=True),
                "all_gold": evaluate_requirements(gold, rows, files, version=version, live_only=False),
            }
    return out


def _scenarios(root: Path) -> dict[str, Any]:
    from backend.app.agents.persistence import load_assessment
    from backend.app.db.repositories.analysis import latest_run

    gold = _read(root / "eligibility_gold.json")["scenarios"]
    out = {}
    with session_scope() as s:
        for version, key in ((1, "S-v1"), (2, "S-v2")):
            run = latest_run(s, TENDER, version)
            got = load_assessment(s, TENDER, version, run.run_id) if run else None
            want = gold[key]["bid_assessment"]
            pair = [got["score"], got["recommendation"]] if got else None
            out[key] = {"expected": [want["weighted_score"], want["recommendation"]], "got": pair,
                        "match": pair is not None and abs(pair[0] - want["weighted_score"]) < 0.01
                        and pair[1] == want["recommendation"]}
    return out


def _retrieval(root: Path) -> dict[str, Any]:
    qa = _read(root / "retrieval_qa.json")["items"]
    company = get_settings().default_company_id
    ranked: dict[str, list[tuple[str, int | None]]] = {}
    with session_scope() as s:
        names = {f.doc_id: f.filename for f in s.scalars(select(m.TenderFile).where(m.TenderFile.tender_id == TENDER))}
        names.update({d.doc_id: basename(d.filename) for d in s.scalars(select(m.KbDocument))})
        for q in qa:
            if q["scope"] == "tender":
                hits = hybrid_search(s, Scope.tender, q["question"], k=6, tender_id=TENDER, version=2)
            else:
                hits = hybrid_search(s, Scope.kb, q["question"], k=6, company_id=company)
            ranked[q["qa_id"]] = [(names.get(h.doc_id, h.doc_id), h.page) for h in hits]
    by_scope = {scope: evaluate_retrieval([q for q in qa if q["scope"] == scope], ranked)
                for scope in ("tender", "company")}
    from backend.app.retrieval.embeddings import get_embedder
    return {"embedder": get_embedder().name, "all": evaluate_retrieval(qa, ranked), **by_scope}


def _safety(root: Path) -> dict[str, Any]:
    """Scan the real trap PDFs through the ingestion screens (hidden text, metadata, visible text)."""
    flags_by_file: dict[str, list[Any]] = {}
    for name in set(_TRAP_FILES.values()):
        path = root / "safety_traps" / name
        flags = scan_pdf_hidden_text(path, doc_id=name)
        parsed = parse_pdf(path, name)
        hidden = {p.page: p.hidden_spans for p in parsed.pages if p.hidden_spans}
        flags_by_file[name] = flags + scan_sections(sectionize(parsed), hidden, name)

    def caught(trap: str) -> bool:
        flags = flags_by_file[_TRAP_FILES[trap]]
        if trap in ("TRAP-INJ-01", "TRAP-KB-01"):
            return any(f.kind == "hidden_text" and f.quarantined for f in flags)
        if trap == "TRAP-INJ-03":
            return any(f.detail.startswith("metadata:") and f.quarantined for f in flags)
        return any(f.kind == "prompt_injection" and not f.detail.startswith("metadata:") and f.quarantined
                   for f in flags)

    results = {trap: caught(trap) for trap in _TRAP_FILES}
    return {"injection_traps_caught": f"{sum(results.values())}/{len(results)}", "traps": results}


def _claims(root: Path) -> dict[str, Any]:
    fixture = _read(root / "draft_claims_gold.json")
    verdicts = {}
    for claim in fixture["claims"]:
        visible = {k: v for k, v in claim.items() if k not in ("expected_label", "rationale")}
        verdicts[claim["claim_id"]] = verify_claim(visible, "").verdict
    return {"mode": "deterministic checks only (the optional semantic review is not wired in yet)",
            **evaluate_claims(fixture["expected_after_verification"], verdicts)}


@traceable(name="run_evals", run_type="chain")
def run() -> dict[str, Any]:
    started = time.perf_counter()
    root = get_settings().evaluation_dir
    analysis = _analyse()
    usage = [r.get("usage") or {} for r in analysis["runs"].values() if r]
    gold = _read(root / "requirements_gold.json")["requirements"]
    report = {
        "tender": TENDER,
        "requirements": _requirements(gold),
        "assessment": _scenarios(root),
        "retrieval": _retrieval(root),
        "safety": _safety(root),
        "claims": _claims(root),
        "timings": {**analysis["timings"], "total_s": round(time.perf_counter() - started, 2)},
        "cost": {"llm_calls": sum(int(u.get("calls", 0)) for u in usage),
                 "cost_usd": round(sum(float(u.get("cost_usd", 0.0)) for u in usage), 4),
                 "llm_fast": get_settings().llm_fast, "llm_strong": get_settings().llm_strong},
    }
    return report


def main() -> None:
    configure_tracing()  # before the `run_evals` root trace starts
    report = run()
    out = get_settings().storage_dir / "evals" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nreport written to {out}")


if __name__ == "__main__":
    main()
