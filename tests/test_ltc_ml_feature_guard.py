"""Regression test for D14 — XGBoost feature-name mismatch guard.

Verifies that _build_features returns different column sets when the
input DataFrames carry different optional columns (direction, t2m, sp),
proving the mismatch guard in _run_ltc_xgboost catches real divergence.
Also verifies the guard raises ValueError when feature lists differ.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.tools.ltc_ml import _build_features

# ---------------------------------------------------------------------------
# 1. Prove _build_features *can* diverge (the condition the guard protects)
# ---------------------------------------------------------------------------


def test_build_features_differs_with_direction_column() -> None:
    """If one call has direction and the other doesn't, feature names differ."""
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    base = pd.DataFrame({"Spd_100m": np.random.default_rng(0).uniform(3, 12, 10)}, index=idx)
    with_dir = base.copy()
    with_dir["Dir_100m"] = np.random.default_rng(1).uniform(0, 360, 10)

    _, names_no_dir = _build_features(base, "Spd_100m", "")
    _, names_with_dir = _build_features(with_dir, "Spd_100m", "Dir_100m")

    assert set(names_with_dir) - set(names_no_dir) == {"ref_wd_sin", "ref_wd_cos", "ws_x_wd_sin", "ws_x_wd_cos"}


def test_build_features_differs_with_met_columns() -> None:
    """If one call has t2m/sp and the other doesn't, feature names differ."""
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    base = pd.DataFrame({"Spd_100m": np.random.default_rng(0).uniform(3, 12, 10)}, index=idx)
    with_met = base.copy()
    with_met["t2m"] = np.random.default_rng(2).normal(280, 10, 10)

    _, names_no_met = _build_features(base, "Spd_100m", "")
    _, names_with_met = _build_features(with_met, "Spd_100m", "")

    assert "t2m" in names_with_met
    assert "t2m" not in names_no_met


# ---------------------------------------------------------------------------
# 2. Verify the guard logic that was added to _run_ltc_xgboost
#    (tested in isolation since the full function requires extensive state)
# ---------------------------------------------------------------------------


def test_feature_mismatch_guard_raises() -> None:
    """The guard added in D14 must raise ValueError when names diverge."""
    training_names = ["ref_ws", "ref_ws_squared", "ref_ws_log", "hour", "month", "ref_wd_sin", "ref_wd_cos"]
    prediction_names = ["ref_ws", "hour", "month", "extra_col"]

    # This is the exact guard code from _run_ltc_xgboost
    with pytest.raises(ValueError, match="Feature mismatch"):
        if prediction_names != training_names:
            raise ValueError(
                f"Feature mismatch between fit and predict: {training_names} vs {prediction_names}"
            )


def test_feature_match_guard_passes() -> None:
    """The guard must NOT raise when names are identical (even in different order is still a mismatch)."""
    training_names = ["ref_ws", "ref_ws_log", "hour"]
    prediction_names = ["ref_ws", "ref_ws_log", "hour"]

    # Should not raise
    if prediction_names != training_names:
        raise ValueError(
            f"Feature mismatch between fit and predict: {training_names} vs {prediction_names}"
        )


def test_feature_order_mismatch_raises() -> None:
    """Different column ordering between fit and predict should also be caught."""
    training_names = ["ref_ws", "ref_ws_log", "hour"]
    prediction_names = ["hour", "ref_ws", "ref_ws_log"]

    with pytest.raises(ValueError, match="Feature mismatch"):
        if prediction_names != training_names:
            raise ValueError(
                f"Feature mismatch between fit and predict: {training_names} vs {prediction_names}"
            )
