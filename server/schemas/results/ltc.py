"""Results of the long-term correction operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class LtcMetrics(Result):
    """What every correction reports (``server/tools/ltc.py::_ltc_response``): the
    concurrent-period fit, the negative predictions clipped, how the measured series was
    matched to the reference, and how much of the reference's variance was kept."""

    r_squared: Number
    rmse: Number
    mae: Number
    mbe: Number
    std_residuals: Number
    algorithm: str
    concurrent_points: int
    total_corrected_points: int
    negative_predictions_clipped: int
    negative_predictions_clipped_fraction: Number
    # Absent when the measured cadence cannot be detected.
    measured_resampled_to_hourly: bool | None = None
    measured_timestep_minutes: int | None = None
    resampling_note: str | None = None
    reference_source: str | None = None
    reference_temporal_semantics: str | None = None
    timestamp_label: str | None = None
    timestamp_shift_minutes: Number = None
    timestamp_shift_note: str | None = None
    hourly_resampled: bool | None = None
    hourly_resample_reason: str | None = None
    hourly_coverage_minimum: Number = None
    hourly_expected_samples: Number = None
    hours_kept: int | None = None
    hours_dropped_below_minimum: int | None = None
    hours_kept_partially_populated: int | None = None
    hourly_coverage_note: str | None = None
    # Absent when fewer than three corrected records pair with the reference.
    long_term_corrected_std: Number = None
    long_term_reference_std: Number = None
    variance_ratio_to_reference: Number = None
    variance_note: str | None = None
    long_term_coefficient_of_variation: Number = None
    warning: str | None = None


class LinearLeastSquaresMetrics(LtcMetrics):
    estimator: str
    huber_delta: Number
    estimator_note: str
    slope: Number
    intercept: Number


class SectorModel(Result):
    slope: Number
    intercept: Number
    threshold: Number
    dog_leg_slope: Number
    count: Number


class SpeedsortMetrics(LtcMetrics):
    threshold: Number
    threshold_basis: str
    threshold_fraction: Number
    threshold_ceiling_mps: Number
    fit_basis: str
    directional: bool
    # Non-directional: one transfer function.
    slope: Number = None
    intercept: Number = None
    dog_leg_slope: Number = None
    # Directional: one per sector, by sector index.
    concurrent_points_scored: int | None = None
    num_sectors: int | None = None
    sector_width_deg: Number = None
    min_sector_records: int | None = None
    independent_sectors: int | None = None
    reference_direction_missing: int | None = None
    unmodelled_records: int | None = None
    unmodelled_fraction: Number = None
    sector_models: dict[str, SectorModel] | None = None


class TotalLeastSquaresMetrics(LtcMetrics):
    error_variance_ratio_assumed: Number
    error_variance_note: str
    slope: Number
    intercept: Number


class VarianceRatioMetrics(LtcMetrics):
    measured_mean: Number
    reference_mean: Number
    measured_std: Number
    reference_std: Number
    variance_ratio: Number
    correlation: Number


class RunLtcLinearLeastSquaresResult(Result):
    status: str
    algorithm: str
    metrics: LinearLeastSquaresMetrics
    #: Empty when result files are not persisted (a sweep leaf).
    result_file: str


class RunLtcSpeedsortResult(Result):
    status: str
    algorithm: str
    metrics: SpeedsortMetrics
    result_file: str


class RunLtcTotalLeastSquaresResult(Result):
    status: str
    algorithm: str
    metrics: TotalLeastSquaresMetrics
    result_file: str


class RunLtcVarianceRatioResult(Result):
    status: str
    algorithm: str
    metrics: VarianceRatioMetrics
    result_file: str
