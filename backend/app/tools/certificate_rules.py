"""Certification validity checks against the applicable date and scope."""
from __future__ import annotations

import re
from datetime import date

from backend.app.schemas.eligibility import (
    Calculation,
    CertificateRecord,
    CertificateStatus,
    CertificationRule,
    EligibilityStatus,
    RuleResult,
)
from backend.app.schemas.requirements import KeyFacts

_STANDARD_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"iso\s*/?\s*(?:iec\s*)?27001", re.I), "ISO27001"),
    (re.compile(r"iso\s*/?\s*(?:iec\s*)?20000(?:-1)?", re.I), "ISO20000"),
    (re.compile(r"iso\s*/?\s*(?:iec\s*)?27017", re.I), "ISO27017"),
    (re.compile(r"iso\s*/?\s*(?:iec\s*)?27018", re.I), "ISO27018"),
    (re.compile(r"iso\s*/?\s*(?:iec\s*)?22301", re.I), "ISO22301"),
    (re.compile(r"iso\s*14001", re.I), "ISO14001"),
    (re.compile(r"iso\s*45001", re.I), "ISO45001"),
    (re.compile(r"iso\s*9001", re.I), "ISO9001"),
    (re.compile(r"cmmi(?:[\s\-]*(?:dev|svc|services)?)?[\s\-]*(?:ml|level|maturity\s*level)?\s*[-:]?\s*([2-5])", re.I), "CMMI{0}"),
    (re.compile(r"\bcmmi\b", re.I), "CMMI"),
    (re.compile(r"soc\s*2", re.I), "SOC2"),
    (re.compile(r"pci[\s\-]*dss", re.I), "PCIDSS"),
    (re.compile(r"\bstqc\b", re.I), "STQC"),
    (re.compile(r"meity\s*empanel", re.I), "MEITY_EMPANELMENT"),
    # personnel certifications
    (re.compile(r"\bpmp\b", re.I), "PMP"),
    (re.compile(r"\bprince\s*2\b", re.I), "PRINCE2"),
    (re.compile(r"\bcissp\b", re.I), "CISSP"),
    (re.compile(r"\bcism\b", re.I), "CISM"),
    (re.compile(r"\bcisa\b", re.I), "CISA"),
    (re.compile(r"\bitil\b", re.I), "ITIL"),
    (re.compile(r"\bccna\b", re.I), "CCNA"),
    (re.compile(r"\bccnp\b", re.I), "CCNP"),
    (re.compile(r"\bccie\b", re.I), "CCIE"),
    (re.compile(r"\brhce\b", re.I), "RHCE"),
    (re.compile(r"\bmcse\b", re.I), "MCSE"),
    (re.compile(r"\bvcp\b", re.I), "VCP"),
    (re.compile(r"\bceh\b", re.I), "CEH"),
]


def normalize_standard(name: str | None) -> str:
    """'ISO/IEC 27001:2022' -> 'ISO27001'; 'CMMI Level 3' -> 'CMMI3'; 'PMP' -> 'PMP'."""
    if not name:
        return ""
    for pat, key in _STANDARD_PATTERNS:
        m = pat.search(name)
        if m:
            if "{0}" in key:
                return key.format(m.group(1))
            return key
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def find_standards(text: str) -> list[str]:
    found: list[str] = []
    for pat, key in _STANDARD_PATTERNS:
        for m in pat.finditer(text or ""):
            k = key.format(m.group(1)) if "{0}" in key else key
            if k == "CMMI" and any(f.startswith("CMMI") for f in found):
                continue
            if k not in found:
                found.append(k)
    return found


def _standard_matches(record_std: str, required: str) -> bool:
    if record_std == required:
        return True
    # CMMI3 satisfies CMMI3 or CMMI; CMMI5 satisfies CMMI3 (higher maturity level)
    if required.startswith("CMMI") and record_std.startswith("CMMI"):
        r_lvl = required[4:] or "0"
        c_lvl = record_std[4:] or "0"
        return c_lvl.isdigit() and r_lvl.isdigit() and int(c_lvl) >= int(r_lvl)
    return False


def _applicable_date(rule: CertificationRule, key_facts: KeyFacts | None) -> tuple[date | None, str]:
    if rule.valid_on == "date" and rule.valid_on_date:
        return rule.valid_on_date, "specified date"
    if key_facts:
        if rule.valid_on == "bid_opening" and key_facts.bid_opening:
            return key_facts.bid_opening.date(), "bid opening"
        if key_facts.submission_deadline:
            return key_facts.submission_deadline.date(), "bid submission deadline"
    if rule.valid_on_date:
        return rule.valid_on_date, "specified date"
    return None, rule.valid_on.replace("_", " ")


def check_certification(certs: list[CertificateRecord], rule: CertificationRule,
                        key_facts: KeyFacts | None) -> RuleResult:
    required = normalize_standard(rule.standard) or rule.standard
    label = rule.display_name or rule.standard
    as_of, as_of_label = _applicable_date(rule, key_facts)
    calcs = [Calculation(label="required standard", value=label),
             Calculation(label="validity required on", value=f"{as_of_label}: {as_of or 'unknown'}")]
    matches = [c for c in certs if _standard_matches(c.standard and normalize_standard(c.standard)
                                                     or normalize_standard(c.name), required)]
    if not matches:
        return RuleResult(rule_kind="certification", status=EligibilityStatus.gap,
                          summary=f"No {label} certificate on record.", calculations=calcs,
                          actions=[f"Confirm whether {label} is held; it is not in the certification register"])

    evidence = [c.source for c in matches if c.source]
    if as_of is None:
        return RuleResult(rule_kind="certification", status=EligibilityStatus.needs_human,
                          summary=f"{label} found but the applicable validity date is unknown.",
                          calculations=calcs, evidence=evidence,
                          unknowns=["submission_deadline"], needs_human_reason="validity date unknown")

    best_reason = ""
    best_status = EligibilityStatus.gap
    candidates = []
    for c in matches:
        cand = {"cert_id": c.cert_id, "name": c.name, "status": c.status.value,
                "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
                "scope": c.scope}
        candidates.append(cand)
        if c.status == CertificateStatus.not_held:
            best_reason = best_reason or f"{label} is recorded as not held."
            continue
        if c.status == CertificateStatus.in_progress:
            if rule.accept_in_progress:
                best_status = EligibilityStatus.meets_with_undertaking
                best_reason = f"{label} audit in progress; tender accepts in-progress certification."
            else:
                best_reason = best_reason or (f"{label} audit is in progress — the tender does not accept "
                                              f"in-progress certification.")
            continue
        if c.status == CertificateStatus.suspended:
            best_reason = best_reason or f"{label} certificate is suspended."
            continue
        if c.expiry_date is None:
            best_status = max(best_status, EligibilityStatus.needs_human, key=_rank)
            best_reason = best_reason or f"{label} expiry date not recorded."
            continue
        calcs.append(Calculation(label=f"{c.cert_id} expiry", value=c.expiry_date.isoformat()))
        if c.expiry_date < as_of:
            days = (as_of - c.expiry_date).days
            best_reason = best_reason or (f"{label} ({c.cert_id}) expires {c.expiry_date.isoformat()}, "
                                          f"{days} day(s) before the {as_of_label} ({as_of.isoformat()}).")
            continue
        # valid on date — scope check
        if rule.required_scope_keywords:
            scope = (c.scope or "").lower()
            missing = [k for k in rule.required_scope_keywords if k.lower() not in scope]
            if missing:
                if _rank(EligibilityStatus.needs_human) > _rank(best_status):
                    best_status = EligibilityStatus.needs_human
                    best_reason = (f"{label} valid until {c.expiry_date.isoformat()} but scope does not "
                                   f"mention: {', '.join(missing)}.")
                continue
        margin = (c.expiry_date - as_of).days
        return RuleResult(
            rule_kind="certification", status=EligibilityStatus.meets,
            summary=(f"{label} ({c.cert_id}) valid until {c.expiry_date.isoformat()}, covering the "
                     f"{as_of_label} {as_of.isoformat()} ({margin} day(s) margin)."),
            calculations=calcs + [Calculation(label="margin days", value=margin)],
            evidence=[c.source] if c.source else evidence, candidates=candidates,
            actions=([f"{label} expires within 30 days of the deadline; plan surveillance/renewal"]
                     if margin < 30 else []))

    actions = []
    if best_status == EligibilityStatus.gap:
        actions.append(f"Renew/obtain {label} before {as_of.isoformat()} or record a no-bid")
    return RuleResult(rule_kind="certification", status=best_status,
                      summary=best_reason or f"{label} not valid on {as_of.isoformat()}.",
                      calculations=calcs, evidence=evidence, candidates=candidates, actions=actions,
                      needs_human_reason=best_reason if best_status == EligibilityStatus.needs_human else None)


_ORDER = [EligibilityStatus.gap, EligibilityStatus.needs_human, EligibilityStatus.partial,
          EligibilityStatus.needs_action, EligibilityStatus.meets_with_undertaking,
          EligibilityStatus.meets_with_substitution, EligibilityStatus.meets]


def _rank(s: EligibilityStatus) -> int:
    return _ORDER.index(s)
