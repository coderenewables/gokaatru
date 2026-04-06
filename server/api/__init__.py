"""api — FastAPI web application package for GoKaatru.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from server.api.main import app, create_app

__all__ = ["app", "create_app"]
