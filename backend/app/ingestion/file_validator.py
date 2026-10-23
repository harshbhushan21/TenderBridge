"""Thin ingestion-facing wrapper around guardrails.file_security."""
from __future__ import annotations

from pathlib import Path

from backend.app.guardrails.file_security import DEFAULT_TENDER_EXTS, validate_upload

KB_EXTS = {"pdf", "docx", "xlsx", "txt", "md", "json", "csv"}


def validate_tender_file(filename: str, data: bytes) -> dict:
    return validate_upload(filename, data, allowed=DEFAULT_TENDER_EXTS)


def validate_kb_file(path: Path) -> dict:
    return validate_upload(path.name, path.read_bytes(), allowed=KB_EXTS)
