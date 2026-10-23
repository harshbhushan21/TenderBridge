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

ROLES = ("viewer", "bid_manager", "reviewer", "admin")
# Which KB `allowed_roles` a caller role may read.
ROLE_HIERARCHY: dict[str, set[str]] = {
    "viewer": {"viewer", "all"},
    "bid_manager": {"viewer", "bid_manager", "all"},
    "reviewer": {"viewer", "bid_manager", "reviewer", "all"},
    "admin": {"viewer", "bid_manager", "reviewer", "admin", "hr", "finance", "legal", "all"},
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


def role_can_read(role: str, allowed_roles: list[str] | None) -> bool:
    if not allowed_roles:
        return True
    visible = ROLE_HIERARCHY.get(role, {"viewer", "all"})
    return bool(visible.intersection(allowed_roles))


async def get_current_user(
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> CurrentUser:
    role = x_role if x_role in ROLES else "bid_manager"
    return CurrentUser(user_id=x_user or "bid.manager@nimbus.example", role=role)


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
