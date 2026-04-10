"""climate_stats — WindKit wind climate statistics MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import windkit
from server.main import mcp
from server.tools.windkit._serializers import _ok, da_to_dict, dict_to_ds, ds_to_dict


@mcp.tool()
def windkit_create_met_fields(west_east: str, south_north: str, height: str, crs: str,
                                n_sectors: int = 12) -> dict:
    """Create an empty dataset filled with met_fields (WindKit).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
        n_sectors: Number of sectors (default 12).
    """
    import pyproj
    we = json.loads(west_east)
    sn = json.loads(south_north)
    h = json.loads(height)
    locs = windkit.spatial.create_point(we, sn, h, pyproj.CRS.from_user_input(crs))
    ds = windkit.create_met_fields(locs, n_sectors=n_sectors)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_mean_ws_moment(wc_dataset: str, moment: int = 1, bysector: bool = False) -> dict:
    """Calculate the mean wind speed moment from a wind climate (WindKit).

    Args:
        wc_dataset: JSON-serialized wind climate xarray Dataset.
        moment: Moment order (default 1).
        bysector: Whether to compute per sector (default False).
    """
    ds = dict_to_ds(json.loads(wc_dataset))
    result = windkit.mean_ws_moment(ds, moment=moment, bysector=bysector)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_ws_cdf(wc_dataset: str, bysector: bool = False) -> dict:
    """Calculate wind speed CDF from a wind climate (WindKit).

    Args:
        wc_dataset: JSON-serialized wind climate xarray Dataset.
        bysector: Whether to compute per sector (default False).
    """
    ds = dict_to_ds(json.loads(wc_dataset))
    result = windkit.ws_cdf(ds, bysector=bysector)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_ws_freq_gt_mean(wc_dataset: str, bysector: bool = False) -> dict:
    """Calculate wind speed frequency greater than the mean from a wind climate (WindKit).

    Args:
        wc_dataset: JSON-serialized wind climate xarray Dataset.
        bysector: Whether to compute per sector (default False).
    """
    ds = dict_to_ds(json.loads(wc_dataset))
    result = windkit.ws_freq_gt_mean(ds, bysector=bysector)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_mean_wind_speed(wc_dataset: str, bysector: bool = False) -> dict:
    """Calculate the mean wind speed from a wind climate (WindKit).

    Args:
        wc_dataset: JSON-serialized wind climate xarray Dataset.
        bysector: Whether to compute per sector (default False).
    """
    ds = dict_to_ds(json.loads(wc_dataset))
    result = windkit.mean_wind_speed(ds, bysector=bysector)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_mean_power_density(wc_dataset: str, bysector: bool = False,
                                 air_density: float = 1.225) -> dict:
    """Calculate the power density of a wind climate (WindKit).

    Args:
        wc_dataset: JSON-serialized wind climate xarray Dataset.
        bysector: Whether to compute per sector (default False).
        air_density: Air density in kg/m³ (default 1.225).
    """
    ds = dict_to_ds(json.loads(wc_dataset))
    result = windkit.mean_power_density(ds, bysector=bysector, air_density=air_density)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_get_cross_predictions(wcs_dataset: str, wcs_src_dataset: str = "") -> dict:
    """Get cross predictions from a dataset of wind climates (WindKit).

    Args:
        wcs_dataset: JSON-serialized xarray Dataset of wind climates.
        wcs_src_dataset: JSON-serialized source wind climates Dataset (optional).
    """
    wcs = dict_to_ds(json.loads(wcs_dataset))
    kwargs = {}
    if wcs_src_dataset:
        kwargs["wcs_src"] = dict_to_ds(json.loads(wcs_src_dataset))
    result = windkit.get_cross_predictions(wcs, **kwargs)
    return _ok(ds_to_dict(result))
