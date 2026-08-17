"""Regression tests for D5 — clipping must not treat partial years as whole years.

A series starting mid-November must exclude that year, and the gated IAV must
differ materially from the ungated one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.clipping import (
    CLIMATE_FLOOR,
    CLIMATE_MAX,
    CLIMATE_SCALE,
    DEFAULT_MIN_YEAR_COMPLETENESS,
    REFERENCE_WINDOW_YEARS,
    _run_clipping_analysis,
)


def _seasonal_series(start: str, end: str, seed: int = 0) -> pd.Series:
    """Hourly wind speed with a strong winter peak, so a partial winter year reads high."""
    index = pd.date_range(start, end, freq="h", tz="UTC")
    rng = np.random.default_rng(seed)
    # Seasonal cycle peaking in January: day-of-year 1 is the maximum.
    seasonal = 3.0 * np.cos(2.0 * np.pi * (index.dayofyear - 1) / 365.25)
    return pd.Series(8.0 + seasonal + rng.normal(0.0, 0.5, len(index)), index=index)


def _state_with_series(series: pd.Series) -> SessionState:
    """Store the series as an LTC result so clipping can consume it."""
    state = SessionState()
    state.reset()
    state.ltc_results["linear_least_squares"] = {
        "df": pd.DataFrame({"Timestamp": series.index, "corrected_wind_speed": series.to_numpy()}),
        "metrics": {},
    }
    return state


class TestPartialYearExclusion:
    """D5 — the first and last calendar years are almost always partial."""

    def test_mid_november_start_year_is_excluded(self) -> None:
        # Starts 15 Nov 2008: that year holds ~6.5 weeks of pure winter.
        series = _seasonal_series("2008-11-15", "2020-12-31 23:00")
        state = _state_with_series(series)
        result = _run_clipping_analysis(state, "corrected_wind_speed", source="linear_least_squares")

        assert 2008 in result["years_excluded"]
        assert 2008 not in result["years_used"]
        assert result["excluded_reason"]
        detail = {entry["year"]: entry for entry in result["excluded_detail"]}
        assert detail[2008]["completeness"] < DEFAULT_MIN_YEAR_COMPLETENESS

    def test_complete_years_are_kept(self) -> None:
        series = _seasonal_series("2008-11-15", "2020-12-31 23:00")
        state = _state_with_series(series)
        result = _run_clipping_analysis(state, "corrected_wind_speed", source="linear_least_squares")

        assert result["years_used"] == list(range(2009, 2021))
        assert result["min_year_completeness"] == DEFAULT_MIN_YEAR_COMPLETENESS

    def test_gated_iav_differs_materially_from_ungated(self) -> None:
        series = _seasonal_series("2008-11-15", "2020-12-31 23:00")
        state = _state_with_series(series)

        gated = _run_clipping_analysis(state, "corrected_wind_speed", source="linear_least_squares")
        # completeness = 0 admits every partial year, reproducing the old behaviour.
        ungated = _run_clipping_analysis(
            state, "corrected_wind_speed", source="linear_least_squares", min_year_completeness=0.0
        )

        assert 2008 in ungated["years_used"]
        # The winter-only pseudo-year is a high outlier, so ungated IAV is inflated.
        assert ungated["iav"] > gated["iav"] * 2.0

    def test_full_years_produce_no_exclusions(self) -> None:
        series = _seasonal_series("2009-01-01", "2020-12-31 23:00")
        state = _state_with_series(series)
        result = _run_clipping_analysis(state, "corrected_wind_speed", source="linear_least_squares")

        assert result["years_excluded"] == []
        assert result["excluded_reason"] == ""

    def test_too_few_complete_years_raises_with_context(self) -> None:
        series = _seasonal_series("2016-01-01", "2020-06-30 23:00")
        state = _state_with_series(series)
        with pytest.raises(ValueError) as excinfo:
            _run_clipping_analysis(state, "corrected_wind_speed", source="linear_least_squares")
        # The message must say how many were excluded as partial, not just the shortfall.
        assert "excluded as partial" in str(excinfo.value)

    def test_completeness_threshold_validated(self) -> None:
        series = _seasonal_series("2009-01-01", "2020-12-31 23:00")
        state = _state_with_series(series)
        with pytest.raises(ValueError, match="between 0 and 1"):
            _run_clipping_analysis(
                state, "corrected_wind_speed", source="linear_least_squares", min_year_completeness=1.5
            )


class TestNamedConstants:
    """D5 also asks that the magic constants be named and documented."""

    def test_constants_hold_the_documented_values(self) -> None:
        assert CLIMATE_MAX == 0.04
        assert CLIMATE_FLOOR == 0.005
        assert CLIMATE_SCALE == 0.01
        assert REFERENCE_WINDOW_YEARS == 5
        assert DEFAULT_MIN_YEAR_COMPLETENESS == 0.9
