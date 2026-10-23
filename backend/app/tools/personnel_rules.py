"""Personnel checks using the HR tracker-backed structured records."""
from __future__ import annotations

from datetime import date

from backend.app.schemas.eligibility import (
    Calculation,
    EligibilityStatus,
    PersonCert,
    PersonnelRule,
    PersonRecord,
    RuleResult,
)


def _proposed_role(person: PersonRecord) -> str:
    return str(person.extra.get("proposed_role") or "").lower()


def _matches_role(person: PersonRecord, role: str) -> bool:
    return role in person.role.lower() or role in _proposed_role(person)


def _is_alternate(person: PersonRecord) -> bool:
    """People proposed as an alternate are substitutes, not the primary candidate."""
    return "alternate" in _proposed_role(person)


def _cert_valid(cert: PersonCert | None, as_of: date) -> bool:
    # The HR tracker verdict (`valid`) wins over CV text; expiry is then checked on `as_of`.
    if cert is None or cert.valid is False:
        return False
    return cert.expiry_date is None or cert.expiry_date >= as_of


def check_personnel(people: list[PersonRecord], rule: PersonnelRule) -> RuleResult:
    """Count qualified, available people for a role.

    Qualification (years, certifications valid on `as_of`) and availability (by
    `available_by`) are separate: a person rolling off another project before
    takeover still qualifies at the bid deadline.
    """
    as_of = rule.as_of or date.today()
    role = rule.role.lower()
    required = [c.lower() for c in rule.required_certifications]
    any_of = [c.lower() for c in rule.any_of_certifications]

    candidates: list[dict] = []
    qualified: list[PersonRecord] = []
    for person in (p for p in people if _matches_role(p, role)):
        certs = {c.standard.lower(): c for c in person.certifications if c.standard}
        cert_ok = all(_cert_valid(certs.get(c), as_of) for c in required)
        any_ok = not any_of or any(_cert_valid(certs.get(c), as_of) for c in any_of)
        years_ok = person.years_experience >= rule.min_years
        available = person.available and (
            rule.available_by is None or person.available_from is None
            or person.available_from <= rule.available_by)
        ok = years_ok and cert_ok and any_ok and available
        candidates.append({
            "person_id": person.person_id, "qualified": ok, "alternate": _is_alternate(person),
            "years_ok": years_ok, "certifications_ok": cert_ok and any_ok, "available": available,
            "available_from": person.available_from,
        })
        if ok:
            qualified.append(person)

    primary_ok = [p for p in qualified if not _is_alternate(p)]
    calcs = [Calculation(label="certifications valid on", value=as_of.isoformat())]
    if rule.available_by:
        calcs.append(Calculation(label="available by", value=rule.available_by.isoformat()))

    if len(primary_ok) >= rule.count:
        return RuleResult(rule_kind="personnel", status=EligibilityStatus.meets,
                          summary=f"{len(primary_ok)} qualified {rule.role} available: "
                                  f"{', '.join(p.person_id for p in primary_ok)}.",
                          calculations=calcs, candidates=candidates)
    if len(qualified) >= rule.count:
        failed = [c["person_id"] for c in candidates if not c["qualified"] and not c["alternate"]]
        substitutes = [p.person_id for p in qualified if p not in primary_ok]
        return RuleResult(
            rule_kind="personnel", status=EligibilityStatus.meets_with_substitution,
            summary=(f"Primary {rule.role} candidate(s) {', '.join(failed) or '-'} do not qualify; "
                     f"substitute {', '.join(substitutes)} meets the requirement."),
            calculations=calcs, candidates=candidates,
            actions=[f"Propose {', '.join(substitutes)} as {rule.role}"
                     + (f" in place of {', '.join(failed)}" if failed else "")])
    return RuleResult(rule_kind="personnel", status=EligibilityStatus.gap,
                      summary=f"Fewer than {rule.count} qualified, available {rule.role} personnel found.",
                      calculations=calcs, candidates=candidates,
                      actions=[f"Identify or hire a qualified {rule.role}"],
                      needs_human_reason="no qualified candidate in the HR tracker")
