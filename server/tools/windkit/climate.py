"""climate — WindKit wind climate (TSWC, BWC, WWC, GWC, GeoWC) MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import xarray as xr

import windkit
from server.main import mcp
from server.state.session import session
from server.tools.windkit._serializers import _ok, da_to_dict, dict_to_ds, ds_to_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _windkit_dir() -> Path:
    """Return the session-scoped windkit data directory, creating it if needed."""
    base = Path(session.get_data_dir()) / "windkit"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# Time Series Wind Climate (TSWC)
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_tswc(dataset: str) -> dict:
    """Validate that an xarray Dataset is a valid time series wind climate (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_tswc(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_tswc(dataset: str) -> dict:
    """Check whether an xarray Dataset is a valid TSWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.is_tswc(ds)
    return _ok({"is_tswc": bool(result)})


@mcp.tool()
def windkit_create_tswc(west_east: str, south_north: str, height: str, crs: str,
                         date_range_start: str = "", date_range_end: str = "",
                         freq: str = "h") -> dict:
    """Create an empty time series wind climate dataset (WindKit).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: Coordinate reference system string (e.g. 'EPSG:4326').
        date_range_start: Start date ISO string (optional).
        date_range_end: End date ISO string (optional).
        freq: Time frequency string (default 'h').
    """
    import pyproj
    we = json.loads(west_east)
    sn = json.loads(south_north)
    h = json.loads(height)
    output_locs = windkit.spatial.create_point(we, sn, h, pyproj.CRS.from_user_input(crs))
    kwargs = {}
    if date_range_start and date_range_end:
        kwargs["date_range"] = pd.date_range(date_range_start, date_range_end, freq=freq)
    ds = windkit.create_tswc(output_locs, **kwargs)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_read_tswc(filename: str, file_format: str = "") -> dict:
    """Read a time series wind climate file (WindKit).

    Args:
        filename: Path to the TSWC file (relative to session windkit dir or absolute).
        file_format: File format hint (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    ds = windkit.read_tswc(str(path), **kwargs)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_tswc_from_dataframe(dataframe_json: str, west_east: float, south_north: float,
                                  height: float, crs: str) -> dict:
    """Transform a pandas DataFrame into a TSWC xarray Dataset (WindKit).

    Args:
        dataframe_json: JSON-serialized pandas DataFrame (split-orient).
        west_east: Easting coordinate.
        south_north: Northing coordinate.
        height: Measurement height.
        crs: CRS string (e.g. 'EPSG:4326').
    """
    import pyproj
    df = pd.read_json(dataframe_json, orient="split")
    ds = windkit.tswc_from_dataframe(df, west_east, south_north, height, pyproj.CRS.from_user_input(crs))
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_tswc_resample(dataset: str, freq: str) -> dict:
    """Resample a TSWC wind speed and direction to a given frequency (WindKit).

    Args:
        dataset: JSON-serialized TSWC xarray Dataset.
        freq: Target frequency string (e.g. '6h', 'D', 'ME').
    """
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.tswc_resample(ds, freq)
    return _ok(ds_to_dict(result))


# ---------------------------------------------------------------------------
# Binned Wind Climate (BWC)
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_bwc(dataset: str) -> dict:
    """Validate that an xarray Dataset is a valid binned wind climate (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_bwc(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_bwc(dataset: str) -> dict:
    """Check whether an xarray Dataset is a valid BWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_bwc": bool(windkit.is_bwc(ds))})


@mcp.tool()
def windkit_create_bwc(west_east: str, south_north: str, height: str, crs: str,
                        n_sectors: int = 12, n_wsbins: int = 30) -> dict:
    """Create an empty binned wind climate dataset (WindKit).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
        n_sectors: Number of wind direction sectors (default 12).
        n_wsbins: Number of wind speed bins (default 30).
    """
    import pyproj
    we = json.loads(west_east)
    sn = json.loads(south_north)
    h = json.loads(height)
    locs = windkit.spatial.create_point(we, sn, h, pyproj.CRS.from_user_input(crs))
    ds = windkit.create_bwc(locs, n_sectors=n_sectors, n_wsbins=n_wsbins)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_read_bwc(filename: str, crs: str = "", file_format: str = "") -> dict:
    """Read a binned wind climate from file (WindKit).

    Args:
        filename: Path to the BWC file.
        crs: CRS string override (optional).
        file_format: File format hint (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if crs:
        import pyproj
        kwargs["crs"] = pyproj.CRS.from_user_input(crs)
    if file_format:
        kwargs["file_format"] = file_format
    ds = windkit.read_bwc(str(path), **kwargs)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_bwc_from_tswc(tswc_dataset: str, wsbin_width: float = 1.0, n_wsbins: int = 40,
                            n_sectors: int = 12) -> dict:
    """Create a BWC from a time series wind climate (WindKit).

    Args:
        tswc_dataset: JSON-serialized TSWC xarray Dataset.
        wsbin_width: Wind speed bin width (default 1.0).
        n_wsbins: Number of wind speed bins (default 40).
        n_sectors: Number of sectors (default 12).
    """
    ds = dict_to_ds(json.loads(tswc_dataset))
    result = windkit.bwc_from_tswc(ds, wsbin_width=wsbin_width, n_wsbins=n_wsbins, n_sectors=n_sectors)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_bwc_to_file(dataset: str, filename: str, file_format: str = "") -> dict:
    """Write a binned wind climate to file (WindKit).

    Args:
        dataset: JSON-serialized BWC xarray Dataset.
        filename: Output filename (relative to session windkit dir or absolute).
        file_format: File format hint (optional).
    """
    ds = dict_to_ds(json.loads(dataset))
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    windkit.bwc_to_file(ds, str(path), **kwargs)
    return _ok({"written": str(path)})


@mcp.tool()
def windkit_combine_bwcs(datasets: str) -> dict:
    """Combine a list of BWC datasets into one (WindKit).

    Args:
        datasets: JSON array of serialized BWC xarray Datasets.
    """
    ds_list = [dict_to_ds(d) for d in json.loads(datasets)]
    result = windkit.combine_bwcs(ds_list)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_weibull_fit(bwc_dataset: str, include_met_fields: bool = False) -> dict:
    """Fit sectorwise Weibull parameters from a BWC using WAsP algorithm (WindKit).

    Args:
        bwc_dataset: JSON-serialized BWC xarray Dataset.
        include_met_fields: Whether to include met fields in result (default False).
    """
    ds = dict_to_ds(json.loads(bwc_dataset))
    result = windkit.weibull_fit(ds, include_met_fields=include_met_fields)
    return _ok(ds_to_dict(result))


# ---------------------------------------------------------------------------
# Weibull Wind Climate (WWC)
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_wwc(dataset: str) -> dict:
    """Validate that an xarray Dataset is a valid Weibull wind climate (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_wwc(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_wwc(dataset: str) -> dict:
    """Check whether an xarray Dataset is a valid WWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_wwc": bool(windkit.is_wwc(ds))})


@mcp.tool()
def windkit_create_wwc(west_east: str, south_north: str, height: str, crs: str,
                        n_sectors: int = 12) -> dict:
    """Create an empty Weibull wind climate dataset (WindKit).

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
    ds = windkit.create_wwc(locs, n_sectors=n_sectors)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_read_wwc(filename: str, file_format: str = "") -> dict:
    """Read a Weibull wind climate from file (WindKit).

    Args:
        filename: Path to the WWC file.
        file_format: File format hint (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    ds = windkit.read_wwc(str(path), **kwargs)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_read_mfwwc(filenames: str, file_format: str = "") -> dict:
    """Read multiple WWC files into a single dataset (WindKit).

    Args:
        filenames: JSON array of file paths.
        file_format: File format hint (optional).
    """
    paths = json.loads(filenames)
    resolved = [str(_windkit_dir() / f) if not Path(f).is_absolute() else f for f in paths]
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    ds = windkit.read_mfwwc(resolved, **kwargs)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_wwc_to_file(dataset: str, filename: str, file_format: str = "") -> dict:
    """Write a Weibull wind climate to file (WindKit).

    Args:
        dataset: JSON-serialized WWC xarray Dataset.
        filename: Output filename.
        file_format: File format hint (optional).
    """
    ds = dict_to_ds(json.loads(dataset))
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    windkit.wwc_to_file(ds, str(path), **kwargs)
    return _ok({"written": str(path)})


@mcp.tool()
def windkit_wwc_to_bwc(dataset: str, ws_bins: str) -> dict:
    """Convert a WWC to a BWC using given wind speed bins (WindKit).

    Args:
        dataset: JSON-serialized WWC xarray Dataset.
        ws_bins: JSON array of wind speed bin edges.
    """
    ds = dict_to_ds(json.loads(dataset))
    bins = json.loads(ws_bins)
    result = windkit.wwc_to_bwc(ds, bins)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_weibull_combined(wwc_dataset: str) -> dict:
    """Return the all-sector combined A and k from a WWC (WindKit).

    Args:
        wwc_dataset: JSON-serialized WWC xarray Dataset.
    """
    ds = dict_to_ds(json.loads(wwc_dataset))
    result = windkit.weibull_combined(ds)
    return _ok(ds_to_dict(result))


# ---------------------------------------------------------------------------
# Generalized Wind Climate (GWC)
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_gwc(dataset: str) -> dict:
    """Validate that an xarray Dataset is a valid GWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_gwc(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_gwc(dataset: str) -> dict:
    """Check whether an xarray Dataset is a valid GWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_gwc": bool(windkit.is_gwc(ds))})


@mcp.tool()
def windkit_create_gwc(west_east: str, south_north: str, height: str, crs: str,
                        n_sectors: int = 12) -> dict:
    """Create an empty generalized wind climate dataset (WindKit).

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
    ds = windkit.create_gwc(locs, n_sectors=n_sectors)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_read_gwc(filename: str, crs: str = "", file_format: str = "") -> dict:
    """Read a generalized wind climate from file (WindKit).

    Args:
        filename: Path to the GWC file.
        crs: CRS string override (optional).
        file_format: File format hint (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if crs:
        import pyproj
        kwargs["crs"] = pyproj.CRS.from_user_input(crs)
    if file_format:
        kwargs["file_format"] = file_format
    ds = windkit.read_gwc(str(path), **kwargs)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_gwc_to_file(dataset: str, filename: str, file_format: str = "") -> dict:
    """Write a generalized wind climate to file (WindKit).

    Args:
        dataset: JSON-serialized GWC xarray Dataset.
        filename: Output filename.
        file_format: File format hint (optional).
    """
    ds = dict_to_ds(json.loads(dataset))
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if file_format:
        kwargs["file_format"] = file_format
    windkit.gwc_to_file(ds, str(path), **kwargs)
    return _ok({"written": str(path)})


# ---------------------------------------------------------------------------
# Geostrophic Wind Climate (GeoWC)
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_validate_geowc(dataset: str) -> dict:
    """Validate that an xarray Dataset is a valid GeoWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    windkit.validate_geowc(ds)
    return _ok({"valid": True})


@mcp.tool()
def windkit_is_geowc(dataset: str) -> dict:
    """Check whether an xarray Dataset is a valid GeoWC (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_geowc": bool(windkit.is_geowc(ds))})
