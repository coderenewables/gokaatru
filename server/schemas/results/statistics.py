"""Results of the statistics operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, SelectionUsed
from server.schemas.results.shear import ClockDisclosure


class ComputeDiurnalProfileResult(ClockDisclosure):
    sensor: str
    #: UTC hours 0-23.
    hours: list[int]
    mean_speeds: list[Number]
    #: The same bins as site local hours, when a timezone was declared.
    hours_local: list[int] | None = None
    selection: SelectionUsed | None = None


class ComputeMommResult(Result):
    sensor: str
    momm_speed: Number
    table: list[list[Number]]
    cells_observed: int
    cells_total: int
    filled_cells: int
    filled_fraction: Number
    months_observed: list[int]
    months_missing: list[int]
    fill_value: Number
    #: Present when months or month-hour cells were never observed.
    warning: str | None = None
    selection: SelectionUsed | None = None


class MonthStatistics(Result):
    month: int
    mean: Number
    min: Number
    max: Number
    coverage_pct: Number


class ComputeMonthlyStatsResult(Result):
    sensor: str
    months: list[MonthStatistics]
    selection: SelectionUsed | None = None


class ComputeScatterStatsResult(Result):
    sensor_a: str
    sensor_b: str
    r2: Number
    rmse: Number
    mae: Number
    mbe: Number
    slope: Number
    intercept: Number
    count: int
    selection: SelectionUsed | None = None


class TurbulenceBin(Result):
    bin_center_mps: Number
    mean_ti: Number
    representative_ti: Number
    count: int
    sufficient_records: bool


class ComputeTurbulenceAnalysisResult(Result):
    speed_sensor: str
    sd_sensor: str
    record_count: int
    speed_gate_mps: Number
    ti_basis: str
    mean_ti: Number
    p90_ti: Number
    representative_ti: Number
    representative_ti_basis: str
    representative_ti_unweighted: Number
    iec_ti_at_15ms: Number
    iec_ti_bin_mps: int
    iec_ti_bin_records: int
    iec_ti_reference_speed_mps: Number
    min_bin_records: int
    bins: list[TurbulenceBin]
    selection: SelectionUsed | None = None


class TurbulenceIntensityBin(Result):
    bin_center: Number
    mean_ti: Number
    representative_ti: Number
    count: int
    sufficient_records: bool


class ComputeTurbulenceIntensityResult(Result):
    bins: list[TurbulenceIntensityBin]
    speed_gate_mps: Number
    ti_basis: str
    min_bin_records: int
    record_count: int
    selection: SelectionUsed | None = None


class ComputeWeibullParamsResult(Result):
    sensor: str
    k: Number
    A: Number
    mean_speed: Number
    record_count: int
    record_count_total: int
    calm_fraction: Number
    fit_excludes_calms: bool
    fit_method: str
    selection: SelectionUsed | None = None


class Exceedance(Result):
    p50: Number
    p75: Number
    p90: Number
    p95: Number


class DirectionSummary(Result):
    sensor_name: str
    mean_direction_deg: Number
    circular_variance: Number
    prevailing_sector: str


class ClimateSector(Result):
    center_deg: Number
    label: str
    occurrence_pct: Number
    mean_speed: Number
    energy_pct: Number


class ComputeWindClimateResult(Result):
    speed_sensor: str
    record_count: int
    mean_speed: Number
    mean_speed_basis: str
    mean_speed_excluding_calms: Number
    calm_records: int
    calm_fraction: Number
    positive_record_count: int
    exceedance_basis: str
    basis_note: str
    cube_mean_speed: Number
    weibull_k: Number
    weibull_A: Number
    weibull_rmse: Number
    weibull_method: str
    exceedance: Exceedance
    #: Null, and ``sectors`` empty, without a direction sensor.
    direction: DirectionSummary | None
    sectors: list[ClimateSector]
    selection: SelectionUsed | None = None


class WindroseSector(Result):
    center_deg: Number
    label: str
    frequency_pct: Number
    mean_speed: Number


class ComputeWindroseDataResult(Result):
    sectors: list[WindroseSector]
    selection: SelectionUsed | None = None
