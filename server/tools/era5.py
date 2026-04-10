"""era5 — Phase 3 MCP tools for ERA5 discovery, extraction, and interpolation.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import numpy as np
import pandas as pd
import xarray as xr

from server.core.spatial import bearing_compass, haversine_km, interpolate_spatial
from server.main import mcp
from server.schemas.common import Coordinate
from server.state.session import SessionState, session

ERA5_ZARR_URL = "https://data.earthdatahub.destine.eu/era5/reanalysis-era5-single-levels-v0.zarr"
ERA5_BASE_VARIABLES = ["u100", "v100", "sp", "t2m", "d2m"]
ERA5_OPTIONAL_VARIABLES = ["ust", "blh", "sshf"]
ERA5_FETCH_MAX_ATTEMPTS = 3
ERA5_FETCH_RETRY_DELAYS_SECONDS = (1.0, 2.0)


class Era5UpstreamError(RuntimeError):
    """Raised when EarthDataHub responds with a transient or incomplete payload."""


def _earthdatahub_pat_from_netrc(hostname: str) -> str:
    """Read an EarthDataHub PAT from a simple netrc-style file without exposing the secret."""
    netrc_path = Path(os.environ.get("NETRC", Path.home() / ".netrc"))
    if not netrc_path.exists():
        return ""
    tokens = netrc_path.read_text(encoding="utf-8").split()
    current_machine = ""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "machine" and index + 1 < len(tokens):
            current_machine = tokens[index + 1]
            index += 2
            continue
        if token == "default":
            current_machine = "default"
            index += 1
            continue
        if token == "password" and index + 1 < len(tokens):
            if current_machine in {hostname, "default"}:
                return tokens[index + 1].strip()
            index += 2
            continue
        index += 1
    return ""


def _earthdatahub_pat() -> str:
    """Resolve the EarthDataHub personal access token from env vars or netrc."""
    for variable in ["EARTHDATAHUB_PAT", "EDH_PAT", "DESTINE_PAT"]:
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    return _earthdatahub_pat_from_netrc("data.earthdatahub.destine.eu")


def _era5_dataset_url() -> str:
    """Build the ERA5 Zarr URL, embedding the PAT when one is configured."""
    pat = _earthdatahub_pat()
    if not pat:
        return ERA5_ZARR_URL
    parsed = urlsplit(ERA5_ZARR_URL)
    username = os.environ.get("EARTHDATAHUB_PAT_USERNAME", "edh").strip() or "edh"
    netloc = f"{quote(username, safe='')}:{quote(pat, safe='')}@{parsed.netloc}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _era5_storage_options() -> dict[str, object]:
    """Build fsspec HTTP storage options, including optional EarthDataHub auth headers."""
    headers: dict[str, str] = {}
    explicit_header = os.environ.get("EARTHDATAHUB_AUTH_HEADER", "").strip()
    explicit_value = os.environ.get("EARTHDATAHUB_AUTH_VALUE", "").strip()
    bearer_token = os.environ.get("EARTHDATAHUB_BEARER_TOKEN", "").strip() or os.environ.get(
        "EARTHDATAHUB_TOKEN", ""
    ).strip()
    api_key = os.environ.get("EARTHDATAHUB_API_KEY", "").strip()
    api_key_header = os.environ.get("EARTHDATAHUB_API_KEY_HEADER", "x-api-key").strip() or "x-api-key"
    if explicit_header and explicit_value:
        headers[explicit_header] = explicit_value
    elif bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    elif api_key:
        headers[api_key_header] = api_key
    options: dict[str, object] = {"client_kwargs": {"trust_env": True}}
    if headers:
        options["headers"] = headers
    return options


def _open_era5_dataset() -> xr.Dataset:
    """Open the EarthDataHub ERA5 Zarr store lazily using xarray and zarr."""
    return xr.open_dataset(
        _era5_dataset_url(),
        storage_options=_era5_storage_options(),
        chunks={},
        engine="zarr",
    )


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """Flatten an exception and its causes/contexts into a unique chain for classification."""
    chain: list[BaseException] = []
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        chain.append(current)
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        if isinstance(context, BaseException):
            pending.append(context)
    return chain


def _is_transient_era5_error(exc: BaseException) -> bool:
    """Identify remote ERA5 payload failures that are worth retrying automatically."""
    markers = [
        "response payload is not completed",
        "not enough data to satisfy content length header",
        "contentlengtherror",
        "clientpayloaderror",
        "forcibly closed by the remote host",
        "connection reset by peer",
        "winerror 10054",
    ]
    for current in _exception_chain(exc):
        if isinstance(current, (ConnectionResetError, TimeoutError)):
            return True
        message = f"{type(current).__name__}: {current}".lower()
        if any(marker in message for marker in markers):
            return True
    return False


def _time_coordinate_name(dataset: xr.Dataset) -> str:
    """Resolve the time coordinate name used by the live ERA5 dataset."""
    for name in ["time", "valid_time"]:
        if name in dataset.coords or name in dataset.dims:
            return name
    raise ValueError("ERA5 dataset must expose either a 'time' or 'valid_time' coordinate")


def _grid_resolution(values: np.ndarray) -> float:
    """Infer grid resolution from sorted unique coordinate values in degrees."""
    unique = np.unique(np.asarray(values, dtype=float))
    diffs = np.diff(np.sort(unique))
    positive = diffs[diffs > 0]
    return float(positive.min()) if positive.size else 0.0


def _normalize_longitude(longitude: float, lon_values: np.ndarray) -> float:
    """Map a signed longitude (-180..180) into the dataset's convention (typically 0..360)."""
    lon_min = float(np.min(lon_values))
    lon_max = float(np.max(lon_values))
    if lon_min >= 0 and lon_max > 180 and longitude < 0:
        return longitude % 360
    if lon_min < 0 and longitude > 180:
        return longitude - 360
    return longitude


def _to_signed_longitude(longitude: float) -> float:
    """Convert a 0..360 longitude back to the signed -180..180 convention."""
    if longitude > 180:
        return longitude - 360
    return longitude


def _bounding_pair(values: np.ndarray, target: float) -> tuple[float, float]:
    """Select lower and upper bounding grid coordinates around a target value."""
    sorted_values = np.sort(np.unique(np.asarray(values, dtype=float)))
    if sorted_values.size < 2:
        value = float(sorted_values[0])
        return value, value
    if target <= sorted_values[0]:
        return float(sorted_values[0]), float(sorted_values[1])
    if target >= sorted_values[-1]:
        return float(sorted_values[-2]), float(sorted_values[-1])
    index = int(np.searchsorted(sorted_values, target, side="left"))
    lower = float(sorted_values[index - 1])
    upper = float(sorted_values[index])
    return lower, upper


def _era5_key(latitude: float, longitude: float) -> str:
    """Build the session key used to store ERA5 node dataframes."""
    return f"{float(latitude)}_{float(longitude)}"


def _era5_cache_path(state: SessionState, latitude: float, longitude: float) -> Path:
    """Build the standard ERA5 cache parquet path for a node."""
    cache_dir = Path(state.get_data_dir()) / "era5_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"ERA5_{latitude}_{longitude}.parquet"


def _cache_covers_period(df: pd.DataFrame, start_date: str, end_date: str) -> bool:
    """Check whether a cached ERA5 dataframe fully covers the requested date range."""
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return False
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return bool(df.index.min() <= start and df.index.max() >= end)


def _selected_variables(dataset: xr.Dataset) -> list[str]:
    """Select available ERA5 variables from required and optional Phase 3 variables."""
    desired = ERA5_BASE_VARIABLES + ERA5_OPTIONAL_VARIABLES
    return [variable for variable in desired if variable in dataset.data_vars]


def _close_dataset(dataset: object) -> None:
    """Close xarray datasets when supported so failed attempts do not leak resources."""
    close = getattr(dataset, "close", None)
    if callable(close):
        close()


def _load_cached_era5(cache_path: Path, start_date: str, end_date: str) -> tuple[pd.DataFrame | None, bool]:
    """Load cached ERA5 node data when the parquet file covers the requested period."""
    if not cache_path.exists():
        return None, False
    cached = pd.read_parquet(cache_path)
    if "time" in cached.columns and not isinstance(cached.index, pd.DatetimeIndex):
        cached = cached.set_index("time")
    if not isinstance(cached.index, pd.DatetimeIndex):
        cached.index = pd.DatetimeIndex(cached.index)
    if not _cache_covers_period(cached, start_date, end_date):
        return None, False
    subset = cached.loc[pd.Timestamp(start_date) : pd.Timestamp(end_date)].copy()
    return subset.sort_index(), True


def _read_remote_era5_frame(
    dataset: xr.Dataset,
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Read one ERA5 node from the remote Zarr store into a datetime-indexed dataframe."""
    time_coord = _time_coordinate_name(dataset)
    variables = _selected_variables(dataset)
    if not variables:
        raise ValueError("ERA5 dataset does not expose any expected variables")
    norm_lon = _normalize_longitude(longitude, np.asarray(dataset.longitude.values))
    selected = dataset[variables].sel(latitude=latitude, longitude=norm_lon, method="nearest")
    selected = selected.sel({time_coord: slice(start_date, end_date)}).compute()
    frame = selected.to_dataframe()
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.reset_index().set_index(time_coord)
    elif time_coord in frame.columns and not isinstance(frame.index, pd.DatetimeIndex):
        frame = frame.set_index(time_coord)
    frame.index = pd.DatetimeIndex(frame.index, name="time")
    return frame.sort_index()


def _download_era5_frame_with_retry(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Download ERA5 node data with limited retries for transient upstream truncation failures."""
    last_error: BaseException | None = None
    for attempt in range(1, ERA5_FETCH_MAX_ATTEMPTS + 1):
        dataset: xr.Dataset | None = None
        try:
            dataset = _open_era5_dataset()
            return _read_remote_era5_frame(dataset, latitude, longitude, start_date, end_date)
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not _is_transient_era5_error(exc) or attempt >= ERA5_FETCH_MAX_ATTEMPTS:
                raise Era5UpstreamError(
                    "ERA5 download failed while reading the remote EarthDataHub payload. "
                    "Please retry the request; if it keeps failing, reduce the date range and try again."
                ) from exc
            delay = ERA5_FETCH_RETRY_DELAYS_SECONDS[min(attempt - 1, len(ERA5_FETCH_RETRY_DELAYS_SECONDS) - 1)]
            time.sleep(delay)
        finally:
            if dataset is not None:
                _close_dataset(dataset)
    if last_error is not None:
        raise Era5UpstreamError(
            "ERA5 download failed while reading the remote EarthDataHub payload. Please retry the request."
        ) from last_error
    raise Era5UpstreamError("ERA5 download failed before any remote request completed.")


def _store_coordinate(state: SessionState, latitude: float, longitude: float) -> None:
    """Persist the site coordinate in session state for later interpolation tools."""
    current = state.get_coordinate()
    elevation = 0.0 if current is None else current.elevation_m
    state.set_coordinate(Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation))


def _find_era5_nodes(state: SessionState, latitude: float, longitude: float) -> dict:
    """Find the four surrounding ERA5 grid nodes using 0.25° bounds and haversine distance."""
    try:
        dataset = _open_era5_dataset()
    except Exception as exc:  # noqa: BLE001
        if _is_transient_era5_error(exc):
            raise Era5UpstreamError(
                "ERA5 node lookup failed while contacting EarthDataHub. Please retry the request."
            ) from exc
        raise
    lon_values = np.asarray(dataset.longitude.values)
    norm_lon = _normalize_longitude(longitude, lon_values)
    lower_lat, upper_lat = _bounding_pair(np.asarray(dataset.latitude.values), latitude)
    lower_lon, upper_lon = _bounding_pair(lon_values, norm_lon)
    candidate_points = [(lower_lat, lower_lon), (lower_lat, upper_lon), (upper_lat, lower_lon), (upper_lat, upper_lon)]
    nodes = []
    for node_lat, node_lon in candidate_points:
        signed_lon = _to_signed_longitude(node_lon)
        nodes.append(
            {
                "latitude": float(node_lat),
                "longitude": signed_lon,
                "distance_km": haversine_km(latitude, longitude, node_lat, signed_lon),
                "bearing": bearing_compass(latitude, longitude, node_lat, signed_lon),
            }
        )
    state.era5_nodes = sorted(nodes, key=lambda node: float(node["distance_km"]))
    _store_coordinate(state, latitude, longitude)
    resolution = _grid_resolution(np.asarray(dataset.latitude.values))
    if resolution is None:
        resolution = _grid_resolution(np.asarray(dataset.longitude.values))
    _close_dataset(dataset)
    return {"nodes": state.era5_nodes, "grid_resolution_deg": resolution}


def _extract_era5_data(
    state: SessionState,
    latitude: float,
    longitude: float,
    start_date: str = "2000-01-01",
    end_date: str = "2025-12-31",
) -> dict:
    """Extract ERA5 node data from Zarr, cache it as parquet, and store it in session state."""
    try:
        cache_path = _era5_cache_path(state, latitude, longitude)
    except TypeError:
        # Preserve compatibility with tests or callers that monkeypatch the legacy
        # two-argument cache-path helper signature.
        cache_path = _era5_cache_path(latitude, longitude)
    cached_df, cache_hit = _load_cached_era5(cache_path, start_date, end_date)
    if cached_df is None:
        cached_df = _download_era5_frame_with_retry(latitude, longitude, start_date, end_date)
        cached_df.to_parquet(cache_path)
    state.era5_data[_era5_key(latitude, longitude)] = cached_df.copy()
    _store_coordinate(state, latitude, longitude)
    return {
        "status": "ok",
        "latitude": float(latitude),
        "longitude": float(longitude),
        "rows": int(len(cached_df)),
        "start": cached_df.index.min().isoformat(),
        "end": cached_df.index.max().isoformat(),
        "variables": cached_df.columns.tolist(),
        "cached": cache_hit,
    }


def _compute_era5_wind_speed(state: SessionState, latitude: float, longitude: float) -> dict:
    """Compute 100 m wind speed and meteorological direction from ERA5 u and v components."""
    key = _era5_key(latitude, longitude)
    if key not in state.era5_data:
        raise ValueError(f"ERA5 data for node '{key}' is not loaded. Run extract_era5_data first")
    frame = state.era5_data[key].copy()
    if "u100" not in frame.columns or "v100" not in frame.columns:
        raise ValueError("ERA5 dataframe must contain u100 and v100 columns to compute wind speed")
    u100 = frame["u100"].to_numpy(dtype=float)
    v100 = frame["v100"].to_numpy(dtype=float)
    frame["Spd_100m"] = np.sqrt(u100**2 + v100**2)
    frame["Dir_100m"] = (270.0 - np.degrees(np.arctan2(v100, u100))) % 360.0
    state.era5_data[key] = frame
    return {
        "status": "ok",
        "mean_speed": float(frame["Spd_100m"].mean()),
        "record_count": int(frame["Spd_100m"].count()),
    }


def _interpolate_era5_to_site(state: SessionState) -> dict:
    """Spatially interpolate ERA5 node data to the site using linear interpolation with IDW fallback."""
    coordinate = state.get_coordinate()
    if coordinate is None:
        raise ValueError("Site coordinate is not set. Run find_era5_nodes first")
    if not state.era5_nodes or len(state.era5_nodes) < 4:
        raise ValueError("ERA5 nodes are not available. Run find_era5_nodes first")
    points = [(float(node["latitude"]), float(node["longitude"])) for node in state.era5_nodes]
    frames = []
    for node in state.era5_nodes:
        key = _era5_key(float(node["latitude"]), float(node["longitude"]))
        if key not in state.era5_data:
            raise ValueError(f"ERA5 data for node '{key}' is not loaded")
        frame = state.era5_data[key]
        if "Spd_100m" not in frame.columns or "Dir_100m" not in frame.columns:
            raise ValueError(f"ERA5 node '{key}' must have Spd_100m and Dir_100m. Run compute_era5_wind_speed first")
        frames.append(frame)
    common_index = frames[0].index
    for frame in frames[1:]:
        common_index = common_index.intersection(frame.index)
    if common_index.empty:
        raise ValueError("ERA5 node dataframes do not share any common timestamps for interpolation")
    variables = ["Spd_100m", "sp", "t2m", "d2m"]
    site = (coordinate.latitude, coordinate.longitude)
    result = pd.DataFrame(index=common_index)
    methods_used: set[str] = set()
    for variable in variables:
        if all(variable in frame.columns for frame in frames):
            values = np.vstack([frame.loc[common_index, variable].to_numpy(dtype=float) for frame in frames])
            interpolated, method = interpolate_spatial(points, values, site)
            methods_used.add(method)
            result[variable] = np.asarray(interpolated, dtype=float)
    speed_values = np.vstack([frame.loc[common_index, "Spd_100m"].to_numpy(dtype=float) for frame in frames])
    direction_values = np.vstack([frame.loc[common_index, "Dir_100m"].to_numpy(dtype=float) for frame in frames])
    direction_rad = np.radians(direction_values)
    u_values = -speed_values * np.sin(direction_rad)
    v_values = -speed_values * np.cos(direction_rad)
    interp_u, method_u = interpolate_spatial(points, u_values, site)
    interp_v, method_v = interpolate_spatial(points, v_values, site)
    methods_used.update({method_u, method_v})
    result["Dir_100m"] = (270.0 - np.degrees(np.arctan2(np.asarray(interp_v), np.asarray(interp_u)))) % 360.0
    if "Spd_100m" not in result.columns:
        result["Spd_100m"] = np.sqrt(np.asarray(interp_u) ** 2 + np.asarray(interp_v) ** 2)
    state.era5_interpolated_df = result.sort_index()
    method_name = "idw" if "idw" in methods_used else "linear"
    return {
        "status": "ok",
        "rows": int(len(state.era5_interpolated_df)),
        "method": method_name,
        "variables": state.era5_interpolated_df.columns.tolist(),
    }


@mcp.tool()
def find_era5_nodes(latitude: float, longitude: float) -> dict:
    """Find the four surrounding ERA5 grid nodes using 0.25° bounds and haversine distance."""
    return _find_era5_nodes(session, latitude, longitude)


@mcp.tool()
def extract_era5_data(
    latitude: float,
    longitude: float,
    start_date: str = "2000-01-01",
    end_date: str = "2025-12-31",
) -> dict:
    """Extract ERA5 node data from Zarr, cache it as parquet, and store it in session state."""
    return _extract_era5_data(session, latitude, longitude, start_date, end_date)


@mcp.tool()
def compute_era5_wind_speed(latitude: float, longitude: float) -> dict:
    """Compute 100 m wind speed and meteorological direction from ERA5 u and v components."""
    return _compute_era5_wind_speed(session, latitude, longitude)


@mcp.tool()
def interpolate_era5_to_site() -> dict:
    """Spatially interpolate ERA5 node data to the site using linear interpolation with IDW fallback."""
    return _interpolate_era5_to_site(session)
