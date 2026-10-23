"""Deterministic query rewrite: expand procurement acronyms and phrasing (no LLM call).

"Is Nimbus an MSE?" must match a Udyam record that says "Micro, Small and
Medium Enterprises". Expansions are appended, so exact acronym hits still count.
"""
from __future__ import annotations

import re

ACRONYMS: dict[str, str] = {
    "MSE": "micro small enterprise MSME Udyam registration",
    "MSME": "micro small medium enterprise Udyam",
    "EMD": "earnest money deposit bid security",
    "PBG": "performance bank guarantee",
    "SLA": "service level agreement penalty",
    "QGR": "quarterly guaranteed revenue payment",
    "RPO": "recovery point objective",
    "RTO": "recovery time objective",
    "DR": "disaster recovery",
    "DC": "data centre",
    "NOC": "network operations centre",
    "SOC": "security operations centre",
    "MAF": "manufacturer authorisation form OEM",
    "OEM": "original equipment manufacturer",
    "PQ": "pre-qualification",
    "NIT": "notice inviting tender",
    "RFP": "request for proposal",
    "BoQ": "bill of quantities price schedule",
    "CA": "chartered accountant",
    "PoA": "power of attorney",
    "LoA": "letter of award",
    "QCBS": "quality and cost based selection",
    "CMMI": "capability maturity model integration maturity level",
    "ISMS": "information security management system ISO 27001",
    "PMP": "project management professional",
    "CISSP": "certified information systems security professional",
    "CISM": "certified information security manager",
    "ITSM": "IT service management",
    "EMS": "enterprise management system monitoring",
    "NMS": "network management system",
    "CERT-In": "Indian computer emergency response team incident reporting",
}
# How tenders phrase things users ask about in other words (lowercase keys).
PHRASES: dict[str, str] = {
    "limit": "not exceed maximum cap",
    "deadline": "last date submission end date",
    "due": "last date submission end date",
    "exempt": "exemption exempted",
    "penalty": "penalties deduction liquidated damages",
    "experience": "similar works completed",
    "valid": "validity valid as on",
    "expire": "expiry valid until",
    "expires": "expiry valid until",
}
_WORD = re.compile(r"[A-Za-z][A-Za-z\-]*")
_LOOKUP = {k.lower(): v for k, v in ACRONYMS.items()}


def expand_query(query: str) -> str:
    extra = []
    for token in dict.fromkeys(_WORD.findall(query)):
        exp = _LOOKUP.get(token.lower())
        if exp and (token.isupper() or token in ACRONYMS):
            extra.append(exp)
        elif token.lower() in PHRASES:
            extra.append(PHRASES[token.lower()])
    return f"{query} {' '.join(extra)}" if extra else query
