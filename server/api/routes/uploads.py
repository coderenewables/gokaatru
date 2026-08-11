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

# Maps sensor_type (as stored in sensor_inventory) to the sensor_mapping slot
# that holds the column name for that measurement kind.
_SENSOR_TYPE_TO_SLOT: dict[str, str] = {
    "wind_speed": "speed_col",
    "wind_direction": "dir_col",
    "temperature": "temp_col",
    "pressure": "pressure_col",
}


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

    Removes the named sensors from ``sensor_inventory``, clears their column
    slot from ``sensor_mapping`` (by height), and drops their columns from both
    the working and raw timeseries dataframes. If a height entry in the mapping
    becomes entirely ``None`` after removal, the height is dropped from the
    mapping. The exclusion is persisted to ``excluded_sensors`` in the
    runconfig so the selection is authoritative and survives config saves and
    datamodel-only re-imports. Loading the timeseries again or re-importing
    from BrightHub clears the exclusion and restores the full dataset.
    """
    del session_id
    if not state.sensor_inventory:
        raise to_bad_request(ValueError("Sensor inventory is not loaded"))

    removed: list[str] = []
    not_found: list[str] = []

    for name in body.sensor_names:
        if name not in state.sensor_inventory:
            not_found.append(name)
            continue

        meta = state.sensor_inventory.pop(name)
        removed.append(name)

        # Clean up the height-keyed sensor_mapping slot for this sensor type.
        height = meta.get("height_m")
        sensor_type = meta.get("sensor_type", "")
        slot = _SENSOR_TYPE_TO_SLOT.get(str(sensor_type))
        if slot is not None and height is not None:
            # sensor_mapping keys are float heights; match loosely.
            for map_height, slots in list(state.sensor_mapping.items()):
                if abs(float(map_height) - float(height)) < 0.01 and slots.get(slot) == name:
                    slots[slot] = None
                    # Also clear auto-derived sd_col if this was a speed sensor.
                    if slot == "speed_col":
                        slots["sd_col"] = None
                    # If every slot is now None, drop the height entirely.
                    if all(v is None for v in slots.values()):
                        del state.sensor_mapping[map_height]
                    break

    # Re-sort the mapping descending by height (consistent with parse_datamodel).
    state.sensor_mapping = dict(sorted(state.sensor_mapping.items(), reverse=True))

    if removed:
        # The selection is authoritative: drop the excluded columns from the
        # working and raw data so downstream analysis never sees them.
        removed_set = set(removed)
        for frame_attr in ("timeseries_df", "raw_timeseries_df"):
            frame = getattr(state, frame_attr)
            if frame is not None:
                drop_cols = [column for column in frame.columns if column in removed_set]
                if drop_cols:
                    setattr(state, frame_attr, frame.drop(columns=drop_cols))

        # Persist the exclusion so it survives config saves and datamodel-only
        # re-imports. runconfig.json is the single source of truth — write through.
        existing = state.runconfig.get("excluded_sensors")
        excluded_list = [str(name) for name in existing] if isinstance(existing, list) else []
        for name in removed:
            if name not in excluded_list:
                excluded_list.append(name)
        state.runconfig["excluded_sensors"] = excluded_list
        _persist_runconfig(state)

    state.touch()

    return {
        "status": "ok",
        "removed": removed,
        "not_found": not_found,
        "remaining_count": len(state.sensor_inventory),
    }
