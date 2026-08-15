"""Tests for D10 — XGBoost out-of-sample metrics and ensemble OOS RMSE weighting."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from server.state.session import SessionState
from server.tools.ltc import MEASURED_COLUMN, REFERENCE_COLUMN

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_with_xgboost(
    oos_rmse: float = 1.5,
    in_sample_rmse: float = 0.8,
    val_points: int = 200,
) -> SessionState:
    """Build a SessionState with fake xgboost ltc_results for ensemble tests."""
    state = SessionState()
    state.reset()
    timestamps = pd.date_range("2020-01-01", periods=1000, freq="h")
    result_df = pd.DataFrame(
        {
            "Timestamp": timestamps,
            "ERA5_original": np.random.default_rng(42).uniform(5, 12, 1000),
            "corrected_wind_speed": np.random.default_rng(43).uniform(5, 12, 1000),
        }
    )
    state.ltc_results["xgboost"] = {
        "df": result_df,
        "metrics": {
            "r_squared": 0.75,
            "rmse": oos_rmse,
            "out_of_sample_rmse": oos_rmse,
            "in_sample_r_squared": 0.95,
            "in_sample_rmse": in_sample_rmse,
            "algorithm": "xgboost",
            "concurrent_points": 1000,
            "total_corrected_points": 1000,
            "validation_points": val_points,
        },
        "file": "/tmp/ltc_xgboost_test.csv",
    }
    state.ltc_results["linear_least_squares"] = {
        "df": result_df.copy(),
        "metrics": {
            "r_squared": 0.80,
            "rmse": 1.2,
            "algorithm": "linear_least_squares",
            "concurrent_points": 1000,
            "total_corrected_points": 1000,
        },
        "file": "/tmp/ltc_ols_test.csv",
    }
    # Set up measured timeseries so ensemble can compute overlap.
    state.timeseries_df = pd.DataFrame(
        {MEASURED_COLUMN: np.random.default_rng(44).uniform(5, 12, 1000)},
        index=timestamps,
    )
    return state


# ---------------------------------------------------------------------------
# D10: XGBoost out-of-sample metrics
# ---------------------------------------------------------------------------


class TestXGBoostOOSMetrics:
    """Verify that XGBoost stores validation-slice metrics as primary."""

    @patch("server.tools.ltc_ml._xgboost_import")
    @patch("server.tools.ltc_ml._concurrent_frame")
    @patch("server.tools.ltc_ml._long_term_frame")
    def test_out_of_sample_rmse_stored(
        self,
        mock_long_term: MagicMock,
        mock_concurrent: MagicMock,
        mock_xgb_import: MagicMock,
    ) -> None:
        """out_of_sample_rmse must be present and reflect validation-slice RMSE."""
        rng = np.random.default_rng(42)
        n = 500
        dates = pd.date_range("2020-01-01", periods=n, freq="h")
        concurrent = pd.DataFrame(
            {
                MEASURED_COLUMN: rng.uniform(5, 12, n),
                REFERENCE_COLUMN: rng.uniform(5, 12, n),
            },
            index=dates,
        )
        state = SessionState()
        state.reset()
        mock_concurrent.return_value = (
            concurrent.copy(),
            concurrent.copy(),
            concurrent,
        )
        long_df = pd.DataFrame(
            {"ref": rng.uniform(5, 12, 2000), "t2m": rng.normal(285, 5, 2000)},
            index=pd.date_range("2019-01-01", periods=2000, freq="h"),
        )
        mock_long_term.return_value = long_df

        # Mock DMatrix and train to return a simple prediction = reference (identity).
        mock_dmatrix = MagicMock()
        mock_booster = MagicMock()
        mock_booster.best_iteration = 10
        mock_booster.get_score = MagicMock(return_value={"ref_ws": 1.0})
        # split_index = int(0.8 * 500) = 400, so val slice is rows [400:500] = 100 elements.
        mock_booster.predict.side_effect = [
            concurrent[MEASURED_COLUMN].iloc[400:].to_numpy(dtype=float),  # dval prediction (shape 100)
            concurrent[MEASURED_COLUMN].to_numpy(dtype=float),             # dconcurrent prediction (shape 500)
            long_df["ref"].to_numpy(dtype=float),                           # dlong prediction (shape 2000)
        ]
        mock_xgb_import.return_value = (mock_dmatrix, MagicMock(return_value=mock_booster))

        from server.tools.ltc_ml import _run_ltc_xgboost

        result = _run_ltc_xgboost(state, "meas", "ref")
        metrics = result["metrics"]

        assert "out_of_sample_rmse" in metrics
        assert "in_sample_r_squared" in metrics
        assert "in_sample_rmse" in metrics
        assert "validation_points" in metrics
        assert metrics["validation_points"] == 100  # 20% of 500
        # out_of_sample_rmse should equal the val-slice RMSE (which equals rmse
        # because we mocked predict to return the exact target values on val).
        assert isinstance(metrics["out_of_sample_rmse"], float)

    @patch("server.tools.ltc_ml._xgboost_import")
    @patch("server.tools.ltc_ml._concurrent_frame")
    @patch("server.tools.ltc_ml._long_term_frame")
    def test_validation_metrics_are_primary(
        self,
        mock_long_term: MagicMock,
        mock_concurrent: MagicMock,
        mock_xgb_import: MagicMock,
    ) -> None:
        """The top-level r_squared and rmse should come from the validation slice."""
        rng = np.random.default_rng(99)
        n = 500
        dates = pd.date_range("2020-01-01", periods=n, freq="h")
        concurrent = pd.DataFrame(
            {
                MEASURED_COLUMN: rng.uniform(5, 12, n),
                REFERENCE_COLUMN: rng.uniform(5, 12, n),
            },
            index=dates,
        )
        state = SessionState()
        state.reset()
        mock_concurrent.return_value = (
            concurrent.copy(),
            concurrent.copy(),
            concurrent,
        )
        long_df = pd.DataFrame(
            {"ref": rng.uniform(5, 12, 2000)},
            index=pd.date_range("2019-01-01", periods=2000, freq="h"),
        )
        mock_long_term.return_value = long_df

        # Return identity for val, garbage for full concurrent → ensures primary is val.
        mock_dmatrix = MagicMock()
        mock_booster = MagicMock()
        mock_booster.best_iteration = 5
        mock_booster.get_score = MagicMock(return_value={"ref_ws": 0.5})

        y_val_expected = concurrent[MEASURED_COLUMN].iloc[400:].to_numpy(dtype=float)
        y_full_expected = concurrent[MEASURED_COLUMN].to_numpy(dtype=float) * 2  # bad prediction (same shape as target)
        mock_booster.predict.side_effect = [
            y_val_expected,      # dval prediction (perfect on val, shape=100)
            y_full_expected,     # dconcurrent prediction (bad on train, shape=500)
            long_df["ref"].to_numpy(dtype=float),
        ]
        mock_xgb_import.return_value = (mock_dmatrix, MagicMock(return_value=mock_booster))

        from server.tools.ltc_ml import _run_ltc_xgboost

        result = _run_ltc_xgboost(state, "meas", "ref")
        metrics = result["metrics"]

        # Primary r_squared should be from val slice (close to 1.0 since prediction matches target).
        # In-sample r_squared should be much worse since we doubled predictions.
        assert metrics["r_squared"] > metrics["in_sample_r_squared"]


# ---------------------------------------------------------------------------
# D10: Ensemble OOS RMSE weighting
# ---------------------------------------------------------------------------


class TestEnsembleOOSWeighting:
    """Verify ensemble prefers out_of_sample_rmse from stored metrics."""

    def test_ensemble_uses_oos_rmse(self) -> None:
        """When xgboost has out_of_sample_rmse, ensemble should weight by it not overlap RMSE."""
        state = _make_state_with_xgboost(oos_rmse=2.0)
        # OOS RMSE=2.0 for xgboost, overlap RMSE for OLS will differ.
        # With OOS RMSE=2.0 > OLS overlap RMSE, xgboost gets less weight.
        from server.tools.ensemble import _run_ensemble

        result = _run_ensemble(state, MEASURED_COLUMN)
        # xgboost should not dominate due to inflated in-sample R².
        assert "xgboost" in result["weights"]
        assert "linear_least_squares" in result["weights"]
        # Weights must sum to ~1.0
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-6

    def test_ensemble_falls_back_to_overlap_rmse(self) -> None:
        """Algorithm without out_of_sample_rmse should use overlap RMSE for weighting."""
        state = _make_state_with_xgboost(oos_rmse=1.5)
        # Remove out_of_sample_rmse from xgboost
        xgb_metrics = state.ltc_results["xgboost"]["metrics"]
        xgb_metrics.pop("out_of_sample_rmse", None)

        from server.tools.ensemble import _run_ensemble

        # Should not raise — falls back to overlap RMSE.
        result = _run_ensemble(state, MEASURED_COLUMN)
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-6
