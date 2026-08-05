"""config — Phase 1 MCP tools for run configuration management.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

from server.main import mcp
from server.schemas.common import Coordinate
from server.state.session import SessionState, session


def _speed_sensor_columns(state: SessionState) -> list[str]:
    """Return mapped wind-speed columns present in the loaded measured dataframe."""
    if state.timeseries_df is None:
        return []
    return [
        str(mapping["speed_col"])
        for _height, mapping in sorted(state.sensor_mapping.items(), reverse=True)
        if mapping.get("speed_col") in state.timeseries_df.columns
    ]


def _avg_coverage(state: SessionState) -> float | None:
    """Compute mean coverage across mapped wind-speed sensors for overview scorecards."""
    if state.timeseries_df is None:
        return None
    speed_columns = _speed_sensor_columns(state)
    if not speed_columns:
        return None
    coverage_values = [float(state.timeseries_df[column].notna().mean() * 100.0) for column in speed_columns]
    return float(sum(coverage_values) / len(coverage_values))


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


def _normalize_runconfig(config: dict[str, object]) -> dict[str, object]:
    """Promote legacy UI aliases to canonical keys and remove duplicated values."""
    project = config.get("project")
    if isinstance(project, dict):
        if "project_name" not in config and isinstance(project.get("name"), str):
            config["project_name"] = project["name"]
        if "measurement_type" not in config and isinstance(project.get("measurementType"), str):
            config["measurement_type"] = project["measurementType"]
        project.pop("name", None)
        project.pop("measurementType", None)

    site = config.get("site")
    if isinstance(site, dict):
        location = config.get("location")
        if not isinstance(location, dict):
            location = {}
            config["location"] = location
        for legacy_key, canonical_key in (("latitude", "latitude"), ("longitude", "longitude"), ("elevationM", "elevation_m")):
            if canonical_key not in location and legacy_key in site:
                location[canonical_key] = site[legacy_key]
            site.pop(legacy_key, None)
        if "hub_height_m" not in config and "hubHeightM" in site:
            config["hub_height_m"] = site["hubHeightM"]
        site.pop("hubHeightM", None)

    shear = config.get("shear")
    if isinstance(shear, dict):
        shear.pop("targetHubHeightM", None)

    reanalysis = config.get("reanalysis")
    if isinstance(reanalysis, dict):
        reanalysis.pop("searchLatitude", None)
        reanalysis.pop("searchLongitude", None)

    ltc = config.get("ltc")
    if isinstance(ltc, dict):
        uncertainty = ltc.get("uncertainty")
        if isinstance(uncertainty, dict):
            uncertainty.pop("hubHeightM", None)

    return config


def _sync_state_from_runconfig(state: SessionState) -> None:
    """Project known runconfig fields back onto session state per the GoKaatru session model."""
    config = _normalize_runconfig(state.runconfig)
    state.coordinate = None
    state.project_name = None
    state.measurement_type = None
    state.hub_height_m = None
    location = config.get("location")
    if isinstance(location, dict) and {"latitude", "longitude"}.issubset(location):
        latitude = float(location["latitude"])
        longitude = float(location["longitude"])
        elevation = float(location.get("elevation_m", 0.0))
        state.set_coordinate(Coordinate(latitude=latitude, longitude=longitude, elevation_m=elevation))
    if "project_name" in config and isinstance(config["project_name"], str):
        state.set_project_name(str(config["project_name"]))
    if "measurement_type" in config and isinstance(config["measurement_type"], str):
        state.set_measurement_type(str(config["measurement_type"]))
    if "hub_height_m" in config and isinstance(config["hub_height_m"], (int, float)):
        state.set_hub_height_m(float(config["hub_height_m"]))


def _runconfig_path(state: SessionState) -> Path:
    """Resolve the standard Phase 1 runconfig file path beneath the data directory."""
    return Path(state.get_data_dir()) / "runconfig.json"


def _get_run_config(state: SessionState) -> dict:
    """Return the active run configuration dictionary defined by the GoKaatru Phase 1 config spec."""
    _normalize_runconfig(state.runconfig)
    state.runconfig = _normalize_runconfig(state.to_runconfig())
    return dict(state.runconfig)


def _update_run_config(state: SessionState, key: str, value: str) -> dict:
    """Update a dotted runconfig key using JSON parsing rules from the Phase 1 config manager spec."""
    _set_nested_value(state.runconfig, key, _parse_config_value(value))
    _sync_state_from_runconfig(state)
    _normalize_runconfig(state.runconfig)
    state.runconfig = _normalize_runconfig(state.to_runconfig())
    return dict(state.runconfig)


def _save_run_config(state: SessionState) -> dict:
    """Write the current run configuration to data/runconfig.json per the Phase 1 persistence spec."""
    _normalize_runconfig(state.runconfig)
    state.runconfig = _normalize_runconfig(state.to_runconfig())
    runconfig_path = _runconfig_path(state)
    runconfig_path.write_text(json.dumps(state.runconfig, indent=2), encoding="utf-8")
    return {"status": "ok", "file_path": str(runconfig_path), "keys": sorted(state.runconfig.keys())}


def _persist_runconfig(state: SessionState) -> None:
    """Write-through helper: persist the current runconfig to runconfig.json.

    runconfig.json in the session workspace is the single source of truth, so
    every in-memory mutation (dataset load, BrightHub import, scenario import)
    must call this to keep the on-disk file authoritative.
    """
    if state.workspace_dir is None:
        return
    _save_run_config(state)


def _load_run_config(state: SessionState) -> dict:
    """Load data/runconfig.json into session state following the Phase 1 configuration workflow."""
    runconfig_path = _runconfig_path(state)
    if not runconfig_path.exists():
        raise ValueError(f"Run configuration file not found: {runconfig_path}")
    state.runconfig = json.loads(runconfig_path.read_text(encoding="utf-8"))
    _sync_state_from_runconfig(state)
    return dict(state.runconfig)


def _get_analysis_summary(state: SessionState) -> dict:
    """Report Phase 1 analysis readiness flags based on populated session-state fields."""
    coordinate = state.get_coordinate()
    speed_columns = _speed_sensor_columns(state)
    return {
        "project_name": state.get_project_name(),
        "hub_height_m": state.get_hub_height_m(),
        "timeseries_loaded": state.timeseries_df is not None,
        "sensor_mapping_loaded": bool(state.sensor_mapping),
        "sensor_count": len(speed_columns),
        "avg_coverage_pct": _avg_coverage(state),
        "cleaning_rules_applied": len(state.cleaning_log),
        "shear_table_ready": state.shear_table is not None,
        "roughness_table_ready": state.roughness_table is not None,
        "era5_nodes_loaded": state.era5_nodes is not None,
        "era5_data_sets_loaded": len(state.era5_data),
        "era5_interpolated_ready": state.era5_interpolated_df is not None,
        "ltc_algorithms_run": sorted(state.ltc_results.keys()),
        "ensemble_ready": state.ensemble_df is not None,
        "scenario_count": len(state.scenarios),
        "coordinate": None if coordinate is None else coordinate.model_dump(),
    }


@mcp.tool()
def get_run_config() -> dict:
    """Return the active run configuration dictionary defined by the GoKaatru Phase 1 config spec."""
    return _get_run_config(session)


@mcp.tool()
def update_run_config(key: str, value: str) -> dict:
    """Update a dotted runconfig key using JSON parsing rules from the Phase 1 config manager spec."""
    return _update_run_config(session, key, value)


@mcp.tool()
def save_run_config() -> dict:
    """Write the current run configuration to data/runconfig.json per the Phase 1 persistence spec."""
    return _save_run_config(session)


@mcp.tool()
def load_run_config() -> dict:
    """Load data/runconfig.json into session state following the Phase 1 configuration workflow."""
    return _load_run_config(session)


@mcp.tool()
def get_analysis_summary() -> dict:
    """Report Phase 1 analysis readiness flags based on populated session-state fields."""
    return _get_analysis_summary(session)
