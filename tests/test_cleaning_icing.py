"""Regression test for D17 — icing filter uses exact zero comparison.

Verifies that the icing filter now uses a configurable sd_threshold_mps
(default 0.01) instead of exact float equality with zero, so real icing
events with small-but-non-zero standard deviation are caught.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.cleaning import _apply_icing_filter


def _iced_session(
    *,
    sd_values: np.ndarray | None = None,
    temp_values: np.ndarray | None = None,
    speed_values: np.ndarray | None = None,
) -> SessionState:
    """Build a minimal session with a speed sensor, sd companion, and temperature column."""
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="10min")
    rng = np.random.default_rng(42)

    if speed_values is None:
        speed_values = rng.uniform(6, 10, n)
    if sd_values is None:
        sd_values = rng.uniform(0.05, 0.5, n)
    if temp_values is None:
        temp_values = rng.uniform(-10, 20, n)

    df = pd.DataFrame(
        {"Spd_80m": speed_values, "Spd_80m_sd": sd_values, "Temp_80m": temp_values},
        index=idx,
    )

    state = SessionState()
    state.reset()
    state.timeseries_df = df
    state.raw_timeseries_df = df.copy(deep=True)
    state.sensor_mapping = {
        80.0: {
            "speed_col": "Spd_80m",
            "dir_col": None,
            "sd_col": "Spd_80m_sd",
            "temp_col": "Temp_80m",
            "pressure_col": None,
            "humidity_col": None,
        }
    }
    return state


def test_exact_zero_is_caught() -> None:
    """Exact zero sd with cold temperature should still be flagged."""
    state = _iced_session()
    state.timeseries_df.iloc[:5, state.timeseries_df.columns.get_loc("Spd_80m_sd")] = 0.0
    state.timeseries_df.iloc[:5, state.timeseries_df.columns.get_loc("Temp_80m")] = -5.0
    mask = np.ones(len(state.timeseries_df), dtype=bool)

    n = _apply_icing_filter(state, state.timeseries_df, "Spd_80m", mask, {})
    assert n == 5


def test_near_zero_sd_is_caught() -> None:
    """A genuinely frozen cup anemometer with sd=0.005 m/s (not exactly zero) should be flagged."""
    state = _iced_session()
    state.timeseries_df.iloc[10:15, state.timeseries_df.columns.get_loc("Spd_80m_sd")] = 0.005
    state.timeseries_df.iloc[10:15, state.timeseries_df.columns.get_loc("Temp_80m")] = -3.0
    mask = np.ones(len(state.timeseries_df), dtype=bool)

    n = _apply_icing_filter(state, state.timeseries_df, "Spd_80m", mask, {})
    assert n == 5, "Near-zero sd (0.005 < 0.01 threshold) with cold temp should be flagged"


def test_above_threshold_sd_not_caught() -> None:
    """An sd of 0.02 (above default 0.01) should NOT be flagged even when cold."""
    state = _iced_session()
    state.timeseries_df.iloc[20:25, state.timeseries_df.columns.get_loc("Spd_80m_sd")] = 0.02
    state.timeseries_df.iloc[20:25, state.timeseries_df.columns.get_loc("Temp_80m")] = -3.0
    mask = np.ones(len(state.timeseries_df), dtype=bool)

    n = _apply_icing_filter(state, state.timeseries_df, "Spd_80m", mask, {})
    assert n == 0, "sd=0.02 is above the 0.01 threshold — should not be flagged"


def test_custom_sd_threshold() -> None:
    """A custom sd_threshold_mps=0.05 should catch sd=0.03 but not sd=0.06."""
    state = _iced_session()

    # sd=0.03, cold → should be caught with threshold 0.05
    state.timeseries_df.iloc[30:32, state.timeseries_df.columns.get_loc("Spd_80m_sd")] = 0.03
    state.timeseries_df.iloc[30:32, state.timeseries_df.columns.get_loc("Temp_80m")] = -2.0

    # sd=0.06, cold → should NOT be caught with threshold 0.05
    state.timeseries_df.iloc[40:42, state.timeseries_df.columns.get_loc("Spd_80m_sd")] = 0.06
    state.timeseries_df.iloc[40:42, state.timeseries_df.columns.get_loc("Temp_80m")] = -2.0

    mask = np.ones(len(state.timeseries_df), dtype=bool)
    n = _apply_icing_filter(
        state, state.timeseries_df, "Spd_80m", mask, {"sd_threshold_mps": 0.05}
    )
    assert n == 2, "Only the sd=0.03 rows (below custom threshold 0.05) should be caught"


def test_warm_temperature_not_caught() -> None:
    """Near-zero sd with warm temperature should NOT be flagged."""
    state = _iced_session()
    state.timeseries_df.iloc[50:55, state.timeseries_df.columns.get_loc("Spd_80m_sd")] = 0.005
    state.timeseries_df.iloc[50:55, state.timeseries_df.columns.get_loc("Temp_80m")] = 15.0
    mask = np.ones(len(state.timeseries_df), dtype=bool)

    n = _apply_icing_filter(state, state.timeseries_df, "Spd_80m", mask, {})
    assert n == 0, "Warm temperature should suppress the icing flag regardless of sd"
