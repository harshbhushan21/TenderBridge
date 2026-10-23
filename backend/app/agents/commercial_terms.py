"""Commercial and legal clause risk register.

Finds the contract terms that bid teams negotiate (liability, PBG, payment,
SLA penalty cap, LD, termination, IP, subcontracting, price firmness), reads
the tender's value, and compares it with the company's approved positions via
`tools.commercial_rules`. Values already in key facts (which amendments
update) take precedence over re-reading the section text.
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.schemas.documents import SourceSpan
from backend.app.schemas.eligibility import RiskItem, RiskLevel, RiskPositionRecord
from backend.app.schemas.requirements import KeyFacts
from backend.app.tools.commercial_rules import assess_commercial_risk


def _section(sections: list[dict[str, Any]], *titles: str) -> dict[str, Any] | None:
    for section in sections:
        title = str(section.get("title") or "").lower()
        if any(t in title for t in titles):
            return section
    return None


def _num(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    return float(m.group(1)) if m else None


def _days(text: str | None) -> float | None:
    return _num(r"within\s+(\d+)\s+days", text or "")


def detect_commercial_risks(sections: list[dict[str, Any]], key_facts: KeyFacts | None,
                            positions: list[RiskPositionRecord], *, tender_id: str,
                            version: int) -> list[dict[str, Any]]:
    by_cat = {p.category: p for p in positions}
    items: list[dict[str, Any]] = []

    def add(category: str, section: dict[str, Any] | None, *, value: float | None = None,
            level: RiskLevel | None = None, tender_value: str = "", note: str = "",
            policy_key: str | None = None) -> None:
        if section is None:
            return
        position = by_cat.get(policy_key or category)
        if level is None:
            assessed = assess_commercial_risk(category, value, position)
            level = RiskLevel(assessed["level"])
        approver = position.approver if position else None
        items.append(RiskItem(
            risk_id=f"RISK-{category}", tender_id=tender_id, tender_version=version, category=category,
            level=level, tender_value=tender_value, policy_value=position.policy if position else
            "No approved company position: review required", summary=note or f"{category}: {tender_value}",
            approver=approver, approval_status="pending" if level is not RiskLevel.within_policy else "not_required",
            source=SourceSpan(doc_id=section.get("doc_id", "unknown"), page=section.get("page_start"),
                              section_path=section.get("section_path"), text_span=tender_value[:300],
                              tender_version=section.get("tender_version")),
        ).model_dump(mode="json"))

    kf = key_facts
    liability = _section(sections, "limitation of liability")
    if liability:
        text = str(liability.get("text") or "")
        if re.search(r"\bunlimited\b|\buncapped\b|shall not apply", text, re.IGNORECASE):
            add("unlimited_liability", liability, level=RiskLevel.escalate,
                tender_value="Cap at total contract value, but unlimited for gross negligence, data breach "
                             "and IP indemnity",
                note="Uncapped liability carve-outs: deal-breaker unless the MD & CEO approves with insurance")
        else:
            add("limitation_of_liability", liability, value=1.0, tender_value="Capped at contract value")

    pbg = _section(sections, "performance bank guarantee")
    pbg_value = kf.pbg_percent if kf and kf.pbg_percent is not None else _num(
        r"guarantee of\s+(\d+(?:\.\d+)?)\s*%", str((pbg or {}).get("text") or ""))
    add("performance_guarantee", pbg, value=pbg_value, tender_value=f"PBG {pbg_value:g}% of contract value"
        if pbg_value is not None else "PBG percentage not found")

    payment = _section(sections, "payment terms")
    days = _days(kf.payment_terms if kf else None) or _days(str((payment or {}).get("text") or ""))
    add("payment_terms", payment, value=days, tender_value=f"Quarterly in arrears within {days:g} days"
        if days is not None else "Payment period not found")

    sla = _section(sections, "service level agreement")
    cap = kf.penalty_cap_percent if kf and kf.penalty_cap_percent is not None else _num(
        r"capped at\s+(\d+(?:\.\d+)?)\s*%\s+of the qgr", str((sla or {}).get("text") or ""))
    add("sla_penalty_cap", sla, value=cap, tender_value=f"SLA penalties capped at {cap:g}% of QGR per quarter"
        if cap is not None else "SLA penalty cap not found")

    ld = _section(sections, "liquidated damages")
    ld_cap = _num(r"maximum of\s+(\d+(?:\.\d+)?)\s*%", str((ld or {}).get("text") or ""))
    add("liquidated_damages", ld, value=ld_cap, tender_value=f"LD capped at {ld_cap:g}%"
        if ld_cap is not None else "LD cap not found")

    termination = _section(sections, "termination")
    notice = _num(r"convenience[^.]*?(\d+)\s+days", str((termination or {}).get("text") or ""))
    add("termination_for_convenience", termination, value=notice,
        tender_value=f"{notice:g} days' notice for convenience" if notice is not None else "notice not found")

    ip = _section(sections, "intellectual property")
    if ip:
        text = str(ip.get("text") or "").lower()
        licensed = "pre-existing" in text and "licen" in text and "assign" not in text
        add("ip_ownership", ip, level=RiskLevel.within_policy if licensed else RiskLevel.review,
            tender_value="Deliverables owned by the buyer; pre-existing tools licensed" if licensed
            else "Pre-existing IP may transfer to the buyer")

    sub = _section(sections, "subcontracting")
    if sub:
        text = str(sub.get("text") or "").lower()
        approved = "prior" in text and "approval" in text
        add("subcontracting", sub, level=RiskLevel.within_policy if approved else RiskLevel.review,
            tender_value="Only with prior written approval; key roles never" if approved
            else "Subcontracting terms unclear")

    prices = _section(sections, "bid prices")
    if prices and re.search(r"\bfirm\b", str(prices.get("text") or ""), re.IGNORECASE):
        add("price_firmness", prices, level=RiskLevel.review,
            tender_value="Prices firm for the full contract; no wage or FX variation",
            note="Fixed prices for the contract term: no approved company position, so it needs review")
    return items


