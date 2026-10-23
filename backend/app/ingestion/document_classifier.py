"""Rule-based classification of tender files and KB documents (no LLM needed)."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from backend.app.schemas.documents import TenderDocRole

# Checked in order against the first page; the first match wins.
_TENDER_TEXT_RULES: list[tuple[re.Pattern, TenderDocRole]] = [
    # A corrigendum names itself ("Corrigendum No. 1") or lists amendments; a passing
    # mention ("refer to any corrigendum") does not make a document one.
    (re.compile(r"\b(corrigendum|addendum)\s+(no\.?|number)\s*\d+|\bamendments?\s+(are\s+made\s+)?to\s+the\s+rfp\b",
                re.I), TenderDocRole.corrigendum),
    (re.compile(r"\bresponses?\s+to\s+pre-?bid\s+quer", re.I), TenderDocRole.clarification),
    (re.compile(r"\bnotice\s+inviting\s+tender\b|\bNIT\s+No\b", re.I), TenderDocRole.notice),
    (re.compile(r"\bformats?\s+and\s+annexures?\b|\bformat\s+PQ-\d", re.I), TenderDocRole.annexures),
    (re.compile(r"\bprice\s+schedule\b|\bbill\s+of\s+quantit|\bBoQ\b", re.I), TenderDocRole.boq),
    (re.compile(r"\brequest\s+for\s+proposal\b|\binstructions\s+to\s+bidders\b|\bRFP\b", re.I),
     TenderDocRole.main_rfp),
]
_TENDER_NAME_RULES: list[tuple[re.Pattern, TenderDocRole]] = [
    (re.compile(r"corrigend|addend|amendment", re.I), TenderDocRole.corrigendum),
    (re.compile(r"clarif|pre-?bid", re.I), TenderDocRole.clarification),
    (re.compile(r"notice|\bnit\b", re.I), TenderDocRole.notice),
    (re.compile(r"annex|format", re.I), TenderDocRole.annexures),
    (re.compile(r"boq|price|schedule|quantit", re.I), TenderDocRole.boq),
    (re.compile(r"rfp|tender|proposal", re.I), TenderDocRole.main_rfp),
]

KB_FOLDER_TYPES = {
    "01_company": "company", "02_financials": "financials", "03_certifications": "certifications",
    "04_project_experience": "project_experience", "05_personnel": "personnel",
    "06_past_proposals": "past_proposal", "07_policies": "policy",
    "08_legal_commercial": "legal_commercial", "09_registrations": "registration",
}


def classify_tender_file(filename: str, first_text: str = "") -> TenderDocRole:
    """Role of a tender file. Spreadsheets are price schedules; otherwise the
    first page decides (a renamed corrigendum is still caught), then the name."""
    ext = PurePosixPath(filename).suffix.lower()
    if ext == ".xlsx":
        return TenderDocRole.boq
    head = (first_text or "")[:3000]
    for pattern, role in _TENDER_TEXT_RULES:
        if pattern.search(head):
            return role
    for pattern, role in _TENDER_NAME_RULES:
        if pattern.search(filename):
            return role
    return TenderDocRole.other


def classify_kb_file(rel_path: str) -> str:
    """Fallback KB document type from its folder (the manifest's type wins when present)."""
    parts = PurePosixPath(rel_path.replace("\\", "/")).parts
    return KB_FOLDER_TYPES.get(parts[0], "other") if parts else "other"
