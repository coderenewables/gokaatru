"""Results of the advanced analysis operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, SelectionUsed


class EnergySector(Result):
    label: str
    power_density_w_m2: Number
    energy_pct: Number


class ComputeEnergyMetricsResult(Result):
    speed_sensor: str
    record_count: int
    air_density_kg_m3: Number
    density_source: str
    monthly_density_basis: str
    density_height_basis: str
    density_height_adjustment: Number
    pressure_sensor_height_m: Number
    speed_sensor_height_m: Number
    wind_power_density_w_m2: Number
    mean_cube_speed_m_s: Number
    monthly_power_density_w_m2: list[Number]
    #: Sixteen sectors when a direction sensor is named, otherwise empty.
    sectors: list[EnergySector]
    selection: SelectionUsed | None = None


class AnnualMaximum(Result):
    year: int
    max_speed: Number


class PartialYear(Result):
    year: int
    records: int
    days_covered: int
    days_in_year: int
    day_coverage: Number
    record_completeness: Number
    months_covered: list[int]
    partial_year_max_speed: Number


class ReturnLevels(Result):
    wind_50_year: Number
    wind_100_year: Number
    plausible: bool
    below_largest_observed: bool
    #: Present when the fit is not usable: why.
    implausibility: str | None = None


class GumbelFit(ReturnLevels):
    location: Number
    scale: Number


class GevFit(Result):
    """Fitted only with enough years; otherwise unavailable, with the reason."""

    available: bool
    reason: str | None = None
    shape: Number = None
    location: Number = None
    scale: Number = None
    wind_50_year: Number = None
    wind_100_year: Number = None
    plausible: bool | None = None
    below_largest_observed: bool | None = None
    implausibility: str | None = None


class ComputeExtremeWindsResult(Result):
    speed_sensor: str
    series_basis: str
    source: str
    sample_years: int
    minimum_recommended_years: int
    gev_minimum_years: int
    screening_only: bool
    min_year_coverage: Number
    annual_maxima: list[AnnualMaximum]
    years_excluded: list[PartialYear]
    largest_observed_max_speed: Number
    gev: GevFit
    gumbel: GumbelFit
    warning: str | None = None


class ComputeWindPersistenceResult(Result):
    speed_sensor: str
    timestep_minutes: int
    calm_threshold_m_s: Number
    high_wind_threshold_m_s: Number
    calm_pct: Number
    high_wind_pct: Number
    calm_period_count: int
    high_wind_period_count: int
    max_calm_duration_minutes: Number
    max_high_wind_duration_minutes: Number
    calm_durations_minutes: list[Number]
    high_wind_durations_minutes: list[Number]
    selection: SelectionUsed | None = None


class RampEvent(Result):
    timestamp: str
    ramp_m_s: Number


class ComputeWindRampsResult(Result):
    speed_sensor: str
    timestep_minutes: int
    record_count: int
    mean_absolute_ramp_m_s: Number
    p95_absolute_ramp_m_s: Number
    event_threshold_m_s: Number
    event_count: int
    largest_events: list[RampEvent]
    selection: SelectionUsed | None = None
