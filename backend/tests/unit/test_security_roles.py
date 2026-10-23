"""Phase 1: roles match the data pack's allowed_roles tags (decision D3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.errors import PermissionDenied
from backend.app.core.security import CurrentUser, resolve_role, role_can_read

MANIFEST = Path(__file__).resolve().parents[3] / "demo_data" / "demo_config" / "company_manifest.json"


def _docs():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("documents", [])


def test_bid_manager_reads_every_kb_document():
    assert all(role_can_read("bid_manager", d["allowed_roles"]) for d in _docs())


def test_analyst_cannot_read_finance_hr_or_legal_only_docs():
    for doc in _docs():
        tags = set(doc["allowed_roles"])
        expected = bool(tags & {"analyst"})
        assert role_can_read("analyst", doc["allowed_roles"]) is expected, doc.get("doc_id")
    assert not role_can_read("analyst", ["bid_manager", "legal"])


def test_writer_reads_writer_and_analyst_docs():
    assert role_can_read("writer", ["bid_manager", "writer"])
    assert role_can_read("writer", ["bid_manager", "analyst"])
    assert not role_can_read("writer", ["bid_manager", "finance"])


@pytest.mark.parametrize("header, role", [(None, "bid_manager"), ("Analyst", "analyst"),
                                          ("viewer", "analyst"), ("root", "analyst")])
def test_resolve_role_defaults_and_least_privilege(header, role):
    assert resolve_role(header) == role


def test_only_bid_manager_or_admin_can_approve():
    CurrentUser("bm", "bid_manager").require_approver()
    CurrentUser("adm", "admin").require_approver()
    for role in ("analyst", "writer"):
        user = CurrentUser("u", role)
        assert not user.can_approve
        with pytest.raises(PermissionDenied):
            user.require_approver()
