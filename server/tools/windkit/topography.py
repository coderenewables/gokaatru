"""topography — WindKit topography (landcover, elevation, raster/vector maps) MCP tools.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import windkit
from server.main import mcp
from server.state.session import session
from server.tools.windkit._serializers import _ok, da_to_dict, dict_to_ds, ds_to_dict, gdf_to_geojson, geojson_to_gdf


def _windkit_dir() -> Path:
    base = Path(session.get_data_dir()) / "windkit"
    base.mkdir(parents=True, exist_ok=True)
    return base


# ---------------------------------------------------------------------------
# Landcover
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_get_landcover_table(dataset: str, table: str = "") -> dict:
    """Get landcover table from a dataset (WindKit).

    Args:
        dataset: JSON-serialized xarray Dataset.
        table: Table name (optional).
    """
    ds = dict_to_ds(json.loads(dataset))
    kwargs = {}
    if table:
        kwargs["table"] = table
    lct = windkit.get_landcover_table(ds, **kwargs)
    return _ok(dict(lct))


@mcp.tool()
def windkit_add_landcover_table(geojson_data: str, lctable: str) -> dict:
    """Add a landcover table to a GeoDataFrame (WindKit).

    Args:
        geojson_data: GeoJSON string of the GeoDataFrame.
        lctable: JSON-serialized LandCoverTable dict mapping landcover codes to roughness.
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    table = windkit.LandCoverTable(json.loads(lctable))
    result = windkit.add_landcover_table(gdf, table)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_roughness_to_landcover(roughness_dataset: str) -> dict:
    """Convert a roughness map to landcover map (WindKit).

    Args:
        roughness_dataset: JSON-serialized roughness map xarray Dataset.
    """
    ds = dict_to_ds(json.loads(roughness_dataset))
    result = windkit.roughness_to_landcover(ds)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_landcover_to_roughness(geojson_data: str, lctable: str) -> dict:
    """Convert a landcover map to roughness map (WindKit).

    Args:
        geojson_data: GeoJSON string of the landcover GeoDataFrame.
        lctable: JSON-serialized LandCoverTable dict.
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    table = windkit.LandCoverTable(json.loads(lctable))
    result = windkit.landcover_to_roughness(gdf, table)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_read_roughness_map(filename: str, crs: str = "") -> dict:
    """Read roughness map from file (WindKit).

    Args:
        filename: Path to roughness map file.
        crs: CRS string override (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if crs:
        import pyproj
        kwargs["crs"] = pyproj.CRS.from_user_input(crs)
    result = windkit.read_roughness_map(str(path), **kwargs)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_read_landcover_map(filename: str, crs: str = "") -> dict:
    """Read landcover map from file (WindKit).

    Args:
        filename: Path to landcover map file.
        crs: CRS string override (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if crs:
        import pyproj
        kwargs["crs"] = pyproj.CRS.from_user_input(crs)
    result = windkit.read_landcover_map(str(path), **kwargs)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_landcover_map_to_file(geojson_data: str, filename: str) -> dict:
    """Write landcover map to file (WindKit).

    Args:
        geojson_data: GeoJSON string of the landcover GeoDataFrame.
        filename: Output filename.
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    windkit.landcover_map_to_file(gdf, str(path))
    return _ok({"written": str(path)})


@mcp.tool()
def windkit_roughness_map_to_file(geojson_data: str, filename: str) -> dict:
    """Write roughness map to file (WindKit).

    Args:
        geojson_data: GeoJSON string of the roughness GeoDataFrame.
        filename: Output filename.
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    windkit.roughness_map_to_file(gdf, str(path))
    return _ok({"written": str(path)})


# ---------------------------------------------------------------------------
# Elevation
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_read_elevation_map(filename: str, crs: str = "") -> dict:
    """Read elevation map from file (WindKit).

    Args:
        filename: Path to elevation map file.
        crs: CRS string override (optional).
    """
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    kwargs = {}
    if crs:
        import pyproj
        kwargs["crs"] = pyproj.CRS.from_user_input(crs)
    result = windkit.read_elevation_map(str(path), **kwargs)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_elevation_map_to_file(dataset: str, filename: str) -> dict:
    """Write elevation map to file (WindKit).

    Args:
        dataset: JSON-serialized elevation DataArray.
        filename: Output filename.
    """
    from server.tools.windkit._serializers import dict_to_da
    da = dict_to_da(json.loads(dataset))
    path = _windkit_dir() / filename if not Path(filename).is_absolute() else Path(filename)
    windkit.elevation_map_to_file(da, str(path))
    return _ok({"written": str(path)})


# ---------------------------------------------------------------------------
# Raster maps
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_create_raster_map(west_east: str, south_north: str, height: str, crs: str,
                                resolution: float = 100.0) -> dict:
    """Create an empty raster map DataArray (WindKit).

    Args:
        west_east: JSON array of easting coordinates.
        south_north: JSON array of northing coordinates.
        height: JSON array of heights.
        crs: CRS string.
        resolution: Grid resolution in meters (default 100.0).
    """
    import pyproj
    we = json.loads(west_east)
    sn = json.loads(south_north)
    h = json.loads(height)
    locs = windkit.spatial.create_point(we, sn, h, pyproj.CRS.from_user_input(crs))
    result = windkit.create_raster_map(locs, resolution)
    return _ok(da_to_dict(result))


@mcp.tool()
def windkit_get_raster_map(bbox: str, dataset: str = "copernicus_dem_30", band: str = "",
                             source: str = "") -> dict:
    """Download a raster map from DTU, Planetary Computer, or Google Earth Engine (WindKit).

    Args:
        bbox: JSON-serialized bounding box [west, south, east, north, crs_string].
        dataset: Dataset name (default 'copernicus_dem_30').
        band: Band name (optional).
        source: Data source (optional).
    """
    bbox_data = json.loads(bbox)
    import pyproj
    ring = bbox_data[:4]
    crs = pyproj.CRS.from_user_input(bbox_data[4]) if len(bbox_data) > 4 else pyproj.CRS.from_epsg(4326)
    wk_bbox = windkit.spatial.BBox(ring, crs)
    kwargs = {"dataset": dataset}
    if band:
        kwargs["band"] = band
    if source:
        kwargs["source"] = source
    result = windkit.get_raster_map(wk_bbox, **kwargs)
    return _ok(da_to_dict(result))


# ---------------------------------------------------------------------------
# Vector maps
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_create_vector_map(bbox: str, map_type: str = "elevation") -> dict:
    """Create a square elevation or roughness vector map within a bounding box (WindKit).

    Args:
        bbox: JSON-serialized bounding box [west, south, east, north, crs_string].
        map_type: Map type - 'elevation' or 'roughness' (default 'elevation').
    """
    bbox_data = json.loads(bbox)
    import pyproj
    ring = bbox_data[:4]
    crs = pyproj.CRS.from_user_input(bbox_data[4]) if len(bbox_data) > 4 else pyproj.CRS.from_epsg(4326)
    wk_bbox = windkit.spatial.BBox(ring, crs)
    result = windkit.create_vector_map(wk_bbox, map_type=map_type)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_get_vector_map(bbox: str, dataset: str = "", source: str = "") -> dict:
    """Download a vector map from the GWA map API (WindKit).

    Args:
        bbox: JSON-serialized bounding box [west, south, east, north, crs_string].
        dataset: Dataset name (optional).
        source: Data source (optional).
    """
    bbox_data = json.loads(bbox)
    import pyproj
    ring = bbox_data[:4]
    crs = pyproj.CRS.from_user_input(bbox_data[4]) if len(bbox_data) > 4 else pyproj.CRS.from_epsg(4326)
    wk_bbox = windkit.spatial.BBox(ring, crs)
    kwargs = {}
    if dataset:
        kwargs["dataset"] = dataset
    if source:
        kwargs["source"] = source
    result = windkit.get_vector_map(wk_bbox, **kwargs)
    return _ok(gdf_to_geojson(result))


# ---------------------------------------------------------------------------
# Map conversion
# ---------------------------------------------------------------------------

@mcp.tool()
def windkit_lines_to_polygons(geojson_data: str, check_errors: bool = True) -> dict:
    """Convert a GeoDataFrame of lines into polygons (WindKit).

    Args:
        geojson_data: GeoJSON string of line geometries.
        check_errors: Whether to check for topology errors (default True).
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    result = windkit.lines_to_polygons(gdf, check_errors=check_errors)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_polygons_to_lines(geojson_data: str, lctable: str = "", map_type: str = "") -> dict:
    """Convert a GeoDataFrame of polygons into line segments (WindKit).

    Args:
        geojson_data: GeoJSON string of polygon geometries.
        lctable: JSON-serialized LandCoverTable dict (optional).
        map_type: Map type hint (optional).
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    kwargs = {}
    if lctable:
        kwargs["lctable"] = windkit.LandCoverTable(json.loads(lctable))
    if map_type:
        kwargs["map_type"] = map_type
    result = windkit.polygons_to_lines(gdf, **kwargs)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_snap_to_layer(geojson_data: str, tolerance: float = 1.0) -> dict:
    """Snap geometries in a GeoDataFrame to each other within a tolerance (WindKit).

    Args:
        geojson_data: GeoJSON string of geometries.
        tolerance: Snap tolerance (default 1.0).
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    result = windkit.snap_to_layer(gdf, tolerance=tolerance)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_check_dead_ends(geojson_data: str) -> dict:
    """Detect dead ends in a set of lines (WindKit).

    Args:
        geojson_data: GeoJSON string of line geometries.
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    result = windkit.check_dead_ends(gdf)
    return _ok(gdf_to_geojson(result))


@mcp.tool()
def windkit_check_lines_cross(geojson_data: str) -> dict:
    """Detect crossing line geometries in a GeoDataFrame (WindKit).

    Args:
        geojson_data: GeoJSON string of line geometries.
    """
    gdf = geojson_to_gdf(json.loads(geojson_data))
    result = windkit.check_lines_cross(gdf)
    return _ok(gdf_to_geojson(result))
