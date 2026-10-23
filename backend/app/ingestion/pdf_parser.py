"""PDF parsing: PyMuPDF (default, page-faithful) → pypdf fallback; Docling optional.

Docling gives better table structure but is heavy; enable with
`TB_USE_DOCLING=1`. Page text always comes from PyMuPDF/pypdf so page
numbers stay exact for citations. Pages with no usable text are OCR'd.
Hidden (white/tiny/off-page) spans are removed from page text and recorded.
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

from backend.app.core.logging import get_logger
from backend.app.ingestion.hashes import sha256_file
from backend.app.ingestion.ocr import ocr_page
from backend.app.schemas.documents import ParsedDocument, ParsedPage, TableBlock

log = get_logger(__name__)
MIN_TEXT_CHARS = 25
# Running headers/footers use small fonts; a page whose only text is below this
# size (e.g. a scanned page with a printed header) still needs OCR.
MIN_BODY_FONT = 8.0


def _fitz():
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        import fitz  # type: ignore
    return fitz


def _is_hidden_span(span: dict, rect) -> bool:
    color = int(span.get("color", 0))
    r, g, b = (color >> 16) & 255, (color >> 8) & 255, color & 255
    if min(r, g, b) >= 240:
        return True
    if float(span.get("size", 10)) < 2.5:
        return True
    x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
    return x1 < rect.x0 or x0 > rect.x1 or y1 < rect.y0 or y0 > rect.y1


def _page_text_and_hidden(page, sizes: Counter | None = None,
                          headings: list[dict] | None = None) -> tuple[str, list[str]]:
    """Visible text and hidden spans of a page. Optionally tallies visible
    characters per font size (`sizes`) and collects bold lines (`headings`)."""
    rect = page.rect
    lines_out: list[str] = []
    hidden: list[str] = []
    d = page.get_text("dict", sort=True)
    for block in d.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            visible = []
            line_size, line_bold = 0.0, True
            for span in line.get("spans", []):
                t = span.get("text") or ""
                if not t.strip():
                    visible.append(t)
                    continue
                if _is_hidden_span(span, rect):
                    hidden.append(t.strip())
                else:
                    visible.append(t)
                    size = round(float(span.get("size", 0)), 1)
                    line_size = max(line_size, size)
                    bold = bool(int(span.get("flags", 0)) & 16) or "bold" in str(span.get("font", "")).lower()
                    line_bold = line_bold and bold
                    if sizes is not None:
                        sizes[size] += len(t.strip())
            s = "".join(visible).rstrip()
            if s.strip():
                lines_out.append(s)
                if headings is not None and line_bold and len(s.strip()) <= 160:
                    headings.append({"text": " ".join(s.split()), "size": line_size})
        lines_out.append("")
    text = "\n".join(lines_out)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip(), hidden


def _page_tables(page, page_no: int) -> list[TableBlock]:
    tables: list[TableBlock] = []
    finder = getattr(page, "find_tables", None)
    if finder is None:
        return tables
    try:
        for t in finder().tables:
            data = t.extract() or []
            rows = [[("" if c is None else str(c).strip()) for c in row] for row in data]
            if not rows:
                continue
            tables.append(TableBlock(headers=rows[0], rows=rows[1:], page=page_no))
    except Exception:
        pass
    return tables


def _parse_pymupdf(path: Path, doc_id: str, sha: str) -> ParsedDocument:
    fitz = _fitz()
    pages: list[ParsedPage] = []
    warnings: list[str] = []
    tables_meta: list[dict] = []
    sizes: Counter = Counter()
    with fitz.open(str(path)) as doc:
        meta = dict(doc.metadata or {})
        for i, page in enumerate(doc, start=1):
            headings: list[dict] = []
            page_sizes: Counter = Counter()
            text, hidden = _page_text_and_hidden(page, page_sizes, headings)
            sizes.update(page_sizes)
            body_chars = sum(n for size, n in page_sizes.items() if size >= MIN_BODY_FONT)
            ocr = False
            if len(text.strip()) < MIN_TEXT_CHARS or body_chars < MIN_TEXT_CHARS:
                ocr_text = ocr_page(path, i)
                if ocr_text.strip():
                    text, ocr = ocr_text.strip(), True
                else:
                    warnings.append(f"page {i}: no extractable text (OCR unavailable or empty)")
            pages.append(ParsedPage(page=i, text=text, ocr=ocr, hidden_spans=hidden,
                                    heading_candidates=[] if ocr else headings))
            for tb in _page_tables(page, i):
                tables_meta.append(tb.model_dump())
    body_size = sizes.most_common(1)[0][0] if sizes else None
    return ParsedDocument(doc_id=doc_id, filename=path.name, file_sha256=sha, parser="pymupdf",
                          pages=pages, metadata={"pdf": meta, "tables": tables_meta,
                                                 "body_font_size": body_size},
                          warnings=warnings)


def _parse_pypdf(path: Path, doc_id: str, sha: str) -> ParsedDocument:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    warnings = []
    for i, p in enumerate(reader.pages, start=1):
        text = (p.extract_text() or "").strip()
        ocr = False
        if len(text) < MIN_TEXT_CHARS:
            o = ocr_page(path, i)
            if o.strip():
                text, ocr = o.strip(), True
            else:
                warnings.append(f"page {i}: no extractable text")
        pages.append(ParsedPage(page=i, text=text, ocr=ocr))
    return ParsedDocument(doc_id=doc_id, filename=path.name, file_sha256=sha, parser="pypdf",
                          pages=pages, metadata={}, warnings=warnings)


def _docling_tables(path: Path) -> list[dict]:
    """Optional Docling table extraction (structure-faithful)."""
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except Exception:
        return []
    try:
        result = DocumentConverter().convert(str(path))
        out = []
        for t in getattr(result.document, "tables", []):
            df = t.export_to_dataframe()
            prov = getattr(t, "prov", None) or []
            page = prov[0].page_no if prov else None
            out.append(TableBlock(headers=[str(c) for c in df.columns],
                                  rows=[[str(v) for v in r] for r in df.values.tolist()],
                                  page=page).model_dump())
        return out
    except Exception as exc:
        log.warning("docling failed on %s: %s", path, exc)
        return []


def parse_pdf(path: str | Path, doc_id: str) -> ParsedDocument:
    path = Path(path)
    sha = sha256_file(path)
    try:
        parsed = _parse_pymupdf(path, doc_id, sha)
    except Exception as exc:
        log.warning("PyMuPDF failed on %s (%s); falling back to pypdf", path, exc)
        parsed = _parse_pypdf(path, doc_id, sha)
    if os.getenv("TB_USE_DOCLING") == "1":
        tables = _docling_tables(path)
        if tables:
            parsed.metadata["tables"] = tables
            parsed.parser = f"{parsed.parser}+docling"
    parsed.metadata["page_count"] = len(parsed.pages)
    return parsed
