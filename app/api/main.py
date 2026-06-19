import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401 — register models with Base before create_all
from app.agent.mcp_host import build_obd_host
from app.api.routers import vehicles, jobs, documents, chat, scanner
from app.config import settings
from app.db import Base, get_engine, get_session_factory

logger = logging.getLogger(__name__)


def configure_db(app: FastAPI, db_url: str) -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = get_session_factory(engine)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not getattr(app.state, "session_factory", None):
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        configure_db(app, f"sqlite:///{db_path}")

    app.state.obd_host = None
    if settings.obd_mcp_enabled:
        host = build_obd_host(settings)
        if not host.start():
            logger.warning("OBD MCP host failed to start; chat will run without OBD tools")
        app.state.obd_host = host

    try:
        yield
    finally:
        host = getattr(app.state, "obd_host", None)
        if host is not None:
            host.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Mechanics Sidekick API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(vehicles.router)
    app.include_router(jobs.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(scanner.router)

    spa_dir = Path(settings.spa_dist_dir)
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(spa_dir), html=True), name="spa")

    return app
