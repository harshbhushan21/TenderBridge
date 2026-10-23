"""Explicit tool policy for agent nodes.

Safety-sensitive nodes may only call deterministic local tools. Outbound
networking and side effects require an explicit human-approved service path.
"""
from __future__ import annotations

from collections.abc import Iterable

ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    "extract_key_facts": frozenset({"facts.read", "citation.check"}),
    "route_requirements": frozenset({"rules.evaluate", "retrieval.search", "citation.check"}),
    "eligibility_and_risk": frozenset({"rules.evaluate", "facts.read", "citation.check"}),
    "bid_score": frozenset({"rules.evaluate", "policy.score"}),
    "claim_verifier": frozenset({"citation.check", "llm.semantic_support"}),
}
OUTBOUND_ACTIONS = frozenset({"email.send", "http.post", "file.delete", "shell.execute", "db.write"})


def is_allowed(node: str, tool: str) -> bool:
    return tool in ALLOWED_TOOLS.get(node, frozenset())


def assert_allowed(node: str, tools: Iterable[str]) -> None:
    requested = set(tools)
    denied = sorted(requested - ALLOWED_TOOLS.get(node, frozenset()) - OUTBOUND_ACTIONS)
    outbound = sorted(requested & OUTBOUND_ACTIONS)
    if outbound:
        raise PermissionError(f"outbound actions are not allowed for node '{node}': {outbound}")
    if denied:
        raise PermissionError(f"tools are not allowlisted for node '{node}': {denied}")
