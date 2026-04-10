"""windfarm — WindKit wind farm (turbines, WTG, losses/uncertainty) MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import windkit
from server.main import mcp
from server.state.session import session
from server.tools.windkit._serializers import _ok, da_to_dict, dict_to_ds, ds_to_dict, gdf_to_geojson, df_to_dict


def _windkit_dir() -> Path:
    base = Path(session.get_data_dir()) / "windkit"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# Wind Turbines
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_windturbines(dataset: str) -> dict:
    """Validate a wind turbines dataset (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_windturbines(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_windturbines(dataset: str) -> dict:
    """Check whether a dataset is a valid wind turbines object (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_windturbines": bool(windkit.is_windturbines(ds))})


@mcp.tool()
def windkit_check_wtg_keys(wind_turbines_dataset: str, wtg_dict: str) -> dict:
    """Check that all WTG keys in a wind turbines object are present (WindKit).

    Args:
        wind_turbines_dataset: JSON-serialized wind turbines xarray Dataset.
        wtg_dict: JSON dict mapping WTG keys to WTG objects.
    """
    ds = dict_to_ds(json.loads(wind_turbines_dataset))
    wtg = json.loads(wtg_dict)
    windkit.check_wtg_keys(ds, wtg)
    return _ok({"valid": True})


@mcp.tool()
def windkit_create_wind_turbines_from_dataframe(dataframe_json: str) -> dict:
    """Create a wind turbines point dataset from a DataFrame (WindKit).

    Args:
        dataframe_json: JSON-serialized pandas DataFrame (split-orient) with location columns.
    """
    df = pd.read_json(dataframe_json, orient="split")
    ds = windkit.create_wind_turbines_from_dataframe(df)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_create_wind_turbines_from_arrays(west_east: str, south_north: str, height: str,
                                               crs: str, wtg_keys: str = "") -> dict:
    """Create a wind turbines point dataset from explicit arrays (WindKit).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of hub heights.
        crs: CRS string.
        wtg_keys: JSON array of WTG key strings (optional).
    """
    import pyproj
    we = json.loads(west_east)
    sn = json.loads(south_north)
    h = json.loads(height)
    kwargs = {}
    if wtg_keys:
        kwargs["wtg_keys"] = json.loads(wtg_keys)
    ds = windkit.create_wind_turbines_from_arrays(
        we, sn, h, pyproj.CRS.from_user_input(crs), **kwargs
    )
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_wind_turbines_to_geodataframe(dataset: str) -> dict:
    """Convert a wind turbines dataset to a GeoDataFrame (WindKit).

    Args:
        dataset: JSON-serialized wind turbines xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    gdf = windkit.wind_turbines_to_geodataframe(ds)
    return _ok(gdf_to_geojson(gdf))


# ---------------------------------------------------------------------------
# Wind Turbine Generators (WTG)
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_wtg(dataset: str) -> dict:
    """Validate a WTG dataset (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_wtg(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_wtg(dataset: str) -> dict:
    """Check whether a dataset is a valid WTG object (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_wtg": bool(windkit.is_wtg(ds))})


@mcp.tool()
def windkit_estimate_regulation_type(wtg_dataset: str) -> dict:
    """Estimate the regulation type of a WTG (WindKit).

    Args:
        wtg_dataset: JSON-serialized WTG xarray Dataset.
    """
    ds = dict_to_ds(json.loads(wtg_dataset))
    reg_type = windkit.estimate_regulation_type(ds)
    return _ok({"regulation_type": str(reg_type)})


@mcp.tool()
def windkit_read_wtg(filename: str, file_format: str = "") -> dict:
    """Read a Wind Turbine Generator data file (WindKit).

    Args:
        filename: Path to the WTG file.
        file_format: File format hint (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    result = windkit.read_wtg(str(path), **kwargs)
    if isinstance(result, dict):
        return _ok({k: ds_to_dict(v) for k, v in result.items()})
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_wtg_power(wtg_dataset: str, ws: str = "", interp_method: str = "linear") -> dict:
    """Get power output for given inflow wind speeds from a WTG (WindKit).

    Args:
        wtg_dataset: JSON-serialized WTG xarray Dataset.
        ws: JSON array of wind speeds (optional, uses default range if empty).
        interp_method: Interpolation method (default 'linear').
    """
    ds = dict_to_ds(json.loads(wtg_dataset))
    kwargs = {"interp_method": interp_method}
    if ws:
        kwargs["ws"] = json.loads(ws)
    result = windkit.wtg_power(ds, **kwargs)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_wtg_cp(wtg_dataset: str, ws: str = "", air_density: float = 1.225) -> dict:
    """Get power coefficient for given wind speeds from a WTG (WindKit).

    Args:
        wtg_dataset: JSON-serialized WTG xarray Dataset.
        ws: JSON array of wind speeds (optional).
        air_density: Air density in kg/m³ (default 1.225).
    """
    ds = dict_to_ds(json.loads(wtg_dataset))
    kwargs = {"air_density": air_density}
    if ws:
        kwargs["ws"] = json.loads(ws)
    result = windkit.wtg_cp(ds, **kwargs)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_wtg_ct(wtg_dataset: str, ws: str = "", interp_method: str = "linear") -> dict:
    """Get thrust coefficient for given wind speeds from a WTG (WindKit).

    Args:
        wtg_dataset: JSON-serialized WTG xarray Dataset.
        ws: JSON array of wind speeds (optional).
        interp_method: Interpolation method (default 'linear').
    """
    ds = dict_to_ds(json.loads(wtg_dataset))
    kwargs = {"interp_method": interp_method}
    if ws:
        kwargs["ws"] = json.loads(ws)
    result = windkit.wtg_ct(ds, **kwargs)
    return _ok(da_to_dict(result))


# ---------------------------------------------------------------------------
# Losses and Uncertainty
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_uncertainty_table(table_json: str) -> dict:
    """Validate an uncertainty table DataFrame (WindKit).

    Args:
        table_json: JSON-serialized pandas DataFrame (split-orient).
    """
    df = pd.read_json(table_json, orient="split")
    windkit.validate_uncertainty_table(df)
    return _ok({"valid": True})


@mcp.tool()
def windkit_get_uncertainty_table(table_name: str = "") -> dict:
    """Get a standard wind/energy uncertainty table (WindKit).

    Args:
        table_name: Name of the uncertainty table (optional, uses default if empty).
    """
    kwargs = {}
    if table_name:
        kwargs["table_name"] = table_name
    df = windkit.get_uncertainty_table(**kwargs)
    return _ok(df_to_dict(df))


@mcp.tool()
def windkit_total_uncertainty(table_json: str) -> dict:
    """Calculate total uncertainty from an uncertainty table (WindKit).

    Args:
        table_json: JSON-serialized uncertainty table DataFrame (split-orient).
    """
    df = pd.read_json(table_json, orient="split")
    result = windkit.total_uncertainty(df)
    return _ok(df_to_dict(result))


@mcp.tool()
def windkit_uncertainty_table_summary(table_json: str) -> dict:
    """Print a summary of uncertainties in a table (WindKit).

    Args:
        table_json: JSON-serialized uncertainty table DataFrame (split-orient).
    """
    df = pd.read_json(table_json, orient="split")
    summary = windkit.uncertainty_table_summary(df)
    return _ok({"summary": str(summary)})


@mcp.tool()
def windkit_total_uncertainty_factor(table_json: str) -> dict:
    """Calculate total uncertainty factor for exceedance probabilities (WindKit).

    Args:
        table_json: JSON-serialized uncertainty table DataFrame (split-orient).
    """
    df = pd.read_json(table_json, orient="split")
    result = windkit.total_uncertainty_factor(df)
    return _ok(df_to_dict(result))
