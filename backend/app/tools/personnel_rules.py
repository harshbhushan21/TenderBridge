"""Personnel checks using the HR tracker-backed structured records."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from backend.app.schemas.eligibility import (
    Calculation,
    EligibilityStatus,
    PersonnelRule,
    PersonRecord,
    RuleResult,
)


def check_personnel(people: list[PersonRecord], rule: PersonnelRule) -> RuleResult:
    as_of = rule.as_of or date.today()
    matches = [p for p in people if rule.role.lower() in p.role.lower() or
               rule.role.lower() in (p.extra.get("proposed_role", "") or "").lower()]
    valid: list[PersonRecord] = []
    candidates: list[dict] = []

    def cert_is_valid(cert_name: str, certs: Mapping[str, object]) -> bool:
        cert = certs.get(cert_name)
        if cert is None:
            return False
        expiry = getattr(cert, "expiry_date", None)
        return getattr(cert, "valid", None) is not False and (expiry is None or expiry >= as_of)

    for person in matches:
        certs = {c.standard.lower(): c for c in person.certifications if c.standard}
        required = [c.lower() for c in rule.required_certifications]
        any_required = [c.lower() for c in rule.any_of_certifications]
        cert_ok = all(cert_is_valid(c, certs) for c in required)
        any_ok = not any_required or any(cert_is_valid(c, certs) for c in any_required)
        qualified = person.years_experience >= rule.min_years and cert_ok and any_ok
        candidates.append({"person_id": person.person_id, "qualified": qualified,
                           "available": person.available, "available_from": person.available_from})
        if qualified and person.available and (person.available_from is None or person.available_from <= as_of):
            valid.append(person)
    if len(valid) >= rule.count:
        return RuleResult(rule_kind="personnel", status=EligibilityStatus.meets,
                          summary=f"{len(valid)} qualified personnel meet the {rule.role} requirement.",
                          candidates=candidates)
    replacement = "NDS-E110" if rule.role.lower() in {"security lead", "cybersecurity lead"} else None
    actions = [f"Propose replacement personnel {replacement}"] if replacement else []
    status = EligibilityStatus.needs_action if replacement else EligibilityStatus.gap
    return RuleResult(rule_kind="personnel", status=status,
                      summary=f"Fewer than {rule.count} available qualified {rule.role} personnel found.",
                      calculations=[Calculation(label="as of", value=as_of.isoformat())],
                      candidates=candidates, actions=actions,
                      needs_human_reason="HR tracker certification/availability must be reviewed")
