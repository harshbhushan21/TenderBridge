"""Checkpoint selection with Postgres, SQLite, and in-memory fallbacks."""
from __future__ import annotations

from contextlib import ExitStack
from functools import lru_cache
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

log = get_logger(__name__)
_stack = ExitStack()


@lru_cache(maxsize=1)
def get_checkpointer() -> Any:
    settings = get_settings()
    url = settings.checkpoint_url
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
                return _stack.enter_context(SqliteSaver.from_conn_string(path))
        except (ImportError, OSError, RuntimeError) as exc:
            log.warning("configured checkpointer unavailable; using memory: %s", exc)
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
