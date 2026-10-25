"""FastAPI app.   uvicorn backend.app.main:app --port 8104   (run from the repo root; migrate first: see README)"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import settings
from .observability import middleware, setup_logging
from .routes import auth, incidents, meta, runbooks


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    settings.check()
    db.init()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="On-call Runbook Copilot", version="2.0.0", lifespan=lifespan)
    app.middleware("http")(middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Last-Event-ID"],
        expose_headers=["X-Request-ID"],
    )
    for r in (auth.router, incidents.router, runbooks.router, meta.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
