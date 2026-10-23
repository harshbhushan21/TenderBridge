"""Export routes: list, generate and download the analysis artefacts for a tender version."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.errors import NotFoundError, ValidationFailed
from backend.app.core.security import CurrentUser, get_current_user
from backend.app.db.engine import db_dependency
from backend.app.db.repositories.analysis import latest_export, latest_run, list_exports
from backend.app.db.repositories.tenders import get_tender
from backend.app.exports.service import ALL_KINDS, FILENAMES, export_outputs
from backend.app.ops.audit import audit

router = APIRouter(prefix="/tenders", tags=["exports"])
MEDIA = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".ics": "text/calendar", ".json": "application/json"}


class ExportRequest(BaseModel):
    version: int | None = None
    kinds: list[str] | None = None


def _row(r) -> dict[str, Any]:
    return {"export_id": r.export_id, "kind": r.kind, "version": r.version, "run_id": r.run_id,
            "sha256": r.sha256, "created_at": r.created_at.isoformat() if r.created_at else None}


def _generate(session: Session, tender_id: str, version: int, kinds: list[str], actor: str) -> list[dict]:
    bad = [k for k in kinds if k not in ALL_KINDS]
    if bad:
        raise ValidationFailed("unknown export kind", details={"unknown": bad, "allowed": list(ALL_KINDS)})
    run = latest_run(session, tender_id, version, completed_only=True)
    if run is None:
        raise NotFoundError("nothing to export yet: run the analysis first")
    made = export_outputs(session, tender_id, version, run.run_id, kinds=kinds)
    audit(actor, "export.generated", tender_id=tender_id, version=version, run_id=run.run_id,
          session=session, kinds=[x["kind"] for x in made])
    return made


@router.get("/{tender_id}/exports")
def exports(tender_id: str, version: int | None = None, session: Session = Depends(db_dependency)
            ) -> dict[str, Any]:
    v = version or get_tender(session, tender_id).current_version
    return {"items": [_row(r) for r in list_exports(session, tender_id, v)]}


@router.post("/{tender_id}/exports")
def generate(tender_id: str, body: ExportRequest | None = None, session: Session = Depends(db_dependency),
             user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    body = body or ExportRequest()
    v = body.version or get_tender(session, tender_id).current_version
    made = _generate(session, tender_id, v, body.kinds or list(ALL_KINDS), user.user_id)
    return {"items": made}


@router.get("/{tender_id}/exports/{kind}")
def download(tender_id: str, kind: str, version: int | None = None, session: Session = Depends(db_dependency),
             user: CurrentUser = Depends(get_current_user)) -> FileResponse:
    """Download the latest export of a kind, generating it on first request."""
    v = version or get_tender(session, tender_id).current_version
    row = latest_export(session, tender_id, v, kind)
    if row is None or not Path(row.path).exists():
        _generate(session, tender_id, v, [kind], user.user_id)
        row = latest_export(session, tender_id, v, kind)
    if row is None:
        raise NotFoundError(f"'{kind}' is not available for this tender version yet")
    path = Path(row.path)
    return FileResponse(path, filename=FILENAMES.get(kind, path.name),
                        media_type=MEDIA.get(path.suffix, "application/octet-stream"))
