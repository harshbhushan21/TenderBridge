"""Upload validation: extension/MIME allowlist, size limits, ZIP bombs, traversal."""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import PurePosixPath

from backend.app.core.config import get_settings
from backend.app.core.errors import FileRejected

ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
    "txt": {"text/plain"},
    "md": {"text/plain", "text/markdown"},
    "json": {"application/json", "text/plain"},
    "csv": {"text/csv", "text/plain"},
    "zip": {"application/zip"},
}
DEFAULT_TENDER_EXTS = {"pdf", "docx", "xlsx", "zip", "txt"}

# Executable / scriptable content that must never be accepted inside archives.
BLOCKED_INNER_EXTS = {"exe", "dll", "bat", "cmd", "sh", "ps1", "js", "vbs", "jar", "msi", "scr",
                      "com", "py", "docm", "xlsm", "pptm", "html", "htm", "hta", "lnk"}


def _sniff_mime(data: bytes, ext: str) -> str:
    """Magic-number sniffing; python-magic used when available."""
    try:  # optional dependency
        import magic  # type: ignore

        m = magic.from_buffer(data[:8192], mime=True)
        if m:
            return m
    except Exception:
        pass
    head = data[:8]
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        if ext == "docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if ext == "xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    if head.startswith(b"MZ") or head.startswith(b"\x7fELF"):
        return "application/x-executable"
    try:
        data[:4096].decode("utf-8")
        if ext == "json":
            return "application/json"
        if ext == "csv":
            return "text/csv"
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


def _check_zip(data: bytes, ext: str) -> None:
    s = get_settings()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise FileRejected(f"corrupt {ext} archive") from exc
    infos = zf.infolist()
    if len(infos) > max(s.max_zip_entries, 2000 if ext in ("docx", "xlsx") else 0):
        raise FileRejected("archive has too many entries", details={"entries": len(infos)})
    total = 0
    for info in infos:
        name = info.filename
        p = PurePosixPath(name.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts:
            raise FileRejected("archive entry escapes target directory", details={"entry": name})
        total += info.file_size
        if info.compress_size and info.file_size / max(info.compress_size, 1) > 200:
            raise FileRejected("suspicious compression ratio (zip bomb)", details={"entry": name})
        inner_ext = p.suffix.lower().lstrip(".")
        if inner_ext in BLOCKED_INNER_EXTS:
            raise FileRejected("archive contains blocked file type", details={"entry": name})
        if ext in ("docx", "xlsx") and "vbaProject.bin" in name:
            raise FileRejected("macro-enabled content is not allowed", details={"entry": name})
    if total > s.max_zip_uncompressed_mb * 1024 * 1024:
        raise FileRejected("archive uncompressed size too large", details={"bytes": total})


def validate_upload(filename: str, data: bytes, *, allowed: set[str] | None = None) -> dict:
    """Validate an uploaded file. Returns {mime, sha256, ext, size}; raises FileRejected."""
    s = get_settings()
    allowed = allowed or DEFAULT_TENDER_EXTS
    if not filename or "\x00" in filename:
        raise FileRejected("invalid filename")
    ext = PurePosixPath(filename.replace("\\", "/")).suffix.lower().lstrip(".")
    if ext not in allowed or ext not in ALLOWED_EXTENSIONS:
        raise FileRejected(f"file type '.{ext}' not allowed", details={"allowed": sorted(allowed)})
    size = len(data)
    if size == 0:
        raise FileRejected("empty file")
    if size > s.max_upload_mb * 1024 * 1024:
        raise FileRejected("file too large", details={"max_mb": s.max_upload_mb, "bytes": size})
    mime = _sniff_mime(data, ext)
    if mime not in ALLOWED_EXTENSIONS[ext]:
        raise FileRejected("file content does not match its extension",
                           details={"ext": ext, "detected_mime": mime})
    if ext in ("zip", "docx", "xlsx"):
        _check_zip(data, ext)
    if ext == "pdf":
        head = data[:1 << 20]
        for marker in (b"/JavaScript", b"/Launch", b"/EmbeddedFile"):
            if marker in head:
                raise FileRejected("PDF contains active content", details={"marker": marker.decode()})
    return {"mime": mime, "sha256": hashlib.sha256(data).hexdigest(), "ext": ext, "size": size}
