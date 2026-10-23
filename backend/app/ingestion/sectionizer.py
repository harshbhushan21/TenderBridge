"""Split a parsed document into a heading hierarchy of sections.

Headings come from font data when the parser provides it (bold lines clearly
larger than body text), from markdown-style '#' lines for DOCX, and from text
patterns as a last resort (pypdf / OCR output). Running headers and footers
are removed, tables are attached to the section they appear in, and each
section keeps page offsets so chunks cite exact pages.
"""
from __future__ import annotations

import re
from collections import Counter

from backend.app.schemas.documents import ParsedDocument, ParsedSection, TableBlock

HEADING_SIZE_RATIO = 1.15   # heading font >= 115% of body font
REPEAT_LINE_SHARE = 0.5     # a line on >= half the pages is a running header/footer
_PAGE_NO = re.compile(r"^(page\s+)?\d+(\s*(of|/)\s*\d+)?$", re.IGNORECASE)
_PATTERN_HEADING = re.compile(
    r"^(section\s+\d+\s*[:.\-]|part\s+[a-z]\s*:|format\s+[a-z]+-\d+\s*:|annexure\s+[a-z0-9]+\s*:|"
    r"schedule\s+[a-z0-9]+\s*:|\d+(\.\d+){0,2}[a-z]?\s+[A-Z])", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def _running_lines(doc: ParsedDocument) -> set[str]:
    if len(doc.pages) < 3:
        return set()
    counts: Counter = Counter()
    for page in doc.pages:
        counts.update({_norm(line) for line in page.text.splitlines() if line.strip()})
    limit = max(2, int(len(doc.pages) * REPEAT_LINE_SHARE))
    return {line for line, n in counts.items() if n >= limit}


def _looks_like_pattern_heading(line: str) -> bool:
    """Fallback for text without font data: short, title-cased, numbered lines."""
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";", ":")) or not _PATTERN_HEADING.match(s):
        return False
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]*", s) if len(w) > 3]
    return not words or sum(w[0].isupper() for w in words) / len(words) >= 0.6


def _heading_levels(doc: ParsedDocument) -> dict[str, int] | None:
    """Map normalised heading text -> level from font sizes; None if no font data."""
    body = doc.metadata.get("body_font_size")
    candidates = [h for p in doc.pages for h in p.heading_candidates]
    if not body or not candidates:
        return None
    big = [h for h in candidates if float(h["size"]) >= float(body) * HEADING_SIZE_RATIO]
    sizes = sorted({float(h["size"]) for h in big}, reverse=True)
    return {_norm(h["text"]): sizes.index(float(h["size"])) + 1 for h in big}


def sectionize(doc: ParsedDocument) -> list[ParsedSection]:
    running = _running_lines(doc)
    font_levels = _heading_levels(doc)
    markdown = doc.parser in ("docx", "xlsx")  # '#' headings (DOCX styles, XLSX sheet names)
    has_any_heading = font_levels is not None or markdown

    sections: list[ParsedSection] = []
    stack: list[ParsedSection] = []
    lines: list[str] = []
    offsets: list[list[int]] = []

    def close() -> None:
        if not sections:
            return
        cur = sections[-1]
        cur.text = "\n".join(lines).strip()
        cur.page_offsets = offsets[:] or [[0, cur.page_start or 1]]

    def open_section(title: str, level: int, page: int) -> None:
        nonlocal lines, offsets
        close()
        while stack and stack[-1].level >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        path = f"{parent.section_path} > {title}" if parent else title
        sec = ParsedSection(section_id=f"{doc.doc_id}::s{len(sections) + 1:03d}", doc_id=doc.doc_id,
                            title=title[:500], section_path=path[:1000], level=level,
                            page_start=page, page_end=page,
                            parent_id=parent.section_id if parent else None)
        sections.append(sec)
        stack.append(sec)
        lines, offsets = [], []

    continuing_heading = False
    for page in doc.pages:
        page_started = False
        continuing_heading = False
        for raw in page.text.splitlines():
            line = raw.rstrip()
            key = _norm(line)
            if not key or key in running or _PAGE_NO.match(key):
                continue
            level = None
            if font_levels is not None:
                level = font_levels.get(key)
            elif markdown and line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                line = line.lstrip("#").strip()
            elif not has_any_heading and _looks_like_pattern_heading(line):
                level = line.count(".") + 1 if re.match(r"^\d", line) else 1
            if level is not None:
                title = " ".join(line.split())
                cur = sections[-1] if sections else None
                if (cur is not None and not lines and cur.level == level and cur.page_start == page.page
                        and continuing_heading):
                    # A heading wrapped onto a second line: merge it into one title.
                    cur.title = f"{cur.title} {title}"[:500]
                    parent_path = cur.section_path.rsplit(" > ", 1)[0] if " > " in cur.section_path else ""
                    cur.section_path = (f"{parent_path} > {cur.title}" if parent_path else cur.title)[:1000]
                else:
                    open_section(title, level, page.page)
                page_started = True
                continuing_heading = True
                continue
            continuing_heading = False
            if not sections:
                open_section("Preamble", 1, page.page)
            if not page_started or not offsets or offsets[-1][1] != page.page:
                offsets.append([len("\n".join(lines)) + (1 if lines else 0), page.page])
                page_started = True
            lines.append(line)
            sections[-1].page_end = page.page
            if page.ocr and "ocr" not in sections[-1].flags:
                sections[-1].flags.append("ocr")
    close()

    sections = [s for s in sections if s.text or any(c.parent_id == s.section_id for c in sections)]
    _attach_tables(doc, sections)
    return sections


def _attach_tables(doc: ParsedDocument, sections: list[ParsedSection]) -> None:
    for raw in doc.metadata.get("tables") or []:
        table = TableBlock.model_validate(raw)
        if table.page is None or not sections:
            continue
        owner = None
        for sec in sections:
            if sec.page_start is not None and sec.page_start <= table.page <= (sec.page_end or sec.page_start):
                owner = sec  # deepest/latest section covering the page
        if owner is not None:
            owner.tables.append(table)
