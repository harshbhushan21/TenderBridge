"""Uniform error responses: {"error": code, "message": ..., "details": {...}} (docs/api_contract.md)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.core.errors import TenderBridgeError
from backend.app.core.logging import get_logger

log = get_logger(__name__)


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": code, "message": message, "details": details or {}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TenderBridgeError)
    async def _known(_: Request, exc: TenderBridgeError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content=_body(getattr(exc, "code", "error"), exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content=_body("validation_failed", "request is invalid",
                                                           {"errors": exc.errors()}))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=_body("internal_error", "unexpected server error"))
