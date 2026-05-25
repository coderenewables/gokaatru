"""main — FastAPI entry point for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from server.api.deps import get_session_manager
from server.api.mcp import create_session_aware_mcp_app
from server.api.routes.analysis import router as analysis_router
from server.api.routes.brighthub import router as brighthub_router
from server.api.routes.chat import router as chat_router
from server.api.routes.config import router as config_router
from server.api.routes.datasets import router as datasets_router
from server.api.routes.exports import router as exports_router
from server.api.routes.health import router as health_router
from server.api.routes.mcp import router as mcp_router
from server.api.routes.results import router as results_router
from server.api.routes.sessions import router as sessions_router
from server.api.routes.uploads import router as uploads_router
from server.api.routes.windkit import router as windkit_router
from server.api.routes.workflow_execution import router as workflow_execution_router


def _get_allowed_origins() -> list[str]:
    configured = [
        origin.strip()
        for origin in os.getenv("GOKAATRU_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    defaults = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]
    return list(dict.fromkeys([*defaults, *configured]))


def create_app() -> FastAPI:
    """Create the FastAPI application shell for the browser-based workflow UI."""
    session_aware_mcp_app = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if session_aware_mcp_app is None:
            yield
            return
        async with session_aware_mcp_app.lifespan():
            yield

    app = FastAPI(title="GoKaatru Web API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(mcp_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(datasets_router, prefix="/api")
    app.include_router(workflow_execution_router, prefix="/api")
    app.include_router(uploads_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")
    app.include_router(brighthub_router, prefix="/api")
    app.include_router(results_router, prefix="/api")
    app.include_router(exports_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(windkit_router, prefix="/api")

    def _session_manager_provider():
        override = app.dependency_overrides.get(get_session_manager)
        if override is not None:
            return override()
        return get_session_manager()

    session_aware_mcp_app = create_session_aware_mcp_app(_session_manager_provider)
    app.mount("/api/sessions/{session_id}/mcp", session_aware_mcp_app)

    @app.get("/")
    def root() -> RedirectResponse:
        """Redirect the root URL to the API health endpoint for local smoke checks."""
        return RedirectResponse(url="/api/health")

    return app


app = create_app()
