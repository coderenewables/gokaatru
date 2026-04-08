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


def _upload_bytes(path: Path) -> bytes:
    """Read one of the checked-in upload fixtures as browser file bytes."""
    return path.read_bytes()


def test_api_workflow(
    uploaded_timeseries_path: Path,
    uploaded_datamodel_path: Path,
    api_client: tuple[TestClient, SessionManager],
) -> None:
    """Verify the browser-facing API flow works end-to-end with the checked-in Boxkite upload dataset."""
    client, manager = api_client

    create_response = client.post("/api/sessions")
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    timeseries_response = client.post(
        f"/api/sessions/{session_id}/uploads/timeseries",
        headers=headers,
        files={
            "file": (
                uploaded_timeseries_path.name,
                _upload_bytes(uploaded_timeseries_path),
                "text/csv",
            )
        },
    )
    assert timeseries_response.status_code == 200
    assert timeseries_response.json()["rows"] == 73532
    assert timeseries_response.json()["timestep_minutes"] == 10
    assert timeseries_response.json()["start"] == "2019-02-10T09:00:00"
    assert timeseries_response.json()["end"] == "2021-02-11T23:50:00"

    datamodel_response = client.post(
        f"/api/sessions/{session_id}/uploads/datamodel",
        headers=headers,
        files={
            "file": (
                uploaded_datamodel_path.name,
                _upload_bytes(uploaded_datamodel_path),
                "application/json",
            )
        },
    )
    assert datamodel_response.status_code == 200
    assert 100.0 in datamodel_response.json()["heights"]
    assert datamodel_response.json()["project_name"] == "HKW-B-FLS-Boxkite"
    assert datamodel_response.json()["measurement_type"] == "lidar"
    assert datamodel_response.json()["location"] == {
        "latitude": 52.57005,
        "longitude": 3.737733,
        "elevation_m": 0.0,
    }

    config_seed_response = client.get(f"/api/sessions/{session_id}/config", headers=headers)
    assert config_seed_response.status_code == 200
    assert config_seed_response.json()["location"] == {
        "latitude": 52.57005,
        "longitude": 3.737733,
        "elevation_m": 0.0,
    }

    sensors_response = client.get(f"/api/sessions/{session_id}/sensors", headers=headers)
    assert sensors_response.status_code == 200
    assert len(sensors_response.json()["sensors"]) == 16
    assert sensors_response.json()["sensors"][0]["name"] == "Spd_250m"

    coverage_response = client.get(f"/api/sessions/{session_id}/coverage/Spd_100m", headers=headers)
    assert coverage_response.status_code == 200
    assert coverage_response.json()["valid_records"] == 65879
    assert coverage_response.json()["largest_gap_minutes"] == 314310

    statistics_response = client.get(f"/api/sessions/{session_id}/statistics/Spd_100m", headers=headers)
    assert statistics_response.status_code == 200
    assert statistics_response.json()["sensor_name"] == "Spd_100m"
    assert statistics_response.json()["count"] == 65879
    assert statistics_response.json()["coverage_pct"] == pytest.approx(89.59228635152043)

    config_response = client.put(
        f"/api/sessions/{session_id}/config",
        headers=headers,
        json={
            "updates": [
                {"key": "project_name", "value": "HKW-B-FLS-Boxkite"},
                {"key": "location.latitude", "value": 52.57005},
                {"key": "location.longitude", "value": 3.737733},
                {"key": "hub_height_m", "value": 150},
            ]
        },
    )
    assert config_response.status_code == 200
    assert config_response.json()["runconfig"]["hub_height_m"] == 150

    height_sensors = json.dumps(
        {
            "250": "Spd_250m",
            "200": "Spd_200m",
            "180": "Spd_180m",
            "160": "Spd_160m",
            "140": "Spd_140m",
            "120": "Spd_120m",
            "100": "Spd_100m",
            "80": "Spd_80m",
        }
    )
    shear_response = client.post(
        f"/api/sessions/{session_id}/shear/calculate",
        headers=headers,
        json={"height_sensors": height_sensors},
    )
    assert shear_response.status_code == 200
    assert shear_response.json()["records"] == 66066
    assert shear_response.json()["mean_shear"] == pytest.approx(0.06056611979501554)
    table_response = client.post(
        f"/api/sessions/{session_id}/shear/table",
        headers=headers,
        json={"aggregation": "momm"},
    )
    assert table_response.status_code == 200
    assert len(table_response.json()["table"]) == 12

    extrapolation_response = client.post(
        f"/api/sessions/{session_id}/extrapolation/hub",
        headers=headers,
        json={"hub_height_m": 150.0, "shear_model": "power_law"},
    )
    assert extrapolation_response.status_code == 200
    assert extrapolation_response.json()["column_name"] == "Spd_150m_hub"
    assert extrapolation_response.json()["method_counts"] == {
        "direct": 0,
        "interpolated": 65519,
        "extrapolated": 757,
    }

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
        f"/api/sessions/{session_id}/plots/timeseries_preview",
        headers=headers,
        json={},
    )
    assert plot_response.status_code == 200
    assert "plotly_json" in plot_response.json()
    assert plot_response.json()["title"] == "Data Preview — First 7 Days"

    map_response = client.get(f"/api/sessions/{session_id}/map/site", headers=headers)
    assert map_response.status_code == 200
    assert map_response.json()["type"] == "FeatureCollection"

    export_response = client.get(f"/api/sessions/{session_id}/runconfig/export", headers=headers)
    assert export_response.status_code == 200
    assert Path(export_response.json()["file_path"]).exists()
