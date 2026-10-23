"""Create the database schema (and the pgvector extension on Postgres).

Usage: uv run python -m backend.scripts.init_db [--drop]
"""
from __future__ import annotations

import argparse
import json

from backend.app.core.config import get_settings
from backend.app.db.engine import check_db, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drop", action="store_true",
                        help="drop all tables first (destroys local data)")
    args = parser.parse_args()
    init_db(drop=args.drop)
    print(json.dumps({"database_url": get_settings().database_url.split("@")[-1], **check_db()}))


if __name__ == "__main__":
    main()
