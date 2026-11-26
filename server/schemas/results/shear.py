"""Results of the shear and roughness operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, SelectionUsed


class ShearClamping(Result):
    """How often the shear exponent hit the backstop. Empty when a table is built before any
    shear timeseries carried the statistics."""

    records_used: int | None = None
    records_clamped: int | None = None
    clamped_fraction: Number = None
    min_speed_mps: Number = None
    #: Present when more than ``SHEAR_CLAMP_WARNING_FRACTION`` of records were clamped.
    warning: str | None = None


class RoughnessClipping(Result):
    """How much of a roughness series is a clip bound. Empty when none was computed."""

    records_used: int | None = None
    records_clipped: int | None = None
    clipped_fraction: Number = None
    clipped_at_min: int | None = None
    clipped_at_max: int | None = None
    roughness_bounds_m: list[Number] | None = None
    warning: str | None = None


class TableCoverage(Result):
    cells_observed: int
    cells_total: int
    filled_cells: int
    filled_fraction: Number
    months_observed: list[int]
    months_missing: list[int]
    warning: str | None = None


class ClockDisclosure(Result):
    """``SessionState.clock_disclosure``: hour bins are UTC hours."""

    hour_basis: str
    hour_note: str
    #: Null when no timezone was declared.
    site_utc_offset_hours: Number
    local_hour_note: str


class BuildAggrMommShearTableResult(Result):
    method: str
    aggregation: str
    #: 12 months by 24 hours.
    table: list[list[Number]]
    shear_clamping: ShearClamping
    fallback_alpha: Number
    fallback_source: str
    table_coverage: TableCoverage
    warning: str | None = None


class BuildRoughnessTableResult(ClockDisclosure):
    method: str
    aggregation: str
    table: list[list[Number]]
    roughness_clipping: RoughnessClipping
    fallback_z0: Number
    fallback_source: str
    table_coverage: TableCoverage
    warning: str | None = None


class BuildShearTableResult(ClockDisclosure):
    method: str
    aggregation: str
    table: list[list[Number]]
    shear_clamping: ShearClamping
    fallback_alpha: Number
    fallback_source: str
    table_coverage: TableCoverage
    warning: str | None = None


class ExcludedSector(Result):
    sector: str
    records: int
    #: ``empty`` or ``below_minimum_records``.
    reason: str


class BuildSectorShearTablesResult(ClockDisclosure):
    #: A 12x24 table per sector, by sector label.
    sectors: dict[str, list[list[Number]]]
    shear_clamping: ShearClamping
    min_sector_records: int
    sector_record_counts: dict[str, int]
    sectors_excluded: list[ExcludedSector]
    sector_coverage: dict[str, TableCoverage]
    warning: str | None = None
    coverage_warning: str | None = None
    selection: SelectionUsed | None = None


class CalculateRoughnessTimeseriesResult(Result):
    status: str
    records: int
    mean_roughness: Number
    median_roughness: Number
    std_roughness: Number
    roughness_clipping: RoughnessClipping
    warning: str | None = None


class CalculateShearTimeseriesResult(ShearClamping):
    status: str
    records: int
    mean_shear: Number
    median_shear: Number
    std_shear: Number


class ProfilePoint(Result):
    height_m: Number
    mean_speed: Number


class AlphaDistribution(Result):
    record_count: int
    mean: Number
    median: Number
    std: Number
    p10: Number
    p90: Number


class Veer(Result):
    record_count: int
    mean_deg_per_100m: Number
    std_deg_per_100m: Number


class ComputeVerticalStructureResult(Result):
    mean_profile: list[ProfilePoint]
    power_law_alpha: Number
    power_law_alpha_basis: str
    power_law_r_squared: Number
    roughness_length_m: Number
    records_used: int
    records_available: int
    concurrent_fraction: Number
    shear_clamping: ShearClamping
    alpha: AlphaDistribution
    #: Null without two direction sensors.
    veer: Veer | None
    selection: SelectionUsed | None = None


class BuildConstantShearTableResult(Result):
    status: str
    alpha: Number
    #: `analyst_supplied` for a given exponent, `fitted` for the mean of the shear series.
    shear_source: str
    aggregation: str
