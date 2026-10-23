"""Checkpoint selection with Postgres, SQLite, and in-memory fallbacks."""
from __future__ import annotations

from contextlib import ExitStack
from functools import lru_cache
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

log = get_logger(__name__)
_stack = ExitStack()


def _checkpoint_url() -> str:
    """CHECKPOINT_URL, or by default the app database (Postgres) or a SQLite file in
    storage/, so a run paused at Gate 1 survives an API restart without extra setup."""
    settings = get_settings()
    if settings.checkpoint_url:
        return settings.checkpoint_url
    if settings.is_postgres:
        return settings.database_url
    return f"sqlite:///{(settings.storage_dir / 'checkpoints.sqlite').as_posix()}"


@lru_cache(maxsize=1)
def get_checkpointer() -> Any:
    url = _checkpoint_url()
    saver: Any
    if url:
        try:
            if url.startswith("postgresql"):
                from langgraph.checkpoint.postgres import PostgresSaver
                saver = _stack.enter_context(PostgresSaver.from_conn_string(url.replace("+psycopg", "")))
                saver.setup()
                return saver
            if url.startswith("sqlite"):
                from langgraph.checkpoint.sqlite import SqliteSaver
                path = url.removeprefix("sqlite:///")
                saver = _stack.enter_context(SqliteSaver.from_conn_string(path))
                saver.setup()
                return saver
        except (ImportError, OSError, RuntimeError) as exc:
            log.warning("configured checkpointer unavailable; using memory: %s", exc)
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
