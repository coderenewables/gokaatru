"""config — Phase 1 MCP tools for run configuration management.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

from server.main import mcp
from server.schemas.common import Coordinate
from server.state.session import session


def _parse_config_value(value: str) -> object:
    """Parse config values as JSON first, then preserve raw strings per the Phase 1 config contract."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _set_nested_value(config: dict[str, object], key: str, value: object) -> None:
    """Set a dotted configuration path using nested dictionaries per the Phase 1 runconfig schema."""
    parts = key.split(".")
    cursor = config
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


def _sync_state_from_runconfig() -> None:
    """Project known runconfig fields back onto session state per the GoKaatru session model."""
    config = session.runconfig
    session.coordinate = None
    session.project_name = None
    session.measurement_type = None
    session.hub_height_m = None
    location = config.get("location")
    if isinstance(location, dict) and {"latitude", "longitude"}.issubset(location):
        latitude = float(location["latitude"])
        longitude = float(location["longitude"])
        elevation = float(location.get("elevation_m", 0.0))
        session.set_coordinate(Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation))
    if "project_name" in config and isinstance(config["project_name"], str):
        session.set_project_name(str(config["project_name"]))
    if "measurement_type" in config and isinstance(config["measurement_type"], str):
        session.set_measurement_type(str(config["measurement_type"]))
    if "hub_height_m" in config and isinstance(config["hub_height_m"], (int, float)):
        session.set_hub_height_m(float(config["hub_height_m"]))


def _runconfig_path() -> Path:
    """Resolve the standard Phase 1 runconfig file path beneath the data directory."""
    return Path(session.get_data_dir()) / "runconfig.json"


@mcp.tool()
def get_run_config() -> dict:
    """Return the active run configuration dictionary defined by the GoKaatru Phase 1 config spec."""
    session.runconfig = session.to_runconfig()
    return dict(session.runconfig)


@mcp.tool()
def update_run_config(key: str, value: str) -> dict:
    """Update a dotted runconfig key using JSON parsing rules from the Phase 1 config manager spec."""
    _set_nested_value(session.runconfig, key, _parse_config_value(value))
    _sync_state_from_runconfig()
    session.runconfig = session.to_runconfig()
    return dict(session.runconfig)


@mcp.tool()
def save_run_config() -> dict:
    """Write the current run configuration to data/runconfig.json per the Phase 1 persistence spec."""
    session.runconfig = session.to_runconfig()
    runconfig_path = _runconfig_path()
    runconfig_path.write_text(json.dumps(session.runconfig, indent=2), encoding="utf-8")
    return {"status": "ok", "file_path": str(runconfig_path), "keys": sorted(session.runconfig.keys())}


@mcp.tool()
def load_run_config() -> dict:
    """Load data/runconfig.json into session state following the Phase 1 configuration workflow."""
    runconfig_path = _runconfig_path()
    if not runconfig_path.exists():
        raise ValueError(f"Run configuration file not found: {runconfig_path}")
    session.runconfig = json.loads(runconfig_path.read_text(encoding="utf-8"))
    _sync_state_from_runconfig()
    return dict(session.runconfig)


@mcp.tool()
def get_analysis_summary() -> dict:
    """Report Phase 1 analysis readiness flags based on populated session-state fields."""
    coordinate = session.get_coordinate()
    return {
        "project_name": session.get_project_name(),
        "hub_height_m": session.get_hub_height_m(),
        "timeseries_loaded": session.timeseries_df is not None,
        "sensor_mapping_loaded": bool(session.sensor_mapping),
        "cleaning_rules_applied": len(session.cleaning_log),
        "shear_table_ready": session.shear_table is not None,
        "roughness_table_ready": session.roughness_table is not None,
        "era5_nodes_loaded": session.era5_nodes is not None,
        "era5_data_sets_loaded": len(session.era5_data),
        "era5_interpolated_ready": session.era5_interpolated_df is not None,
        "ltc_algorithms_run": sorted(session.ltc_results.keys()),
        "ensemble_ready": session.ensemble_df is not None,
        "coordinate": None if coordinate is None else coordinate.model_dump(),
    }
