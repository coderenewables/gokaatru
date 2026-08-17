"""Regression tests for D11 — XGBoost truncation above the campaign maximum.

Trees are piecewise-constant, so every long-term reference value above the
campaign maximum collapses onto the model's highest leaf. The defect is not that
this happens — it is inherent — but that it happened silently.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.ltc import MIN_CONCURRENT_HOURS
from server.tools.ltc_ml import TRUNCATION_WARNING_FRACTION, _run_ltc_xgboost

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("xgboost") is None, reason="xgboost not installed"
)

CAMPAIGN_MAX = 18.0


def _capped_campaign_state(long_term_hours: int = 20000, seed: int = 0) -> SessionState:
    """Campaign capped at 18 m/s, long-term period containing windier events.

    The measured series must be derived from the *same* reference values the
    model trains on — it is the concurrent overlap that becomes the training set,
    so the campaign maximum is the maximum of the reference over that window.
    """
    rng = np.random.default_rng(seed)
    campaign_n = MIN_CONCURRENT_HOURS

    long_ref = rng.weibull(2.0, long_term_hours) * 8.0
    # Concurrent window is capped: this is the campaign the model ever sees.
    long_ref[:campaign_n] = np.clip(long_ref[:campaign_n], 0.5, CAMPAIGN_MAX)
    # Guaranteed exceedances, all strictly outside the concurrent window.
    long_ref[campaign_n : campaign_n + 200] = rng.uniform(CAMPAIGN_MAX + 2.0, 32.0, 200)

    measured = 1.15 * long_ref[:campaign_n] + rng.normal(0.0, 0.4, campaign_n)
    long_index = pd.date_range("2020-01-01", periods=long_term_hours, freq="h", tz="UTC")

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_100m": measured}, index=long_index[:campaign_n])
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m_hub": long_ref}, index=long_index)
    return state


class TestTruncationDisclosure:
    """D11.1/D11.2 — the truncation must be counted and warned about."""

    def test_reports_records_above_campaign_maximum(self) -> None:
        state = _capped_campaign_state()
        metrics = _run_ltc_xgboost(state, "Spd_100m", "Spd_100m_hub")["metrics"]

        assert metrics["n_above_training_max"] > 0
        assert 0.0 < metrics["fraction_above_training_max"] <= 1.0
        assert metrics["campaign_reference_max_mps"] == pytest.approx(CAMPAIGN_MAX, abs=0.5)

    def test_warning_names_the_campaign_maximum_and_count(self) -> None:
        state = _capped_campaign_state()
        metrics = _run_ltc_xgboost(state, "Spd_100m", "Spd_100m_hub")["metrics"]

        assert metrics["fraction_above_training_max"] > TRUNCATION_WARNING_FRACTION
        warning = metrics["warning"]
        assert f"{metrics['n_above_training_max']:,}" in warning
        assert "extreme-wind estimation" in warning

    def test_predictions_are_actually_truncated(self) -> None:
        """The disclosed ceiling must match reality: nothing predicted above it."""
        state = _capped_campaign_state()
        result = _run_ltc_xgboost(state, "Spd_100m", "Spd_100m_hub")
        corrected = state.ltc_results["xgboost"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)

        ceiling = result["metrics"]["prediction_ceiling_mps"]
        assert corrected.max() == pytest.approx(ceiling)
        # A 30 m/s reference under a true 1.15x transfer would be ~34.5 m/s;
        # the tree cannot get anywhere near that.
        assert ceiling < 1.15 * CAMPAIGN_MAX + 5.0

    def test_no_hybrid_linear_branch_was_added(self) -> None:
        """DECIDED: disclose only. High references must still flatline, not extrapolate."""
        state = _capped_campaign_state()
        _run_ltc_xgboost(state, "Spd_100m", "Spd_100m_hub")
        stored = state.ltc_results["xgboost"]["df"]

        far_above = stored[stored["ERA5_original"] > CAMPAIGN_MAX + 5.0]["corrected_wind_speed"]
        assert not far_above.empty
        # All collapse onto (nearly) the same leaf value rather than tracking the reference.
        assert far_above.std() < 0.5

    def test_suitability_statement_always_present(self) -> None:
        state = _capped_campaign_state()
        metrics = _run_ltc_xgboost(state, "Spd_100m", "Spd_100m_hub")["metrics"]
        assert "extreme-wind" in metrics["extreme_wind_suitability"]


class TestNoTruncation:
    """A long-term period inside the campaign range reports zero, and no warning."""

    def test_zero_when_long_term_within_campaign_range(self) -> None:
        rng = np.random.default_rng(3)
        n = MIN_CONCURRENT_HOURS
        # The concurrent window spans 1-25 m/s; the long-term tail beyond it stays
        # strictly inside that range, so nothing is truncated.
        long_ref = np.concatenate([rng.uniform(1.0, 25.0, n), rng.uniform(1.0, 20.0, n)])
        measured = 1.1 * long_ref[:n] + rng.normal(0.0, 0.3, n)

        index = pd.date_range("2020-01-01", periods=2 * n, freq="h", tz="UTC")
        state = SessionState()
        state.reset()
        state.timeseries_df = pd.DataFrame({"Spd_100m": measured}, index=index[:n])
        state.era5_interpolated_df = pd.DataFrame({"Spd_100m_hub": long_ref}, index=index)

        metrics = _run_ltc_xgboost(state, "Spd_100m", "Spd_100m_hub")["metrics"]
        assert metrics["n_above_training_max"] == 0
        assert metrics["fraction_above_training_max"] == 0.0
        assert "warning" not in metrics
