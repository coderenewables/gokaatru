"""test_phase7 — Verification tests for GoKaatru Phase 7 data explorer features.

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
from server.state.session import session
from server.tools.cleaning import _apply_cleaning_rule
from server.tools.visualization import (
    _plot_cleaning_overlay,
    _plot_coverage_timeline,
    _plot_shear_profile,
    _plot_timeseries_preview,
    _plot_turbulence_intensity,
    _plot_turbulence_windrose,
)
from server.tools.data_io import _list_sensors, _parse_datamodel, _parse_timeseries


@pytest.fixture
def api_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client backed by a temporary per-test session registry."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _set_sensor_mapping() -> None:
    """Seed a representative speed and direction sensor mapping for Phase 7 plot helpers."""
    session.sensor_mapping = {
        100.0: {
            "speed_col": "Spd_100m",
            "dir_col": "Dir_100m",
            "sd_col": "Spd_100m_sd",
            "temp_col": None,
            "pressure_col": None,
        },
        80.0: {
            "speed_col": "Spd_80m",
            "dir_col": None,
            "sd_col": None,
            "temp_col": None,
            "pressure_col": None,
        },
        60.0: {
            "speed_col": "Spd_60m",
            "dir_col": None,
            "sd_col": None,
            "temp_col": None,
            "pressure_col": None,
        },
    }


def _timeseries_upload_bytes(sample_timeseries_df: pd.DataFrame) -> bytes:
    """Serialize the sample dataset into a CSV payload with an explicit Timestamp column."""
    payload = sample_timeseries_df.reset_index().rename(columns={"index": "Timestamp"})
    return payload.to_csv(index=False).encode("utf-8")


def _datamodel_bytes() -> bytes:
    """Build a minimal datamodel JSON payload compatible with the browser upload flow."""
    payload = {
        "measurement_location": [
            {
                "name": "TestSite",
                "latitude_ddeg": 10.0,
                "longitude_ddeg": 20.0,
                "logger_main_config": [{"offset_from_utc_hrs": 0}],
                "measurement_point": [
                    {"name": "Spd_100m", "height_m": 100, "measurement_type_id": "wind_speed"},
                    {"name": "Dir_100m", "height_m": 100, "measurement_type_id": "wind_direction"},
                    {"name": "Spd_80m", "height_m": 80, "measurement_type_id": "wind_speed"},
                    {"name": "Spd_60m", "height_m": 60, "measurement_type_id": "wind_speed"},
                ],
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


def test_plot_timeseries_preview_returns_plotly_json(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify the new data-preview helper returns Plotly JSON with at least one rendered trace."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy()
    _set_sensor_mapping()

    result = _plot_timeseries_preview(session)
    parsed = json.loads(result["plotly_json"])

    assert result["title"] == "Data Preview — First 7 Days"
    assert len(parsed["data"]) >= 1


def test_plot_cleaning_overlay_shows_removed(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify the cleaning overlay includes both cleaned data and removed-point traces after filtering."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy(deep=True)
    _set_sensor_mapping()
    _apply_cleaning_rule(session, "range_check", "Spd_100m", json.dumps({"min": 0.0, "max": 6.0}), "", "")

    result = _plot_cleaning_overlay(session, "Spd_100m")
    parsed = json.loads(result["plotly_json"])

    assert len(parsed["data"]) == 2
    assert {trace["name"] for trace in parsed["data"]} == {"Cleaned", "Removed"}


def test_plot_coverage_timeline_dimensions(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify the coverage timeline heatmap rows match the number of mapped sensors included in the plot."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy()
    _set_sensor_mapping()

    result = _plot_coverage_timeline(session)
    parsed = json.loads(result["plotly_json"])

    assert len(parsed["data"][0]["y"]) == 4


def test_plot_turbulence_intensity_bins(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify turbulence plotting returns sample, mean, representative, and IEC class traces."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy()
    _set_sensor_mapping()

    result = _plot_turbulence_intensity(session, "Spd_100m", "Spd_100m_sd")
    parsed = json.loads(result["plotly_json"])
    names = {trace["name"] for trace in parsed["data"]}

    assert {"Samples", "Mean TI", "Representative TI"}.issubset(names)
    assert len(parsed["data"]) >= 6
    iec_a = next(trace for trace in parsed["data"] if trace["name"] == "IEC Class A")
    assert iec_a["y"][0] > iec_a["y"][-1]


def test_plot_turbulence_windrose_uses_directional_ti(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify the turbulence rose summarizes TI by the corresponding wind direction."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy()
    _set_sensor_mapping()

    result = _plot_turbulence_windrose(session, "Spd_100m", "Spd_100m_sd", "Dir_100m")
    parsed = json.loads(result["plotly_json"])

    assert result["title"] == "Turbulence Wind Rose — Spd_100m by Dir_100m"
    assert {trace["name"] for trace in parsed["data"]} == {"Mean TI", "P90 TI"}
    assert len(parsed["data"][0]["r"]) == 16


def test_plot_shear_profile_annotation(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify the shear profile plot annotates the fitted shear exponent alpha."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy()
    _set_sensor_mapping()

    result = _plot_shear_profile(session)
    parsed = json.loads(result["plotly_json"])
    annotations = parsed["layout"].get("annotations", [])

    assert any("α =" in annotation["text"] for annotation in annotations)


def test_sensor_statistics_endpoint(
    sample_timeseries_df: pd.DataFrame,
    api_client: tuple[TestClient, SessionManager],
) -> None:
    """Verify the browser API exposes the Phase 7 per-sensor statistics payload after upload."""
    client, _manager = api_client

    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
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

    response = client.get(f"/api/sessions/{session_id}/statistics/Spd_100m", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["sensor_name"] == "Spd_100m"
    assert len(payload["monthly_means"]) == 12
    assert len(payload["diurnal_means"]) == 24
    assert set(payload["percentiles"]) == {"p10", "p25", "p50", "p75", "p90", "p99"}


def test_sensor_statistics_endpoint_supports_temperature_and_pressure(
    sample_timeseries_df: pd.DataFrame,
    api_client: tuple[TestClient, SessionManager],
) -> None:
    """Verify non-speed sensors retain descriptive and diurnal statistics without Weibull fitting."""
    client, _manager = api_client
    frame = sample_timeseries_df.copy()
    frame["Temp_100m"] = [-5.0 + (index % 24) * 0.5 for index in range(len(frame))]
    frame["Pressure_100m"] = 1000.0 + (pd.Series(range(len(frame)), index=frame.index) % 12).to_numpy()

    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    datamodel = {
        "measurement_location": [
            {
                "name": "TestSite",
                "latitude_ddeg": 10.0,
                "longitude_ddeg": 20.0,
                "logger_main_config": [{"offset_from_utc_hrs": 0}],
                "measurement_point": [
                    {"name": "Spd_100m", "height_m": 100, "measurement_type_id": "wind_speed"},
                    {"name": "Temp_100m", "height_m": 100, "measurement_type_id": "temperature"},
                    {"name": "Pressure_100m", "height_m": 100, "measurement_type_id": "pressure"},
                ],
            }
        ]
    }
    client.post(
        f"/api/sessions/{session_id}/uploads/timeseries",
        headers=headers,
        files={"file": ("timeseries.csv", _timeseries_upload_bytes(frame), "text/csv")},
    )
    client.post(
        f"/api/sessions/{session_id}/uploads/datamodel",
        headers=headers,
        files={"file": ("datamodel.json", json.dumps(datamodel).encode("utf-8"), "application/json")},
    )

    for sensor_name in ("Temp_100m", "Pressure_100m"):
        response = client.get(f"/api/sessions/{session_id}/statistics/{sensor_name}", headers=headers)

        assert response.status_code == 200
        payload = response.json()
        assert payload["weibull_k"] is None
        assert payload["weibull_A"] is None
        assert len(payload["diurnal_means"]) == 24


def test_sensor_inventory_includes_all_datamodel_backed_uploaded_sensors(tmp_path: Path) -> None:
    """Verify inventory retains auxiliary sensor types and sensors below ground level."""
    uploads = (Path(session.get_data_dir()) / "uploads").resolve()
    uploads.mkdir(parents=True, exist_ok=True)
    timeseries_path = uploads / "timeseries.csv"
    datamodel_path = uploads / "datamodel.json"
    pd.DataFrame(
        {
            "Timestamp": pd.date_range("2024-01-01", periods=3, freq="10min"),
            "Spd_60m": [5.0, 6.0, 7.0],
            "Tmp_55m": [10.0, 11.0, 12.0],
            "Prs_55m": [1010.0, 1011.0, 1012.0],
            "Hum_13m": [70.0, 71.0, 72.0],
            "Wtr_tmp_-4m": [8.0, 8.1, 8.2],
            "Qual_Spd_60m": [1, 1, 1],
        }
    ).to_csv(timeseries_path, index=False)
    datamodel_path.write_text(
        json.dumps(
            {
                "measurement_location": [
                    {
                        "name": "TestSite",
                        "latitude_ddeg": 10.0,
                        "longitude_ddeg": 20.0,
                        "logger_main_config": [{"offset_from_utc_hrs": 0}],
                        "measurement_point": [
                            {"name": "Spd_60m", "height_m": 60, "measurement_type_id": "wind_speed"},
                            {"name": "Tmp_55m", "height_m": 55, "measurement_type_id": "air_temperature"},
                            {"name": "Prs_55m", "height_m": 55, "measurement_type_id": "air_pressure"},
                            {"name": "Hum_13m", "height_m": 13, "measurement_type_id": "relative_humidity"},
                            {"name": "Wtr_tmp_-4m", "height_m": -4, "measurement_type_id": "water_temperature"},
                            {"name": "Qual_Spd_60m", "height_m": 60, "measurement_type_id": "quality"},
                            {"name": "Missing", "height_m": 20, "measurement_type_id": "air_pressure"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _parse_timeseries(session, str(timeseries_path))
    _parse_datamodel(session, str(datamodel_path))
    inventory = _list_sensors(session)["sensors"]

    assert [sensor["name"] for sensor in inventory] == [
        "Qual_Spd_60m",
        "Spd_60m",
        "Prs_55m",
        "Tmp_55m",
        "Hum_13m",
        "Wtr_tmp_-4m",
    ]
    sensor_types = {sensor["name"]: sensor["sensor_type"] for sensor in inventory}
    assert sensor_types["Tmp_55m"] == "temperature"
    assert sensor_types["Prs_55m"] == "pressure"
    assert sensor_types["Hum_13m"] == "humidity"
    assert inventory[-1]["height_m"] == -4.0
    assert inventory[-1]["sensor_type"] == "water_temperature"