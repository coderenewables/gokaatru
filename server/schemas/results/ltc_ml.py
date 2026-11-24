"""Results of the XGBoost long-term correction (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result
from server.schemas.results.ltc import LtcMetrics


class CrossValidationFold(Result):
    fold: int
    records: int
    start: str
    end: str
    months: list[int]
    mean_measured: Number
    rmse: Number
    r_squared: Number


class XgboostMetrics(LtcMetrics):
    out_of_sample_rmse: Number
    out_of_sample_basis: str
    cv_folds: int
    cv_fold_reports: list[CrossValidationFold]
    cv_rmse_spread: Number
    cv_records_scored: int
    cv_note: str
    in_sample_r_squared: Number
    in_sample_rmse: Number
    campaign_reference_max_mps: Number
    n_above_training_max: int
    fraction_above_training_max: Number
    prediction_ceiling_mps: Number
    extreme_wind_suitability: str
    best_iteration: int
    train_error: Number
    val_error: Number
    #: The most important features, by name.
    feature_importance: dict[str, Number]
    validation_points: int


class RunLtcXgboostResult(Result):
    status: str
    algorithm: str
    metrics: XgboostMetrics
    result_file: str
