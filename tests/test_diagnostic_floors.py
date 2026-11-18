"""P0-3: the readiness diagnostic must use the correction's own floor."""

from __future__ import annotations

import numpy as np
import pandas as pd

from server.state.session import SessionState
from server.tools import diagnostics
from server.tools.diagnostics import _compute_mcp_readiness
from server.tools.ltc import MIN_CONCURRENT_HOURS


def _readiness_session(hours: int) -> SessionState:
    """Hourly measured series and a near-perfectly correlated reference of the given length."""
    rng = np.random.default_rng(7)
    index = pd.date_range("2023-01-01", periods=hours, freq="h")
    speed = 7.0 + 2.0 * np.sin(np.arange(hours) / 37.0) + rng.normal(0.0, 0.3, hours)
    state = SessionState()
    state.timeseries_df = pd.DataFrame({"Spd_80m": speed}, index=index)
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m": speed * 0.96 + 0.35}, index=index)
    return state


def test_readiness_refuses_what_the_correction_would_refuse() -> None:
    hours = MIN_CONCURRENT_HOURS - 1
    assert hours >= 720
    result = _compute_mcp_readiness(_readiness_session(hours), "Spd_80m")

    assert result["r_squared"] > 0.9
    assert result["ready"] is False
    assert result["min_concurrent_hours"] == MIN_CONCURRENT_HOURS
    assert result["min_r_squared"] == diagnostics.READINESS_MIN_R_SQUARED
    assert len(result["not_ready_reasons"]) == 1
    assert str(hours) in result["not_ready_reasons"][0]
    assert str(MIN_CONCURRENT_HOURS) in result["not_ready_reasons"][0]


def test_readiness_passes_at_the_correction_floor() -> None:
    result = _compute_mcp_readiness(_readiness_session(MIN_CONCURRENT_HOURS), "Spd_80m")

    assert result["ready"] is True
    assert result["not_ready_reasons"] == []
    assert result["min_concurrent_hours"] == MIN_CONCURRENT_HOURS


def test_readiness_reports_a_low_r_squared_reason() -> None:
    state = _readiness_session(MIN_CONCURRENT_HOURS)
    rng = np.random.default_rng(1)
    state.era5_interpolated_df = pd.DataFrame(
        {"Spd_100m": rng.normal(7.0, 2.0, MIN_CONCURRENT_HOURS)}, index=state.timeseries_df.index
    )
    result = _compute_mcp_readiness(state, "Spd_80m")

    assert result["ready"] is False
    assert len(result["not_ready_reasons"]) == 1
    assert "R-squared" in result["not_ready_reasons"][0]
