"""brighthub — MCP tools for BrightHub authentication, dataset browsing, and data import.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd

from server.core.brighthub import (
    authenticate,
    download_reanalysis_data,
    fetch_reanalysis_nodes,
    fetch_timeseries_csv,
    get_data_model,
    list_measurement_locations,
)
from server.core.reanalysis import DEFAULT_REFERENCE_SOURCE, reference_source_names
from server.operations import operation
from server.schemas.common import Coordinate
from server.schemas.results import brighthub as result_models
from server.state.session import SessionState, get_active_session, session
from server.tools.era5 import _era5_key


class BrightHubAuthError(ValueError):
    """No BrightHub login in this session; the HTTP routes answer it with 401."""


def _require_token(state: SessionState) -> str:
    """Return the stored BrightHub token or raise BrightHubAuthError."""
    token = getattr(state, "brighthub_token", None)
    if not token:
        raise BrightHubAuthError("Not authenticated with BrightHub. Run brighthub_login first.")
    return token


# ---------------------------------------------------------------------------
# Authentication tools
#
# No BrightHub tool is offered to the assistant: they call the network, and the credential
# ones would hand an injected prompt a view of the session's authentication state.
# ---------------------------------------------------------------------------


@operation(
    effect="change",
    stage="reanalysis_download",
    assistant=False,
    network=True,
    secret_parameters=("client_id", "client_secret"),
    result=result_models.BrighthubLoginResult,
    writes=("credentials",),
)
def brighthub_login(client_id: str, client_secret: str) -> dict:
    """Authenticate with BrightHub using API key credentials and store token in session."""
    try:
        result = authenticate(client_id, client_secret)
    except Exception as exc:
        raise RuntimeError(f"BrightHub login failed: {exc}") from exc
    session.brighthub_token = result["id_token"]
    session.touch()
    return {"status": "ok", "authenticated": True}


@operation(
    effect="change", stage="reanalysis_download", assistant=False, result=result_models.BrighthubLogoutResult,
    writes=("credentials",),
)
def brighthub_logout() -> dict:
    """Clear the stored BrightHub authentication token."""
    session.brighthub_token = None
    session.touch()
    return {"status": "ok", "authenticated": False}


@operation(
    effect="read", stage="reanalysis_download", assistant=False, result=result_models.BrighthubStatusResult,
    reads=("credentials",),
)
def brighthub_status() -> dict:
    """Check whether the session holds a valid BrightHub token."""
    has_token = bool(getattr(session, "brighthub_token", None))
    return {"authenticated": has_token, "has_token": has_token}


# ---------------------------------------------------------------------------
# Location browsing tools
# ---------------------------------------------------------------------------


@operation(
    effect="read", stage="reanalysis_download", assistant=False, network=True,
    result=result_models.BrighthubListLocationsResult,
    reads=("credentials",),
)
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


@operation(
    effect="read", stage="reanalysis_download", assistant=False, network=True,
    result=result_models.BrighthubGetDataModelResult,
    reads=("credentials",),
)
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


@operation(
    effect="change", stage="reanalysis_download", assistant=False, network=True,
    disclosure=(
        "upstream_processing",
    ),
    result=result_models.BrighthubImportLocationResult,
    reads=("credentials",),
    writes=("data_model", "measured_data", "hub_height_series", "label", "site"),
)
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
    live_session = get_active_session()
    data_dir = Path(live_session.get_data_dir())
    uploads_dir = data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch import inputs before mutating session state or its workspace files.
    dm_payload = get_data_model(token, uuid)
    csv_text = fetch_timeseries_csv(
        token,
        uuid,
        apply_cleaning_log=apply_cleaning_log,
        apply_cleaning_rules=apply_cleaning_rules,
        apply_calibration=apply_calibration,
        apply_deadband_offset=apply_deadband_offset,
        apply_orientation_offset=apply_orientation_offset,
    )
    datamodel_path = uploads_dir / f"datamodel_{uuid}.json"
    timeseries_path = uploads_dir / f"ts_{uuid}.csv"
    with (
        NamedTemporaryFile("w", encoding="utf-8", dir=uploads_dir, suffix=".json", delete=False) as datamodel_file,
        NamedTemporaryFile("w", encoding="utf-8", dir=uploads_dir, suffix=".csv", delete=False) as timeseries_file,
    ):
        temporary_datamodel_path = Path(datamodel_file.name)
        temporary_timeseries_path = Path(timeseries_file.name)
        datamodel_file.write(json.dumps(dm_payload, indent=2))
        timeseries_file.write(csv_text)
    staged_session = live_session.clone_for_transaction()
    try:
        ts_result = _parse_timeseries(staged_session, str(temporary_timeseries_path))
        dm_result = _parse_datamodel(staged_session, str(temporary_datamodel_path))
    except Exception:
        temporary_datamodel_path.unlink(missing_ok=True)
        temporary_timeseries_path.unlink(missing_ok=True)
        raise

    # 4b. Record what BrightHub did to the data before we saw it (D27). Without
    # this, the cleaning log — an audit artifact for a bankable report — reads as
    # the complete record of what was removed, and the coverage figures computed
    # at import describe a post-BrightHub-cleaning dataset while appearing to
    # describe the raw campaign.
    upstream_flags = {
        "apply_cleaning_log": bool(apply_cleaning_log),
        "apply_cleaning_rules": bool(apply_cleaning_rules),
        "apply_calibration": bool(apply_calibration),
        "apply_wind_vane_deadband_offset": bool(apply_deadband_offset),
        "apply_device_orientation_offset": bool(apply_orientation_offset),
    }
    provenance_entry: dict[str, object] = {
        "rule_type": "brighthub_upstream_processing",
        "sensor": "*",
        "records_affected": None,
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": upstream_flags,
        "start_date": "",
        "end_date": "",
        "source": "brighthub",
        "upstream": True,
        "undoable": False,
        "brighthub_uuid": uuid,
        "note": (
            "Applied by BrightHub before import. GoKaatru did not perform this processing, cannot "
            "reverse it, and cannot report how many records it affected. Coverage and recovery "
            "figures below describe the data as received, not the raw campaign."
        ),
    }
    staged_session.cleaning_log.insert(0, provenance_entry)

    # 5. Apply location metadata if not already set
    if name and staged_session.get_project_name() in {None, ""}:
        staged_session.set_project_name(name)
    if latitude_ddeg != 0.0 and longitude_ddeg != 0.0 and staged_session.get_coordinate() is None:
        from server.schemas.common import Coordinate

        staged_session.set_coordinate(Coordinate(latitude=latitude_ddeg, longitude=longitude_ddeg))

    # 6. Store BrightHub UUID in runconfig
    staged_session.runconfig["brighthub_uuid"] = uuid
    temporary_datamodel_path.replace(datamodel_path)
    temporary_timeseries_path.replace(timeseries_path)
    live_session.commit_transaction(staged_session)
    live_session.touch()

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
        # Surfaced in the import response so the upstream processing is visible
        # at the point of import, not only to whoever reads the cleaning log.
        "upstream_processing": upstream_flags,
        "upstream_processing_note": provenance_entry["note"],
    }


# ---------------------------------------------------------------------------
# Reanalysis tools
# ---------------------------------------------------------------------------


@operation(
    effect="read", stage="reanalysis_download", assistant=False, network=True,
    result=result_models.BrighthubFindReanalysisNodesResult,
    reads=("credentials",),
)
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


@operation(
    effect="change", stage="reanalysis_download", assistant=False, network=True,
    result=result_models.BrighthubDownloadReanalysisResult,
    reads=("credentials", "measured_data"),
    writes=("reanalysis_nodes",),
)
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

    items = _download_brighthub_nodes(session, dataset, nodes)
    return {"dataset": dataset, "source": "brighthub", "items": items, "count": len(items)}


def _campaign_end(state: SessionState) -> pd.Timestamp | None:
    """The last measured record, in UTC without an offset, as the cached frames are kept."""
    frame = state.timeseries_df
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return None
    last = pd.Timestamp(frame.index.max())
    return last.tz_convert("UTC").tz_localize(None) if last.tzinfo is not None else last


def _cached_node(state: SessionState, dataset: str, latitude: float, longitude: float) -> pd.DataFrame | None:
    """A node already downloaded, if its series reaches the campaign's last measured record.

    The long-term correction needs the reference over the concurrent period, so a node
    cached for an earlier campaign that ends before this one's last record is downloaded
    again. A cached node is never refreshed otherwise: values that were still preliminary
    (ERA5T) when it was downloaded are not revised.
    """
    path = _brighthub_cache_path(state, dataset, latitude, longitude)
    end = _campaign_end(state)
    if end is None or not path.exists():
        return None
    frame = pd.read_parquet(path)
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.max() < end:
        return None
    return frame


def _download_brighthub_nodes(
    state: SessionState, dataset: str, nodes: list[dict], store: dict[str, pd.DataFrame] | None = None
) -> list[dict]:
    """Store each node's series, in the session's own store unless ``store`` is given: from
    the project's cache when it covers the campaign (``_cached_node``), from BrightHub
    otherwise. Every item says which."""
    column_map = _BRIGHTHUB_ERA5_COLUMNS if dataset == "ERA5" else _BRIGHTHUB_MERRA_COLUMNS
    if store is None:
        store = state.era5_data if dataset == "ERA5" else state.merra_data
    items: list[dict] = []
    missing: list[dict] = []
    for node in nodes:
        latitude, longitude = float(node["latitude_ddeg"]), float(node["longitude_ddeg"])
        cached = _cached_node(state, dataset, latitude, longitude)
        if cached is None:
            missing.append(node)
            continue
        store[_era5_key(latitude, longitude) if dataset == "ERA5" else f"{latitude}_{longitude}"] = cached
        items.append({"latitude": latitude, "longitude": longitude, "rows": int(len(cached)), "cache": "hit",
                      "cached_through": pd.Timestamp(cached.index.max()).isoformat()})
    if missing:
        token = _require_token(state)
        try:
            results = download_reanalysis_data(token, missing, dataset)
        except Exception as exc:
            raise RuntimeError(f"BrightHub API error: {exc}") from exc
        for r in results:
            latitude = float(r["latitude"])
            longitude = float(r["longitude"])
            ts = r.get("timeseries_data")
            if not isinstance(ts, dict) or not ts.get("data"):
                items.append({"latitude": latitude, "longitude": longitude, "rows": None, "cache": "empty",
                              "cached_through": None})
                continue
            frame = _persist_reanalysis_frame(state, dataset, latitude, longitude, r, column_map)
            store[_era5_key(latitude, longitude) if dataset == "ERA5" else f"{latitude}_{longitude}"] = frame
            items.append({"latitude": latitude, "longitude": longitude, "rows": int(len(frame)),
                          "cache": "downloaded", "cached_through": pd.Timestamp(frame.index.max()).isoformat()})
    state.touch()
    return items


_BRIGHTHUB_ERA5_COLUMNS = {
    "Spd_100m_mps": "Spd_100m",
    "Dir_100m_deg": "Dir_100m",
    "Tmp_2m_degC": "t2m",
    "Prs_0m_hPa": "sp",
}

# MERRA-2 serves 50 m winds and has no 100 m field; `download_reanalysis_data` requests
# `Spd_50m_mps,Dir_50m_deg` accordingly. This map used to also carry `Spd_100m_mps` and
# `Dir_100m_deg` entries for keys the payload never contains, which read as though a
# 100 m MERRA-2 field existed and was simply missing. The heights each source is served
# at now live in `server/core/reanalysis.py`.
_BRIGHTHUB_MERRA_COLUMNS = {
    "Spd_50m_mps": "Spd_50m",
    "Dir_50m_deg": "Dir_50m",
    "Tmp_2m_degC": "t2m",
    "Prs_0m_hPa": "sp",
}


# BrightHub reports temperature in degC and pressure in hPa, then the column map renames
# both to `t2m` and `sp` — the exact names EarthDataHub uses for native ERA5 Kelvin and
# Pascals.  Without conversion the same column name carried different units depending on
# which source the session had downloaded from, so a consumer could not know what it was
# reading.  Converting here means `t2m` and `sp` mean one thing everywhere, and the unit
# detection in the air-density tool becomes a backstop rather than the only defence.
_BRIGHTHUB_UNIT_CONVERSIONS: dict[str, tuple[float, float]] = {
    # source column -> (multiplier, offset) taking it to the native ERA5 unit
    "Tmp_2m_degC": (1.0, 273.15),  # degC -> K
    "Prs_0m_hPa": (100.0, 0.0),  # hPa  -> Pa
}


def _convert_to_native_reanalysis_units(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert BrightHub-unit columns to the native ERA5 units their names will imply."""
    for column, (multiplier, offset) in _BRIGHTHUB_UNIT_CONVERSIONS.items():
        if column in frame.columns:
            frame[column] = frame[column].astype(float) * multiplier + offset
    return frame


def _reanalysis_frame(payload: dict, column_map: dict[str, str]) -> pd.DataFrame:
    """Normalize a BrightHub reanalysis payload into the session dataframe format.

    Units are converted to the native ERA5 convention before the columns are renamed,
    because the target names (``t2m``, ``sp``) carry Kelvin and Pascals everywhere else.
    """
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
    frame = _convert_to_native_reanalysis_units(frame)
    return frame.rename(columns=column_map).sort_index()


_BRIGHTHUB_CACHE_TOKENS = {"ERA5": "ERA5", "MERRA-2": "MERRA-2"}


def _brighthub_cache_path(state: SessionState, dataset: str, latitude: float, longitude: float) -> Path:
    """Build the standard BrightHub reanalysis cache parquet path for a node.

    Mirrors the EarthDataHub ``_era5_cache_path`` layout: the session's ``brighthub_cache/``,
    or the project's shared cache for a campaign in one (``SessionState.reanalysis_cache_dir``).
    """
    token = _BRIGHTHUB_CACHE_TOKENS.get(dataset, dataset.replace(" ", "-"))
    return state.reanalysis_cache_dir("brighthub") / f"{token}_{latitude}_{longitude}.parquet"


def _persist_reanalysis_frame(
    state: SessionState,
    dataset: str,
    latitude: float,
    longitude: float,
    payload: dict,
    column_map: dict[str, str],
) -> pd.DataFrame:
    """Parse a BrightHub reanalysis payload and persist it to the session workspace.

    Returns the parsed dataframe so callers can store it in ``state.era5_data`` /
    ``state.merra_data`` exactly as they did before persistence was added.
    """
    frame = _reanalysis_frame(payload, column_map)
    frame.to_parquet(_brighthub_cache_path(state, dataset, latitude, longitude))
    return frame


def _prepare_brighthub_reanalysis(
    state: SessionState,
    latitude: float,
    longitude: float,
    source: str = "brighthub",
) -> dict:
    """Load BrightHub ERA5 + MERRA-2 and interpolate *both* to the project site.

    MERRA-2 used to be downloaded, cached, extrapolated and then used for nothing: this
    function called `_interpolate_era5_to_site(state)` with its default `source="era5"`,
    so the `source="merra2"` path — which already existed and already required four
    nodes — was unreachable. Both are now interpolated, which is what makes reference
    source a usable scenario axis (design doc §6.2).
    """
    from server.core.spatial import bearing_compass, haversine_km
    from server.tools.era5 import _interpolate_era5_to_site

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
        and len(state.merra_nodes) >= 4
        and bool(state.merra_data)
        # Both series must be present for the cache to be a hit. Checking only the
        # active one would serve a half-prepared session as complete and fail later,
        # at the point some scenario switched to the source that was never built.
        and all(state.has_reference_series(name) for name in reference_source_names())
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
                name: {
                    "status": "ok",
                    "rows": int(len(state.reanalysis_interpolated[name])),
                    "method": "cached",
                    "variables": state.reanalysis_interpolated[name].columns.tolist(),
                }
                for name in reference_source_names()
            },
        }

    token = _require_token(state)
    try:
        node_sets = fetch_reanalysis_nodes(token, latitude, longitude)
    except Exception as exc:
        raise RuntimeError(f"BrightHub reanalysis preparation failed: {exc}") from exc
    # Fresh stores, assigned only once both sources are in: a failed download leaves the
    # session's reanalysis as it was.
    era5_data: dict[str, pd.DataFrame] = {}
    merra_data: dict[str, pd.DataFrame] = {}
    era5_items = _download_brighthub_nodes(state, "ERA5", node_sets.get("era5_nodes", []), era5_data)
    merra_items = _download_brighthub_nodes(state, "MERRA-2", node_sets.get("merra2_nodes", []), merra_data)

    if len(era5_items) < 4:
        raise ValueError("BrightHub returned fewer than four ERA5 nodes; site interpolation requires four nodes")
    if len(merra_items) < 4:
        raise ValueError(
            "BrightHub returned fewer than four MERRA-2 nodes; site interpolation requires four nodes"
        )

    def located(items: list[dict]) -> list[dict]:
        return [
            {
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "distance_km": haversine_km(latitude, longitude, item["latitude"], item["longitude"]),
                "bearing": bearing_compass(latitude, longitude, item["latitude"], item["longitude"]),
            }
            for item in items
        ]

    current_coordinate = state.get_coordinate()
    elevation_m = 0.0 if current_coordinate is None else current_coordinate.elevation_m
    state.set_coordinate(Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation_m))
    state.era5_nodes = located(era5_items)
    state.merra_nodes = located(merra_items)
    state.era5_data = era5_data
    state.merra_data = merra_data
    # Interpolate every source, then leave the default active so a caller that prepares
    # and immediately runs an LTC gets ERA5 as before.
    interpolation = {name: _interpolate_era5_to_site(state, name) for name in reference_source_names()}
    state.set_active_reference_source(DEFAULT_REFERENCE_SOURCE)
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


@operation(
    effect="change", stage="reanalysis_download", assistant=False, network=True,
    result=result_models.BrighthubPrepareReanalysisResult,
    reads=("credentials",),
    writes=("reanalysis_nodes", "reference_series", "reference_choice", "site"),
)
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
