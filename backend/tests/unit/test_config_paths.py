"""Phase 1: paths resolve from the project root on any machine and any cwd."""
from __future__ import annotations

from pathlib import Path

from backend.app.core.config import Settings

ROOT = Path(__file__).resolve().parents[3]


def test_relative_sqlite_url_is_anchored_at_project_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # run from somewhere else entirely
    s = Settings(DATABASE_URL="sqlite:///storage/x.db", CHECKPOINT_URL="sqlite:///storage/cp.db")
    assert s.database_url == f"sqlite:///{(ROOT / 'storage' / 'x.db').as_posix()}"
    assert s.checkpoint_url == f"sqlite:///{(ROOT / 'storage' / 'cp.db').as_posix()}"


def test_absolute_memory_and_postgres_urls_unchanged():
    pg = "postgresql+psycopg://u:p@localhost:5433/db"
    assert Settings(DATABASE_URL=pg).database_url == pg
    assert Settings(DATABASE_URL="sqlite:///:memory:").database_url == "sqlite:///:memory:"
    absolute = f"sqlite:///{(ROOT / 'a.db').as_posix()}"
    assert Settings(DATABASE_URL=absolute).database_url == absolute


def test_relative_data_dirs_resolve_from_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = Settings(DEMO_DATA_DIR="demo_data", STORAGE_DIR="storage")
    assert s.demo_data_dir == ROOT / "demo_data"
    assert s.storage_dir == ROOT / "storage"
