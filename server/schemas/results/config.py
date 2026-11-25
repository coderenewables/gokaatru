"""Results of the configuration operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, RunConfig
from server.schemas.results.data_io import Coordinate


class GetAnalysisSummaryResult(Result):
    project_name: str | None
    hub_height_m: Number
    timeseries_loaded: bool
    sensor_mapping_loaded: bool
    sensor_count: int
    avg_coverage_pct: Number
    cleaning_rules_applied: int
    shear_table_ready: bool
    roughness_table_ready: bool
    era5_nodes_loaded: bool
    era5_data_sets_loaded: int
    era5_interpolated_ready: bool
    ltc_algorithms_run: list[str]
    ensemble_ready: bool
    scenario_count: int
    coordinate: Coordinate | None


class GetRunConfigResult(RunConfig):
    pass


class LoadRunConfigResult(RunConfig):
    pass


class UpdateRunConfigResult(RunConfig):
    pass


class SaveRunConfigResult(Result):
    status: str
    file_path: str
    keys: list[str]
