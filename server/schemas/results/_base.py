"""Shared pieces of the operation result models (P1-19).

A result model describes what an operation's generated route sends. It is documentation for
the OpenAPI schema and the TypeScript client generated from it, checked against real
responses in ``tests/test_operation_results.py``; the routes do not validate against it, so
a model can never turn a working call into an error.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

#: A number. Any float an operation computes can be NaN or infinite on degenerate data, and
#: the routes send those as null, so every float field admits null.
Number = float | None


class Result(BaseModel):
    """A response object whose fields are all declared."""

    model_config = ConfigDict(extra="forbid")


class OpenResult(BaseModel):
    """A response object with declared fields and others that are the caller's own."""

    model_config = ConfigDict(extra="allow")


class ErrorDetail(Result):
    """A refusal (400) or an upstream failure (502), with the reason."""

    detail: str


class SelectionUsed(Result):
    """The selection a result was computed on (``server.operations.SELECTION_BASIS``)."""

    #: The saved selection's name; ``None`` for a definition sent inline.
    name: str | None
    inline: bool
    records: int
    of_records: int
    basis: str


class PlotResult(Result):
    plotly_json: str
    png_base64: str | None
    title: str
    #: Present when the figure draws a sample of the records: how many it drew, of how many.
    sampled_count: int | None = None
    total_count: int | None = None


class SelectablePlotResult(PlotResult):
    selection: SelectionUsed | None = None


class Staleness(Result):
    """``SessionState.staleness_report``: derived artifacts that no longer match."""

    data_version: int
    stale_artifacts: list[str]
    stale_reasons: dict[str, str | None] | None = None
    warning: str | None = None


class CleaningDetail(Result):
    """What a cleaning rule reports about how it ran, beside its count; each rule sets its own."""

    # range_check
    bounds_source: str | None = None
    sensor_type: str | None = None
    min_applied: Number = None
    max_applied: Number = None
    note: str | None = None
    # icing_filter
    temp_threshold_c: Number = None
    sd_threshold_mps: Number = None
    direction_basis: str | None = None
    direction_sensor: str | None = None
    direction_tolerance_deg: Number = None
    direction_window: int | None = None
    retained_by_direction_test: int | None = None
    # stuck_sensor
    consecutive_count: int | None = None
    calm_threshold_mps: Number = None
    calms_preserved: int | None = None
    calm_corroboration: str | None = None
    corroborating_sensors: list[str] | None = None
    # tower_shadow
    sector_basis: str | None = None
    boom_orientation_deg: Number = None
    sector_width_deg: Number = None
    exclude_sectors: list[Number] | None = None
    warning: str | None = None
    # exclude_selection
    reason: str | None = None
    #: The frozen definition in words.
    description: str | None = None
    #: Records the definition held when the rule ran, before any column's own gaps.
    selected_records: int | None = None
    #: Values set missing, by column; ``records_affected`` is their sum.
    affected_by_sensor: dict[str, int] | None = None


class CleaningLogEntry(CleaningDetail):
    """One entry of ``state.cleaning_log``. BrightHub's upstream processing is recorded as a
    non-undoable entry of its own (``source``, ``upstream``, ``undoable``)."""

    rule_type: str
    sensor: str
    sequence: int | None = None
    records_affected: int | None
    applied_at: str
    #: Who applied the rule; absent on upstream processing and on entries saved before it.
    actor: str | None = None
    params: dict[str, Any]
    start_date: str | None
    end_date: str | None
    source: str | None = None
    upstream: bool | None = None
    undoable: bool | None = None
    brighthub_uuid: str | None = None


class SensorMappingEntry(Result):
    """The columns mapped at one height."""

    speed_col: str | None
    dir_col: str | None = None
    sd_col: str | None = None
    temp_col: str | None = None
    pressure_col: str | None = None
    humidity_col: str | None = None


class RunConfigLocation(OpenResult):
    latitude: Number = None
    longitude: Number = None
    elevation_m: Number = None


class RunConfig(OpenResult):
    """The run configuration (``server/core/runconfig.py``). The canonical keys are typed;
    the sections the interface writes, and any key set through ``update_run_config``, are
    the caller's own and pass as they are."""

    project_name: str | None = None
    measurement_type: str | None = None
    hub_height_m: Number = None
    location: RunConfigLocation | None = None
    site: dict[str, Any] | None = None
    reference_source: str | None = None
    sensor_mapping: dict[str, SensorMappingEntry] | None = None
    cleaning_log: list[CleaningLogEntry] | None = None
    shear_table_shape: list[int] | None = None
    roughness_table_shape: list[int] | None = None
    mean_air_density_kgm3: Number = None
