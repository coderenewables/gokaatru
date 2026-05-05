"""brighthub — BrightHub authentication and dataset browsing routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

# BrightHub UUIDs are RFC-4122 hex strings; restrict to that shape so they can
# never be used to escape the per-session uploads directory when interpolated
# into file paths.
_BRIGHTHUB_UUID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _validate_brighthub_uuid(uuid: str) -> str:
    """Reject UUIDs containing path separators or traversal tokens to keep filenames safe."""
    cleaned = uuid.strip()
    if not _BRIGHTHUB_UUID_PATTERN.fullmatch(cleaned) or ".." in cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid BrightHub UUID format",
        )
    return cleaned

from server.api.deps import get_session_state, to_bad_gateway, to_bad_request
from server.core.brighthub import (
    authenticate,
    download_reanalysis_data,
    fetch_reanalysis_nodes,
    fetch_timeseries_csv,
    get_data_model,
    list_measurement_locations,
)
from server.state.session import SessionState

router = APIRouter(prefix="/sessions/{session_id}/brighthub", tags=["brighthub"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class BrightHubLoginRequest(BaseModel):
    """Credentials for BrightHub API-key authentication."""

    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)


class BrightHubLoginResponse(BaseModel):
    status: str = "ok"
    authenticated: bool = True


class BrightHubStatusResponse(BaseModel):
    authenticated: bool
    has_token: bool


class MeasurementLocation(BaseModel):
    uuid: str = ""
    name: str = ""
    latitude_ddeg: float | None = None
    longitude_ddeg: float | None = None
    measurement_station_type_id: str | int | None = None

    model_config = {"extra": "allow"}


class MeasurementLocationsResponse(BaseModel):
    locations: list[MeasurementLocation]


class DataModelResponse(BaseModel):
    uuid: str
    data_model: dict


class ReanalysisNodesRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ReanalysisNode(BaseModel):
    latitude_ddeg: float
    longitude_ddeg: float
    distance_sq: float | None = None

    model_config = {"extra": "allow"}


class ReanalysisNodesResponse(BaseModel):
    era5_nodes: list[ReanalysisNode]
    merra2_nodes: list[ReanalysisNode]


class ReanalysisDownloadRequest(BaseModel):
    dataset: str = Field(..., pattern="^(ERA5|MERRA-2)$")
    nodes: list[ReanalysisNode]
    source: str = Field("brighthub", pattern="^(brighthub|earthdatahub)$")


class ReanalysisDataItem(BaseModel):
    latitude: float
    longitude: float
    rows: int | None = None

    model_config = {"extra": "allow"}


class ReanalysisDownloadResponse(BaseModel):
    dataset: str
    source: str = "brighthub"
    items: list[ReanalysisDataItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_token(state: SessionState) -> str:
    """Return the stored BrightHub token or raise 401."""
    token = getattr(state, "brighthub_token", None)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated with BrightHub. Please log in first.",
        )
    return token


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=BrightHubLoginResponse)
def brighthub_login(
    body: BrightHubLoginRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> BrightHubLoginResponse:
    """Authenticate with BrightHub and store the token in the session."""
    try:
        result = authenticate(body.client_id, body.client_secret)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"BrightHub login failed: {exc}")) from exc
    state.brighthub_token = result["id_token"]
    state.touch()
    return BrightHubLoginResponse()


@router.post("/logout")
def brighthub_logout(
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, str]:
    """Clear the stored BrightHub token."""
    state.brighthub_token = None
    state.touch()
    return {"status": "ok"}


@router.get("/status", response_model=BrightHubStatusResponse)
def brighthub_status(
    state: Annotated[SessionState, Depends(get_session_state)],
) -> BrightHubStatusResponse:
    """Check whether the session holds a valid BrightHub token."""
    token = getattr(state, "brighthub_token", None)
    return BrightHubStatusResponse(authenticated=bool(token), has_token=bool(token))


@router.get("/locations", response_model=MeasurementLocationsResponse)
def brighthub_locations(
    state: Annotated[SessionState, Depends(get_session_state)],
) -> MeasurementLocationsResponse:
    """List measurement locations available to the authenticated BrightHub user."""
    token = _require_token(state)
    try:
        raw = list_measurement_locations(token)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"BrightHub API error: {exc}")) from exc
    locations = [MeasurementLocation(**loc) if isinstance(loc, dict) else loc for loc in raw]
    return MeasurementLocationsResponse(locations=locations)


@router.get("/locations/{uuid}/datamodel", response_model=DataModelResponse)
def brighthub_datamodel(
    uuid: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> DataModelResponse:
    """Fetch the data model for one BrightHub measurement location."""
    uuid = _validate_brighthub_uuid(uuid)
    token = _require_token(state)
    try:
        dm = get_data_model(token, uuid)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"BrightHub API error: {exc}")) from exc
    return DataModelResponse(uuid=uuid, data_model=dm)


@router.post("/reanalysis/nodes", response_model=ReanalysisNodesResponse)
def brighthub_reanalysis_nodes(
    body: ReanalysisNodesRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> ReanalysisNodesResponse:
    """Find nearest ERA5 and MERRA-2 reanalysis nodes for a coordinate."""
    from server.core.spatial import bearing_compass, haversine_km
    from server.schemas.common import Coordinate

    token = _require_token(state)
    try:
        nodes = fetch_reanalysis_nodes(token, body.latitude, body.longitude)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"BrightHub API error: {exc}")) from exc

    # Persist ERA5 nodes in state so interpolation can find them
    era5_state_nodes = []
    for n in nodes.get("era5_nodes", []):
        nlat, nlon = n["latitude_ddeg"], n["longitude_ddeg"]
        era5_state_nodes.append({
            "latitude": nlat,
            "longitude": nlon,
            "distance_km": haversine_km(body.latitude, body.longitude, nlat, nlon),
            "bearing": bearing_compass(body.latitude, body.longitude, nlat, nlon),
        })
    state.era5_nodes = sorted(era5_state_nodes, key=lambda nd: float(nd["distance_km"]))

    # Persist MERRA-2 nodes in state
    merra_state_nodes = []
    for n in nodes.get("merra2_nodes", []):
        nlat, nlon = n["latitude_ddeg"], n["longitude_ddeg"]
        merra_state_nodes.append({
            "latitude": nlat,
            "longitude": nlon,
            "distance_km": haversine_km(body.latitude, body.longitude, nlat, nlon),
            "bearing": bearing_compass(body.latitude, body.longitude, nlat, nlon),
        })
    state.merra_nodes = sorted(merra_state_nodes, key=lambda nd: float(nd["distance_km"]))

    # Store site coordinate for later interpolation
    current = state.get_coordinate()
    elev = 0.0 if current is None else current.elevation_m
    state.set_coordinate(Coordinate(latitude=body.latitude, longitude=body.longitude, elevation_m=elev))
    state.touch()

    return ReanalysisNodesResponse(
        era5_nodes=[ReanalysisNode(**n) for n in nodes.get("era5_nodes", [])],
        merra2_nodes=[ReanalysisNode(**n) for n in nodes.get("merra2_nodes", [])],
    )


@router.post("/reanalysis/download", response_model=ReanalysisDownloadResponse)
def brighthub_reanalysis_download(
    body: ReanalysisDownloadRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> ReanalysisDownloadResponse:
    """Download reanalysis timeseries data for specified nodes.

    For ERA5 data, the ``source`` field selects either BrightHub or the
    EarthDataHub Zarr store.  MERRA-2 always uses BrightHub.
    """
    use_earthdatahub = body.source == "earthdatahub" and body.dataset == "ERA5"

    if use_earthdatahub:
        return _download_era5_earthdatahub(state, body)

    token = _require_token(state)
    node_dicts = [n.model_dump() for n in body.nodes]
    try:
        results = download_reanalysis_data(token, node_dicts, body.dataset)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"BrightHub API error: {exc}")) from exc
    items: list[ReanalysisDataItem] = []
    for r in results:
        ts = r.get("timeseries_data")
        row_count = len(ts.get("data", [])) if isinstance(ts, dict) else None
        items.append(ReanalysisDataItem(latitude=r["latitude"], longitude=r["longitude"], rows=row_count))
        # Store as DataFrame in session state so interpolation works
        if isinstance(ts, dict):
            if body.dataset == "ERA5":
                _store_brighthub_era5_frame(state, r["latitude"], r["longitude"], ts)
            elif body.dataset == "MERRA-2":
                _store_brighthub_merra_frame(state, r["latitude"], r["longitude"], ts)
    state.touch()
    return ReanalysisDownloadResponse(dataset=body.dataset, source="brighthub", items=items)


# BrightHub ERA5 column mapping → internal ERA5 convention used by interpolation
_BH_ERA5_COLUMN_MAP = {
    "Spd_100m_mps": "Spd_100m",
    "Dir_100m_deg": "Dir_100m",
    "Tmp_2m_degC": "t2m",
    "Prs_0m_hPa": "sp",
}


def _store_brighthub_era5_frame(
    state: SessionState,
    latitude: float,
    longitude: float,
    ts: dict,
) -> None:
    """Parse a BrightHub timeseries JSON payload into a DataFrame and store it in session state."""
    import pandas as pd

    from server.tools.era5 import _era5_key

    data = ts.get("data", [])
    if not data:
        return
    # BrightHub returns [{"timestamp": ..., "var1": ..., ...}, ...] or
    # {"columns": [...], "data": [[...], ...]} depending on version.
    if isinstance(data[0], dict):
        frame = pd.DataFrame(data)
    else:
        columns = ts.get("columns", [])
        frame = pd.DataFrame(data, columns=columns if columns else None)
    # Set time index
    time_col = next((c for c in frame.columns if c.lower() in ("timestamp", "time", "datetime")), None)
    if time_col is not None:
        frame[time_col] = pd.to_datetime(frame[time_col], utc=True)
        frame = frame.set_index(time_col)
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(frame.index, name="time")
    # Strip timezone so index is tz-naive (matches EarthDataHub + measured convention)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame.index.name = "time"
    # Rename BrightHub columns to internal convention
    frame = frame.rename(columns=_BH_ERA5_COLUMN_MAP)
    state.era5_data[_era5_key(latitude, longitude)] = frame.sort_index()


def _merra_key(latitude: float, longitude: float) -> str:
    """Build a dict key for MERRA-2 nodes matching the ERA5 convention."""
    return f"{latitude}_{longitude}"


# BrightHub MERRA-2 column mapping → internal convention
_BH_MERRA_COLUMN_MAP = {
    "Spd_100m_mps": "Spd_100m",
    "Dir_100m_deg": "Dir_100m",
    "Spd_50m_mps": "Spd_50m",
    "Dir_50m_deg": "Dir_50m",
    "Tmp_2m_degC": "t2m",
    "Prs_0m_hPa": "sp",
}


def _store_brighthub_merra_frame(
    state: SessionState,
    latitude: float,
    longitude: float,
    ts: dict,
) -> None:
    """Parse a BrightHub MERRA-2 JSON payload into a DataFrame and store it in session state."""
    import pandas as pd

    data = ts.get("data", [])
    if not data:
        return
    if isinstance(data[0], dict):
        frame = pd.DataFrame(data)
    else:
        columns = ts.get("columns", [])
        frame = pd.DataFrame(data, columns=columns if columns else None)
    time_col = next((c for c in frame.columns if c.lower() in ("timestamp", "time", "datetime")), None)
    if time_col is not None:
        frame[time_col] = pd.to_datetime(frame[time_col], utc=True)
        frame = frame.set_index(time_col)
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(frame.index, name="time")
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    frame.index.name = "time"
    frame = frame.rename(columns=_BH_MERRA_COLUMN_MAP)
    state.merra_data[_merra_key(latitude, longitude)] = frame.sort_index()


def _download_era5_earthdatahub(
    state: SessionState,
    body: ReanalysisDownloadRequest,
) -> ReanalysisDownloadResponse:
    """Download ERA5 data from EarthDataHub Zarr store for the requested nodes."""
    from server.tools.era5 import Era5UpstreamError, _compute_era5_wind_speed, _extract_era5_data

    items: list[ReanalysisDataItem] = []
    for node in body.nodes:
        lat, lon = node.latitude_ddeg, node.longitude_ddeg
        try:
            result = _extract_era5_data(state, lat, lon)
            _compute_era5_wind_speed(state, lat, lon)
        except Era5UpstreamError as exc:
            raise to_bad_gateway(RuntimeError(f"EarthDataHub ERA5 error: {exc}")) from exc
        except Exception as exc:
            raise to_bad_gateway(RuntimeError(f"ERA5 extraction error: {exc}")) from exc
        items.append(ReanalysisDataItem(
            latitude=lat,
            longitude=lon,
            rows=result.get("rows"),
        ))
    return ReanalysisDownloadResponse(dataset="ERA5", source="earthdatahub", items=items)


# ---------------------------------------------------------------------------
# Import location (timeseries + datamodel) into session
# ---------------------------------------------------------------------------

class ImportLocationRequest(BaseModel):
    """Select a BrightHub measurement location to import into the session."""

    uuid: str = Field(..., min_length=1)
    name: str = ""
    latitude_ddeg: float | None = None
    longitude_ddeg: float | None = None
    apply_cleaning_log: bool = True
    apply_cleaning_rules: bool = False
    apply_calibration: bool = False
    apply_deadband_offset: bool = False
    apply_orientation_offset: bool = False


class ImportLocationResponse(BaseModel):
    status: str = "ok"
    uuid: str
    timeseries_rows: int = 0
    timeseries_columns: list[str] = []
    timeseries_start: str | None = None
    timeseries_end: str | None = None
    datamodel_heights: list[float] = []
    project_name: str | None = None
    measurement_type: str | None = None
    location: dict | None = None


@router.post("/import", response_model=ImportLocationResponse)
def brighthub_import_location(
    body: ImportLocationRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> ImportLocationResponse:
    """Fetch timeseries and datamodel from BrightHub and load them into the session.

    This replicates the Flask app flow: fetch datamodel → build sensor mapping,
    fetch timeseries via presigned URL → parse into session state.
    """
    import json
    from pathlib import Path

    from server.tools.data_io import _parse_datamodel, _parse_timeseries

    safe_uuid = _validate_brighthub_uuid(body.uuid)
    token = _require_token(state)

    if state.workspace_dir is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has no workspace directory. Create a session first.",
        )

    uploads_dir = state.workspace_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch and save datamodel JSON
    try:
        dm_payload = get_data_model(token, safe_uuid)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"Failed to fetch data model: {exc}")) from exc

    datamodel_path = uploads_dir / f"datamodel_{safe_uuid}.json"
    datamodel_path.write_text(json.dumps(dm_payload, indent=2), encoding="utf-8")

    # 2. Fetch and save timeseries CSV
    try:
        csv_text = fetch_timeseries_csv(
            token,
            safe_uuid,
            apply_cleaning_log=body.apply_cleaning_log,
            apply_cleaning_rules=body.apply_cleaning_rules,
            apply_calibration=body.apply_calibration,
            apply_deadband_offset=body.apply_deadband_offset,
            apply_orientation_offset=body.apply_orientation_offset,
        )
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"Failed to fetch timeseries: {exc}")) from exc

    timeseries_path = uploads_dir / f"ts_{safe_uuid}.csv"
    timeseries_path.write_text(csv_text, encoding="utf-8")

    # 3. Parse timeseries into session state
    try:
        ts_result = _parse_timeseries(state, str(timeseries_path))
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    # 4. Parse datamodel into session state (sensor mapping + metadata)
    try:
        dm_result = _parse_datamodel(state, str(datamodel_path))
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    # 5. Apply location metadata from the request if not already set by datamodel
    if body.name and state.get_project_name() in {None, ""}:
        state.set_project_name(body.name)
    if body.latitude_ddeg is not None and body.longitude_ddeg is not None and state.get_coordinate() is None:
        from server.schemas.common import Coordinate
        state.set_coordinate(Coordinate(latitude=body.latitude_ddeg, longitude=body.longitude_ddeg))

    # 6. Store BrightHub UUID in runconfig for traceability
    state.runconfig["brighthub_uuid"] = safe_uuid
    state.touch()

    return ImportLocationResponse(
        uuid=safe_uuid,
        timeseries_rows=ts_result.get("rows", 0),
        timeseries_columns=ts_result.get("columns", []),
        timeseries_start=ts_result.get("start"),
        timeseries_end=ts_result.get("end"),
        datamodel_heights=dm_result.get("heights", []),
        project_name=state.get_project_name(),
        measurement_type=state.get_measurement_type(),
        location=dm_result.get("location"),
    )
