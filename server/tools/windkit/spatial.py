"""spatial — WindKit spatial operations MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import windkit
import windkit.spatial
from server.main import mcp
from server.tools.windkit._serializers import (
    _ok,
    da_to_dict,
    dict_to_da,
    dict_to_ds,
    ds_to_dict,
    gdf_to_geojson,
    geojson_to_gdf,
)


# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_get_crs(dataset: str) -> dict:
    """Get the CRS from a WindKit object (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
    """
    ds = dict_to_ds(json.loads(dataset))
    crs = windkit.spatial.get_crs(ds)
    return _ok({"crs": str(crs)})


@mcp.tool()
def windkit_set_crs(dataset: str, crs: str) -> dict:
    """Set the CRS on a WindKit object (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
        crs: CRS string (e.g. 'EPSG:4326').
    """
    import pyproj
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.spatial.set_crs(ds, pyproj.CRS.from_user_input(crs))
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_crs_are_equal(dataset_a: str, dataset_b: str) -> dict:
    """Check if CRS of two WindKit objects are equal (WindKit Spatial).

    Args:
        dataset_a: JSON-serialized first xarray Dataset.
        dataset_b: JSON-serialized second xarray Dataset.
    """
    ds_a = dict_to_ds(json.loads(dataset_a))
    ds_b = dict_to_ds(json.loads(dataset_b))
    return _ok({"equal": bool(windkit.spatial.crs_are_equal(ds_a, ds_b))})


# ---------------------------------------------------------------------------
# Create spatial objects
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_create_dataset(west_east: str, south_north: str, height: str, crs: str) -> dict:
    """Create a WindKit dataset from locations (WindKit Spatial).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
    """
    import pyproj
    ds = windkit.spatial.create_dataset(
        json.loads(west_east), json.loads(south_north), json.loads(height),
        pyproj.CRS.from_user_input(crs),
    )
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_create_raster(west_east: str, south_north: str, crs: str) -> dict:
    """Create a WindKit raster dataset from locations (WindKit Spatial).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        crs: CRS string.
    """
    import pyproj
    ds = windkit.spatial.create_raster(
        json.loads(west_east), json.loads(south_north),
        pyproj.CRS.from_user_input(crs),
    )
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_create_point(west_east: str, south_north: str, height: str, crs: str) -> dict:
    """Create a WindKit point dataset from locations (WindKit Spatial).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
    """
    import pyproj
    ds = windkit.spatial.create_point(
        json.loads(west_east), json.loads(south_north), json.loads(height),
        pyproj.CRS.from_user_input(crs),
    )
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_create_stacked_point(west_east: str, south_north: str, height: str, crs: str) -> dict:
    """Create a WindKit stacked point dataset from locations (WindKit Spatial).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
    """
    import pyproj
    ds = windkit.spatial.create_stacked_point(
        json.loads(west_east), json.loads(south_north), json.loads(height),
        pyproj.CRS.from_user_input(crs),
    )
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_create_cuboid(west_east: str, south_north: str, height: str, crs: str) -> dict:
    """Create a WindKit cuboid dataset from locations (WindKit Spatial).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
    """
    import pyproj
    ds = windkit.spatial.create_cuboid(
        json.loads(west_east), json.loads(south_north), json.loads(height),
        pyproj.CRS.from_user_input(crs),
    )
    return _ok(ds_to_dict(ds))


# ---------------------------------------------------------------------------
# Validate spatial objects
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_is_point(dataset: str) -> dict:
    """Check if a WindKit object has 'point' spatial dimension (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_point": bool(windkit.spatial.is_point(ds))})


@mcp.tool()
def windkit_is_stacked_point(dataset: str) -> dict:
    """Check if a WindKit object has 'stacked_point' dimension (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_stacked_point": bool(windkit.spatial.is_stacked_point(ds))})


@mcp.tool()
def windkit_is_cuboid(dataset: str) -> dict:
    """Check if a WindKit object has cuboid dimensions (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_cuboid": bool(windkit.spatial.is_cuboid(ds))})


@mcp.tool()
def windkit_is_raster(dataset: str) -> dict:
    """Check if a WindKit object has raster-like dimensions (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
    """
    ds = dict_to_ds(json.loads(dataset))
    return _ok({"is_raster": bool(windkit.spatial.is_raster(ds))})


# ---------------------------------------------------------------------------
# Convert between spatial objects
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_to_point(dataset: str) -> dict:
    """Convert a WindKit object to 'point' structure (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
    """
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.spatial.to_point(ds)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_to_cuboid(dataset: str) -> dict:
    """Convert a point-based object to cuboid (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
    """
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.spatial.to_cuboid(ds)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_to_stacked_point(dataset: str) -> dict:
    """Convert a WindKit object to 'stacked_point' structure (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
    """
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.spatial.to_stacked_point(ds)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_to_raster(dataset: str) -> dict:
    """Convert a point-based object to raster (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
    """
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.spatial.to_raster(ds)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_gdf_to_ds(geojson_data: str, height: float = 0.0, struct: str = "point") -> dict:
    """Convert a GeoDataFrame to a WindKit spatial structure (WindKit Spatial).

    Args:
        geojson_data: GeoJSON string of the GeoDataFrame.
        height: Height value (default 0.0).
        struct: Spatial structure type (default 'point').
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    ds = windkit.spatial.gdf_to_ds(gdf, height=height, struct=struct)
    return _ok(ds_to_dict(ds))


@mcp.tool()
def windkit_ds_to_gdf(dataset: str, include_height: bool = False) -> dict:
    """Convert a WindKit spatial structure to a GeoDataFrame (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
        include_height: Whether to include height column (default False).
    """
    ds = dict_to_ds(json.loads(dataset))
    gdf = windkit.spatial.ds_to_gdf(ds, include_height=include_height)
    return _ok(gdf_to_geojson(gdf))


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_interp_structured_like(source_dataset: str, target_dataset: str) -> dict:
    """Interpolate spatially from cuboid to another spatial structure (WindKit Spatial).

    Args:
        source_dataset: JSON-serialized source xarray Dataset.
        target_dataset: JSON-serialized target xarray Dataset.
    """
    src = dict_to_ds(json.loads(source_dataset))
    tgt = dict_to_ds(json.loads(target_dataset))
    result = windkit.spatial.interp_structured_like(src, tgt)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_interp_unstructured(dataset: str, west_east: str = "", south_north: str = "") -> dict:
    """Interpolate spatially from unstructured data to new coordinates (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
        west_east: JSON array of target easting coordinates (optional).
        south_north: JSON array of target northing coordinates (optional).
    """
    ds = dict_to_ds(json.loads(dataset))
    kwargs = {}
    if west_east:
        kwargs["west_east"] = json.loads(west_east)
    if south_north:
        kwargs["south_north"] = json.loads(south_north)
    result = windkit.spatial.interp_unstructured(ds, **kwargs)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_interp_unstructured_like(source_dataset: str, target_dataset: str) -> dict:
    """Interpolate from unstructured data to another spatial structure (WindKit Spatial).

    Args:
        source_dataset: JSON-serialized source xarray Dataset.
        target_dataset: JSON-serialized target xarray Dataset.
    """
    src = dict_to_ds(json.loads(source_dataset))
    tgt = dict_to_ds(json.loads(target_dataset))
    result = windkit.spatial.interp_unstructured_like(src, tgt)
    return _ok(ds_to_dict(result))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_are_spatially_equal(dataset_a: str, dataset_b: str) -> dict:
    """Check that spatial points are equivalent for two datasets (WindKit Spatial).

    Args:
        dataset_a: JSON-serialized first xarray Dataset.
        dataset_b: JSON-serialized second xarray Dataset.
    """
    ds_a = dict_to_ds(json.loads(dataset_a))
    ds_b = dict_to_ds(json.loads(dataset_b))
    return _ok({"equal": bool(windkit.spatial.are_spatially_equal(ds_a, ds_b))})


@mcp.tool()
def windkit_equal_spatial_shape(dataset_a: str, dataset_b: str) -> dict:
    """Check if two spatial objects have the same shape (WindKit Spatial).

    Args:
        dataset_a: JSON-serialized first xarray Dataset.
        dataset_b: JSON-serialized second xarray Dataset.
    """
    ds_a = dict_to_ds(json.loads(dataset_a))
    ds_b = dict_to_ds(json.loads(dataset_b))
    return _ok({"equal": bool(windkit.spatial.equal_spatial_shape(ds_a, ds_b))})


@mcp.tool()
def windkit_covers(dataset_a: str, dataset_b: str) -> dict:
    """Check if dataset_a spatially covers dataset_b (WindKit Spatial).

    Args:
        dataset_a: JSON-serialized first xarray Dataset.
        dataset_b: JSON-serialized second xarray Dataset.
    """
    ds_a = dict_to_ds(json.loads(dataset_a))
    ds_b = dict_to_ds(json.loads(dataset_b))
    return _ok({"covers": bool(windkit.spatial.covers(ds_a, ds_b))})


# ---------------------------------------------------------------------------
# Spatial operations
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_clip(dataset: str, mask_geojson: str) -> dict:
    """Clip a WindKit object to a geometric mask (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
        mask_geojson: GeoJSON string of the mask geometry.
    """
    ds = dict_to_ds(json.loads(dataset))
    mask_gdf = geojson_to_gdf(json.loads(mask_geojson))
    result = windkit.spatial.clip(ds, mask_gdf)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_clip_with_margin(dataset: str, clipper_dataset: str, margin: float = 0.0) -> dict:
    """Clip a dataset to the bounding box of another with margin (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset to clip.
        clipper_dataset: JSON-serialized clipper xarray Dataset.
        margin: Margin size (default 0.0).
    """
    ds = dict_to_ds(json.loads(dataset))
    clipper = dict_to_ds(json.loads(clipper_dataset))
    kwargs = {}
    if margin > 0:
        kwargs["margin"] = margin
    result = windkit.spatial.clip_with_margin(ds, clipper, **kwargs)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_mask(dataset: str, mask_geojson: str) -> dict:
    """Mask a WindKit object with a geometric mask (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
        mask_geojson: GeoJSON string of the mask geometry.
    """
    ds = dict_to_ds(json.loads(dataset))
    mask_gdf = geojson_to_gdf(json.loads(mask_geojson))
    result = windkit.spatial.mask(ds, mask_gdf)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_nearest_points(ref_dataset: str, target_dataset: str) -> dict:
    """Get nearest points from reference dataset for each target point (WindKit Spatial).

    Args:
        ref_dataset: JSON-serialized reference xarray Dataset.
        target_dataset: JSON-serialized target xarray Dataset.
    """
    ref = dict_to_ds(json.loads(ref_dataset))
    tgt = dict_to_ds(json.loads(target_dataset))
    result = windkit.spatial.nearest_points(ref, tgt)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_reproject(dataset: str, to_crs: str) -> dict:
    """Reproject a WindKit object to a new CRS without changing data (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
        to_crs: Target CRS string.
    """
    import pyproj
    ds = dict_to_ds(json.loads(dataset))
    result = windkit.spatial.reproject(ds, pyproj.CRS.from_user_input(to_crs))
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_warp(dataset: str, to_crs: str, resolution: float = 0.0) -> dict:
    """Warp a cuboid WindKit object to a new CRS with data interpolation (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset.
        to_crs: Target CRS string.
        resolution: Target resolution (optional, 0 means auto).
    """
    import pyproj
    ds = dict_to_ds(json.loads(dataset))
    kwargs = {}
    if resolution > 0:
        kwargs["resolution"] = resolution
    result = windkit.spatial.warp(ds, pyproj.CRS.from_user_input(to_crs), **kwargs)
    return _ok(ds_to_dict(result))


@mcp.tool()
def windkit_count_spatial_points(dataset: str) -> dict:
    """Get the number of spatial points in a WindKit object (WindKit Spatial).

    Args:
        dataset: JSON-serialized xarray Dataset or DataArray.
    """
    ds = dict_to_ds(json.loads(dataset))
    count = windkit.spatial.count_spatial_points(ds)
    return _ok({"count": int(count)})
