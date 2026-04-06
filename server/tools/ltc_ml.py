"""ltc_ml — Phase 3 MCP tool for XGBoost long-term correction.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from server.main import mcp
from server.state.session import SessionState, session
from server.tools.ltc import MEASURED_COLUMN, REFERENCE_COLUMN, _concurrent_frame, _regression_metrics


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
    output_dir = Path(state.get_data_dir()) / "ltc_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    output_path = output_dir / f"ltc_xgboost_{timestamp}.csv"
    result_df.to_csv(output_path, index=False)
    state.ltc_results["xgboost"] = {"df": result_df.copy(), "metrics": dict(metrics), "file": str(output_path)}
    return str(output_path)


def _run_ltc_xgboost(
    state: SessionState,
    short_col: str,
    long_col: str,
    short_dir_col: str = "",
    long_dir_col: str = "",
) -> dict:
    """Run XGBoost MCP with temporal, directional, and meteorological features and early stopping."""
    DMatrix, xgb_train = _xgboost_import()
    _, _, concurrent = _concurrent_frame(state, short_col, long_col)
    if len(concurrent) < 100:
        raise ValueError(f"XGBoost LTC requires at least 100 concurrent samples, got {len(concurrent)}")
    long_df = _long_term_frame(state, long_col)
    reference_feature_columns = [
        column for column in [long_dir_col, "t2m", "sp"] if column and column in long_df.columns
    ]
    if reference_feature_columns:
        concurrent = concurrent.join(long_df[reference_feature_columns], how="left")
    concurrent_features, feature_names = _build_features(concurrent, REFERENCE_COLUMN, long_dir_col)
    target = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    split_index = int(0.8 * len(concurrent_features))
    X_train = concurrent_features.iloc[:split_index]
    X_val = concurrent_features.iloc[split_index:]
    y_train = target[:split_index]
    y_val = target[split_index:]
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
    dtrain = DMatrix(X_train.to_numpy(dtype=float), label=y_train, feature_names=feature_names)
    dval = DMatrix(X_val.to_numpy(dtype=float), label=y_val, feature_names=feature_names)
    evals_result: dict[str, dict[str, list[float]]] = {}
    booster = xgb_train(
        params,
        dtrain,
        num_boost_round=2000,
        evals=[(dtrain, "train"), (dval, "eval")],
        early_stopping_rounds=50,
        evals_result=evals_result,
        verbose_eval=False,
    )
    best_iteration = int(getattr(booster, "best_iteration", 2000))
    dconcurrent = DMatrix(concurrent_features.to_numpy(dtype=float), feature_names=feature_names)
    concurrent_pred = np.maximum(0.0, booster.predict(dconcurrent))
    metrics: dict[str, object] = dict(_regression_metrics(target, concurrent_pred))
    feature_importance = booster.get_score(importance_type="gain")
    top_features = dict(sorted(feature_importance.items(), key=lambda item: item[1], reverse=True)[:10])
    train_error = float(evals_result.get("train", {}).get("rmse", [float("nan")])[-1])
    val_error = float(evals_result.get("eval", {}).get("rmse", [float("nan")])[-1])
    long_features, _ = _build_features(long_df, long_col, long_dir_col)
    dlong = DMatrix(long_features.to_numpy(dtype=float), feature_names=feature_names)
    corrected = np.maximum(0.0, booster.predict(dlong))
    result_df = pd.DataFrame(
        {
            "Timestamp": long_df.index,
            "ERA5_original": long_df[long_col].to_numpy(dtype=float),
            "corrected_wind_speed": corrected,
        }
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
        }
    )
    result_file = _save_xgboost_result(state, result_df, metrics)
    return {"status": "ok", "algorithm": "xgboost", "metrics": metrics, "result_file": result_file}


@mcp.tool()
def run_ltc_xgboost(short_col: str, long_col: str, short_dir_col: str = "", long_dir_col: str = "") -> dict:
    """Run XGBoost MCP with temporal, directional, and meteorological features and early stopping."""
    return _run_ltc_xgboost(session, short_col, long_col, short_dir_col, long_dir_col)
