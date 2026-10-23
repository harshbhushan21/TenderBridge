"""Deterministic company-registration and tender-document checks."""
from __future__ import annotations

from backend.app.schemas.eligibility import (
    CompanyProfile,
    DocumentPresenceRule,
    EligibilityStatus,
    RuleResult,
)


def check_registration(company: CompanyProfile, document_types: set[str] | None = None,
                       rule: DocumentPresenceRule | None = None) -> RuleResult:
    """Check company facts and optional tender-document presence."""
    docs = document_types or set()
    if rule:
        present = rule.document_type in docs
        if present:
            return RuleResult(rule_kind="document", status=EligibilityStatus.meets,
                              summary=f"Required document '{rule.document_type}' is present.")
        status = EligibilityStatus.needs_action if rule.undertaking_acceptable else EligibilityStatus.gap
        return RuleResult(rule_kind="document", status=status,
                          summary=f"Required document '{rule.document_type}' is missing.",
                          actions=[f"Obtain {rule.document_type} before submission"])
    if company.blacklisted:
        return RuleResult(rule_kind="registration", status=EligibilityStatus.gap,
                          summary="Company is recorded as blacklisted or debarred.")
    msme = company.extra.get("msme") or {}
    if company.is_mse and not msme.get("valid", True):
        return RuleResult(rule_kind="registration", status=EligibilityStatus.gap,
                          summary="MSE status is not valid.")
    return RuleResult(rule_kind="registration", status=EligibilityStatus.meets,
                      summary="Company registration and declarations are acceptable.")
