"""_serializers — Shared xarray/geopandas/plotly serialization for WindKit tool wrappers.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

from server.state.session import session


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy scalar types."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
        import datetime
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return super().default(obj)


def ds_to_dict(ds: xr.Dataset) -> dict[str, Any]:
    """Serialize an xarray.Dataset to a JSON-safe dictionary."""
    raw = ds.to_dict(data="list")
    return json.loads(json.dumps(raw, cls=_NumpyEncoder))


def da_to_dict(da: xr.DataArray) -> dict[str, Any]:
    """Serialize an xarray.DataArray to a JSON-safe dictionary."""
    raw = da.to_dict(data="list")
    return json.loads(json.dumps(raw, cls=_NumpyEncoder))


def dict_to_ds(data: dict[str, Any]) -> xr.Dataset:
    """Reconstruct an xarray.Dataset from a serialized dictionary."""
    return xr.Dataset.from_dict(data)


def dict_to_da(data: dict[str, Any]) -> xr.DataArray:
    """Reconstruct an xarray.DataArray from a serialized dictionary."""
    return xr.DataArray.from_dict(data)


def gdf_to_geojson(gdf: gpd.GeoDataFrame) -> dict[str, Any]:
    """Serialize a GeoDataFrame to GeoJSON dict."""
    data = json.loads(gdf.to_json())
    if gdf.crs is not None:
        data["crs"] = {"type": "name", "properties": {"name": gdf.crs.to_string()}}
    return data


def geojson_to_gdf(data: dict[str, Any]) -> gpd.GeoDataFrame:
    """Reconstruct a GeoDataFrame from a GeoJSON dict."""
    crs_data = data.get("crs")
    crs = crs_data.get("properties", {}).get("name") if isinstance(crs_data, dict) else None
    return gpd.GeoDataFrame.from_features(data.get("features", data), crs=crs or "EPSG:4326")


def windkit_file_path(filename: str) -> Path:
    """Return a session-scoped WindKit path, rejecting traversal outside its data directory.

    ``is_absolute()`` alone is not the right test on Windows: ``Path("/etc/passwd")`` is
    *rooted* but not *absolute* there, because an absolute Windows path needs a drive. The
    first branch therefore never fired for a POSIX-style absolute path, and the input fell
    through to the containment check below.

    Containment still rejected it — ``/etc/passwd`` resolves onto the base's drive, outside
    the WindKit directory — so nothing was ever exposed. What was wrong is that the guard
    behaved differently on Windows and POSIX and reported the wrong reason, which is exactly
    the kind of divergence a traversal guard must not have. Testing root and drive as well
    makes the two platforms agree.
    """
    base = (Path(session.get_data_dir()) / "windkit").resolve()
    base.mkdir(parents=True, exist_ok=True)
    candidate = Path(filename)
    if candidate.is_absolute() or candidate.root or candidate.drive:
        raise ValueError("filename must be relative to the session WindKit directory")
    path = (base / candidate).resolve()
    if not path.is_relative_to(base):
        raise ValueError("filename must remain inside the session WindKit directory")
    return path


def df_to_dict(df: pd.DataFrame) -> dict[str, Any]:
    """Serialize a pandas DataFrame to a JSON-safe dict of lists."""
    return json.loads(df.to_json(orient="split", date_format="iso"))


def dict_to_df(data: dict[str, Any]) -> pd.DataFrame:
    """Reconstruct a pandas DataFrame from a split-orient dict."""
    import io
    return pd.read_json(io.StringIO(json.dumps(data)), orient="split")


def fig_to_dict(fig: Any) -> dict[str, Any]:
    """Serialize a Plotly figure to a JSON-safe dict."""
    return json.loads(fig.to_json())


def _ensure_json(obj: Any) -> str:
    """Return a JSON string from any serializable object."""
    return json.dumps(obj, cls=_NumpyEncoder)


def _ok(data: Any) -> dict[str, Any]:
    """Wrap a result in a standard status envelope."""
    return {"status": "ok", "result": data}
