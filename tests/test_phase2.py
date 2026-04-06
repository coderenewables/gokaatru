"""test_phase2 — Verification tests for GoKaatru Phase 2 features.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from server.core.formulas import air_density_iec, power_law_extrapolate
from server.core.regression import robust_huber_fit, total_least_squares_fit
from server.state.session import session
from server.tools.cleaning import apply_cleaning_rule, undo_cleaning_rule
from server.tools.extrapolation import extrapolate_to_hub_height
from server.tools.shear import build_shear_table, calculate_shear_timeseries


def _load_sample_session(sample_timeseries_df: pd.DataFrame) -> None:
    """Load the synthetic sample dataset and a matching multi-height sensor mapping into session state."""
    session.timeseries_df = sample_timeseries_df.copy()
    session.raw_timeseries_df = sample_timeseries_df.copy(deep=True)
    session.sensor_mapping = {
        100.0: {
            "speed_col": "Spd_100m",
            "dir_col": "Dir_100m",
            "sd_col": "Spd_100m_sd",
            "temp_col": None,
            "pressure_col": None,
        },
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None, "temp_col": None, "pressure_col": None},
        60.0: {"speed_col": "Spd_60m", "dir_col": None, "sd_col": None, "temp_col": None, "pressure_col": None},
    }


def test_shear_timeseries_known_alpha(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify multi-height shear recovers the known alpha used in the synthetic test fixture."""
    _load_sample_session(sample_timeseries_df)
    result = calculate_shear_timeseries(json.dumps({"100": "Spd_100m", "80": "Spd_80m", "60": "Spd_60m"}))
    assert result["status"] == "ok"
    assert math.isclose(result["mean_shear"], 0.14, abs_tol=0.05)


def test_shear_table_shape(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify the Phase 2 shear table builder returns a full 12x24 lookup table with positive values."""
    _load_sample_session(sample_timeseries_df)
    calculate_shear_timeseries(json.dumps({"100": "Spd_100m", "80": "Spd_80m", "60": "Spd_60m"}))
    result = build_shear_table("momm")
    table = np.asarray(result["table"], dtype=float)
    assert table.shape == (12, 24)
    assert np.all(table > 0)


def test_extrapolate_to_hub_height(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify hub-height extrapolation creates a positive 120 m series above the 100 m mean speed."""
    _load_sample_session(sample_timeseries_df)
    calculate_shear_timeseries(json.dumps({"100": "Spd_100m", "80": "Spd_80m", "60": "Spd_60m"}))
    build_shear_table("mean")
    result = extrapolate_to_hub_height(120.0)
    assert result["status"] == "ok"
    assert "Spd_120m_hub" in session.timeseries_df.columns
    assert session.timeseries_df["Spd_120m_hub"].dropna().gt(0).all()
    assert session.timeseries_df["Spd_120m_hub"].mean() > session.timeseries_df["Spd_100m"].mean()


def test_cleaning_range_check(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify range-check cleaning removes only values outside the configured min-max bounds."""
    dirty = sample_timeseries_df.copy()
    dirty.iloc[0, dirty.columns.get_loc("Spd_100m")] = 80.0
    dirty.iloc[1, dirty.columns.get_loc("Spd_100m")] = -1.0
    _load_sample_session(dirty)
    result = apply_cleaning_rule("range_check", "Spd_100m", '{"min": 0.0, "max": 50.0}')
    remaining = session.timeseries_df["Spd_100m"].dropna()
    assert result["records_affected"] == 2
    assert remaining.between(0.0, 50.0).all()


def test_cleaning_undo(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify undo restores the raw timeseries after removing one cleaning rule from the log."""
    dirty = sample_timeseries_df.copy()
    dirty.iloc[0, dirty.columns.get_loc("Spd_100m")] = 30.0
    _load_sample_session(dirty)
    apply_cleaning_rule("range_check", "Spd_100m", '{"min": 0.0, "max": 25.0}')
    result = undo_cleaning_rule(0)
    pd.testing.assert_frame_equal(session.timeseries_df, session.raw_timeseries_df)
    assert result["remaining_rules"] == 0


def test_huber_regression() -> None:
    """Verify Huber IRLS recovers the underlying slope despite a few large outliers."""
    x_values = np.arange(40, dtype=float)
    y_values = 2.0 * x_values + 1.0
    y_values[[5, 10, 15]] += np.array([50.0, -60.0, 40.0])
    slope, intercept, _, _ = robust_huber_fit(x_values, y_values)
    assert math.isclose(slope, 2.0, abs_tol=0.2)
    assert math.isclose(intercept, 1.0, abs_tol=2.0)


def test_tls_fit() -> None:
    """Verify TLS stays close to the true slope when both x and y contain noise."""
    np.random.seed(7)
    true_x = np.linspace(0.0, 10.0, 200)
    observed_x = true_x + np.random.normal(0.0, 0.2, size=true_x.size)
    observed_y = 3.0 * true_x + 2.0 + np.random.normal(0.0, 0.2, size=true_x.size)
    slope, intercept = total_least_squares_fit(observed_x, observed_y)
    assert math.isclose(slope, 3.0, abs_tol=0.2)
    assert math.isclose(intercept, 2.0, abs_tol=0.5)


def test_power_law_formula() -> None:
    """Verify the power-law extrapolation helper matches the IEC analytical expression exactly."""
    expected = 10.0 * (100.0 / 80.0) ** 0.14
    assert math.isclose(power_law_extrapolate(10.0, 80.0, 100.0, 0.14), expected, rel_tol=1e-12)


def test_air_density() -> None:
    """Verify the IEC air-density helper reproduces standard-atmosphere density within tolerance."""
    density = air_density_iec(101325.0, 288.15, 275.0)
    assert math.isclose(density, 1.225, abs_tol=0.01)
