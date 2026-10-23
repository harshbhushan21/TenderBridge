"""Run offline Phase 8 evaluation checks.

Usage: uv run python -m backend.app.evals.run_evals
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.db import models as m
from backend.app.db.engine import session_scope
from backend.app.evals.evaluators import evaluate_requirements
from backend.app.guardrails.claim_verifier import verify_claim
from backend.app.guardrails.injection import scan_text


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run() -> dict[str, Any]:
    started = time.perf_counter()
    root = get_settings().evaluation_dir
    requirements = _read(root / "requirements_gold.json")
    if isinstance(requirements, dict):
        requirements = requirements.get("items") or requirements.get("requirements") or []
    safety = _read(root / "safety_traps" / "traps_manifest.json")
    payloads = [str(t.get("payload", "")) for t in safety.get("traps", [])]
    safety_flags = sum(len(scan_text(text, doc_id="safety-fixture")) for text in payloads)
    claims = _read(root / "draft_claims_gold.json")
    if isinstance(claims, dict):
        claims = claims.get("claims", [])
    claim_rows = claims if isinstance(claims, list) else []
    claim_results = [
        verify_claim(claim, " ".join(str(item.get("span", "")) for item in claim.get("evidence", [])))
        for claim in claim_rows
    ]
    expected_struck = sum(
        claim.get("expected_label") in {"unsupported", "contradicted"} for claim in claim_rows
    )
    expected_conditional = sum(
        claim.get("expected_label") == "supported_with_condition" for claim in claim_rows
    )
    live_requirements = [item for item in requirements if item.get("live_subset")]
    with session_scope() as session:
        actual_rows = session.query(m.RequirementRow).filter(
            m.RequirementRow.tender_id == "TDR-001",
            m.RequirementRow.version == 1,
        ).all()
        actual = [{"requirement_id": row.requirement_id, "text": row.text} for row in actual_rows]
    mandatory = evaluate_requirements(live_requirements, actual)
    result = {
        "mandatory_recall": mandatory,
        "safety_traps": {"payloads": len(payloads), "flags": safety_flags},
        "claim_verification": {
            "claims": len(claim_results),
            "supported": sum(r.verdict == "supported" for r in claim_results),
            "conditional": sum(r.verdict == "conditional" for r in claim_results),
            "unsupported": sum(r.verdict == "unsupported" for r in claim_results),
            "fixture_expected_struck": expected_struck,
            "fixture_expected_conditional": expected_conditional,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "cost_usd": 0.0,
        "mode": "offline-deterministic",
    }
    return result


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
