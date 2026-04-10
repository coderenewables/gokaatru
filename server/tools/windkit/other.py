"""other — WindKit other utilities (Weibull, WAsP, coordinates, ERA5) MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import windkit
import windkit.weibull
from server.main import mcp
from server.state.session import session
from server.tools.windkit._serializers import _ok, da_to_dict, ds_to_dict, dict_to_ds


def _windkit_dir() -> Path:
    base = Path(session.get_data_dir()) / "windkit"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# Tutorial data
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_get_tutorial_data(name: str) -> dict:
    """Download and extract tutorial data, returning the path (WindKit).

    Args:
        name: Tutorial data name.
    """
    path = windkit.get_tutorial_data(name)
    return _ok({"path": str(path)})


@mcp.tool()
def windkit_load_tutorial_data(name: str) -> dict:
    """Download, extract, and load tutorial data into memory (WindKit).

    Args:
        name: Tutorial data name.
    """
    data = windkit.load_tutorial_data(name)
    if hasattr(data, "to_dict"):
        return _ok(ds_to_dict(data))
    return _ok({"type": str(type(data).__name__), "repr": repr(data)[:500]})


# ---------------------------------------------------------------------------
# Weibull distribution
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_fit_weibull_wasp_m1_m3_fgtm(m1: float, m3: float, fgtm: float) -> dict:
    """Fit Weibull parameters from 1st/3rd moments and fraction GT mean (WindKit).

    Args:
        m1: First moment of wind speed.
        m3: Third moment of wind speed.
        fgtm: Fraction of probability above the mean.
    """
    A, k = windkit.weibull.fit_weibull_wasp_m1_m3_fgtm(m1, m3, fgtm)
    return _ok({"A": float(A), "k": float(k)})


@mcp.tool()
def windkit_fit_weibull_wasp_m1_m3(m1: float, m3: float) -> dict:
    """Fit Weibull parameters from 1st and 3rd moments (WindKit).

    Args:
        m1: First moment of wind speed.
        m3: Third moment of wind speed.
    """
    A, k = windkit.weibull.fit_weibull_wasp_m1_m3(m1, m3)
    return _ok({"A": float(A), "k": float(k)})


@mcp.tool()
def windkit_fit_weibull_k_sumlogm(sumlogm: float) -> dict:
    """Fit Weibull shape parameter from the sum of log of moments (WindKit).

    Args:
        sumlogm: Sum of log of moments.
    """
    k = windkit.weibull.fit_weibull_k_sumlogm(sumlogm)
    return _ok({"k": float(k)})


@mcp.tool()
def windkit_weibull_moment(A: float, k: float, n: int = 1) -> dict:
    """Calculate moment for a Weibull distribution (WindKit).

    Args:
        A: Weibull A (scale) parameter.
        k: Weibull k (shape) parameter.
        n: Moment order (default 1).
    """
    result = windkit.weibull.weibull_moment(A, k, n=n)
    return _ok({"moment": float(result)})


@mcp.tool()
def windkit_weibull_pdf(A: float, k: float, x: str) -> dict:
    """Calculate Weibull PDF for given wind speeds (WindKit).

    Args:
        A: Weibull A (scale) parameter.
        k: Weibull k (shape) parameter.
        x: JSON array of wind speed values.
    """
    import numpy as np
    x_arr = np.array(json.loads(x))
    result = windkit.weibull.weibull_pdf(A, k, x_arr)
    return _ok({"pdf": result.tolist() if hasattr(result, "tolist") else [float(result)]})


@mcp.tool()
def windkit_weibull_cdf(A: float, k: float, x: str) -> dict:
    """Calculate Weibull CDF for given wind speeds (WindKit).

    Args:
        A: Weibull A (scale) parameter.
        k: Weibull k (shape) parameter.
        x: JSON array of wind speed values.
    """
    import numpy as np
    x_arr = np.array(json.loads(x))
    result = windkit.weibull.weibull_cdf(A, k, x_arr)
    return _ok({"cdf": result.tolist() if hasattr(result, "tolist") else [float(result)]})


@mcp.tool()
def windkit_weibull_freq_gt_mean(A: float, k: float) -> dict:
    """Calculate fraction of probability mass above the mean for a Weibull distribution (WindKit).

    Args:
        A: Weibull A (scale) parameter.
        k: Weibull k (shape) parameter.
    """
    result = windkit.weibull.weibull_freq_gt_mean(A, k)
    return _ok({"freq_gt_mean": float(result)})


@mcp.tool()
def windkit_get_weibull_probability(A: float, k: float, speed_range: str) -> dict:
    """Calculate Weibull probability for wind speed bins (WindKit).

    Args:
        A: Weibull A (scale) parameter.
        k: Weibull k (shape) parameter.
        speed_range: JSON array of wind speed bin edges.
    """
    import numpy as np
    sr = np.array(json.loads(speed_range))
    result = windkit.weibull.get_weibull_probability(A, k, sr)
    if isinstance(result, tuple):
        # Returns (bin_centers, probabilities)
        probs = result[1] if len(result) > 1 else result[0]
        return _ok({"probability": probs.tolist() if hasattr(probs, 'tolist') else list(probs)})
    return _ok({"probability": result.tolist() if hasattr(result, 'tolist') else [float(result)]})


# ---------------------------------------------------------------------------
# WAsP
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_read_cfdres(filename: str, crs: str) -> dict:
    """Read a .cfdres file into an xarray Dataset (WindKit).

    Args:
        filename: Path to the .cfdres file.
        crs: CRS string.
    """
    import pyproj
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    ds = windkit.read_cfdres(str(path), pyproj.CRS.from_user_input(crs))
    return _ok(ds_to_dict(ds))


# ---------------------------------------------------------------------------
# Coordinates
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_create_sector_coords(bins: int = 12, start: float = 0.0) -> dict:
    """Create wind sector coordinate as a DataArray (WindKit).

    Args:
        bins: Number of sector bins (default 12).
        start: Starting angle (default 0.0).
    """
    result = windkit.create_sector_coords(bins=bins, start=start)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_create_wsbin_coords(bins: int = 30, width: float = 1.0, start: float = 0.0) -> dict:
    """Create wind speed bin coordinates (WindKit).

    Args:
        bins: Number of wind speed bins (default 30).
        width: Bin width (default 1.0).
        start: Starting wind speed (default 0.0).
    """
    result = windkit.create_wsbin_coords(bins=bins, width=width, start=start)
    return _ok(da_to_dict(result))


# ---------------------------------------------------------------------------
# ERA5
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_get_era5(datetime_range: str, bbox: str = "", source: str = "") -> dict:
    """Download ERA5 reanalysis data (WindKit).

    Args:
        datetime_range: ISO datetime string or range (e.g. '2020-01-01/2020-12-31').
        bbox: JSON bounding box [west, south, east, north, crs_string] (optional).
        source: Data source (optional).
    """
    kwargs = {}
    if bbox:
        import pyproj
        bbox_data = json.loads(bbox)
        ring = bbox_data[:4]
        crs = pyproj.CRS.from_user_input(bbox_data[4]) if len(bbox_data) > 4 else pyproj.CRS.from_epsg(4326)
        kwargs["bbox"] = windkit.spatial.BBox(ring, crs)
    if source:
        kwargs["source"] = source
    ds = windkit.get_era5(datetime_range, **kwargs)
    return _ok(ds_to_dict(ds))
