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

from server.core.reanalysis import (
    AUXILIARY_VARIABLES,
    get_reference_source,
    reference_source_names,
)
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
    # ERA5 is natively UTC; ensure the index is tz-aware (D8).
    if subset.index.tz is None:
        subset.index = subset.index.tz_localize("UTC")
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
    # ERA5 is natively UTC; ensure the index is tz-aware (D8).
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("UTC")
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
    dataset: xr.Dataset | None = None
    try:
        dataset = _open_era5_dataset()
    except Exception as exc:  # noqa: BLE001
        if _is_transient_era5_error(exc):
            raise Era5UpstreamError(
                "ERA5 node lookup failed while contacting EarthDataHub. Please retry the request."
            ) from exc
        raise
    try:
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
        return {"nodes": state.era5_nodes, "grid_resolution_deg": resolution}
    finally:
        _close_dataset(dataset)


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


REFERENCE_SOURCES = reference_source_names()


def _reference_nodes_and_data(
    state: SessionState,
    source: str,
) -> tuple[list[dict[str, object]], dict[str, "pd.DataFrame"], object]:
    """Return the node list, node frames and key function for one reanalysis source.

    F-58: MERRA-2 was acquired, cached, extrapolated to hub height and used for nothing.
    ``_interpolate_era5_to_site`` read ``state.era5_data`` only and ``_require_ltc_inputs``
    read ``state.era5_interpolated_df`` only, so nothing in ``state.merra_data`` could ever
    become an LTC reference — its only consumers were a hub-height column nothing read and a
    map marker. A second independent long-term source is the standard way to test whether an
    LTC result depends on the reference chosen, and the download cost was already being paid.
    """
    if source == "era5":
        return list(state.era5_nodes or []), state.era5_data, _era5_key
    nodes = list(state.merra_nodes or [])
    return nodes, state.merra_data, lambda lat, lon: f"{lat}_{lon}"


def _interpolate_era5_to_site(state: SessionState, source: str = "era5") -> dict:
    """Spatially interpolate reanalysis node data to the site with linear interpolation and IDW fallback.

    Speed (``Spd_100m``) is interpolated as a *scalar* to avoid the
    vector-cancellation bias that under-predicts speed where node wind
    directions diverge across the cell.  Direction (``Dir_100m``) is
    derived from vector-interpolated u/v components, which is the correct
    approach for direction.

    ``source`` selects which downloaded reanalysis becomes the LTC reference (F-58). Both
    write ``state.era5_interpolated_df``, which is the single series every LTC algorithm
    reads, so switching source and re-running the LTC is how a reference-dependence check is
    made. The source actually used is recorded on the run configuration.
    """
    descriptor = get_reference_source(source)
    speed_col, dir_col = descriptor.speed_col, descriptor.dir_col
    coordinate = state.get_coordinate()
    if coordinate is None:
        raise ValueError("Site coordinate is not set. Run find_era5_nodes first")
    nodes, node_data, key_for = _reference_nodes_and_data(state, source)
    label = descriptor.label
    if len(nodes) < 4:
        raise ValueError(
            f"{label} nodes are not available. "
            + ("Run find_era5_nodes first" if source == "era5"
               else "Download MERRA-2 nodes with brighthub_download_reanalysis first")
        )
    points = [(float(node["latitude"]), float(node["longitude"])) for node in nodes]
    frames = []
    for node in nodes:
        key = key_for(float(node["latitude"]), float(node["longitude"]))
        if key not in node_data:
            raise ValueError(f"{label} data for node '{key}' is not loaded")
        frame = node_data[key]
        if speed_col not in frame.columns or dir_col not in frame.columns:
            raise ValueError(
                f"{label} node '{key}' must have {speed_col} and {dir_col}. "
                "Run compute_era5_wind_speed first"
            )
        frames.append(frame)
    common_index = frames[0].index
    for frame in frames[1:]:
        common_index = common_index.intersection(frame.index)
    if common_index.empty:
        raise ValueError(f"{label} node dataframes do not share any common timestamps for interpolation")
    variables = [speed_col, *AUXILIARY_VARIABLES]
    site = (coordinate.latitude, coordinate.longitude)
    result = pd.DataFrame(index=common_index)
    methods_used: set[str] = set()
    # F-62: `methods_used` collapsed to "idw" if *any* member fell back, so a run where
    # speed interpolated bilinearly and only direction fell back was reported wholly as IDW.
    # The per-variable map is what a reader actually needs.
    variable_methods: dict[str, str] = {}
    # F-63: a variable is interpolated only when EVERY node carries it, so one node missing
    # `d2m` silently removed dew point from the site series - which is what the density
    # calculation needs. It was visible only as an absence from the `variables` list, and
    # surfaced later as a missing-column error somewhere unrelated.
    skipped_variables: list[dict[str, object]] = []
    for variable in variables:
        missing = [
            key
            for key, frame in zip((key_for(float(n["latitude"]), float(n["longitude"])) for n in nodes), frames)
            if variable not in frame.columns
        ]
        if missing:
            skipped_variables.append({"variable": variable, "missing_from_nodes": missing})
            continue
        values = np.vstack([frame.loc[common_index, variable].to_numpy(dtype=float) for frame in frames])
        interpolated, method = interpolate_spatial(points, values, site)
        methods_used.add(method)
        variable_methods[variable] = method
        result[variable] = np.asarray(interpolated, dtype=float)
    # Vector-interpolate u/v for direction only.  Speed was already
    # scalar-interpolated above to avoid vector-cancellation bias.
    speed_values = np.vstack([frame.loc[common_index, speed_col].to_numpy(dtype=float) for frame in frames])
    direction_values = np.vstack([frame.loc[common_index, dir_col].to_numpy(dtype=float) for frame in frames])
    direction_rad = np.radians(direction_values)
    u_values = -speed_values * np.sin(direction_rad)
    v_values = -speed_values * np.cos(direction_rad)
    interp_u, method_u = interpolate_spatial(points, u_values, site)
    interp_v, method_v = interpolate_spatial(points, v_values, site)
    methods_used.update({method_u, method_v})
    variable_methods[dir_col] = method_u if method_u == method_v else f"{method_u}/{method_v}"
    result[dir_col] = (270.0 - np.degrees(np.arctan2(np.asarray(interp_v), np.asarray(interp_u)))) % 360.0
    # Stored per source (design doc §6.4), so ERA5 and MERRA-2 site series coexist and a
    # scenario can switch between them without recomputing either. Interpolating a source
    # also makes it the active reference, preserving the previous single-slot behaviour
    # for callers that interpolate and then immediately run an LTC.
    state.reanalysis_interpolated[descriptor.name] = result.sort_index()
    state.set_active_reference_source(descriptor.name)
    state.touch()
    method_name = "idw" if "idw" in methods_used else "linear"
    payload: dict[str, object] = {
        "status": "ok",
        "rows": int(len(result)),
        "method": method_name,
        # The collapsed label is retained for existing consumers; the map is the truth.
        "method_by_variable": variable_methods,
        "method_is_mixed": len(methods_used) > 1,
        "variables": result.columns.tolist(),
        "skipped_variables": skipped_variables,
        # Reported by the path rather than asserted as a literal, so a future change of
        # approach would show up here instead of silently contradicting the field (F-62).
        "speed_interpolation": "scalar" if speed_col in variable_methods else "unavailable",
        "reference_source": descriptor.name,
        "reference_height_m": descriptor.native_height_m,
        "speed_column": speed_col,
        "direction_column": dir_col,
        "nodes_used": len(points),
        "reference_source_note": (
            "This is the series every LTC algorithm will use. Re-running the interpolation "
            "with the other source and repeating the LTC is how a result's dependence on the "
            "reference is tested; a large difference means the correction is being driven by "
            "the reanalysis rather than by the site."
        ),
    }
    if skipped_variables:
        names = ", ".join(str(entry["variable"]) for entry in skipped_variables)
        payload["warning"] = (
            f"{len(skipped_variables)} variable(s) ({names}) were not interpolated because at "
            "least one node does not carry them, so they are absent from the site series. "
            "Dew point feeds the air-density calculation and temperature and pressure feed "
            "the XGBoost features, so the absence surfaces later as a missing-column error "
            "somewhere unrelated unless it is dealt with here."
        )
    return payload


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
def interpolate_era5_to_site(source: str = "era5") -> dict:
    """Spatially interpolate reanalysis node data to the site with linear interpolation and IDW fallback.

    Speed is scalar-interpolated; direction is derived from vector-interpolated
    u/v.  The response includes ``speed_interpolation`` indicating the convention
    used.

    ``source`` is ``"era5"`` (default) or ``"merra2"`` and selects which downloaded
    reanalysis becomes the long-term reference. Both write the same interpolated series that
    every LTC algorithm reads, so switching source and re-running the LTC is how a result's
    dependence on the reference is tested.
    """
    return _interpolate_era5_to_site(session, source)
