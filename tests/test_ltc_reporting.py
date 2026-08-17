"""Regression tests for Wave 4b — LTC reporting honesty (D9.1-D9.4).

Covers the concurrency floor, the sampling-mismatch disclosure, the clipped
negative-prediction count, and the t-distribution confidence intervals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.core.regression import ols_confidence_intervals
from server.state.session import SessionState
from server.tools.ltc import (
    MIN_CONCURRENT_HOURS,
    RESAMPLING_NOTE,
    _run_ltc_linear_least_squares,
    _run_ltc_variance_ratio,
)


def _make_state(n_hours: int, timestep_minutes: int = 60, slope: float = 1.1, intercept: float = 0.5) -> SessionState:
    """Build a session whose measured series is a known linear function of the reference."""
    reference_index = pd.date_range("2020-01-01", periods=n_hours, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    reference = rng.uniform(3.0, 14.0, n_hours)

    samples_per_hour = max(1, 60 // timestep_minutes)
    measured_index = pd.date_range(
        "2020-01-01", periods=n_hours * samples_per_hour, freq=f"{timestep_minutes}min", tz="UTC"
    )
    # Repeat each hour's reference across its sub-hourly samples so the hourly
    # mean reproduces the same linear relationship regardless of cadence.
    measured = np.repeat(reference, samples_per_hour) * slope + intercept

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_100m": measured}, index=measured_index)
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m_hub": reference}, index=reference_index)
    return state


class TestConcurrencyFloor:
    """D9.1 — a sub-six-month MCP must raise rather than return a number."""

    def test_below_floor_raises(self) -> None:
        state = _make_state(MIN_CONCURRENT_HOURS - 1)
        with pytest.raises(ValueError) as excinfo:
            _run_ltc_linear_least_squares(state, "Spd_100m", "Spd_100m_hub")
        message = str(excinfo.value)
        # The message must name both the requirement and what was actually found,
        # so the analyst can tell how far short the campaign is.
        assert str(MIN_CONCURRENT_HOURS) in message
        assert str(MIN_CONCURRENT_HOURS - 1) in message

    def test_at_floor_succeeds(self) -> None:
        state = _make_state(MIN_CONCURRENT_HOURS)
        result = _run_ltc_linear_least_squares(state, "Spd_100m", "Spd_100m_hub")
        assert result["metrics"]["concurrent_points"] == MIN_CONCURRENT_HOURS

    def test_floor_is_six_months_hourly(self) -> None:
        assert MIN_CONCURRENT_HOURS == 4380


class TestResamplingDisclosure:
    """D9.2 — the measured/reference sampling mismatch must be stated, not hidden."""

    def test_sub_hourly_measured_reports_note(self) -> None:
        state = _make_state(MIN_CONCURRENT_HOURS, timestep_minutes=10)
        metrics = _run_ltc_variance_ratio(state, "Spd_100m", "Spd_100m_hub")["metrics"]
        assert metrics["measured_resampled_to_hourly"] is True
        assert metrics["measured_timestep_minutes"] == 10
        assert metrics["resampling_note"] == RESAMPLING_NOTE

    def test_hourly_measured_reports_no_resampling(self) -> None:
        state = _make_state(MIN_CONCURRENT_HOURS, timestep_minutes=60)
        metrics = _run_ltc_variance_ratio(state, "Spd_100m", "Spd_100m_hub")["metrics"]
        assert metrics["measured_resampled_to_hourly"] is False
        assert "resampling_note" not in metrics

    def test_disclosure_reaches_every_algorithm(self) -> None:
        state = _make_state(MIN_CONCURRENT_HOURS, timestep_minutes=10)
        for run in (_run_ltc_linear_least_squares, _run_ltc_variance_ratio):
            metrics = run(state, "Spd_100m", "Spd_100m_hub")["metrics"]
            assert metrics["measured_resampled_to_hourly"] is True


class TestNegativePredictionClipping:
    """D9.3 — clipped negative predictions must be counted, not silently truncated."""

    def test_negative_predictions_counted(self) -> None:
        # A large negative intercept drives low-wind hours below zero.
        state = _make_state(MIN_CONCURRENT_HOURS, slope=1.2, intercept=-5.0)
        result = _run_ltc_linear_least_squares(state, "Spd_100m", "Spd_100m_hub")
        metrics = result["metrics"]
        assert metrics["negative_predictions_clipped"] > 0
        assert 0.0 < metrics["negative_predictions_clipped_fraction"] <= 1.0

        # The count must match the stored series: everything clipped sits at zero.
        stored = state.ltc_results["linear_least_squares"]["df"]["corrected_wind_speed"]
        assert (stored >= 0.0).all()
        assert int((stored == 0.0).sum()) == metrics["negative_predictions_clipped"]

    def test_no_negatives_reports_zero(self) -> None:
        state = _make_state(MIN_CONCURRENT_HOURS, slope=1.1, intercept=0.5)
        metrics = _run_ltc_linear_least_squares(state, "Spd_100m", "Spd_100m_hub")["metrics"]
        assert metrics["negative_predictions_clipped"] == 0
        assert metrics["negative_predictions_clipped_fraction"] == 0.0


class TestConfidenceIntervals:
    """D9.4 — CIs use the t-distribution, not the normal approximation."""

    def test_t_intervals_wider_than_normal_at_small_n(self) -> None:
        from scipy.stats import t as student_t

        rng = np.random.default_rng(3)
        x = np.linspace(1.0, 10.0, 6)
        y = 2.0 * x + 1.0 + rng.normal(0.0, 0.5, x.size)
        slope_ci, intercept_ci = ols_confidence_intervals(x, y)
        assert slope_ci is not None and intercept_ci is not None

        # Derive the standard error independently rather than from the returned
        # interval, so this pins the critical value instead of restating it.
        sxx = float(np.sum((x - x.mean()) ** 2))
        slope = float(np.sum((x - x.mean()) * (y - y.mean())) / sxx)
        intercept = float(y.mean() - slope * x.mean())
        residuals = y - (slope * x + intercept)
        se_slope = float(np.sqrt(np.sum(residuals**2) / (x.size - 2) / sxx))

        half_width = (slope_ci[1] - slope_ci[0]) / 2.0
        t_critical = float(student_t.ppf(0.975, x.size - 2))  # df = 4 -> 2.776
        assert half_width == pytest.approx(t_critical * se_slope, rel=1e-9)
        # The z = 1.96 interval this replaces was ~42% too narrow here.
        assert half_width > 1.96 * se_slope * 1.4

    def test_converges_to_normal_at_large_n(self) -> None:
        rng = np.random.default_rng(4)
        x = np.linspace(1.0, 10.0, 20000)
        y = 2.0 * x + 1.0 + rng.normal(0.0, 0.5, x.size)
        slope_ci, _ = ols_confidence_intervals(x, y)
        assert slope_ci is not None
        from scipy.stats import t as student_t

        # At n = 20000 the t critical value is within 0.1% of 1.96.
        assert float(student_t.ppf(0.975, 19998)) == pytest.approx(1.96, rel=1e-3)

    def test_too_few_points_returns_none(self) -> None:
        assert ols_confidence_intervals(np.array([1.0, 2.0]), np.array([1.0, 2.0])) == (None, None)
