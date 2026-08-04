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
    assert "Spd_250m" in {sensor["name"] for sensor in sensors_response.json()["sensors"]}

    coverage_response = client.get(f"/api/sessions/{session_id}/coverage/Spd_100m", headers=headers)
    assert coverage_response.status_code == 200
    assert coverage_response.json()["valid_records"] == 65879
    assert coverage_response.json()["largest_gap_minutes"] == 314310

    statistics_response = client.get(f"/api/sessions/{session_id}/statistics/Spd_100m", headers=headers)
    assert statistics_response.status_code == 200
    assert statistics_response.json()["sensor_name"] == "Spd_100m"
    assert statistics_response.json()["count"] == 65879
    assert statistics_response.json()["coverage_pct"] == pytest.approx(89.59228635152043)

    wind_climate_response = client.get(
        f"/api/sessions/{session_id}/wind-climate/Spd_100m?direction_sensor=Dir_100m",
        headers=headers,
    )
    assert wind_climate_response.status_code == 200
    wind_climate = wind_climate_response.json()
    assert wind_climate["weibull_k"] > 0
    assert wind_climate["direction"]["prevailing_sector"]
    assert len(wind_climate["sectors"]) == 16

    distribution_response = client.post(
        f"/api/sessions/{session_id}/plots/speed_distribution",
        headers=headers,
        json={"sensor_name": "Spd_100m"},
    )
    assert distribution_response.status_code == 200
    assert json.loads(distribution_response.json()["plotly_json"])["data"]

    vertical_structure_response = client.get(
        f"/api/sessions/{session_id}/vertical-structure?speed_sensors=Spd_80m,Spd_100m,Spd_120m&direction_sensors=Dir_80m,Dir_100m,Dir_120m",
        headers=headers,
    )
    assert vertical_structure_response.status_code == 200
    assert vertical_structure_response.json()["alpha"]["record_count"] > 0
    assert vertical_structure_response.json()["veer"] is not None

    alpha_plot_response = client.post(
        f"/api/sessions/{session_id}/plots/shear_alpha",
        headers=headers,
        json={"sensor_names": "Spd_80m,Spd_100m,Spd_120m"},
    )
    assert alpha_plot_response.status_code == 200
    assert json.loads(alpha_plot_response.json()["plotly_json"])["data"]

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


def test_api_atmosphere_workflow(
    uploaded_timeseries_path: Path,
    api_client: tuple[TestClient, SessionManager],
) -> None:
    """Verify P4 atmospheric analysis and density plotting through the browser-facing session API."""
    client, manager = api_client
    uploads_dir = uploaded_timeseries_path.parent
    timeseries_path = uploads_dir / "HornsRev-MAST_timeseries_data.csv"
    datamodel_path = uploads_dir / "HornsRev-MAST_data_model.json"
    create_response = client.post("/api/sessions")
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    for kind, path, content_type in [
        ("timeseries", timeseries_path, "text/csv"),
        ("datamodel", datamodel_path, "application/json"),
    ]:
        response = client.post(
            f"/api/sessions/{session_id}/uploads/{kind}",
            headers=headers,
            files={"file": (path.name, _upload_bytes(path), content_type)},
        )
        assert response.status_code == 200

    atmosphere_response = client.get(
        f"/api/sessions/{session_id}/atmosphere?temperature_sensor=Tmp2_55m&pressure_sensor=Prs_55m&humidity_sensor=Hum_13m",
        headers=headers,
    )
    assert atmosphere_response.status_code == 200
    assert 0.9 < atmosphere_response.json()["air_density"]["mean"] < 1.4

    density_plot_response = client.post(
        f"/api/sessions/{session_id}/plots/air_density",
        headers=headers,
        json={"sensor_a": "Tmp2_55m", "sensor_b": "Prs_55m", "sensor_name": "Hum_13m"},
    )
    assert density_plot_response.status_code == 200
    assert json.loads(density_plot_response.json()["plotly_json"])["data"]

    energy_response = client.get(
        f"/api/sessions/{session_id}/energy/Spd_58m?direction_sensor=Dir_58m",
        headers=headers,
    )
    assert energy_response.status_code == 200
    assert energy_response.json()["wind_power_density_w_m2"] > 0

    extremes_response = client.get(f"/api/sessions/{session_id}/extremes/Spd_58m", headers=headers)
    assert extremes_response.status_code == 200
    assert extremes_response.json()["screening_only"] is True

    ramps_response = client.get(f"/api/sessions/{session_id}/ramps/Spd_58m", headers=headers)
    assert ramps_response.status_code == 200
    assert ramps_response.json()["record_count"] > 0

    persistence_response = client.get(f"/api/sessions/{session_id}/persistence/Spd_58m", headers=headers)
    assert persistence_response.status_code == 200
    assert persistence_response.json()["calm_period_count"] > 0

    power_density_plot_response = client.post(
        f"/api/sessions/{session_id}/plots/power_density",
        headers=headers,
        json={"speed_sensor": "Spd_58m", "direction_sensor": "Dir_58m"},
    )
    assert power_density_plot_response.status_code == 200
    assert json.loads(power_density_plot_response.json()["plotly_json"])["data"]

    comparison_response = client.get(f"/api/sessions/{session_id}/comparison", headers=headers)
    assert comparison_response.status_code == 200
    comparison = comparison_response.json()
    assert comparison["record_count"] > 0

    mast_effects_response = client.get(
        f"/api/sessions/{session_id}/mast-effects?direction_sensor=Dir_43m",
        headers=headers,
    )
    assert mast_effects_response.status_code == 200
    assert len(mast_effects_response.json()["sectors"]) == 16

    qc_response = client.get(f"/api/sessions/{session_id}/qc-diagnostics", headers=headers)
    assert qc_response.status_code == 200
    assert len(qc_response.json()["sensors"]) == 8

    state = manager.get_session(session_id)
    hourly = state.timeseries_df[["Spd_58m"]].resample("h").mean().dropna().iloc[:1000]
    state.era5_interpolated_df = pd.DataFrame(
        {"Spd_100m": hourly["Spd_58m"].to_numpy(dtype=float) * 0.96 + 0.35},
        index=hourly.index,
    )
    mcp_response = client.get(f"/api/sessions/{session_id}/mcp-readiness/Spd_58m", headers=headers)
    assert mcp_response.status_code == 200
    assert mcp_response.json()["r_squared"] > 0.99

    mcp_plot_response = client.post(
        f"/api/sessions/{session_id}/plots/mcp_readiness",
        headers=headers,
        json={"speed_sensor": "Spd_58m"},
    )
    assert mcp_plot_response.status_code == 200
    assert json.loads(mcp_plot_response.json()["plotly_json"])["data"]

    summary_response = client.get(
        f"/api/sessions/{session_id}/overview-summary?speed_sensor=Spd_58m&direction_sensor=Dir_58m",
        headers=headers,
    )
    assert summary_response.status_code == 200
    assert summary_response.json()["speed_sensor"] == "Spd_58m"
    assert summary_response.json()["items"]
