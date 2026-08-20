"""ltc_ml — Phase 3 MCP tool for XGBoost long-term correction.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from server.core.validators import to_utc_index
from server.main import mcp
from server.state.session import SessionState, session
from server.tools.ltc import (
    MEASURED_COLUMN,
    REFERENCE_COLUMN,
    _clip_negative_predictions,
    _concurrent_frame,
    _regression_metrics,
    _resampling_disclosure,
)

# Fraction of long-term records above the campaign maximum that triggers an
# explicit warning (D11).  Even a small fraction matters: those records are the
# ones that drive extreme-wind and site-suitability outputs.
TRUNCATION_WARNING_FRACTION = 0.001

# F-39 / F-40.  The holdout used to be a single terminal 20% block, so on a one-year
# campaign it covered October to December only - a +17.7% seasonal offset reported as
# `out_of_sample_rmse`, which is exactly the number that earns XGBoost its ensemble weight
# (F-45).  Early stopping also selected the boosting iteration on that same slice, making
# the figure optimistic through model selection on top of being seasonally biased.
#
# Blocks are contiguous rather than random: hourly wind is strongly autocorrelated, so a
# random fold would put a record's own neighbours in the training set and score near-perfect
# skill it does not have.  Four blocks put roughly one season in each on a one-year campaign.
CV_FOLDS = 4
MIN_FOLD_TRAIN_ROWS = 50
INNER_VALIDATION_FRACTION = 0.15
MAX_BOOST_ROUNDS = 2000
EARLY_STOPPING_ROUNDS = 50


def _blocked_folds(n_rows: int, folds: int) -> list[tuple[int, int]]:
    """Split ``n_rows`` chronological records into contiguous, near-equal holdout blocks."""
    if n_rows <= 0 or folds <= 0:
        return []
    edges = [int(round(index * n_rows / folds)) for index in range(folds + 1)]
    return [(start, stop) for start, stop in zip(edges[:-1], edges[1:]) if stop > start]


class DMatrixFactory(Protocol):
    """Typed constructor protocol for the lazily imported XGBoost DMatrix."""

    def __call__(
        self,
        data: object,
        *,
        label: np.ndarray | None = None,
        feature_names: list[str] | None = None,
    ) -> object: ...


class BoosterLike(Protocol):
    """Typed subset of the XGBoost Booster API used by the LTC tool."""

    @property
    def best_iteration(self) -> int: ...

    def predict(self, data: object) -> np.ndarray: ...

    def get_score(
        self,
        fmap: str = "",
        importance_type: str = "weight",
    ) -> Mapping[str, float | list[float]]: ...


class XGBoostTrain(Protocol):
    """Typed callable protocol for xgboost.train used via lazy import."""

    def __call__(
        self,
        params: Mapping[str, str | float | int],
        dtrain: object,
        *,
        num_boost_round: int,
        evals: list[tuple[object, str]],
        early_stopping_rounds: int,
        evals_result: dict[str, dict[str, list[float]]],
        verbose_eval: bool,
    ) -> BoosterLike: ...


def _long_term_frame(state: SessionState, long_col: str) -> pd.DataFrame:
    """Return the long-term reference dataframe required for ML LTC prediction."""
    if state.era5_interpolated_df is None:
        raise ValueError("Interpolated ERA5 dataframe is not available")
    if long_col not in state.era5_interpolated_df.columns:
        raise ValueError(f"Reference column '{long_col}' not found in session.era5_interpolated_df")
    return state.era5_interpolated_df.copy()


def _truncation_disclosure(
    training_reference: np.ndarray,
    long_reference: np.ndarray,
    corrected: np.ndarray,
) -> dict[str, object]:
    """Report long-term reference values above the campaign maximum (D11).

    Gradient-boosted trees are piecewise-constant and cannot predict outside the
    range of their training target: every reference value above the campaign
    maximum collapses onto the model's highest leaf.  The campaign is typically
    1-2 years while the long-term period is 20+, so windier-than-campaign events
    are routine.  This is inherent to the method and is deliberately *not*
    patched — it is surfaced so the analyst can see it.
    """
    campaign_max = float(np.max(training_reference)) if training_reference.size else float("nan")
    total = int(long_reference.size)
    above = int(np.count_nonzero(long_reference > campaign_max)) if np.isfinite(campaign_max) else 0
    fraction = float(above / total) if total else 0.0
    disclosure: dict[str, object] = {
        "campaign_reference_max_mps": campaign_max,
        "n_above_training_max": above,
        "fraction_above_training_max": fraction,
        "prediction_ceiling_mps": float(np.max(corrected)) if corrected.size else float("nan"),
        "extreme_wind_suitability": (
            "XGBoost truncates the upper tail and must not be used alone for extreme-wind estimation."
        ),
    }
    if fraction > TRUNCATION_WARNING_FRACTION:
        disclosure["warning"] = (
            f"{above:,} long-term records ({fraction:.1%}) exceed the campaign maximum of "
            f"{campaign_max:.1f} m/s and are truncated to the model's upper bound of "
            f"{disclosure['prediction_ceiling_mps']:.1f} m/s. Do not use this algorithm for "
            "extreme-wind estimation."
        )
    return disclosure


def _build_features(df: pd.DataFrame, long_col: str, long_dir_col: str) -> tuple[pd.DataFrame, list[str]]:
    """Create XGBoost features from wind speed, direction, temporal, and ERA5 met inputs."""
    features = pd.DataFrame(index=df.index)
    speed = df[long_col].to_numpy(dtype=float)
    features["ref_ws"] = speed
    features["ref_ws_squared"] = speed**2
    features["ref_ws_log"] = np.log1p(speed)
    if long_dir_col and long_dir_col in df.columns:
        direction_rad = np.radians(df[long_dir_col].to_numpy(dtype=float))
        sin_dir = np.sin(direction_rad)
        cos_dir = np.cos(direction_rad)
        features["ref_wd_sin"] = sin_dir
        features["ref_wd_cos"] = cos_dir
        features["ws_x_wd_sin"] = speed * sin_dir
        features["ws_x_wd_cos"] = speed * cos_dir
    index = pd.DatetimeIndex(df.index)
    features["hour"] = index.hour
    features["month"] = index.month
    features["day_of_year"] = index.dayofyear
    features["hour_sin"] = np.sin(2 * np.pi * index.hour / 24)
    features["hour_cos"] = np.cos(2 * np.pi * index.hour / 24)
    features["month_sin"] = np.sin(2 * np.pi * index.month / 12)
    features["month_cos"] = np.cos(2 * np.pi * index.month / 12)
    for column in ["t2m", "sp"]:
        if column in df.columns:
            features[column] = df[column].to_numpy(dtype=float)
    feature_names = features.columns.tolist()
    return features, feature_names


def _xgboost_import() -> tuple[DMatrixFactory, XGBoostTrain]:
    """Import XGBoost lazily so the server still imports when ML extras are absent."""
    try:
        from xgboost import DMatrix, train
    except ImportError as exc:
        raise ValueError("XGBoost is required for run_ltc_xgboost. Install the ml extras first") from exc
    return DMatrix, train


def _save_xgboost_result(state: SessionState, result_df: pd.DataFrame, metrics: Mapping[str, object]) -> str:
    """Persist the XGBoost LTC result to CSV and session state."""
    output_path = ""
    if state.persist_result_files:
        output_dir = Path(state.get_data_dir()) / "ltc_results"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        path = output_dir / f"ltc_xgboost_{timestamp}.csv"
        result_df.to_csv(path, index=False)
        output_path = str(path)
    state.ltc_results["xgboost"] = {
        "df": result_df.copy(),
        "metrics": dict(metrics),
        "file": output_path,
        "persisted": bool(output_path),
    }
    state.stamp_derived("ltc:xgboost")
    return output_path


def _run_ltc_xgboost(
    state: SessionState,
    short_col: str,
    long_col: str,
    short_dir_col: str = "",
    long_dir_col: str = "",
) -> dict:
    """Run XGBoost MCP with temporal, directional, and meteorological features and early stopping.

    **Not suitable alone for extreme-wind work.** Gradient-boosted trees cannot
    predict beyond their training target range, so every long-term reference
    value above the campaign maximum is truncated to the model's highest leaf.
    That biases GEV/Gumbel annual maxima low and distorts the upper tail of the
    corrected distribution. The returned metrics carry
    ``n_above_training_max`` / ``fraction_above_training_max`` and a ``warning``
    once the fraction is material (D11).
    """
    DMatrix, xgb_train = _xgboost_import()
    _, _, concurrent = _concurrent_frame(state, short_col, long_col)
    if len(concurrent) < 100:
        raise ValueError(f"XGBoost LTC requires at least 100 concurrent samples, got {len(concurrent)}")
    long_df = _long_term_frame(state, long_col)
    reference_feature_columns = [
        column for column in [long_dir_col, "t2m", "sp"] if column and column in long_df.columns
    ]
    if reference_feature_columns:
        # Ensure tz-awareness compatibility for the join (D8).
        long_df = to_utc_index(long_df)
        concurrent = to_utc_index(concurrent)
        concurrent = concurrent.join(long_df[reference_feature_columns], how="left")
    concurrent_features, feature_names = _build_features(concurrent, REFERENCE_COLUMN, long_dir_col)
    target = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    params = {
        "objective": "reg:squarederror",
        "eta": 0.05,
        "max_depth": 6,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "lambda": 1.0,
        "alpha": 0.1,
        "min_child_weight": 3,
        "gamma": 0.1,
        "seed": 42,
    }
    folds = _blocked_folds(len(concurrent_features), CV_FOLDS)
    oof_prediction = np.full(len(target), np.nan)
    fold_reports: list[dict[str, object]] = []
    fold_iterations: list[int] = []
    for fold_number, (start, stop) in enumerate(folds, start=1):
        train_rows = np.concatenate([np.arange(0, start), np.arange(stop, len(target))])
        if train_rows.size < MIN_FOLD_TRAIN_ROWS:
            continue
        # Early stopping watches a slice carved out of THIS fold's training data, never the
        # held-out block, so the reported error is not optimistic through model selection.
        inner_cut = max(1, int(train_rows.size * (1.0 - INNER_VALIDATION_FRACTION)))
        inner_fit, inner_watch = train_rows[:inner_cut], train_rows[inner_cut:]
        if inner_watch.size == 0:
            inner_fit, inner_watch = train_rows[:-1], train_rows[-1:]
        fold_booster = xgb_train(
            params,
            DMatrix(
                concurrent_features.iloc[inner_fit].to_numpy(dtype=float),
                label=target[inner_fit],
                feature_names=feature_names,
            ),
            num_boost_round=MAX_BOOST_ROUNDS,
            evals=[
                (
                    DMatrix(
                        concurrent_features.iloc[inner_watch].to_numpy(dtype=float),
                        label=target[inner_watch],
                        feature_names=feature_names,
                    ),
                    "inner",
                )
            ],
            early_stopping_rounds=EARLY_STOPPING_ROUNDS,
            verbose_eval=False,
        )
        fold_iterations.append(int(getattr(fold_booster, "best_iteration", MAX_BOOST_ROUNDS)) + 1)
        predicted = np.maximum(
            0.0,
            fold_booster.predict(
                DMatrix(
                    concurrent_features.iloc[start:stop].to_numpy(dtype=float),
                    feature_names=feature_names,
                )
            ),
        )
        oof_prediction[start:stop] = predicted
        fold_metrics = _regression_metrics(target[start:stop], predicted)
        fold_index = concurrent_features.index[start:stop]
        fold_reports.append(
            {
                "fold": fold_number,
                "records": int(stop - start),
                "start": fold_index[0].isoformat(),
                "end": fold_index[-1].isoformat(),
                "months": sorted({int(month) for month in fold_index.month}),
                "mean_measured": round(float(np.mean(target[start:stop])), 4),
                "rmse": fold_metrics["rmse"],
                "r_squared": fold_metrics["r_squared"],
            }
        )
    scored = np.isfinite(oof_prediction)
    if not fold_reports:
        raise ValueError(
            "XGBoost LTC could not build a cross-validated holdout: the concurrent period is "
            f"too short to split into {CV_FOLDS} blocks with at least {MIN_FOLD_TRAIN_ROWS} "
            "training records each."
        )
    # The reported out-of-sample error is now the out-of-fold error across the whole
    # campaign, so it covers every season the campaign saw (F-39/F-40).
    val_metrics = _regression_metrics(target[scored], oof_prediction[scored])

    # The delivered model is retrained on everything at the boosting depth the folds agreed
    # on, so no early stopping is fitted against data it is then scored on.
    best_iteration = int(np.median(fold_iterations)) if fold_iterations else MAX_BOOST_ROUNDS
    X_train = concurrent_features
    dtrain = DMatrix(
        concurrent_features.to_numpy(dtype=float), label=target, feature_names=feature_names
    )
    evals_result: dict[str, dict[str, list[float]]] = {}
    booster = xgb_train(
        params,
        dtrain,
        num_boost_round=max(1, best_iteration),
        evals=[(dtrain, "train")],
        evals_result=evals_result,
        verbose_eval=False,
    )
    # In-sample (full concurrent) metrics — kept for diagnostics.
    dconcurrent = DMatrix(concurrent_features.to_numpy(dtype=float), feature_names=feature_names)
    concurrent_pred = np.maximum(0.0, booster.predict(dconcurrent))
    in_sample_metrics = _regression_metrics(target, concurrent_pred)
    fold_rmse = [float(report["rmse"]) for report in fold_reports]
    metrics: dict[str, object] = {
        **val_metrics,
        "out_of_sample_rmse": val_metrics["rmse"],
        "out_of_sample_basis": "blocked_cross_validation",
        "cv_folds": len(fold_reports),
        "cv_fold_reports": fold_reports,
        "cv_rmse_spread": round(max(fold_rmse) - min(fold_rmse), 6),
        "cv_records_scored": int(scored.sum()),
        "cv_note": (
            f"out_of_sample_rmse is the out-of-fold error over {int(scored.sum()):,} records "
            f"from {len(fold_reports)} contiguous blocks spanning the whole concurrent period, "
            "not a single terminal holdout. Blocks are contiguous rather than random so no "
            "neighbouring hour leaks across the boundary, and early stopping watches a slice "
            "of each fold's own training data so the reported error is not optimistic through "
            "model selection. cv_rmse_spread is the fold-to-fold range - a large value means "
            "the model's skill depends on the season."
        ),
        "in_sample_r_squared": in_sample_metrics["r_squared"],
        "in_sample_rmse": in_sample_metrics["rmse"],
    }
    feature_importance = booster.get_score(importance_type="gain")
    top_features = dict(sorted(feature_importance.items(), key=lambda item: item[1], reverse=True)[:10])
    train_error = float(evals_result.get("train", {}).get("rmse", [float("nan")])[-1])
    val_error = float(val_metrics["rmse"])
    long_features, long_feature_names = _build_features(long_df, long_col, long_dir_col)
    if long_feature_names != feature_names:
        raise ValueError(
            f"Feature mismatch between fit and predict: {feature_names} vs {long_feature_names}"
        )
    dlong = DMatrix(long_features.to_numpy(dtype=float), feature_names=feature_names)
    corrected, clip_stats = _clip_negative_predictions(booster.predict(dlong))
    result_df = pd.DataFrame(
        {
            "Timestamp": long_df.index,
            "ERA5_original": long_df[long_col].to_numpy(dtype=float),
            "corrected_wind_speed": corrected,
        }
    )
    metrics.update(clip_stats)
    metrics.update(_resampling_disclosure(state))
    metrics.update(
        _truncation_disclosure(
            X_train["ref_ws"].to_numpy(dtype=float),
            long_features["ref_ws"].to_numpy(dtype=float),
            corrected,
        )
    )
    metrics.update(
        {
            "algorithm": "xgboost",
            "best_iteration": best_iteration,
            "train_error": train_error,
            "val_error": val_error,
            "feature_importance": top_features,
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
            "validation_points": int(scored.sum()),
        }
    )
    result_file = _save_xgboost_result(state, result_df, metrics)
    return {"status": "ok", "algorithm": "xgboost", "metrics": metrics, "result_file": result_file}


@mcp.tool()
def run_ltc_xgboost(short_col: str, long_col: str, short_dir_col: str = "", long_dir_col: str = "") -> dict:
    """Run XGBoost MCP with temporal, directional, and meteorological features and early stopping.

    Tree models cannot extrapolate: long-term speeds above the campaign maximum
    are truncated to the model's upper bound, so this algorithm must not be used
    alone for extreme-wind estimation. The extent of the truncation is reported
    in the metrics (D11).
    """
    return _run_ltc_xgboost(session, short_col, long_col, short_dir_col, long_dir_col)
