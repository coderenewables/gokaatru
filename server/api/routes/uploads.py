"""uploads — Upload and sensor inventory routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from server.api.deps import get_session_state, to_bad_request
from server.state.session import SessionState
from server.tools.data_io import _get_data_coverage, _list_sensors, _parse_datamodel, _parse_timeseries

router = APIRouter(prefix="/sessions/{session_id}", tags=["uploads"])


def _upload_dir(state: SessionState) -> Path:
    """Return the per-session uploads directory for browser file ingestion."""
    if state.workspace_dir is None:
        raise ValueError("Session workspace directory is not available")
    upload_dir = state.workspace_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _save_upload(state: SessionState, uploaded_file: UploadFile, stem: str) -> Path:
    """Persist an uploaded browser file into the session workspace uploads directory."""
    filename = Path(uploaded_file.filename or f"{stem}.bin").name or f"{stem}.bin"
    target_path = _upload_dir(state) / filename
    with target_path.open("wb") as handle:
        handle.write(uploaded_file.file.read())
    return target_path


@router.post("/uploads/timeseries")
def upload_timeseries(
    session_id: str,
    file: UploadFile = File(...),
    state: Annotated[SessionState, Depends(get_session_state)] = None,
) -> dict:
    """Save an uploaded timeseries file into the session workspace and parse it into session state."""
    del session_id
    try:
        saved_path = _save_upload(state, file, "timeseries")
        result = _parse_timeseries(state, str(saved_path))
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return {**result, "file_path": str(saved_path)}


@router.post("/uploads/datamodel")
def upload_datamodel(
    session_id: str,
    file: UploadFile = File(...),
    state: Annotated[SessionState, Depends(get_session_state)] = None,
) -> dict:
    """Save an uploaded datamodel file into the session workspace and parse it into session state."""
    del session_id
    try:
        saved_path = _save_upload(state, file, "datamodel")
        result = _parse_datamodel(state, str(saved_path))
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return {**result, "file_path": str(saved_path)}


@router.get("/sensors")
def get_sensors(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return the parsed sensor inventory for the current session."""
    del session_id
    try:
        return _list_sensors(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/coverage/{sensor_name}")
def get_sensor_coverage(
    session_id: str,
    sensor_name: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return coverage and gap statistics for one sensor in the current session."""
    del session_id
    try:
        return _get_data_coverage(state, sensor_name)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
