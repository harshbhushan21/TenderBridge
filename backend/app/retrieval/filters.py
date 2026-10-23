"""Shared pre-ranking filters for both retrieval scopes.

Filters are applied before any scoring (principle: a chunk a role may not read
is never ranked). On Postgres they run in SQL; on SQLite the role filter runs
in Python on the candidate rows, still before ranking.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, literal, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from backend.app.core.errors import ToolError
from backend.app.core.security import readable_tags, role_can_read
from backend.app.db import models as m
from backend.app.schemas.documents import Scope


@dataclass
class SearchFilters:
    scope: Scope
    tender_id: str | None = None
    version: int | None = None
    company_id: str | None = None
    role: str = "bid_manager"
    doc_types: list[str] | None = None
    approved_only: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.scope is Scope.tender and (not self.tender_id or self.version is None):
            raise ToolError("tender-scope search requires tender_id and version")
        if self.scope is Scope.kb and not self.company_id:
            raise ToolError("company-scope search requires company_id")

    @property
    def model(self) -> Any:
        return m.TenderChunk if self.scope is Scope.tender else m.KbChunk


def is_postgres(session: Session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def candidate_query(session: Session, f: SearchFilters) -> Select:
    """Searchable (child, non-quarantined) chunks visible under the filters."""
    model = f.model
    stmt = select(model).where(model.is_parent.is_(False))
    if f.scope is Scope.tender:
        stmt = stmt.where(model.tender_id == f.tender_id, model.version <= f.version,
                          model.quarantined.is_(False))
    else:
        stmt = stmt.where(model.company_id == f.company_id)
        if f.doc_types:
            stmt = stmt.where(model.doc_type.in_(f.doc_types))
        if f.approved_only:
            stmt = stmt.where(model.approved_for_reuse.is_(True))
        if is_postgres(session):
            tags = sorted(readable_tags(f.role))
            stmt = stmt.where(model.allowed_roles.cast(JSONB).op("?|")(literal(tags, ARRAY(String))))
    return stmt


def visible(row: Any, f: SearchFilters) -> bool:
    """Python-side role check (SQLite path, and defence in depth on Postgres)."""
    return f.scope is Scope.tender or role_can_read(f.role, row.allowed_roles)
