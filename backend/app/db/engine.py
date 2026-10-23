"""SQLAlchemy engine/session management (PostgreSQL+pgvector or SQLite fallback)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if s.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(s.database_url, **kwargs)
    if s.is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


def get_session() -> Session:
    return _session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_dependency() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as s:
        yield s


def init_db(drop: bool = False) -> None:
    """Create extension (postgres) and all tables. Alembic migrations can replace this."""
    from backend.app.db import models  # noqa: F401  (register models)
    from backend.app.db.models import Base

    engine = get_engine()
    if get_settings().is_postgres:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    if drop:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    if get_settings().is_postgres:
        _create_pg_indexes(engine)


def _create_pg_indexes(engine: Engine) -> None:
    stmts = [
        "CREATE INDEX IF NOT EXISTS ix_kb_chunks_tsv ON kb_chunks USING GIN (to_tsvector('english', text))",
        "CREATE INDEX IF NOT EXISTS ix_tender_chunks_tsv ON tender_chunks USING GIN (to_tsvector('english', text))",
    ]
    with engine.begin() as conn:
        for st in stmts:
            conn.execute(text(st))


def check_db() -> dict:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            info = {"ok": True, "dialect": get_engine().dialect.name}
            if get_settings().is_postgres:
                r = conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).first()
                info["pgvector"] = bool(r)
            return info
    except Exception as exc:  # pragma: no cover - depends on environment
        return {"ok": False, "error": str(exc)}
