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


def to_bad_request(exc: ValueError) -> HTTPException:
    """Translate domain-level validation errors into HTTP 400 responses for the web API."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def to_bad_gateway(exc: RuntimeError) -> HTTPException:
    """Translate upstream service failures into HTTP 502 responses for the web API."""
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def completed_steps(state: SessionState) -> list[str]:
    """Summarize coarse workflow milestones completed in the current browser session."""
    steps: list[str] = []
    if state.timeseries_df is not None:
        steps.append("timeseries")
    if state.sensor_mapping:
        steps.append("datamodel")
    has_config = (
        state.get_coordinate() is not None
        or state.get_hub_height_m() is not None
        or state.get_project_name() is not None
    )
    if has_config:
        steps.append("config")
    if state.cleaning_log:
        steps.append("cleaning")
    if state.shear_timeseries_df is not None:
        steps.append("shear_timeseries")
    if state.shear_table is not None:
        steps.append("shear_table")
    if state.roughness_timeseries_df is not None:
        steps.append("roughness_timeseries")
    if state.roughness_table is not None:
        steps.append("roughness_table")
    if state.era5_nodes:
        steps.append("era5_nodes")
    if state.era5_data:
        steps.append("era5_extract")
    if state.era5_interpolated_df is not None:
        steps.append("era5_interpolate")
    if state.ltc_results:
        steps.append("ltc")
    if state.ensemble_df is not None:
        steps.append("ensemble")
    return steps


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
