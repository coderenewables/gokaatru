"""Results of the data ingest operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, SensorMappingEntry


class SensorRow(Result):
    """``server.schemas.common.SensorInfo``."""

    name: str
    height_m: Number
    sensor_type: str
    data_coverage_pct: Number
    record_count: int


class GetDataCoverageResult(Result):
    sensor: str
    total_records: int
    valid_records: int
    coverage_pct: Number
    largest_gap_minutes: int
    gaps_over_1_hour: int


class GetPeriodOfRecordResult(Result):
    start: str
    end: str
    total_records: int
    timestep_minutes: int
    sensors: list[SensorRow]


class ListSensorsResult(Result):
    sensors: list[SensorRow]


class Coordinate(Result):
    latitude: Number
    longitude: Number
    elevation_m: Number


class ParseDatamodelResult(Result):
    status: str
    heights: list[Number]
    mapping: dict[str, SensorMappingEntry]
    timezone: str
    timezone_source: str
    #: ``already_aware``, ``strict`` or ``standard_offset`` (a DST transition was crossed and
    #: the timestamps were read as fixed local standard time; then the next three are set).
    timezone_resolution: str
    timezone_requested: str | None = None
    standard_offset_hours: Number = None
    warning: str | None = None
    project_name: str | None = None
    location: Coordinate | None = None
    measurement_type: str | None = None


class ParseTimeseriesResult(Result):
    status: str
    rows: int
    columns: list[str]
    start: str
    end: str
    timestep_minutes: int
    duplicate_timestamps: int
    #: The next three are present when duplicate timestamps were found and averaged.
    duplicate_timestamps_distinct: int | None = None
    duplicate_resolution: str | None = None
    warning: str | None = None
    timestamp_label: str
    timestamp_label_basis: str
    timestamp_label_note: str
    timestamp_column: str
    date_order: str
    date_order_basis: str
