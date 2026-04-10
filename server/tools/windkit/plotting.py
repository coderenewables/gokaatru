"""plotting — WindKit plotting MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import windkit
import windkit.plot
from server.main import mcp
from server.tools.windkit._serializers import _ok, dict_to_ds, fig_to_dict, geojson_to_gdf


@mcp.tool()
def windkit_plot_histogram(bwc_dataset: str, style: str = "bar", weibull: bool = False) -> dict:
    """Plot the histogram from a binned wind climate (WindKit Plot).

    Args:
        bwc_dataset: JSON-serialized BWC xarray Dataset.
        style: Plot style - 'bar' or 'line' (default 'bar').
        weibull: Whether to overlay Weibull fit (default False).
    """
    ds = dict_to_ds(json.loads(bwc_dataset))
    fig = windkit.plot.histogram(ds, style=style, weibull=weibull)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_histogram_lines(bwc_dataset: str) -> dict:
    """Create a distribution plot and matching frequency wind rose for BWC (WindKit Plot).

    Args:
        bwc_dataset: JSON-serialized BWC xarray Dataset.
    """
    ds = dict_to_ds(json.loads(bwc_dataset))
    fig = windkit.plot.histogram_lines(ds)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_operational_curves(wtg_dataset: str) -> dict:
    """Plot wind turbine generator operational curves (WindKit Plot).

    Args:
        wtg_dataset: JSON-serialized WTG xarray Dataset.
    """
    ds = dict_to_ds(json.loads(wtg_dataset))
    fig = windkit.plot.operational_curves(ds)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_raster(data_array: str, contour: bool = False) -> dict:
    """Create a raster map plot (WindKit Plot).

    Args:
        data_array: JSON-serialized xarray DataArray.
        contour: Whether to show contour lines (default False).
    """
    from server.tools.windkit._serializers import dict_to_da
    da = dict_to_da(json.loads(data_array))
    fig = windkit.plot.raster_plot(da, contour=contour)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_roughness_rose(dataset: str, style: str = "bar") -> dict:
    """Create a roughness rose plot (WindKit Plot).

    Args:
        dataset: JSON-serialized xarray Dataset.
        style: Plot style (default 'bar').
    """
    ds = dict_to_ds(json.loads(dataset))
    fig = windkit.plot.roughness_rose(ds, style=style)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_time_series(tswc_dataset: str, range_slider: bool = False) -> dict:
    """Create a time series plot (WindKit Plot).

    Args:
        tswc_dataset: JSON-serialized TSWC xarray Dataset.
        range_slider: Whether to show range slider (default False).
    """
    ds = dict_to_ds(json.loads(tswc_dataset))
    fig = windkit.plot.time_series(ds, range_slider=range_slider)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_vertical_profile(data_array: str = "") -> dict:
    """Plot vertical wind speed profile (WindKit Plot).

    Args:
        data_array: JSON-serialized xarray DataArray of measured data (optional).
    """
    kwargs = {}
    if data_array:
        from server.tools.windkit._serializers import dict_to_da
        kwargs["da_meas"] = dict_to_da(json.loads(data_array))
    fig = windkit.plot.vertical_profile(**kwargs)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_wind_rose(bwc_dataset: str, wind_speed_bins: str = "", style: str = "bar") -> dict:
    """Create a wind rose plot (WindKit Plot).

    Args:
        bwc_dataset: JSON-serialized BWC xarray Dataset.
        wind_speed_bins: JSON array of wind speed bin edges (optional).
        style: Plot style (default 'bar').
    """
    ds = dict_to_ds(json.loads(bwc_dataset))
    kwargs = {"style": style}
    if wind_speed_bins:
        kwargs["wind_speed_bins"] = json.loads(wind_speed_bins)
    fig = windkit.plot.wind_rose(ds, **kwargs)
    return _ok(fig_to_dict(fig))


@mcp.tool()
def windkit_plot_landcover_map(geojson_data: str, column: str = "") -> dict:
    """Plot landcover polygons colored by a field (WindKit Plot).

    Args:
        geojson_data: GeoJSON string of the landcover GeoDataFrame.
        column: Column name to color by (optional).
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    kwargs = {}
    if column:
        kwargs["column"] = column
    fig = windkit.plot.landcover_map(gdf, **kwargs)
    return _ok(fig_to_dict(fig))
