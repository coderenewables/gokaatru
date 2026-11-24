"""Results of the diagnostic operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import CleaningLogEntry, Number, Result, SelectionUsed


class MastEffectSector(Result):
    label: str
    speed_ratio: Number
    record_count: int
    sufficient_records: bool


class ComputeMastEffectsResult(Result):
    sensor_a: str
    sensor_b: str
    direction_sensor: str
    baseline_speed_ratio: Number
    #: Sector labels where each sensor reads low against the other.
    affected_sectors_a: list[str]
    affected_sectors_b: list[str]
    affected_sectors: list[str]
    min_speed_mps: Number
    min_sector_records: int
    records_used: int
    sectors: list[MastEffectSector]
    selection: SelectionUsed | None = None


class PairMetrics(Result):
    correlation: Number
    r_squared: Number
    slope: Number
    offset: Number
    rmse: Number
    bias: Number
    record_count: int


class ComputeMcpReadinessResult(PairMetrics):
    speed_sensor: str
    reference_sensor: str
    concurrent_hours: int
    long_term_adjustment_factor: Number
    ready: bool
    #: One reason per failed condition, with the measured value and the threshold.
    not_ready_reasons: list[str]
    min_concurrent_hours: int
    min_r_squared: Number


class QcSensor(Result):
    sensor: str
    range_failures: int
    range_min: Number
    range_max: Number
    range_bounds_source: str
    flatline_records: int
    removed_after_cleaning: int


class ComputeQcDiagnosticsResult(Result):
    cleaning_rules_applied: int
    cleaning_log: list[CleaningLogEntry]
    sensors: list[QcSensor]
    selection: SelectionUsed | None = None


class Residual(Result):
    timestamp: str
    value: Number


class ComputeSensorComparisonResult(PairMetrics):
    sensor_a: str
    sensor_b: str
    residuals: list[Residual]
    selection: SelectionUsed | None = None
