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
        if rule.undertaking_acceptable:
            # The tender accepts an undertaking instead (e.g. PQ-9 local office): it
            # passes now, with an obligation the bid team must sign and honour.
            return RuleResult(rule_kind="document", status=EligibilityStatus.meets_with_undertaking,
                              summary=f"'{rule.document_type}' not held; the tender accepts an undertaking.",
                              actions=[f"Sign the undertaking for {rule.document_type}"])
        if rule.tender_specific:
            # Issued per tender (e.g. bid-specific OEM MAF): obtainable before
            # submission, so it is an action, not a disqualifying gap.
            return RuleResult(rule_kind="document", status=EligibilityStatus.needs_action,
                              summary=f"Tender-specific '{rule.document_type}' not yet obtained.",
                              actions=[f"Obtain {rule.document_type} for this tender before submission"])
        return RuleResult(rule_kind="document", status=EligibilityStatus.gap,
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
