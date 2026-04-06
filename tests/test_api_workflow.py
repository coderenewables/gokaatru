"""test_api_workflow — Browser-oriented API workflow validation for GoKaatru.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager


@pytest.fixture
def api_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client and session manager backed by a temporary workspace tree."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _timeseries_upload_bytes(sample_timeseries_df: pd.DataFrame) -> bytes:
    """Serialize the sample dataset into a browser-uploadable CSV payload with a Timestamp column."""
    payload = sample_timeseries_df.reset_index().rename(columns={"index": "Timestamp"})
    return payload.to_csv(index=False).encode("utf-8")


def _datamodel_bytes() -> bytes:
    """Build a minimal datamodel JSON payload compatible with the Phase 1 recursive parser."""
    payload = {
        "measurement_point": [
            {"name": "Spd_100m", "height_m": 100, "measurement_type_id": "wind_speed"},
            {"name": "Dir_100m", "height_m": 100, "measurement_type_id": "wind_direction"},
            {"name": "Spd_100m_sd", "height_m": 100, "measurement_type_id": "wind_speed"},
            {"name": "Spd_80m", "height_m": 80, "measurement_type_id": "wind_speed"},
            {"name": "Spd_60m", "height_m": 60, "measurement_type_id": "wind_speed"},
        ]
    }
    return json.dumps(payload).encode("utf-8")


def test_api_workflow(sample_timeseries_df: pd.DataFrame, api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify the browser-facing API flow from uploads through plots uses the shared backend helpers."""
    client, manager = api_client

    create_response = client.post("/api/sessions")
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    timeseries_response = client.post(
        f"/api/sessions/{session_id}/uploads/timeseries",
        headers=headers,
        files={"file": ("timeseries.csv", _timeseries_upload_bytes(sample_timeseries_df), "text/csv")},
    )
    assert timeseries_response.status_code == 200
    assert timeseries_response.json()["rows"] == len(sample_timeseries_df)

    datamodel_response = client.post(
        f"/api/sessions/{session_id}/uploads/datamodel",
        headers=headers,
        files={"file": ("datamodel.json", _datamodel_bytes(), "application/json")},
    )
    assert datamodel_response.status_code == 200
    assert 100.0 in datamodel_response.json()["heights"]

    sensors_response = client.get(f"/api/sessions/{session_id}/sensors", headers=headers)
    assert sensors_response.status_code == 200
    assert len(sensors_response.json()["sensors"]) >= 3

    config_response = client.put(
        f"/api/sessions/{session_id}/config",
        headers=headers,
        json={
            "updates": [
                {"key": "project_name", "value": "North Ridge"},
                {"key": "location.latitude", "value": 52.4},
                {"key": "location.longitude", "value": 4.8},
                {"key": "hub_height_m", "value": 150},
            ]
        },
    )
    assert config_response.status_code == 200
    assert config_response.json()["runconfig"]["hub_height_m"] == 150

    height_sensors = json.dumps({"100": "Spd_100m", "80": "Spd_80m", "60": "Spd_60m"})
    shear_response = client.post(
        f"/api/sessions/{session_id}/shear/calculate",
        headers=headers,
        json={"height_sensors": height_sensors},
    )
    assert shear_response.status_code == 200
    table_response = client.post(
        f"/api/sessions/{session_id}/shear/table",
        headers=headers,
        json={"aggregation": "momm"},
    )
    assert table_response.status_code == 200

    extrapolation_response = client.post(
        f"/api/sessions/{session_id}/extrapolation/hub",
        headers=headers,
        json={"hub_height_m": 150.0, "shear_model": "power_law"},
    )
    assert extrapolation_response.status_code == 200
    assert extrapolation_response.json()["column_name"] == "Spd_150m_hub"

    state = manager.get_session(session_id)
    hourly_reference = state.timeseries_df["Spd_100m"].resample("h").mean().dropna().iloc[:240]
    state.era5_interpolated_df = pd.DataFrame(
        {
            "Spd_100m_hub": hourly_reference.to_numpy(dtype=float) * 0.95 + 0.4,
            "Dir_100m": pd.Series(range(len(hourly_reference)), index=hourly_reference.index).mul(7).mod(360),
            "t2m": 288.15,
            "sp": 101325.0,
            "d2m": 280.15,
        },
        index=hourly_reference.index,
    )
    state.era5_nodes = [
        {"latitude": 52.25, "longitude": 4.5, "distance_km": 10.0, "bearing": "SW"},
        {"latitude": 52.25, "longitude": 4.75, "distance_km": 8.0, "bearing": "W"},
        {"latitude": 52.5, "longitude": 4.5, "distance_km": 7.0, "bearing": "S"},
        {"latitude": 52.5, "longitude": 4.75, "distance_km": 5.0, "bearing": "SE"},
    ]

    ltc_response = client.post(
        f"/api/sessions/{session_id}/ltc/linear_least_squares",
        headers=headers,
        json={"short_col": "Spd_100m", "long_col": "Spd_100m_hub"},
    )
    assert ltc_response.status_code == 200
    assert ltc_response.json()["algorithm"] == "linear_least_squares"

    ltc_results_response = client.get(f"/api/sessions/{session_id}/results/ltc", headers=headers)
    assert ltc_results_response.status_code == 200
    assert ltc_results_response.json()["results"][0]["algorithm"] == "linear_least_squares"

    plot_response = client.post(
        f"/api/sessions/{session_id}/plots/weibull",
        headers=headers,
        json={"sensor_name": "Spd_100m"},
    )
    assert plot_response.status_code == 200
    assert "plotly_json" in plot_response.json()

    map_response = client.get(f"/api/sessions/{session_id}/map/site", headers=headers)
    assert map_response.status_code == 200
    assert map_response.json()["type"] == "FeatureCollection"

    export_response = client.get(f"/api/sessions/{session_id}/runconfig/export", headers=headers)
    assert export_response.status_code == 200
    assert Path(export_response.json()["file_path"]).exists()
