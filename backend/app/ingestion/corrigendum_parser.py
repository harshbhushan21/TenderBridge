"""Read the amendment tables of a corrigendum.

Corrigenda publish their changes as tables: Part A "RFP reference / Existing
provision / Amended provision" and Part B "RFP clause / Query / Response".
Table structure comes from PyMuPDF; each cell's text is read by clipping the
page to the cell box, which keeps proper word spacing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_SPACES = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    return _SPACES.sub(" ", text or "").strip()


def _kind(header: list[str]) -> str | None:
    h = " ".join(header).lower()
    if "existing" in h and "amended" in h:
        return "A"
    if "query" in h and "response" in h:
        return "B"
    return None


def parse_corrigendum_tables(path: str | Path) -> list[dict[str, Any]]:
    """Rows of every amendment table: {part, sl, reference, existing|query, amended|response, page}."""
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz  # type: ignore[no-redef]

    rows: list[dict[str, Any]] = []
    with fitz.open(str(path)) as doc:
        for page_no, page in enumerate(doc, start=1):
            for table in page.find_tables().tables:
                cells_by_row = []
                for row in table.rows:
                    cells_by_row.append([_clean(page.get_text("text", clip=fitz.Rect(c))) if c else ""
                                         for c in row.cells])
                if not cells_by_row:
                    continue
                part = _kind(cells_by_row[0])
                if part is None or len(cells_by_row[0]) < 4:
                    continue
                for cells in cells_by_row[1:]:
                    if not cells or not re.match(r"^\d+$", cells[0]):
                        continue
                    if part == "A":
                        rows.append({"part": "A", "sl": int(cells[0]), "reference": cells[1],
                                     "existing": cells[2], "amended": cells[3], "page": page_no})
                    else:
                        rows.append({"part": "B", "sl": int(cells[0]), "reference": cells[1],
                                     "query": cells[2], "response": cells[3], "page": page_no})
    return rows
