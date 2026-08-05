"""brighthub — MCP tools for BrightHub authentication, dataset browsing, and data import.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from server.core.brighthub import (
    authenticate,
    download_reanalysis_data,
    fetch_reanalysis_nodes,
    fetch_timeseries_csv,
    get_data_model,
    list_measurement_locations,
)
from server.main import mcp
from server.schemas.common import Coordinate
from server.state.session import SessionState, session


def _require_token(state: SessionState) -> str:
    """Return the stored BrightHub token or raise ValueError."""
    token = getattr(state, "brighthub_token", None)
    if not token:
        raise ValueError("Not authenticated with BrightHub. Run brighthub_login first.")
    return token


# ---------------------------------------------------------------------------
# Authentication tools
# ---------------------------------------------------------------------------


@mcp.tool()
def brighthub_login(client_id: str, client_secret: str) -> dict:
    """Authenticate with BrightHub using API key credentials and store token in session."""
    try:
        result = authenticate(client_id, client_secret)
    except Exception as exc:
        raise RuntimeError(f"BrightHub login failed: {exc}") from exc
    session.brighthub_token = result["id_token"]
    session.touch()
    return {"status": "ok", "authenticated": True}


@mcp.tool()
def brighthub_logout() -> dict:
    """Clear the stored BrightHub authentication token."""
    session.brighthub_token = None
    session.touch()
    return {"status": "ok", "authenticated": False}


@mcp.tool()
def brighthub_status() -> dict:
    """Check whether the session holds a valid BrightHub token."""
    has_token = bool(getattr(session, "brighthub_token", None))
    return {"authenticated": has_token, "has_token": has_token}


# ---------------------------------------------------------------------------
# Location browsing tools
# ---------------------------------------------------------------------------


@mcp.tool()
def brighthub_list_locations() -> dict:
    """List measurement locations available to the authenticated BrightHub user."""
    token = _require_token(session)
    try:
        raw = list_measurement_locations(token)
    except Exception as exc:
        raise RuntimeError(f"BrightHub API error: {exc}") from exc
    locations = []
    for loc in raw:
        locations.append({
            "uuid": loc.get("uuid", ""),
            "name": loc.get("name", ""),
            "latitude_ddeg": loc.get("latitude_ddeg"),
            "longitude_ddeg": loc.get("longitude_ddeg"),
            "measurement_station_type_id": loc.get("measurement_station_type_id"),
        })
    return {"locations": locations, "count": len(locations)}


@mcp.tool()
def brighthub_get_data_model(uuid: str) -> dict:
    """Fetch the IEA Task 43 data model for a BrightHub measurement location."""
    token = _require_token(session)
    try:
        dm = get_data_model(token, uuid)
    except Exception as exc:
        raise RuntimeError(f"BrightHub API error: {exc}") from exc
    return {"uuid": uuid, "data_model": dm}


# ---------------------------------------------------------------------------
# Import tool — fetch timeseries + datamodel and load into session
# ---------------------------------------------------------------------------


@mcp.tool()
def brighthub_import_location(
    uuid: str,
    name: str = "",
    latitude_ddeg: float = 0.0,
    longitude_ddeg: float = 0.0,
    apply_cleaning_log: bool = True,
    apply_cleaning_rules: bool = False,
    apply_calibration: bool = False,
    apply_deadband_offset: bool = False,
    apply_orientation_offset: bool = False,
) -> dict:
    """Fetch timeseries and datamodel from BrightHub and load them into the session.

    Downloads the assembled CSV via presigned URL and the data model JSON,
    then parses both into session state (timeseries_df, sensor_mapping, etc.).
    """
    from server.tools.data_io import _parse_datamodel, _parse_timeseries

    token = _require_token(session)
    data_dir = Path(session.get_data_dir())
    uploads_dir = data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch and save datamodel JSON
    dm_payload = get_data_model(token, uuid)
    datamodel_path = uploads_dir / f"datamodel_{uuid}.json"
    datamodel_path.write_text(json.dumps(dm_payload, indent=2), encoding="utf-8")

    # 2. Fetch and save timeseries CSV
    csv_text = fetch_timeseries_csv(
        token,
        uuid,
        apply_cleaning_log=apply_cleaning_log,
        apply_cleaning_rules=apply_cleaning_rules,
        apply_calibration=apply_calibration,
        apply_deadband_offset=apply_deadband_offset,
        apply_orientation_offset=apply_orientation_offset,
    )
    timeseries_path = uploads_dir / f"ts_{uuid}.csv"
    timeseries_path.write_text(csv_text, encoding="utf-8")

    # 3. Parse timeseries into session state
    ts_result = _parse_timeseries(session, str(timeseries_path))

    # 4. Parse datamodel into session state
    dm_result = _parse_datamodel(session, str(datamodel_path))

    # 5. Apply location metadata if not already set
    if name and session.get_project_name() in {None, ""}:
        session.set_project_name(name)
    if latitude_ddeg != 0.0 and longitude_ddeg != 0.0 and session.get_coordinate() is None:
        from server.schemas.common import Coordinate

        session.set_coordinate(Coordinate(latitude=latitude_ddeg, longitude=longitude_ddeg))

    # 6. Store BrightHub UUID in runconfig
    session.runconfig["brighthub_uuid"] = uuid
    session.touch()

    return {
        "status": "ok",
        "uuid": uuid,
        "timeseries_rows": ts_result.get("rows", 0),
        "timeseries_columns": ts_result.get("columns", []),
        "timeseries_start": ts_result.get("start"),
        "timeseries_end": ts_result.get("end"),
        "datamodel_heights": dm_result.get("heights", []),
        "project_name": session.get_project_name(),
        "measurement_type": session.get_measurement_type(),
    }


# ---------------------------------------------------------------------------
# Reanalysis tools
# ---------------------------------------------------------------------------


@mcp.tool()
def brighthub_find_reanalysis_nodes(latitude: float, longitude: float) -> dict:
    """Find nearest ERA5 and MERRA-2 reanalysis nodes via BrightHub for a coordinate."""
    token = _require_token(session)
    try:
        nodes = fetch_reanalysis_nodes(token, latitude, longitude)
    except Exception as exc:
        raise RuntimeError(f"BrightHub API error: {exc}") from exc
    return {
        "era5_nodes": nodes.get("era5_nodes", []),
        "merra2_nodes": nodes.get("merra2_nodes", []),
        "era5_count": len(nodes.get("era5_nodes", [])),
        "merra2_count": len(nodes.get("merra2_nodes", [])),
    }


@mcp.tool()
def brighthub_download_reanalysis(
    dataset: str,
    nodes_json: str,
    source: str = "brighthub",
) -> dict:
    """Download reanalysis timeseries data for specified nodes.

    ``dataset`` must be 'ERA5' or 'MERRA-2'.
    ``nodes_json`` is a JSON array of objects with ``latitude_ddeg`` and ``longitude_ddeg``.
    ``source`` selects 'brighthub' or 'earthdatahub' (ERA5 only; MERRA-2 always uses BrightHub).
    """
    if dataset not in {"ERA5", "MERRA-2"}:
        raise ValueError(f"dataset must be 'ERA5' or 'MERRA-2', got '{dataset}'")
    if source not in {"brighthub", "earthdatahub"}:
        raise ValueError(f"source must be 'brighthub' or 'earthdatahub', got '{source}'")

    try:
        nodes = json.loads(nodes_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for nodes_json: {exc}") from exc

    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes_json must be a non-empty JSON array")

    use_earthdatahub = source == "earthdatahub" and dataset == "ERA5"

    if use_earthdatahub:
        return _download_era5_earthdatahub(nodes)

    token = _require_token(session)
    try:
        results = download_reanalysis_data(token, nodes, dataset)
    except Exception as exc:
        raise RuntimeError(f"BrightHub API error: {exc}") from exc

    items = []
    for r in results:
        ts = r.get("timeseries_data")
        row_count = len(ts.get("data", [])) if isinstance(ts, dict) else None
        items.append({"latitude": r["latitude"], "longitude": r["longitude"], "rows": row_count})

    return {"dataset": dataset, "source": "brighthub", "items": items, "count": len(items)}


_BRIGHTHUB_ERA5_COLUMNS = {
    "Spd_100m_mps": "Spd_100m",
    "Dir_100m_deg": "Dir_100m",
    "Tmp_2m_degC": "t2m",
    "Prs_0m_hPa": "sp",
}

_BRIGHTHUB_MERRA_COLUMNS = {
    "Spd_100m_mps": "Spd_100m",
    "Dir_100m_deg": "Dir_100m",
    "Spd_50m_mps": "Spd_50m",
    "Dir_50m_deg": "Dir_50m",
    "Tmp_2m_degC": "t2m",
    "Prs_0m_hPa": "sp",
}


def _reanalysis_frame(payload: dict, column_map: dict[str, str]) -> pd.DataFrame:
    """Normalize a BrightHub reanalysis payload into the session dataframe format."""
    timeseries = payload.get("timeseries_data")
    if not isinstance(timeseries, dict):
        raise ValueError("BrightHub reanalysis response did not include timeseries data")
    data = timeseries.get("data", [])
    if not data:
        raise ValueError("BrightHub reanalysis response contained no rows")
    if isinstance(data[0], dict):
        frame = pd.DataFrame(data)
    else:
        frame = pd.DataFrame(data, columns=timeseries.get("columns") or None)
    timestamp = next((name for name in frame.columns if str(name).lower() in {"timestamp", "time", "datetime"}), None)
    if timestamp is None:
        raise ValueError("BrightHub reanalysis response did not include a timestamp column")
    frame[timestamp] = pd.to_datetime(frame[timestamp], utc=True)
    frame = frame.set_index(timestamp)
    frame.index = frame.index.tz_localize(None)
    frame.index.name = "time"
    return frame.rename(columns=column_map).sort_index()


def _prepare_brighthub_reanalysis(
    state: SessionState,
    latitude: float,
    longitude: float,
    source: str = "brighthub",
) -> dict:
    """Load BrightHub ERA5 + MERRA-2 and interpolate ERA5 to the project site."""
    from server.core.spatial import bearing_compass, haversine_km
    from server.tools.era5 import _era5_key, _interpolate_era5_to_site

    if source != "brighthub":
        raise ValueError("Combined ERA5 + MERRA-2 preparation currently supports the BrightHub source only")

    cache_identity = {
        "source": source,
        "latitude": float(latitude),
        "longitude": float(longitude),
    }
    if (
        state.reanalysis_cache_identity == cache_identity
        and state.era5_nodes is not None
        and len(state.era5_nodes) >= 4
        and bool(state.era5_data)
        and state.merra_nodes is not None
        and bool(state.merra_data)
        and state.era5_interpolated_df is not None
    ):
        current_coordinate = state.get_coordinate()
        elevation_m = 0.0 if current_coordinate is None else current_coordinate.elevation_m
        state.set_coordinate(Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation_m))
        return {
            "status": "ok",
            "source": source,
            "cached": True,
            "era5_nodes": len(state.era5_nodes),
            "merra2_nodes": len(state.merra_nodes),
            "interpolation": {
                "status": "ok",
                "rows": int(len(state.era5_interpolated_df)),
                "method": "cached",
                "variables": state.era5_interpolated_df.columns.tolist(),
            },
        }

    token = _require_token(state)
    try:
        node_sets = fetch_reanalysis_nodes(token, latitude, longitude)
        era5_nodes = node_sets.get("era5_nodes", [])
        merra_nodes = node_sets.get("merra2_nodes", [])
        era5_results = download_reanalysis_data(token, era5_nodes, "ERA5")
        merra_results = download_reanalysis_data(token, merra_nodes, "MERRA-2")
    except Exception as exc:
        raise RuntimeError(f"BrightHub reanalysis preparation failed: {exc}") from exc

    if len(era5_results) < 4:
        raise ValueError("BrightHub returned fewer than four ERA5 nodes; site interpolation requires four nodes")
    if not merra_results:
        raise ValueError("BrightHub returned no MERRA-2 reanalysis data")

    current_coordinate = state.get_coordinate()
    elevation_m = 0.0 if current_coordinate is None else current_coordinate.elevation_m
    state.set_coordinate(Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation_m))
    state.era5_nodes = [
        {
            "latitude": float(item["latitude"]),
            "longitude": float(item["longitude"]),
            "distance_km": haversine_km(latitude, longitude, float(item["latitude"]), float(item["longitude"])),
            "bearing": bearing_compass(latitude, longitude, float(item["latitude"]), float(item["longitude"])),
        }
        for item in era5_results
    ]
    state.merra_nodes = [
        {
            "latitude": float(item["latitude"]),
            "longitude": float(item["longitude"]),
            "distance_km": haversine_km(latitude, longitude, float(item["latitude"]), float(item["longitude"])),
            "bearing": bearing_compass(latitude, longitude, float(item["latitude"]), float(item["longitude"])),
        }
        for item in merra_results
    ]
    state.era5_data = {
        _era5_key(float(item["latitude"]), float(item["longitude"])): _reanalysis_frame(item, _BRIGHTHUB_ERA5_COLUMNS)
        for item in era5_results
    }
    state.merra_data = {
        f"{float(item['latitude'])}_{float(item['longitude'])}": _reanalysis_frame(item, _BRIGHTHUB_MERRA_COLUMNS)
        for item in merra_results
    }
    interpolation = _interpolate_era5_to_site(state)
    state.reanalysis_cache_identity = cache_identity
    state.touch()
    return {
        "status": "ok",
        "source": source,
        "cached": False,
        "era5_nodes": len(state.era5_nodes),
        "merra2_nodes": len(state.merra_nodes),
        "interpolation": interpolation,
    }


@mcp.tool()
def brighthub_prepare_reanalysis(latitude: float, longitude: float, source: str = "brighthub") -> dict:
    """Load BrightHub ERA5 and MERRA-2, then interpolate ERA5 to the project site."""
    return _prepare_brighthub_reanalysis(session, latitude, longitude, source)


def _download_era5_earthdatahub(nodes: list[dict]) -> dict:
    """Download ERA5 data from EarthDataHub Zarr store for the requested nodes."""
    from server.tools.era5 import Era5UpstreamError, _compute_era5_wind_speed, _extract_era5_data

    items = []
    for node in nodes:
        lat = node["latitude_ddeg"]
        lon = node["longitude_ddeg"]
        try:
            result = _extract_era5_data(session, lat, lon)
            _compute_era5_wind_speed(session, lat, lon)
        except Era5UpstreamError as exc:
            raise RuntimeError(f"EarthDataHub ERA5 error: {exc}") from exc
        items.append({"latitude": lat, "longitude": lon, "rows": result.get("rows")})

    return {"dataset": "ERA5", "source": "earthdatahub", "items": items, "count": len(items)}
