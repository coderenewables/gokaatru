"""brighthub — BrightHub authentication and dataset browsing routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

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

    class Config:
        extra = "allow"


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

    class Config:
        extra = "allow"


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

    class Config:
        extra = "allow"


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
    token = _require_token(state)
    try:
        nodes = fetch_reanalysis_nodes(token, body.latitude, body.longitude)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"BrightHub API error: {exc}")) from exc
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
    return ReanalysisDownloadResponse(dataset=body.dataset, source="brighthub", items=items)


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
        dm_payload = get_data_model(token, body.uuid)
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"Failed to fetch data model: {exc}")) from exc

    datamodel_path = uploads_dir / f"datamodel_{body.uuid}.json"
    datamodel_path.write_text(json.dumps(dm_payload, indent=2), encoding="utf-8")

    # 2. Fetch and save timeseries CSV
    try:
        csv_text = fetch_timeseries_csv(
            token,
            body.uuid,
            apply_cleaning_log=body.apply_cleaning_log,
            apply_cleaning_rules=body.apply_cleaning_rules,
            apply_calibration=body.apply_calibration,
            apply_deadband_offset=body.apply_deadband_offset,
            apply_orientation_offset=body.apply_orientation_offset,
        )
    except Exception as exc:
        raise to_bad_gateway(RuntimeError(f"Failed to fetch timeseries: {exc}")) from exc

    timeseries_path = uploads_dir / f"ts_{body.uuid}.csv"
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
    state.runconfig["brighthub_uuid"] = body.uuid
    state.touch()

    return ImportLocationResponse(
        uuid=body.uuid,
        timeseries_rows=ts_result.get("rows", 0),
        timeseries_columns=ts_result.get("columns", []),
        timeseries_start=ts_result.get("start"),
        timeseries_end=ts_result.get("end"),
        datamodel_heights=dm_result.get("heights", []),
        project_name=state.get_project_name(),
        measurement_type=state.get_measurement_type(),
        location=dm_result.get("location"),
    )
