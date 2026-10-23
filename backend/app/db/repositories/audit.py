"""Audit trail access for the API layer (writes and reads live in ops.audit)."""
from backend.app.ops.audit import audit as record_audit
from backend.app.ops.audit import list_audit

__all__ = ["list_audit", "record_audit"]
