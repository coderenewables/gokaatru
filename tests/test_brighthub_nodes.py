"""test_brighthub_nodes — regression test for distance_km/bearing on reanalysis nodes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from unittest.mock import patch

from server.core.brighthub import fetch_reanalysis_nodes


class _FakeResponse:
    def __init__(self, payload: list[dict]) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> list[dict]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_fetch_reanalysis_nodes_annotates_distance_km_and_bearing() -> None:
    """Every returned node must carry distance_km and bearing, not just distance_sq."""
    site_lat, site_lon = 52.0, 5.0
    # Two ERA5 nodes: one due north (~0.25 deg), one due east (~0.25 deg).
    era5_payload = [
        {"latitude_ddeg": 52.25, "longitude_ddeg": 5.0},   # ~28 km north of site
        {"latitude_ddeg": 52.0, "longitude_ddeg": 5.25},   # ~17 km east of site
    ]
    merra2_payload = [{"latitude_ddeg": 52.25, "longitude_ddeg": 5.25}]

    fake_era5 = _FakeResponse(era5_payload)
    fake_merra2 = _FakeResponse(merra2_payload)

    def fake_get(url: str, **_kwargs):
        if "ERA5" in url:
            return fake_era5
        return fake_merra2

    with patch("server.core.brighthub.requests.get", side_effect=fake_get):
        result = fetch_reanalysis_nodes(token="fake-token", lat=site_lat, lon=site_lon)

    # All nodes are annotated.
    for node in result["era5_nodes"] + result["merra2_nodes"]:
        assert "distance_km" in node, f"missing distance_km on {node}"
        assert "bearing" in node, f"missing bearing on {node}"
        assert isinstance(node["distance_km"], float)
        assert node["distance_km"] > 0
        assert node["bearing"] in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}

    # Bearings are correct: the northern node bears N, the eastern node bears E.
    by_lon = {n["longitude_ddeg"]: n for n in result["era5_nodes"]}
    assert by_lon[5.25]["bearing"] == "E"
    assert by_lon[5.0]["bearing"] == "N"

    # Nodes are sorted by distance_km (ascending), so the nearer east node comes first.
    assert result["era5_nodes"][0]["longitude_ddeg"] == 5.25
    assert result["era5_nodes"][0]["distance_km"] < result["era5_nodes"][1]["distance_km"]


def test_fetch_reanalysis_nodes_limits_counts() -> None:
    """Four nodes are returned for each source (design doc S6.1).

    MERRA-2 used to be capped at one node, which made spatial interpolation to site
    impossible and left it usable only as a raw node series. Both sources now return
    four so either can be interpolated and used as a long-term reference.
    """
    era5_payload = [
        {"latitude_ddeg": 52.0 + i * 0.05, "longitude_ddeg": 5.0} for i in range(10)
    ]
    merra2_payload = [
        {"latitude_ddeg": 52.0 + i * 0.05, "longitude_ddeg": 5.0} for i in range(5)
    ]

    def fake_get(url: str, **_kwargs):
        return _FakeResponse(era5_payload if "ERA5" in url else merra2_payload)

    with patch("server.core.brighthub.requests.get", side_effect=fake_get):
        result = fetch_reanalysis_nodes(token="fake-token", lat=52.0, lon=5.0)

    assert len(result["era5_nodes"]) == 4
    assert len(result["merra2_nodes"]) == 4
    # Still distance-sorted, so the closest node leads.
    assert result["merra2_nodes"][0]["latitude_ddeg"] == 52.0
    merra_distances = [float(node["distance_km"]) for node in result["merra2_nodes"]]
    assert merra_distances == sorted(merra_distances)
