"""test_phase9 — Verification tests for GoKaatru Phase 9 export and reanalysis features.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.schemas.common import Coordinate
from server.state.manager import SessionManager
from server.state.session import SessionState, session
from server.tools.ltc import _run_ltc_linear_least_squares
from server.tools.visualization import _plot_era5_comparison, _plot_era5_measured_overlay


@pytest.fixture
def api_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client backed by a temporary session manager."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _timeseries_upload_bytes(sample_timeseries_df: pd.DataFrame) -> bytes:
    """Serialize the sample dataset into a CSV upload payload with a Timestamp column."""
    payload = sample_timeseries_df.reset_index().rename(columns={"index": "Timestamp"})
    return payload.to_csv(index=False).encode("utf-8")


def _datamodel_bytes() -> bytes:
    """Build a minimal Task 43 datamodel payload for upload workflow tests."""
    payload = {
        "measurement_point": [
            {"name": "Spd_100m", "height_m": 100, "measurement_type_id": "wind_speed"},
            {"name": "Dir_100m", "height_m": 100, "measurement_type_id": "wind_direction"},
            {"name": "Spd_80m", "height_m": 80, "measurement_type_id": "wind_speed"},
        ]
    }
    return json.dumps(payload).encode("utf-8")


def _seed_era5_plot_state(state: SessionState) -> None:
    """Populate deterministic measured and ERA5 series for Phase 9 comparison plots."""
    index = pd.date_range("2019-01-31", periods=24, freq="ME")
    site_speed = 8.1 + 0.8 * np.sin(np.linspace(0.0, 4.0 * np.pi, index.size)) + np.linspace(0.0, 0.4, index.size)
    state.set_coordinate(Coordinate(latitude=12.34, longitude=56.78, elevation_m=0.0))
    state.set_hub_height_m(100)
    state.timeseries_df = pd.DataFrame(
        {"Spd_100m_hub": site_speed * 1.02 + 0.15 * np.cos(np.linspace(0.0, 3.0 * np.pi, index.size))},
        index=index,
    )
    state.era5_nodes = [
        {"latitude": 12.25, "longitude": 56.75, "distance_km": 10.0, "bearing": "NW"},
        {"latitude": 12.25, "longitude": 56.99, "distance_km": 12.0, "bearing": "NE"},
        {"latitude": 12.49, "longitude": 56.75, "distance_km": 11.0, "bearing": "SW"},
        {"latitude": 12.49, "longitude": 56.99, "distance_km": 13.0, "bearing": "SE"},
    ]
    state.era5_data = {
        f"node_{index_value + 1}": pd.DataFrame({"Spd_100m": site_speed + offset}, index=index)
        for index_value, offset in enumerate([-0.4, -0.1, 0.15, 0.35])
    }
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m": site_speed}, index=index)


def test_export_timeseries_csv_response(
    sample_timeseries_df: pd.DataFrame,
    api_client: tuple[TestClient, SessionManager],
) -> None:
    """Verify the cleaned timeseries export returns a CSV attachment."""
    client, _manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    client.post(
        f"/api/sessions/{session_id}/uploads/timeseries",
        headers=headers,
        files={"file": ("timeseries.csv", _timeseries_upload_bytes(sample_timeseries_df), "text/csv")},
    )
    client.post(
        f"/api/sessions/{session_id}/uploads/datamodel",
        headers=headers,
        files={"file": ("datamodel.json", _datamodel_bytes(), "application/json")},
    )

    response = client.get(f"/api/sessions/{session_id}/exports/timeseries", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="timeseries_cleaned.csv"' == response.headers["content-disposition"]
    assert "Timestamp,Spd_100m,Spd_80m,Spd_60m,Dir_100m,Spd_100m_sd" in response.text.splitlines()[0]


def test_export_ltc_csv_response(
    sample_timeseries_df: pd.DataFrame,
    api_client: tuple[TestClient, SessionManager],
) -> None:
    """Verify one stored LTC result can be exported as a CSV attachment."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    state.timeseries_df = sample_timeseries_df.copy()
    state.raw_timeseries_df = sample_timeseries_df.copy()
    state.era5_interpolated_df = (
        sample_timeseries_df[["Spd_100m"]]
        .resample("h")
        .mean()
        .rename(columns={"Spd_100m": "Spd_100m_hub"})
        .assign(Spd_100m_hub=lambda frame: frame["Spd_100m_hub"] * 1.04)
    )
    _run_ltc_linear_least_squares(state, "Spd_100m", "Spd_100m_hub")

    response = client.get(f"/api/sessions/{session_id}/exports/ltc/linear_least_squares", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="ltc_linear_least_squares.csv"' == response.headers["content-disposition"]
    assert response.text.splitlines()[0] == "Timestamp,ERA5_original,corrected_wind_speed"


def test_export_runconfig_json_response(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify the runconfig download returns parseable JSON as an attachment."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    state.set_project_name("North Ridge")
    state.set_hub_height_m(140)

    response = client.get(f"/api/sessions/{session_id}/exports/runconfig", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert 'attachment; filename="runconfig.json"' == response.headers["content-disposition"]
    assert json.loads(response.text)["project_name"] == "North Ridge"


def test_plot_era5_comparison_traces() -> None:
    """Verify the ERA5 annual profile plot renders four node traces plus the interpolated site."""
    _seed_era5_plot_state(session)

    result = _plot_era5_comparison(session)
    parsed = json.loads(result["plotly_json"])

    assert len(parsed["data"]) == 5
    assert parsed["data"][-1]["name"] == "Interpolated site"


def test_plot_era5_measured_overlay() -> None:
    """Verify the measured-vs-ERA5 overlay renders two traces with an R-squared annotation."""
    _seed_era5_plot_state(session)

    result = _plot_era5_measured_overlay(session)
    parsed = json.loads(result["plotly_json"])
    annotations = parsed["layout"].get("annotations", [])

    assert len(parsed["data"]) == 2
    assert any("R²=" in annotation["text"] for annotation in annotations)