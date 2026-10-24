"""Readable citations in exported files: tender documents by filename, KB documents by their id.

Tender `doc_id`s are opaque ("DOC-581F96DAA0"); a reader of the spreadsheet needs "main_rfp.pdf p.4".
`export_outputs` sets the labels for the tender being exported; writers call `cite(span)`.
"""
from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from backend.app.schemas.documents import SourceSpan

_labels: contextvars.ContextVar[Mapping[str, str] | None] = contextvars.ContextVar("export_doc_labels", default=None)


@contextmanager
def doc_labels(labels: Mapping[str, str]) -> Iterator[None]:
    token = _labels.set(labels)
    try:
        yield
    finally:
        _labels.reset(token)


def cite(span: SourceSpan) -> str:
    short = span.short()
    label = (_labels.get() or {}).get(span.doc_id)
    return short.replace(span.doc_id, label, 1) if label else short
