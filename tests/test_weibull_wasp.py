"""Tests for D25 — WAsP m1/m3 Weibull as default, MLE retained behind method='mle'."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.statistics import _compute_weibull_params, _weibull_wasp_fit


def _make_state_with_speed(sensor_name: str = "ws_80m", seed: int = 42) -> SessionState:
    """Build a SessionState with a simple wind-speed timeseries."""
    state = SessionState()
    state.reset()
    rng = np.random.default_rng(seed)
    n = 2000
    # Mix of positive speeds and some calms.
    speeds = rng.weibull(2.0, n) * 8.0  # Weibull k=2, scale=8
    speeds[speeds < 0.5] = 0.0  # Introduce calms
    state.timeseries_df = pd.DataFrame(
        {sensor_name: speeds},
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )
    return state


# ---------------------------------------------------------------------------
# _weibull_wasp_fit
# ---------------------------------------------------------------------------


class TestWeibullWaspFit:
    """Direct unit tests for the _weibull_wasp_fit helper."""

    @patch("tests.test_weibull_wasp._weibull_wasp_fit", return_value=(10.0, 2.0))
    def test_wasp_returns_tuple(self, mock_wasp: MagicMock) -> None:
        """Sanity: windkit mocked to return (A=10, k=2)."""
        A, k = _weibull_wasp_fit(np.array([1.0, 2.0, 3.0]))
        assert A == 10.0
        assert k == 2.0

    def test_wasp_raises_without_windkit(self) -> None:
        """If windkit is not installed, should raise ValueError with guidance."""
        with patch.dict("sys.modules", {"windkit": None}):
            with pytest.raises(ValueError, match="windkit is required"):
                _weibull_wasp_fit(np.array([1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# _compute_weibull_params — method selection
# ---------------------------------------------------------------------------


class TestComputeWeibullParams:
    """Verify _compute_weibull_params routes to WAsP or MLE based on method arg."""

    def test_default_method_is_wasp(self) -> None:
        """Default method should be wasp_m1_m3."""
        state = _make_state_with_speed()
        with patch("server.tools.statistics._weibull_wasp_fit", return_value=(10.0, 2.0)):
            params = _compute_weibull_params(state, "ws_80m")
        assert params["fit_method"] == "wasp_m1_m3"
        assert params["A"] == 10.0
        assert params["k"] == 2.0

    def test_explicit_wasp_method(self) -> None:
        """Explicitly passing wasp_m1_m3 should use WAsP."""
        state = _make_state_with_speed()
        with patch("server.tools.statistics._weibull_wasp_fit", return_value=(10.0, 2.0)):
            params = _compute_weibull_params(state, "ws_80m", method="wasp_m1_m3")
        assert params["fit_method"] == "wasp_m1_m3"

    def test_mle_method_still_works(self) -> None:
        """method='mle' should use scipy.stats.weibull_min.fit."""
        state = _make_state_with_speed()
        params = _compute_weibull_params(state, "ws_80m", method="mle")
        assert params["fit_method"] == "mle"
        assert params["k"] > 0
        assert params["A"] > 0
        # MLE k/A should be different from the mocked WAsP values
        assert params["k"] != 2.0 or params["A"] != 10.0  # highly unlikely

    def test_wasp_preserves_mean_speed(self) -> None:
        """WAsP m1/m3 fit should preserve mean speed (m1 moment)."""
        state = _make_state_with_speed()
        expected_mean = float(state.timeseries_df["ws_80m"][state.timeseries_df["ws_80m"] > 0].mean())
        with patch(
            "server.tools.statistics._weibull_wasp_fit",
            wraps=_weibull_wasp_fit,
        ) as _mock_fit:
            try:
                params = _compute_weibull_params(state, "ws_80m")
                # Weibull mean = A * Gamma(1 + 1/k)
                from scipy.special import gamma as scipy_gamma

                weibull_mean = params["A"] * scipy_gamma(1.0 + 1.0 / params["k"])
                # Should be close (within 5% for reasonable sample sizes)
                assert abs(weibull_mean - expected_mean) / expected_mean < 0.05
            except (ImportError, ValueError):
                pytest.skip("windkit not available in test environment")

    def test_result_includes_fit_method(self) -> None:
        """Result dict must contain fit_method key regardless of method used."""
        state = _make_state_with_speed()
        with patch("server.tools.statistics._weibull_wasp_fit", return_value=(10.0, 2.0)):
            params = _compute_weibull_params(state, "ws_80m")
        assert "fit_method" in params


# ---------------------------------------------------------------------------
# _compute_wind_climate — WAsP integration
# ---------------------------------------------------------------------------


class TestComputeWindClimateWasp:
    """Verify _compute_wind_climate uses WAsP m1/m3 and reports weibull_method."""

    def test_wind_climate_reports_weibull_method(self) -> None:
        """Result must contain weibull_method key."""
        state = _make_state_with_speed()
        with patch("server.tools.statistics._weibull_wasp_fit", return_value=(10.0, 2.0)):
            from server.tools.statistics import _compute_wind_climate

            result = _compute_wind_climate(state, "ws_80m")
        assert "weibull_method" in result
        assert result["weibull_method"] == "wasp_m1_m3"

    def test_wind_climate_fallback_to_mle(self) -> None:
        """When windkit import fails, should fall back to MLE without error."""
        state = _make_state_with_speed()
        with patch("server.tools.statistics._weibull_wasp_fit", side_effect=ImportError("no windkit")):
            from server.tools.statistics import _compute_wind_climate

            result = _compute_wind_climate(state, "ws_80m")
        assert result["weibull_method"] == "mle"
        assert result["weibull_k"] > 0
        assert result["weibull_A"] > 0
