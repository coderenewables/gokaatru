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


def test_readiness_works_when_the_mast_and_the_reference_share_a_column_name() -> None:
    """A 100 m mast speed is often named Spd_100m, as ERA5's is. The join refused the
    overlapping name and the diagnostic raised a raw pandas error (found by P1-7)."""
    renamed = _readiness_session(MIN_CONCURRENT_HOURS)
    same_name = _readiness_session(MIN_CONCURRENT_HOURS)
    same_name.timeseries_df = same_name.timeseries_df.rename(columns={"Spd_80m": "Spd_100m"})

    expected = _compute_mcp_readiness(renamed, "Spd_80m")
    result = _compute_mcp_readiness(same_name, "Spd_100m")

    assert {key: value for key, value in result.items() if key != "speed_sensor"} == {
        key: value for key, value in expected.items() if key != "speed_sensor"
    }
    assert result["speed_sensor"] == "Spd_100m"


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
