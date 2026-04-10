"""wind — WindKit wind function MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import numpy as np
import xarray as xr

import windkit
from server.main import mcp
from server.tools.windkit._serializers import _ok, da_to_dict, dict_to_da, dict_to_ds, ds_to_dict


@mcp.tool()
def windkit_wind_speed(u: str, v: str) -> dict:
    """Calculate wind speed from u,v wind vector arrays (WindKit).

    Args:
        u: JSON array of u-component values.
        v: JSON array of v-component values.
    """
    u_arr = xr.DataArray(json.loads(u))
    v_arr = xr.DataArray(json.loads(v))
    result = windkit.wind_speed(u_arr, v_arr)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_wind_direction(u: str, v: str) -> dict:
    """Calculate wind direction from u,v wind vector arrays (WindKit).

    Args:
        u: JSON array of u-component values.
        v: JSON array of v-component values.
    """
    u_arr = xr.DataArray(json.loads(u))
    v_arr = xr.DataArray(json.loads(v))
    result = windkit.wind_direction(u_arr, v_arr)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_wind_speed_and_direction(u: str, v: str) -> dict:
    """Calculate both wind speed and direction from u,v vectors (WindKit).

    Args:
        u: JSON array of u-component values.
        v: JSON array of v-component values.
    """
    u_arr = xr.DataArray(json.loads(u))
    v_arr = xr.DataArray(json.loads(v))
    ws, wd = windkit.wind_speed_and_direction(u_arr, v_arr)
    return _ok({"wind_speed": da_to_dict(ws), "wind_direction": da_to_dict(wd)})


@mcp.tool()
def windkit_wind_vectors(ws: str, wd: str) -> dict:
    """Calculate u,v wind vectors from speed and direction arrays (WindKit).

    Args:
        ws: JSON array of wind speed values.
        wd: JSON array of wind direction values.
    """
    ws_arr = xr.DataArray(json.loads(ws))
    wd_arr = xr.DataArray(json.loads(wd))
    u, v = windkit.wind_vectors(ws_arr, wd_arr)
    return _ok({"u": da_to_dict(u), "v": da_to_dict(v)})


@mcp.tool()
def windkit_wind_direction_difference(wd_obs: str, wd_mod: str) -> dict:
    """Calculate circular distance between observed and modelled wind directions (WindKit).

    Args:
        wd_obs: JSON array of observed wind directions.
        wd_mod: JSON array of modelled wind directions.
    """
    obs = xr.DataArray(json.loads(wd_obs))
    mod = xr.DataArray(json.loads(wd_mod))
    result = windkit.wind_direction_difference(obs, mod)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_wd_to_sector(wd: str, sectors: int = 12, output_type: str = "indices") -> dict:
    """Convert wind directions to 0-based sector indices (WindKit).

    Args:
        wd: JSON array of wind direction values.
        sectors: Number of sectors (default 12).
        output_type: Output type - 'int' or 'float'.
    """
    wd_arr = xr.DataArray(json.loads(wd))
    result = windkit.wd_to_sector(wd_arr, sectors=sectors, output_type=output_type)
    if isinstance(result, tuple):
        return _ok({"sectors": da_to_dict(result[0]), "sector_coords": da_to_dict(result[1])})
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_vinterp_wind_direction(wind_direction_data: str, height: float) -> dict:
    """Interpolate wind direction to a given height from other height levels (WindKit).

    Args:
        wind_direction_data: JSON-serialized xarray DataArray with height dimension.
        height: Target height in meters.
    """
    da = dict_to_da(json.loads(wind_direction_data))
    result = windkit.vinterp_wind_direction(da, height)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_vinterp_wind_speed(wind_speed_data: str, height: float, method: str = "log") -> dict:
    """Vertically interpolate wind speed to a given height (WindKit).

    Args:
        wind_speed_data: JSON-serialized xarray DataArray with height dimension.
        height: Target height in meters.
        method: Interpolation method ('log' or 'linear', default 'log').
    """
    da = dict_to_da(json.loads(wind_speed_data))
    result = windkit.vinterp_wind_speed(da, height, method=method)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_rotor_equivalent_wind_speed(wind_speed_data: str, wind_direction_data: str,
                                         hub_height: float, rotor_diameter: float) -> dict:
    """Calculate rotor equivalent wind speed (REWS) from height-resolved profiles (WindKit).

    Args:
        wind_speed_data: JSON-serialized xarray DataArray of wind speeds at height levels.
        wind_direction_data: JSON-serialized xarray DataArray of wind directions at height levels.
        hub_height: Hub height in meters.
        rotor_diameter: Rotor diameter in meters.
    """
    ws_da = dict_to_da(json.loads(wind_speed_data))
    wd_da = dict_to_da(json.loads(wind_direction_data))
    result = windkit.rotor_equivalent_wind_speed(ws_da, wd_da, hub_height=hub_height, rotor_diameter=rotor_diameter)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_shear_extrapolate(wind_speed_data: str, height: float, method: str = "power_law") -> dict:
    """Shear-extrapolate wind speeds to new heights using the power law (WindKit).

    Args:
        wind_speed_data: JSON-serialized xarray DataArray of wind speeds with height dimension.
        height: Target height in meters.
        method: Extrapolation method (default 'power_law').
    """
    da = dict_to_da(json.loads(wind_speed_data))
    result = windkit.shear_extrapolate(da, height, method=method)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_shear_exponent(wind_speed_data: str) -> dict:
    """Compute shear exponent from vertical wind speed profiles (WindKit).

    Args:
        wind_speed_data: JSON-serialized xarray DataArray with height dimension.
    """
    da = dict_to_da(json.loads(wind_speed_data))
    result = windkit.shear_exponent(da)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_veer_extrapolate(wind_direction_data: str, height: float) -> dict:
    """Extrapolate wind direction to new heights using linear veer (WindKit).

    Args:
        wind_direction_data: JSON-serialized xarray DataArray with height dimension.
        height: Target height in meters.
    """
    da = dict_to_da(json.loads(wind_direction_data))
    result = windkit.veer_extrapolate(da, height)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_wind_veer(wind_direction_data: str) -> dict:
    """Calculate wind veer (change in wind direction with height) (WindKit).

    Args:
        wind_direction_data: JSON-serialized xarray DataArray with height dimension.
    """
    da = dict_to_da(json.loads(wind_direction_data))
    result = windkit.wind_veer(da)
    return _ok(da_to_dict(result))
