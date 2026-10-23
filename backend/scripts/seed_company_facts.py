"""Seed structured company facts into SQL (idempotent; safe to re-run).

Usage: uv run python -m backend.scripts.seed_company_facts [--company-id NIMBUS-001] [--facts-dir PATH]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.db.engine import init_db, session_scope
from backend.app.knowledge.kb_seed import seed_company_facts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company-id", default=None,
                        help="must match company.json (default: the id in company.json)")
    parser.add_argument("--facts-dir", type=Path, default=None,
                        help="default: $DEMO_DATA_DIR/structured_facts")
    args = parser.parse_args()
    init_db()
    with session_scope() as session:
        result = seed_company_facts(session, args.company_id, facts_dir=args.facts_dir)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
