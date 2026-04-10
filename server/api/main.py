"""main — FastAPI entry point for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from server.api.routes.analysis import router as analysis_router
from server.api.routes.brighthub import router as brighthub_router
from server.api.routes.chat import router as chat_router
from server.api.routes.config import router as config_router
from server.api.routes.exports import router as exports_router
from server.api.routes.health import router as health_router
from server.api.routes.results import router as results_router
from server.api.routes.sessions import router as sessions_router
from server.api.routes.uploads import router as uploads_router


def create_app() -> FastAPI:
    """Create the FastAPI application shell for the browser-based workflow UI."""
    app = FastAPI(title="GoKaatru Web API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(uploads_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(analysis_router, prefix="/api")
    app.include_router(brighthub_router, prefix="/api")
    app.include_router(results_router, prefix="/api")
    app.include_router(exports_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")

    @app.get("/")
    def root() -> RedirectResponse:
        """Redirect the root URL to the API health endpoint for local smoke checks."""
        return RedirectResponse(url="/api/health")

    return app


app = create_app()
