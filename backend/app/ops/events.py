"""Run/tender events: persisted `RunEvent` rows + thread-safe in-process pub/sub.

Graph nodes run in worker threads; SSE subscribers live on the asyncio loop.
Publishing uses `loop.call_soon_threadsafe` so any thread may emit.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger

log = get_logger(__name__)

EVENT_TYPES = (
    "run_started", "node_started", "node_completed", "node_failed", "human_review_required",
    "run_completed", "run_failed", "amendment_diff_ready", "budget_exceeded", "file_status",
)

_lock = threading.Lock()
# key (run_id or tender_id) -> list of (loop, queue)
_subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}


def _persist(event: dict[str, Any]) -> int | None:
    try:
        from backend.app.db.engine import session_scope
        from backend.app.db.models import RunEvent
        with session_scope() as s:
            row = RunEvent(
                run_id=event.get("analysis_run_id") or "",
                tender_id=event.get("tender_id") or "",
                event=event["event"], node=event.get("node"), status=event.get("status"),
                message=event.get("message"),
                payload={**(event.get("payload") or {}), "tender_version": event.get("tender_version")},
            )
            s.add(row)
            s.flush()
            return row.id
    except Exception as exc:  # events must never break a run
        log.warning("failed to persist event: %s", exc)
        return None


def _publish(key: str | None, event: dict[str, Any]) -> None:
    if not key:
        return
    with _lock:
        subs = list(_subscribers.get(key, []))
    for loop, queue in subs:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except RuntimeError:  # loop closed
            pass


def emit_event(*, run_id: str | None, tender_id: str | None, version: int | None, event: str,
               node: str | None = None, status: str | None = None, message: str | None = None,
               payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "event": event, "tender_id": tender_id, "tender_version": version,
        "analysis_run_id": run_id, "node": node, "status": status, "message": message,
        "payload": payload or {}, "ts": datetime.now(UTC).isoformat(),
    }
    data["id"] = _persist(data)
    _publish(run_id, data)
    if tender_id and tender_id != run_id:
        _publish(tender_id, data)
    return data


def open_subscription(key: str) -> tuple[asyncio.Queue, Callable[[], None]]:
    """Register a queue on the running loop. Returns (queue, close). Call from async code."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    entry = (loop, queue)
    with _lock:
        _subscribers.setdefault(key, []).append(entry)

    def close() -> None:
        with _lock:
            lst = _subscribers.get(key, [])
            if entry in lst:
                lst.remove(entry)
            if not lst:
                _subscribers.pop(key, None)

    return queue, close


async def subscribe(key: str) -> AsyncIterator[dict[str, Any]]:
    """Yield events for a run_id or tender_id until the consumer stops iterating."""
    queue, close = open_subscription(key)
    try:
        while True:
            yield await queue.get()
    finally:
        close()


def row_to_event(row) -> dict[str, Any]:
    payload = dict(row.payload or {})
    version = payload.pop("tender_version", None)
    return {
        "id": row.id, "event": row.event, "tender_id": row.tender_id, "tender_version": version,
        "analysis_run_id": row.run_id or None, "node": row.node, "status": row.status,
        "message": row.message, "payload": payload,
        "ts": row.created_at.isoformat() if row.created_at else None,
    }


def list_events(session: Session, run_id: str | None = None, after_id: int = 0, *,
                tender_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    from backend.app.db.models import RunEvent
    q = select(RunEvent).where(RunEvent.id > after_id)
    if run_id:
        q = q.where(RunEvent.run_id == run_id)
    if tender_id:
        q = q.where(RunEvent.tender_id == tender_id)
    rows = session.scalars(q.order_by(RunEvent.id).limit(limit)).all()
    return [row_to_event(r) for r in rows]
