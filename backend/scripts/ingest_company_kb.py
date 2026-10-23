"""Ingest the company knowledge base (idempotent: unchanged files are skipped).

Usage: uv run python -m backend.scripts.ingest_company_kb [--force]
Seeds structured facts first so expiring-certificate checks have data.
"""
from __future__ import annotations

import argparse
import json

from backend.app.db.engine import init_db, session_scope
from backend.app.ingestion.kb_ingest import ingest_company_kb
from backend.app.knowledge.freshness import kb_status
from backend.app.knowledge.kb_seed import seed_company_facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-parse and re-embed every document")
    args = parser.parse_args()
    init_db()
    with session_scope() as session:
        company_id = seed_company_facts(session)["company_id"]
        report = ingest_company_kb(session, company_id, force=args.force)
    with session_scope() as session:
        status = kb_status(session, company_id)
    print(json.dumps({**{k: v for k, v in report.items() if k != "failed"}, "failed": len(report["failed"]),
                      "status": status["status"], "warnings": status["warnings"]}, indent=2))
    for failure in report["failed"]:
        print(f"FAILED {failure['file']}: {failure['error']}")


if __name__ == "__main__":
    main()
