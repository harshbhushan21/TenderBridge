"""OCR for scanned pages (pytesseract optional; returns "" when unavailable)."""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from backend.app.core.logging import get_logger

log = get_logger(__name__)


@lru_cache
def ocr_available() -> bool:
    try:
        import pytesseract  # type: ignore

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_page(pdf_path: str | Path, page_no: int, *, dpi: int = 200) -> str:
    """OCR one 1-indexed page of a PDF."""
    if not ocr_available():
        return ""
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        import fitz  # type: ignore
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        with fitz.open(str(pdf_path)) as doc:
            page = doc[page_no - 1]
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            return pytesseract.image_to_string(img) or ""
    except Exception as exc:
        log.warning("OCR failed for %s p.%s: %s", pdf_path, page_no, exc)
        return ""


def ocr_image_bytes(data: bytes) -> str:
    if not ocr_available():
        return ""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        return pytesseract.image_to_string(Image.open(io.BytesIO(data))) or ""
    except Exception:
        return ""
