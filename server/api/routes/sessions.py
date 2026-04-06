"""sessions — Session lifecycle routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from server.api.deps import get_session_manager, get_session_state
from server.api.schemas import CreateSessionResponse, SessionSummaryResponse
from server.state.manager import SessionManager
from server.state.session import SessionState

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_summary(state: SessionState) -> SessionSummaryResponse:
    """Serialize the current managed session into the workflow summary response."""
    workspace_dir = str(state.workspace_dir) if state.workspace_dir is not None else None
    return SessionSummaryResponse(
        session_id=state.session_id or "",
        workspace_dir=workspace_dir,
        created_at=state.created_at,
        updated_at=state.updated_at,
        project_name=state.get_project_name(),
        measurement_type=state.get_measurement_type(),
        hub_height_m=state.get_hub_height_m(),
        timeseries_loaded=state.timeseries_df is not None,
        datamodel_loaded=bool(state.sensor_mapping),
        era5_nodes_loaded=bool(state.era5_nodes),
        era5_interpolated_loaded=state.era5_interpolated_df is not None,
        ltc_algorithms=sorted(state.ltc_results.keys()),
    )


@router.post("", response_model=CreateSessionResponse)
def create_session(
    manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> CreateSessionResponse:
    """Create a new workflow session and return its identity metadata."""
    state = manager.create_session()
    return CreateSessionResponse(
        session_id=state.session_id or "",
        workspace_dir=str(state.workspace_dir) if state.workspace_dir is not None else "",
        created_at=state.created_at,
    )


@router.get("/{session_id}", response_model=SessionSummaryResponse)
def get_session_summary(
    state: Annotated[SessionState, Depends(get_session_state)],
) -> SessionSummaryResponse:
    """Return a compact summary of the current session workflow state."""
    return _session_summary(state)


@router.post("/{session_id}/reset", response_model=SessionSummaryResponse)
def reset_session(
    session_id: str,
    manager: Annotated[SessionManager, Depends(get_session_manager)],
    _: Annotated[SessionState, Depends(get_session_state)],
) -> SessionSummaryResponse:
    """Clear workflow data for a managed session while preserving its identity and workspace."""
    state = manager.reset_session(session_id)
    return _session_summary(state)


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    manager: Annotated[SessionManager, Depends(get_session_manager)],
    _: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, str]:
    """Delete a managed session and remove its workspace directory."""
    manager.delete_session(session_id)
    return {"status": "ok", "session_id": session_id}
