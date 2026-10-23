"""Shared pytest fixtures: isolated DB + temp demo_data/storage per session.

Tests never touch the dev database. They use a fresh SQLite file, or the
dedicated Postgres database in TEST_DATABASE_URL (`make test-pg`), which is
dropped and recreated at the start of the session.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="tenderbridge-tests-"))
_TEST_DB = os.environ.get("TEST_DATABASE_URL")
os.environ["DATABASE_URL"] = _TEST_DB or f"sqlite:///{_TMP / 'test.db'}"
os.environ["CHECKPOINT_URL"] = ""  # never the dev .env checkpointer: derive from the test DB
os.environ.setdefault("DEMO_DATA_DIR", str(_TMP / "demo_data"))
os.environ.setdefault("STORAGE_DIR", str(_TMP / "storage"))
os.environ.setdefault("LLM_FAST", "fake:fast")
os.environ.setdefault("LLM_STRONG", "fake:strong")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")
os.environ.setdefault("LANGSMITH_TRACING", "false")
(_TMP / "demo_data").mkdir(exist_ok=True)


def _clear_caches() -> None:
    from backend.app.core import config
    from backend.app.db import engine

    config.get_settings.cache_clear()
    engine.get_engine.cache_clear()
    engine._session_factory.cache_clear()
    try:
        from backend.app.llm import routing
        routing.get_routing_config.cache_clear()
    except Exception:
        pass
    try:
        from backend.app.retrieval import embeddings
        embeddings.get_embedder.cache_clear()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    _clear_caches()
    from backend.app.db.engine import init_db
    init_db(drop=bool(_TEST_DB))
    yield


@pytest.fixture
def tmp_root() -> Path:
    return _TMP


@pytest.fixture
def db_session():
    from backend.app.db.engine import session_scope
    with session_scope() as s:
        yield s
