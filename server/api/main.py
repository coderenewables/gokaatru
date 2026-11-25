"""main — FastAPI entry point for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

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
from server.api.routes.operations import router as operations_router
from server.api.routes.results import router as results_router
from server.api.routes.series import router as series_router
from server.api.routes.sessions import router as sessions_router
from server.api.routes.sweep import router as sweep_router
from server.api.routes.uploads import router as uploads_router
from server.api.routes.workflow_execution import router as workflow_execution_router
from server.operations import record_route_change

_SESSION_PATH = re.compile(r"^/api/sessions/([^/]+)/")
_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Hand-written routes that read although they are POSTed to, because their query does not
#: fit a URL. They are neither logged as changes nor saved.
_READING_POST_ROUTES = frozenset({"/api/sessions/{session_id}/series", "/api/sessions/{session_id}/pairs"})


def _get_allowed_origins() -> list[str]:
    configured = [
        origin.strip()
        for origin in os.getenv("GOKAATRU_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if configured:
        return configured
    defaults = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ]
    return defaults


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
    app.include_router(sweep_router, prefix="/api")
    app.include_router(exports_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(operations_router, prefix="/api")
    app.include_router(series_router, prefix="/api")

    def _session_manager_provider():
        override = app.dependency_overrides.get(get_session_manager)
        if override is not None:
            return override()
        return get_session_manager()

    session_aware_mcp_app = create_session_aware_mcp_app(_session_manager_provider)
    app.mount("/api/sessions/{session_id}/mcp", session_aware_mcp_app)

    @app.middleware("http")
    async def record_hand_written_changes(request: Request, call_next):
        """Log and save a successful change made through a hand-written session route.

        Generated operation routes, MCP and chat tool calls are logged by the operation
        wrapper itself; SSE streams are skipped because the response is still running.
        """
        response = await call_next(request)
        path = request.url.path
        match = _SESSION_PATH.match(path)
        if (
            match is None
            or request.method not in _CHANGING_METHODS
            or response.status_code >= 400
            or any(part in path for part in ("/operations/", "/mcp", "/chat"))
            or path.endswith("/stream")
        ):
            return response
        route = getattr(request.scope.get("route"), "path", path)
        if route in _READING_POST_ROUTES:
            return response
        state = _session_manager_provider().loaded(match.group(1))
        if state is not None:
            await run_in_threadpool(record_route_change, state, request.method, route)
        return response

    @app.get("/")
    def root() -> RedirectResponse:
        """Redirect the root URL to the API health endpoint for local smoke checks."""
        return RedirectResponse(url="/api/health")

    return app


app = create_app()
