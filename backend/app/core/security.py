"""Roles, reviewer identity and path-safety helpers.

The demo has no real auth: identity comes from `X-User` / `X-Role` headers
with safe defaults. Swap `get_current_user` for real auth later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import Header

from backend.app.core.errors import FileRejected, PermissionDenied

ROLES = ("analyst", "writer", "bid_manager", "admin")
DEFAULT_ROLE = "bid_manager"     # demo default when no X-Role header is sent
FALLBACK_ROLE = "analyst"        # unknown X-Role values get the least privilege
# Roles that may decide Gate 1, approve Gate 2 and confirm amendments (decision D3).
APPROVER_ROLES = ("bid_manager", "admin")
# Which KB `allowed_roles` tags a caller role may read. `hr`, `finance` and
# `legal` are data scopes from the data pack, not login roles.
ROLE_HIERARCHY: dict[str, set[str]] = {
    "analyst": {"analyst", "all"},
    "writer": {"writer", "analyst", "all"},
    "bid_manager": {"analyst", "writer", "bid_manager", "hr", "finance", "legal", "all"},
    "admin": {"analyst", "writer", "bid_manager", "admin", "hr", "finance", "legal", "all"},
}


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    role: str

    def can_read(self, allowed_roles: list[str] | None) -> bool:
        return role_can_read(self.role, allowed_roles)

    def require(self, *roles: str) -> None:
        if self.role not in roles and self.role != "admin":
            raise PermissionDenied(f"role '{self.role}' cannot perform this action")

    @property
    def can_approve(self) -> bool:
        return self.role in APPROVER_ROLES

    def require_approver(self) -> None:
        self.require(*APPROVER_ROLES)


def role_can_read(role: str, allowed_roles: list[str] | None) -> bool:
    if not allowed_roles:
        return True
    visible = ROLE_HIERARCHY.get(role, ROLE_HIERARCHY[FALLBACK_ROLE])
    return bool(visible.intersection(allowed_roles))


def resolve_role(x_role: str | None) -> str:
    if not x_role:
        return DEFAULT_ROLE
    role = x_role.strip().lower()
    return role if role in ROLES else FALLBACK_ROLE


async def get_current_user(
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> CurrentUser:
    return CurrentUser(user_id=x_user or "bid.manager@nimbus.example", role=resolve_role(x_role))


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """Strip directories and unsafe characters; never trust client filenames."""
    base = Path(name.replace("\\", "/")).name
    base = _SAFE_NAME.sub("_", base).strip("._") or "file"
    return base[:180]


def ensure_within(base: Path, candidate: Path) -> Path:
    """Raise if `candidate` escapes `base` (path traversal guard)."""
    base_r = base.resolve()
    cand_r = candidate.resolve()
    if cand_r != base_r and base_r not in cand_r.parents:
        raise FileRejected("path traversal detected", details={"path": str(candidate)})
    return cand_r
