"""Conservative parsing of tender clauses into deterministic rule dictionaries.

This parser is intentionally not an LLM. It extracts only values that are
explicitly present in the clause and leaves ambiguous clauses for review.
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.tools.certificate_rules import normalize_standard
from backend.app.tools.date_normalization import parse_all_money, word_to_int


def _number(token: str) -> int | None:
    return word_to_int(token.strip().lower()) or (int(token) if token.strip().isdigit() else None)


def parse_requirement(text: str) -> dict[str, Any]:
    """Return the common rule shape used by extraction and deterministic tools."""
    source = " ".join((text or "").split())
    lower = source.lower()
    if not source:
        return {"field": None, "operator": None, "threshold": None, "logic": "AND", "needs_review": True}

    if "turnover" in lower:
        money = parse_all_money(source)
        thresholds = [m.crore for m in money]
        fy_matches = re.findall(r"(?:FY)?\s*(20\d{2})\s*[-/]\s*(\d{2,4})", source, re.I)
        rule: dict[str, Any] = {
            "field": "financials.revenue_inr",
            "operator": ">=",
            "threshold": thresholds[0] if thresholds else None,
            "unit": "INR crore",
            "aggregation": "mean" if "average" in lower else "each",
            "logic": "OR" if "mse" in lower or "micro" in lower or "small enterprise" in lower else "AND",
            "needs_review": not bool(thresholds),
        }
        if len(thresholds) > 1:
            rule["thresholds"] = thresholds
        if fy_matches:
            rule["window"] = [f"{a}-{b[-2:]}" for a, b in fy_matches]
        if "mse" in lower or "micro" in lower or "small enterprise" in lower:
            rule["mse_relaxation"] = True
            rule["branches"] = [
                {"id": "general", "threshold": thresholds[0] if thresholds else None},
                {"id": "mse_relaxation", "threshold": thresholds[1] if len(thresholds) > 1 else None,
                 "condition": {"field": "company.udyam_classification", "operator": "in",
                               "threshold": ["Micro", "Small"]}},
            ]
        return rule

    if "similar" in lower and "work" in lower:
        branches = []
        for branch_text in re.split(r"\s+\bOR\b\s+", source, flags=re.I):
            match = re.search(r"\b(one|two|three|four|five|\d+)\b", branch_text, re.I)
            count = _number(match.group(1)) if match else None
            money = parse_all_money(branch_text)
            if count and money:
                branches.append({"count": count, "min_value_inr": money[0].amount_inr})
        duration_match = re.search(r"(\d+)\s*years?", lower)
        return {
            "field": "projects.eligible_value_inr",
            "operator": ">=",
            "threshold": branches,
            "branches": branches,
            "window": {"years": int(duration_match.group(1)) if duration_match else 7},
            "aggregation": "count",
            "logic": "OR",
            "needs_review": not bool(branches),
        }

    if "certificate" in lower or "iso/" in lower or "iso " in lower:
        standards = re.findall(r"(?:ISO(?:/IEC)?\s*[\w-]+|CMMI(?:\s+Level)?\s*\d+)", source, re.I)
        standard = normalize_standard(standards[0]) if standards else ""
        return {
            "field": "certificates.standard",
            "operator": "any_valid",
            "threshold": standard,
            "valid_on": "submission_deadline",
            "logic": "AND",
            "needs_review": not bool(standard),
        }

    return {
        "field": None,
        "operator": None,
        "threshold": None,
        "logic": "AND",
        "needs_review": True,
        "source_text": source,
    }


parse_rule = parse_requirement
