"""session — In-memory session state for Phase 1 workflows.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from server.schemas.common import Coordinate


class SessionState:
    """Store the active project state following the GoKaatru session contract."""

    project_name: str | None
    coordinate: Coordinate | None
    measurement_type: str | None
    hub_height_m: float | None
    timeseries_df: pd.DataFrame | None
    raw_timeseries_df: pd.DataFrame | None
    sensor_mapping: dict[float, dict[str, str | None]]
    cleaning_log: list[dict[str, object]]
    shear_timeseries_df: pd.DataFrame | None
    roughness_timeseries_df: pd.DataFrame | None
    shear_table: pd.DataFrame | None
    roughness_table: pd.DataFrame | None
    era5_nodes: list[dict[str, object]] | None
    era5_data: dict[str, pd.DataFrame]
    era5_interpolated_df: pd.DataFrame | None
    ltc_results: dict[str, dict[str, object]]
    ensemble_df: pd.DataFrame | None
    runconfig: dict[str, object]

    def __init__(self) -> None:
        """Initialize the singleton session state per the GoKaatru build spec."""
        self.reset()

    def reset(self) -> None:
        """Reset all session fields to empty values per the GoKaatru session contract."""
        self.project_name = None
        self.coordinate = None
        self.measurement_type = None
        self.hub_height_m = None
        self.timeseries_df = None
        self.raw_timeseries_df = None
        self.sensor_mapping = {}
        self.cleaning_log = []
        self.shear_timeseries_df = None
        self.roughness_timeseries_df = None
        self.shear_table = None
        self.roughness_table = None
        self.era5_nodes = None
        self.era5_data = {}
        self.era5_interpolated_df = None
        self.ltc_results = {}
        self.ensemble_df = None
        self.runconfig = {}

    def to_runconfig(self) -> dict[str, object]:
        """Serialize current state into a run configuration dictionary for GoKaatru tools."""
        config: dict[str, object] = dict(self.runconfig)
        if self.project_name is not None:
            config["project_name"] = self.project_name
        if self.coordinate is not None:
            config["location"] = self.coordinate.model_dump()
        if self.measurement_type is not None:
            config["measurement_type"] = self.measurement_type
        if self.hub_height_m is not None:
            config["hub_height_m"] = self.hub_height_m
        if self.sensor_mapping:
            config["sensor_mapping"] = {
                str(height): mapping.copy() for height, mapping in self.sensor_mapping.items()
            }
        if self.cleaning_log:
            config["cleaning_log"] = [entry.copy() for entry in self.cleaning_log]
        if self.shear_table is not None:
            config["shear_table_shape"] = list(self.shear_table.shape)
        if self.roughness_table is not None:
            config["roughness_table_shape"] = list(self.roughness_table.shape)
        return config

    def get_data_dir(self) -> str:
        """Return the runtime data directory path as required by the Phase 1 build spec."""
        data_dir = Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir)


session = SessionState()
