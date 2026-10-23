"""FastAPI application factory.

Run: uv run python dev.py api   (http://localhost:8000, docs at /docs)
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import amendments, exports, health, kb, ops, tenders
from backend.app.api.errors import install_error_handlers
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.engine import init_db
from backend.app.ops.langsmith import configure_tracing


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    configure_tracing()
    init_db()  # creates missing tables; Postgres deployments run `dev.py migrate` first
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="TenderBridge API", version="0.5.0", lifespan=lifespan,
                  description="Evidence-first bid / no-bid copilot for IT-infrastructure tenders. "
                              "Demo data is synthetic; nothing is submitted to any portal.")
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    install_error_handlers(app)
    for router in (health.router, kb.router, tenders.router, amendments.router, exports.router, ops.router):
        app.include_router(router)
    return app


app = create_app()
