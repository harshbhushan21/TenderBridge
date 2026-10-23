"""Append-only audit trail."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger

log = get_logger(__name__)


def audit(actor: str, action: str, *, tender_id: str | None = None, version: int | None = None,
          run_id: str | None = None, target: str | None = None, session: Session | None = None,
          **detail: Any) -> None:
    """Record an audit entry. Uses `session` when given (same transaction), else its own."""
    from backend.app.db.models import AuditLog
    from backend.app.ops.langsmith import redact

    row = AuditLog(actor=actor, action=action, tender_id=tender_id, version=version, run_id=run_id,
                   target=target, detail=redact(detail))
    try:
        if session is not None:
            session.add(row)
            return
        from backend.app.db.engine import session_scope
        with session_scope() as s:
            s.add(row)
    except Exception as exc:
        log.warning("audit write failed: %s", exc)


def list_audit(session: Session, tender_id: str, limit: int = 500) -> list[dict[str, Any]]:
    from backend.app.db.models import AuditLog
    rows = session.scalars(select(AuditLog).where(AuditLog.tender_id == tender_id)
                           .order_by(AuditLog.ts.desc()).limit(limit)).all()
    return [{"ts": r.ts.isoformat() if r.ts else None, "actor": r.actor, "action": r.action,
             "version": r.version, "run_id": r.run_id, "target": r.target, "detail": r.detail}
            for r in rows]
