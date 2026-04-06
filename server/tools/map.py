"""map — Phase 4 MCP tools for GeoJSON site and ERA5 node map overlays.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from server.main import mcp
from server.state.session import SessionState, session


def _mast_feature(state: SessionState) -> dict[str, object]:
    """Build the site GeoJSON point feature from runconfig-backed location metadata."""
    coordinate = state.get_coordinate()
    if coordinate is None:
        raise ValueError("Site coordinate is not set in runconfig")
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [coordinate.longitude, coordinate.latitude]},
        "properties": {"name": "Measurement Mast", "type": "mast", "marker-color": "#083434"},
    }


def _get_mast_marker(state: SessionState) -> dict:
    """Return the site measurement mast as a GeoJSON feature for site overview mapping."""
    return _mast_feature(state)


def _get_era5_node_markers(state: SessionState) -> dict:
    """Return all surrounding ERA5 nodes as a GeoJSON FeatureCollection with distance and bearing metadata."""
    if not state.era5_nodes:
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
        for index, node in enumerate(state.era5_nodes)
    ]
    return {"type": "FeatureCollection", "features": features}


def _get_site_overview_map(state: SessionState) -> dict:
    """Return a combined GeoJSON FeatureCollection of the mast and ERA5 support nodes."""
    nodes = _get_era5_node_markers(state)
    return {"type": "FeatureCollection", "features": [_mast_feature(state), *nodes["features"]]}


@mcp.tool()
def get_mast_marker() -> dict:
    """Return the site measurement mast as a GeoJSON feature for site overview mapping."""
    return _get_mast_marker(session)


@mcp.tool()
def get_era5_node_markers() -> dict:
    """Return all surrounding ERA5 nodes as a GeoJSON FeatureCollection with distance and bearing metadata."""
    return _get_era5_node_markers(session)


@mcp.tool()
def get_site_overview_map() -> dict:
    """Return a combined GeoJSON FeatureCollection of the mast and ERA5 support nodes."""
    return _get_site_overview_map(session)
