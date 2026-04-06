"""map — Phase 4 MCP tools for GeoJSON site and ERA5 node map overlays.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from server.main import mcp
from server.state.session import session


def _mast_feature() -> dict[str, object]:
    """Build the site GeoJSON point feature from runconfig-backed location metadata."""
    coordinate = session.get_coordinate()
    if coordinate is None:
        raise ValueError("Site coordinate is not set in runconfig")
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [coordinate.longitude, coordinate.latitude]},
        "properties": {"name": "Measurement Mast", "type": "mast", "marker-color": "#083434"},
    }


@mcp.tool()
def get_mast_marker() -> dict:
    """Return the site measurement mast as a GeoJSON feature for site overview mapping."""
    return _mast_feature()


@mcp.tool()
def get_era5_node_markers() -> dict:
    """Return all surrounding ERA5 nodes as a GeoJSON FeatureCollection with distance and bearing metadata."""
    if not session.era5_nodes:
        raise ValueError("ERA5 nodes are not available. Run find_era5_nodes first")
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(node["longitude"]), float(node["latitude"])]},
            "properties": {
                "name": f"ERA5 Node {index + 1}",
                "type": "era5_node",
                "distance_km": float(node["distance_km"]),
                "bearing": str(node["bearing"]),
            },
        }
        for index, node in enumerate(session.era5_nodes)
    ]
    return {"type": "FeatureCollection", "features": features}


@mcp.tool()
def get_site_overview_map() -> dict:
    """Return a combined GeoJSON FeatureCollection of the mast and ERA5 support nodes."""
    nodes = get_era5_node_markers()
    return {"type": "FeatureCollection", "features": [_mast_feature(), *nodes["features"]]}
