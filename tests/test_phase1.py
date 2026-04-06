"""test_phase1 — Verification tests for GoKaatru Phase 1 foundation features.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import math

import numpy as np

from server.core.spatial import bilinear_interpolate, haversine_km, idw_interpolate
from server.state.session import session
from server.tools.config import load_run_config, save_run_config, update_run_config
from server.tools.statistics import (
    compute_diurnal_profile,
    compute_momm,
    compute_monthly_stats,
    compute_scatter_stats,
    compute_weibull_params,
)


def test_session_reset() -> None:
    """Verify SessionState.reset clears all Phase 1 singleton state fields."""
    session.project_name = "demo"
    session.hub_height_m = 120.0
    session.sensor_mapping = {
        100.0: {
            "speed_col": "Spd_100m",
            "dir_col": None,
            "sd_col": None,
            "temp_col": None,
            "pressure_col": None,
        }
    }
    session.reset()
    assert session.project_name is None
    assert session.hub_height_m is None
    assert session.timeseries_df is None
    assert session.sensor_mapping == {}
    assert session.runconfig == {}


def test_weibull_params(sample_timeseries_df) -> None:
    """Verify Weibull fitting returns positive k and A values for positive wind speeds."""
    session.timeseries_df = sample_timeseries_df.copy()
    result = compute_weibull_params("Spd_100m")
    assert result["k"] > 0
    assert result["A"] > 0


def test_diurnal_profile(sample_timeseries_df) -> None:
    """Verify the diurnal profile returns one mean value for each hour of day."""
    session.timeseries_df = sample_timeseries_df.copy()
    result = compute_diurnal_profile("Spd_100m")
    assert len(result["hours"]) == 24
    assert len(result["mean_speeds"]) == 24


def test_monthly_stats(sample_timeseries_df) -> None:
    """Verify monthly statistics contain exactly 12 month summaries."""
    session.timeseries_df = sample_timeseries_df.copy()
    result = compute_monthly_stats("Spd_100m")
    assert len(result["months"]) == 12
    assert result["months"][0]["month"] == 1


def test_momm(sample_timeseries_df) -> None:
    """Verify MoMM returns a scalar mean speed plus a 12x24 lookup table."""
    session.timeseries_df = sample_timeseries_df.copy()
    result = compute_momm("Spd_100m")
    assert isinstance(result["momm_speed"], float)
    assert len(result["table"]) == 12
    assert all(len(row) == 24 for row in result["table"])


def test_scatter_stats(sample_timeseries_df) -> None:
    """Verify scatter metrics recover an almost perfect relationship between scaled speed sensors."""
    session.timeseries_df = sample_timeseries_df.copy()
    result = compute_scatter_stats("Spd_100m", "Spd_80m")
    assert result["r2"] > 0.999999
    assert abs(result["intercept"]) < 1e-9


def test_haversine() -> None:
    """Verify haversine distance is close to the known Paris-London great-circle distance."""
    distance_km = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    assert math.isclose(distance_km, 344.0, rel_tol=0.03)


def test_idw() -> None:
    """Verify IDW returns the arithmetic mean when all points are equidistant from the target."""
    points = [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)]
    values = np.array([[1.0], [2.0], [3.0], [4.0]])
    result = idw_interpolate(points, values, (0.0, 0.0))
    assert math.isclose(float(result[0]), 2.5, rel_tol=1e-9)


def test_bilinear_interpolate() -> None:
    """Verify bilinear interpolation returns the midpoint average on a 2x2 grid cell."""
    points = [(0.0, 0.0), (0.0, 2.0), (2.0, 0.0), (2.0, 2.0)]
    values = np.array([10.0, 14.0, 18.0, 22.0])
    result = bilinear_interpolate(points, values, (1.0, 1.0))
    assert math.isclose(float(result), 16.0, rel_tol=1e-9)


def test_config_update_save_load(monkeypatch, tmp_path) -> None:
    """Verify runconfig updates persist to disk and round-trip back into session state."""
    monkeypatch.chdir(tmp_path)
    update_run_config("location.latitude", "52.4")
    update_run_config("location.longitude", "4.8")
    update_run_config("hub_height_m", "150")
    save_result = save_run_config()
    session.runconfig = {}
    session.coordinate = None
    session.hub_height_m = None
    loaded = load_run_config()
    assert save_result["status"] == "ok"
    assert loaded["location"]["latitude"] == 52.4
    assert loaded["hub_height_m"] == 150
    assert session.coordinate is not None
    assert session.coordinate.latitude == 52.4
    assert session.hub_height_m == 150.0
