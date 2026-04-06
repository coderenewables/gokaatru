"""health — Health endpoints for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def get_health() -> dict[str, str]:
    """Return the service status for API startup and frontend liveness checks."""
    return {"status": "ok", "service": "gokaatru-web-api"}
