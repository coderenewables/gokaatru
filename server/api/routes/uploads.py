"""uploads — Upload and sensor inventory routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from server.api.deps import get_session_state, to_bad_request
from server.state.session import SessionState
from server.tools.config import _persist_runconfig
from server.tools.data_io import (
    _build_sensor_rows,
    _get_data_coverage,
    _list_sensors,
    _parse_datamodel,
    _parse_timeseries,
)
from server.tools.datamodel_builder import _build_data_model, _draft_data_model
from server.tools.sensors import _remove_sensors

router = APIRouter(prefix="/sessions/{session_id}", tags=["uploads"])

# Reject path separators, NUL bytes, and other shell-relevant tokens in upload
# filenames; replace anything outside this whitelist with underscores.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
# 500 MiB hard cap; large enough for a multi-year 10-min timeseries CSV but
# small enough to bound per-request memory and disk impact.
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _sanitize_filename(name: str | None, fallback_stem: str) -> str:
    """Strip directory components and unsafe characters from an uploaded file name."""
    base = Path(name).name if name else ""
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._-")
    return cleaned or f"{fallback_stem}.bin"


def _upload_dir(state: SessionState) -> Path:
    """Return the per-session uploads directory for browser file ingestion."""
    if state.workspace_dir is None:
        raise ValueError("Session workspace directory is not available")
    upload_dir = state.workspace_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _save_upload(state: SessionState, uploaded_file: UploadFile, stem: str) -> Path:
    """Persist an uploaded browser file into the session workspace uploads directory."""
    filename = _sanitize_filename(uploaded_file.filename, stem)
    upload_dir = _upload_dir(state)
    target_path = (upload_dir / filename).resolve()

    # Defense in depth: the resolved path must remain inside the uploads dir.
    if upload_dir.resolve() not in target_path.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resolved upload path escapes the session workspace",
        )

    bytes_written = 0
    chunk_size = 1 * 1024 * 1024
    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = uploaded_file.file.read(chunk_size)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Uploaded file exceeds the {_MAX_UPLOAD_BYTES} byte limit",
                    )
                handle.write(chunk)
    except HTTPException:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 - propagate as 400 with cleanup
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to save uploaded file: {exc}",
        ) from exc
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


class BuildDataModelRequest(BaseModel):
    """Request body for POST /datamodel/build — the analyst's declaration of the columns.

    Deliberately permissive at the schema layer: ``server.core.datamodel_builder`` owns
    every refusal so the MCP tool and this route reject exactly the same specs, with the
    same message naming the same column.
    """

    location: dict = Field(default_factory=dict)
    points: list[dict] = Field(default_factory=list)


@router.get("/datamodel/draft")
def draft_data_model(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Draft a Task 43 reading of the loaded timeseries columns for review."""
    del session_id
    try:
        return _draft_data_model(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.post("/datamodel/build")
def build_data_model(
    session_id: str,
    body: BuildDataModelRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Build a minimal IEA Task 43 data model from declared columns and load it."""
    del session_id
    try:
        result = _build_data_model(state, {"location": body.location, "points": body.points})
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.get("/sensors")
def get_sensors(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return the parsed sensor inventory for the current session."""
    del session_id
    # A new session has no data and so no sensors; the interface asks before any upload.
    if state.timeseries_df is None:
        return {"sensors": []}
    try:
        return _list_sensors(state)
    except ValueError as exc:
        if "Sensor mapping is not loaded" in str(exc):
            return {"sensors": _build_sensor_rows(state, require_mapping=False)}
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


# ---------------------------------------------------------------------------
# Sensor selection / removal
# ---------------------------------------------------------------------------

class DeleteSensorsRequest(BaseModel):
    """Request body for POST /sensors/delete — a list of sensor names to remove."""

    sensor_names: list[str] = Field(..., min_length=1)


@router.post("/sensors/delete")
def delete_sensors(
    session_id: str,
    body: DeleteSensorsRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Remove unwanted sensors from the session inventory, mapping, and data.

    The same logic as the ``remove_sensors`` operation (``server/tools/sensors.py``), which
    the workbench calls through the generated route so the removal can be undone; this route
    stays for the current interface until Phase 3 retires it.
    """
    del session_id
    try:
        result = _remove_sensors(state, body.sensor_names)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    if result["removed"]:
        _persist_runconfig(state)
    return result
