import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

import app.models  # noqa: F401 — register models with Base before create_all
from app.agent.mcp_host import build_obd_host
from app.api.routers import vehicles, jobs, documents, chat, scanner, config, telemetry, diagnostic
from app.config import settings
from app.db import Base, get_engine, get_session_factory
from app.telemetry.manager import TelemetryManager

logger = logging.getLogger(__name__)


class SpaStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for unmatched non-API paths, so that
    history-mode SPA deep links and hard refreshes (e.g. /vehicles/3/diagnostic)
    load the app instead of returning a 404. Unknown /api paths still 404."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # `path` has the mount prefix + leading slash stripped (e.g. "api/x", "vehicles/3").
            is_api = path == "api" or path.startswith("api/")
            if exc.status_code == 404 and not is_api:
                return await super().get_response("index.html", scope)
            raise


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
    app.state.telemetry_manager = None
    if settings.obd_mcp_enabled:
        host = build_obd_host(settings)
        if not host.start():
            logger.warning("OBD MCP host failed to start; chat will run without OBD tools")
        app.state.obd_host = host
        if host.available:
            app.state.telemetry_manager = TelemetryManager(
                host, app.state.session_factory, settings
            )

    try:
        yield
    finally:
        host = getattr(app.state, "obd_host", None)
        if host is not None and hasattr(host, "stop"):
            host.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Mechanics Sidekick API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Centralized logging for unhandled errors on non-streaming routes; never leak the trace.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(vehicles.router)
    app.include_router(jobs.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(scanner.router)
    app.include_router(config.router)
    app.include_router(telemetry.router)
    app.include_router(diagnostic.router)

    spa_dir = Path(settings.spa_dist_dir)
    if spa_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=str(spa_dir), html=True), name="spa")

    return app
