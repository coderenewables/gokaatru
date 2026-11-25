"""A BrightHub node already in the project's cache is reused when it covers the campaign
(P2-8b, decisions/0014.11).

The long-term correction needs the reference over the concurrent period, so a cached node
is a hit only when its series reaches the campaign's last measured record; otherwise, or
before any record is loaded, the node is downloaded. Each node says which.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager
from server.state.projects import ProjectRegistry
from server.tools.brighthub import BrightHubAuthError, _download_brighthub_nodes

NODES = [{"latitude_ddeg": 52.0, "longitude_ddeg": 4.0}, {"latitude_ddeg": 52.0, "longitude_ddeg": 5.0}]
SERIES_END = "2024-03-31T23:00:00"


def _payload(latitude: float, longitude: float) -> dict:
    stamps = pd.date_range("2023-01-01", SERIES_END, freq="6h", tz="UTC")
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timeseries_data": {
            "data": [
                {"timestamp": stamp.isoformat(), "Spd_100m_mps": 8.0 + i % 3, "Dir_100m_deg": 180.0,
                 "Tmp_2m_degC": 10.0, "Prs_0m_hPa": 1010.0}
                for i, stamp in enumerate(stamps)
            ]
        },
    }


@pytest.fixture
def downloads(monkeypatch: pytest.MonkeyPatch) -> list[list[dict]]:
    calls: list[list[dict]] = []

    def download(_token: str, nodes: list[dict], _dataset: str) -> list[dict]:
        calls.append(nodes)
        return [_payload(node["latitude_ddeg"], node["longitude_ddeg"]) for node in nodes]

    monkeypatch.setattr("server.tools.brighthub.download_reanalysis_data", download)
    return calls


def _campaigns(tmp_path: Path) -> tuple[SessionManager, list]:
    manager = SessionManager(base_dir=tmp_path / "sessions")
    registry = ProjectRegistry(manager)
    project = registry.create("Ridge")
    states = [registry.add_campaign(project["id"], name, kind)[1] for name, kind in (("M1", "mast"), ("L1", "lidar"))]
    for state, end in zip(states, ("2024-02-01", "2024-03-15")):
        index = pd.date_range("2023-06-01", end, freq="10min", tz="UTC")
        state.timeseries_df = pd.DataFrame({"Spd_100m": np.full(len(index), 7.0)}, index=index)
        state.brighthub_token = "token"
    return manager, states


def test_a_node_one_campaign_downloaded_is_reused_by_the_other(tmp_path: Path, downloads) -> None:
    _, (mast, lidar) = _campaigns(tmp_path)
    first = _download_brighthub_nodes(mast, "ERA5", NODES)
    assert [item["cache"] for item in first] == ["downloaded", "downloaded"] and len(downloads) == 1

    lidar.brighthub_token = None
    second = _download_brighthub_nodes(lidar, "ERA5", NODES)
    assert [item["cache"] for item in second] == ["hit", "hit"] and len(downloads) == 1
    assert second[0]["cached_through"] == "2024-03-31T18:00:00"
    for key, frame in mast.era5_data.items():
        pd.testing.assert_frame_equal(lidar.era5_data[key], frame)


def test_a_cached_node_that_ends_before_the_campaign_is_downloaded_again(tmp_path: Path, downloads) -> None:
    _, (mast, lidar) = _campaigns(tmp_path)
    _download_brighthub_nodes(mast, "ERA5", NODES)
    index = pd.date_range("2023-06-01", "2024-04-30", freq="10min", tz="UTC")
    lidar.timeseries_df = pd.DataFrame({"Spd_100m": np.full(len(index), 7.0)}, index=index)
    again = _download_brighthub_nodes(lidar, "ERA5", NODES[:1])
    assert again[0]["cache"] == "downloaded" and len(downloads) == 2


def test_without_a_record_or_a_login(tmp_path: Path, downloads) -> None:
    _, (mast, lidar) = _campaigns(tmp_path)
    _download_brighthub_nodes(mast, "ERA5", NODES)
    lidar.timeseries_df = None
    assert [item["cache"] for item in _download_brighthub_nodes(lidar, "ERA5", NODES)] == ["downloaded"] * 2
    index = pd.date_range("2025-01-01", periods=10, freq="10min", tz="UTC")
    lidar.timeseries_df = pd.DataFrame({"Spd_100m": np.ones(10)}, index=index)
    lidar.brighthub_token = None
    with pytest.raises(BrightHubAuthError):
        _download_brighthub_nodes(lidar, "ERA5", NODES)


def test_the_route_reports_the_cache_and_answers_401_without_a_login(tmp_path: Path, downloads) -> None:
    manager, (mast, lidar) = _campaigns(tmp_path)
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            def download(state, nodes):
                return client.post(
                    f"/api/sessions/{state.session_id}/brighthub/reanalysis/download",
                    headers={"X-GoKaatru-Session": state.session_id},
                    json={"dataset": "ERA5", "nodes": nodes, "source": "brighthub"},
                )

            downloaded = download(mast, NODES)
            assert downloaded.status_code == 200, downloaded.text
            assert [item["cache"] for item in downloaded.json()["items"]] == ["downloaded", "downloaded"]
            lidar.brighthub_token = None
            hit = download(lidar, NODES)
            assert [item["cache"] for item in hit.json()["items"]] == ["hit", "hit"]
            missing = download(lidar, [{"latitude_ddeg": 53.0, "longitude_ddeg": 4.0}])
            assert missing.status_code == 401
    finally:
        app.dependency_overrides.clear()
