"""PII masking before external LLM calls, traces and embeddings.

Uses Microsoft Presidio when installed; otherwise regex masks for Indian
identifiers (PAN, Aadhaar, phone), emails and dates of birth.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_REGEXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "<PAN>"),
    (re.compile(r"\b[2-9][0-9]{3}\s?[0-9]{4}\s?[0-9]{4}\b"), "<AADHAAR>"),
    (re.compile(r"(?:\+91[\s-]?|\b0)?[6-9][0-9]{4}[\s-]?[0-9]{5}\b"), "<PHONE>"),
    (re.compile(r"\b(?:DOB|Date of Birth|D\.O\.B\.?)\s*[:\-]?\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", re.I), "<DOB>"),
    (re.compile(r"\b[0-9]{9,18}\b(?=.{0,20}\b(?:a/c|account)\b)", re.I), "<ACCOUNT>"),
    (re.compile(r"\bPassport\s*(?:No\.?|Number)?\s*[:\-]?\s*[A-Z][0-9]{7}\b", re.I), "<PASSPORT>"),
]


@lru_cache
def _presidio():
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        from presidio_anonymizer import AnonymizerEngine  # type: ignore
        return AnalyzerEngine(), AnonymizerEngine()
    except Exception:
        return None


def mask_pii(text: str, *, use_presidio: bool = False) -> str:
    """Mask PII. Regex masking always runs; Presidio adds NER-based masking if enabled."""
    if not text:
        return text
    out = text
    for pat, repl in _REGEXES:
        out = pat.sub(repl, out)
    if use_presidio:
        engines = _presidio()
        if engines:
            analyzer, anonymizer = engines
            try:
                results = analyzer.analyze(text=out, language="en",
                                           entities=["PHONE_NUMBER", "EMAIL_ADDRESS", "IBAN_CODE",
                                                     "CREDIT_CARD", "LOCATION"])
                out = anonymizer.anonymize(text=out, analyzer_results=results).text
            except Exception:
                pass
    return out


def mask_obj(obj: Any) -> Any:
    """Recursively mask strings inside dict/list structures."""
    if isinstance(obj, str):
        return mask_pii(obj)
    if isinstance(obj, dict):
        return {k: mask_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(mask_obj(v) for v in obj)
    return obj
