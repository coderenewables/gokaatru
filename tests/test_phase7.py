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
)


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
        "measurement_point": [
            {"name": "Spd_100m", "height_m": 100, "measurement_type_id": "wind_speed"},
            {"name": "Dir_100m", "height_m": 100, "measurement_type_id": "wind_direction"},
            {"name": "Spd_80m", "height_m": 80, "measurement_type_id": "wind_speed"},
            {"name": "Spd_60m", "height_m": 60, "measurement_type_id": "wind_speed"},
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