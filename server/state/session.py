"""session — In-memory session state for Phase 1 workflows.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from server.schemas.common import Coordinate


def _utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp for session lifecycle tracking."""
    return datetime.now(timezone.utc)


class SessionState:
    """Store the active project state following the GoKaatru session contract."""

    session_id: str | None
    workspace_dir: Path | None
    created_at: datetime | None
    updated_at: datetime | None
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
        self.session_id = None
        self.workspace_dir = None
        self.created_at = None
        self.updated_at = None
        self.reset()

    def reset(self, preserve_workspace: bool = False) -> None:
        """Reset session fields while optionally preserving workspace metadata for managed sessions."""
        preserved_session_id = self.session_id if preserve_workspace else None
        preserved_workspace_dir = self.workspace_dir if preserve_workspace else None
        preserved_created_at = self.created_at if preserve_workspace else None
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
        self.session_id = preserved_session_id
        self.workspace_dir = preserved_workspace_dir
        self.created_at = preserved_created_at
        self.updated_at = _utcnow() if preserve_workspace else None

    def touch(self) -> None:
        """Update the last-modified timestamp for managed sessions after state mutations."""
        if self.workspace_dir is None and self.session_id is None:
            return
        if self.created_at is None:
            self.created_at = _utcnow()
        self.updated_at = _utcnow()

    def set_project_name(self, project_name: str | None) -> None:
        """Persist project name in runconfig while retaining a mirrored session convenience field."""
        self.project_name = project_name
        if project_name is None:
            self.runconfig.pop("project_name", None)
            self.touch()
            return
        self.runconfig["project_name"] = project_name
        self.touch()

    def set_coordinate(self, coordinate: Coordinate | None) -> None:
        """Persist site location in runconfig while retaining a mirrored session convenience field."""
        self.coordinate = coordinate
        if coordinate is None:
            self.runconfig.pop("location", None)
            self.touch()
            return
        self.runconfig["location"] = coordinate.model_dump()
        self.touch()

    def set_measurement_type(self, measurement_type: str | None) -> None:
        """Persist measurement type in runconfig while retaining a mirrored session convenience field."""
        self.measurement_type = measurement_type
        if measurement_type is None:
            self.runconfig.pop("measurement_type", None)
            self.touch()
            return
        self.runconfig["measurement_type"] = measurement_type
        self.touch()

    def set_hub_height_m(self, hub_height_m: float | None) -> None:
        """Persist hub height in runconfig while retaining a mirrored session convenience field."""
        self.hub_height_m = hub_height_m
        if hub_height_m is None:
            self.runconfig.pop("hub_height_m", None)
            self.touch()
            return
        self.runconfig["hub_height_m"] = float(hub_height_m)
        self.touch()

    def get_coordinate(self) -> Coordinate | None:
        """Return the site coordinate from runconfig when available, else the mirrored session field."""
        location = self.runconfig.get("location")
        if isinstance(location, dict) and {"latitude", "longitude"}.issubset(location):
            return Coordinate(
                latitude=float(location["latitude"]),
                longitude=float(location["longitude"]),
                elevation_m=float(location.get("elevation_m", 0.0)),
            )
        return self.coordinate

    def get_project_name(self) -> str | None:
        """Return the project name from runconfig when available, else the mirrored session field."""
        value = self.runconfig.get("project_name")
        return str(value) if isinstance(value, str) else self.project_name

    def get_measurement_type(self) -> str | None:
        """Return the measurement type from runconfig when available, else the mirrored session field."""
        value = self.runconfig.get("measurement_type")
        return str(value) if isinstance(value, str) else self.measurement_type

    def get_hub_height_m(self) -> float | None:
        """Return the hub height from runconfig when available, else the mirrored session field."""
        value = self.runconfig.get("hub_height_m")
        if isinstance(value, (int, float)):
            return float(value)
        return self.hub_height_m

    def to_runconfig(self) -> dict[str, object]:
        """Serialize current state into a run configuration dictionary for GoKaatru tools."""
        config: dict[str, object] = dict(self.runconfig)
        if "project_name" not in config and self.project_name is not None:
            config["project_name"] = self.project_name
        if "location" not in config and self.coordinate is not None:
            config["location"] = self.coordinate.model_dump()
        if "measurement_type" not in config and self.measurement_type is not None:
            config["measurement_type"] = self.measurement_type
        if "hub_height_m" not in config and self.hub_height_m is not None:
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
        """Return the runtime data directory, preferring the session workspace when configured."""
        data_dir = self.workspace_dir if self.workspace_dir is not None else Path("data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir)


session = SessionState()
