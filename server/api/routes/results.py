"""results — Placeholder results routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/sessions/{session_id}", tags=["results"])
