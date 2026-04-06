"""deps — Shared FastAPI dependencies for GoKaatru web routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from server.state.manager import SessionManager, session_manager
from server.state.session import SessionState

SESSION_HEADER_NAME = "X-GoKaatru-Session"


def get_session_manager() -> SessionManager:
    """Return the process-local session manager used by the FastAPI layer."""
    return session_manager


def get_session_state(
    session_id: str,
    header_session_id: Annotated[str | None, Header(alias=SESSION_HEADER_NAME)] = None,
    manager: Annotated[SessionManager, Depends(get_session_manager)] = None,
) -> SessionState:
    """Resolve and validate the active browser session for session-scoped API routes."""
    if header_session_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required header '{SESSION_HEADER_NAME}'",
        )
    if header_session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Header '{SESSION_HEADER_NAME}' must match path session_id",
        )
    if manager is None:
        manager = get_session_manager()
    try:
        return manager.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
