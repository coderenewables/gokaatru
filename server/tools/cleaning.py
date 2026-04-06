"""cleaning — Phase 2 MCP tools for rule-based timeseries cleaning.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from server.core.validators import detect_timestep_minutes
from server.main import mcp
from server.state.session import SessionState, session

RULES = {
    "range_check": {"min": 0.0, "max": 50.0},
    "icing_filter": {"temp_threshold_c": 2.0},
    "stuck_sensor": {"consecutive_count": 6},
    "tower_shadow": {"exclude_sectors": [170, 190]},
    "spike_filter": {"window_size": 6, "sigma_threshold": 4.0},
    "timestamp_gap_fill": {},
    "custom_period_exclude": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"},
}


def _float_param(params: dict[str, object], key: str, default: float) -> float:
    """Read a numeric cleaning-rule parameter as float from a parsed JSON object."""
    value = params.get(key, default)
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"Parameter '{key}' must be numeric, got {type(value).__name__}")
    return float(value)


def _int_param(params: dict[str, object], key: str, default: int) -> int:
    """Read an integer cleaning-rule parameter from a parsed JSON object."""
    value = params.get(key, default)
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"Parameter '{key}' must be integer-like, got {type(value).__name__}")
    return int(value)


def _sector_bounds(params: dict[str, object]) -> tuple[float, float]:
    """Read tower-shadow sector bounds from the parsed cleaning-rule parameters."""
    value = params.get("exclude_sectors", [170, 190])
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("exclude_sectors must be a list with start and end degrees")
    start_value, end_value = value[0], value[1]
    if not isinstance(start_value, (int, float, str)) or not isinstance(end_value, (int, float, str)):
        raise ValueError("exclude_sectors values must be numeric")
    return float(start_value), float(end_value)


def _require_timeseries(state: SessionState) -> pd.DataFrame:
    """Return the active timeseries dataframe required for Phase 2 cleaning operations."""
    if state.timeseries_df is None or state.raw_timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return state.timeseries_df


def _parse_params(params: str) -> dict[str, object]:
    """Parse JSON rule parameters for the Phase 2 cleaning tool interface."""
    payload = json.loads(params) if params else {}
    if not isinstance(payload, dict):
        raise ValueError("params must decode to a JSON object")
    return payload


def _date_mask(index: pd.DatetimeIndex, start_date: str, end_date: str) -> np.ndarray:
    """Build an inclusive timestamp mask for optional cleaning date constraints."""
    mask = np.ones(len(index), dtype=bool)
    if start_date:
        mask &= index >= pd.Timestamp(start_date)
    if end_date:
        mask &= index <= pd.Timestamp(end_date)
    return mask


def _mapping_for_sensor(state: SessionState, sensor: str) -> dict[str, str | None]:
    """Find the height-level sensor mapping entry associated with a named speed sensor."""
    for sensor_map in state.sensor_mapping.values():
        if sensor in sensor_map.values():
            return sensor_map
    raise ValueError(f"Sensor '{sensor}' is not present in session.sensor_mapping")


def _apply_range_check(df: pd.DataFrame, sensor: str, mask: np.ndarray, params: dict[str, object]) -> int:
    """Apply min-max threshold cleaning to a single sensor column."""
    min_value = _float_param(params, "min", 0.0)
    max_value = _float_param(params, "max", 50.0)
    affected = mask & ((df[sensor] < min_value) | (df[sensor] > max_value)) & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_icing_filter(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> int:
    """Apply an icing filter where zero standard deviation and low temperature indicate frozen instrumentation."""
    sensor_map = _mapping_for_sensor(state, sensor)
    sd_col = sensor_map.get("sd_col")
    temp_col = sensor_map.get("temp_col")
    if sd_col not in df.columns or temp_col not in df.columns:
        raise ValueError("icing_filter requires matching sd and temperature columns in the timeseries")
    threshold = _float_param(params, "temp_threshold_c", 2.0)
    affected = mask & (df[sd_col].fillna(np.nan) == 0).to_numpy() & (df[temp_col] < threshold).fillna(False).to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_stuck_sensor(df: pd.DataFrame, sensor: str, mask: np.ndarray, params: dict[str, object]) -> int:
    """Remove runs of repeated identical values using a minimum consecutive-count threshold."""
    threshold = _int_param(params, "consecutive_count", 6)
    series = df[sensor]
    groups = series.ne(series.shift()) | series.isna()
    run_ids = groups.cumsum()
    run_lengths = series.groupby(run_ids).transform("size")
    affected = mask & series.notna().to_numpy() & (run_lengths >= threshold).to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_tower_shadow(
    state: SessionState,
    df: pd.DataFrame,
    sensor: str,
    mask: np.ndarray,
    params: dict[str, object],
) -> int:
    """Remove tower-shadow sectors using the paired direction sensor at the same measurement height."""
    sensor_map = _mapping_for_sensor(state, sensor)
    direction_col = sensor_map.get("dir_col")
    if direction_col not in df.columns:
        raise ValueError("tower_shadow requires a paired direction column in session.sensor_mapping")
    start_deg, end_deg = _sector_bounds(params)
    directions = df[direction_col].to_numpy(dtype=float)
    sector_mask = (
        (directions >= start_deg) & (directions <= end_deg)
        if start_deg <= end_deg
        else (directions >= start_deg) | (directions <= end_deg)
    )
    affected = mask & sector_mask & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_spike_filter(df: pd.DataFrame, sensor: str, mask: np.ndarray, params: dict[str, object]) -> int:
    """Remove spikes outside rolling mean plus-minus sigma-threshold times rolling standard deviation."""
    window = _int_param(params, "window_size", 6)
    sigma = _float_param(params, "sigma_threshold", 4.0)
    mean = df[sensor].rolling(window=window, min_periods=2, center=True).mean()
    std = df[sensor].rolling(window=window, min_periods=2, center=True).std(ddof=0)
    spike_mask = (np.abs(df[sensor] - mean) > sigma * std).fillna(False).to_numpy()
    affected = mask & spike_mask
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_timestamp_gap_fill(state: SessionState, df: pd.DataFrame, start_date: str, end_date: str) -> int:
    """Insert missing timestamps at the inferred base frequency to expose data gaps explicitly."""
    timestep_minutes = detect_timestep_minutes(df)
    full_index = pd.date_range(df.index.min(), df.index.max(), freq=f"{timestep_minutes}min")
    before_index = df.index
    state.timeseries_df = df.reindex(full_index)
    inserted = state.timeseries_df.index.difference(before_index)
    inserted_mask = (
        _date_mask(pd.DatetimeIndex(inserted), start_date, end_date)
        if len(inserted)
        else np.array([], dtype=bool)
    )
    return int(inserted_mask.sum())


def _apply_custom_period_exclude(df: pd.DataFrame, sensor: str, mask: np.ndarray) -> int:
    """Set a sensor to NaN over a user-defined inclusive date range."""
    affected = mask & df[sensor].notna().to_numpy()
    df.loc[affected, sensor] = np.nan
    return int(affected.sum())


def _apply_rule(
    state: SessionState,
    rule_type: str,
    sensor: str,
    params: dict[str, object],
    start_date: str,
    end_date: str,
) -> int:
    """Dispatch a cleaning rule implementation to the active session dataframe."""
    df = _require_timeseries(state)
    if rule_type != "timestamp_gap_fill" and sensor not in df.columns:
        raise ValueError(f"Sensor column '{sensor}' not found in loaded timeseries")
    mask = _date_mask(pd.DatetimeIndex(df.index), start_date, end_date)
    if rule_type == "range_check":
        return _apply_range_check(df, sensor, mask, params)
    if rule_type == "icing_filter":
        return _apply_icing_filter(state, df, sensor, mask, params)
    if rule_type == "stuck_sensor":
        return _apply_stuck_sensor(df, sensor, mask, params)
    if rule_type == "tower_shadow":
        return _apply_tower_shadow(state, df, sensor, mask, params)
    if rule_type == "spike_filter":
        return _apply_spike_filter(df, sensor, mask, params)
    if rule_type == "timestamp_gap_fill":
        return _apply_timestamp_gap_fill(state, df, start_date, end_date)
    return _apply_custom_period_exclude(df, sensor, mask)


def _list_cleaning_rules(_state: SessionState) -> dict:
    """List supported cleaning rules and default parameters for the GoKaatru Phase 2 cleaning workflow."""
    rules = [
        {"name": name, "description": name.replace("_", " "), "default_params": params}
        for name, params in RULES.items()
    ]
    return {"rules": rules}


def _apply_cleaning_rule(
    state: SessionState,
    rule_type: str,
    sensor: str,
    params: str,
    start_date: str = "",
    end_date: str = "",
) -> dict:
    """Apply one named cleaning rule to the active timeseries and log the operation for undo."""
    if rule_type not in RULES:
        raise ValueError(f"Unknown cleaning rule '{rule_type}'")
    parsed = _parse_params(params)
    records_affected = _apply_rule(state, rule_type, sensor, parsed, start_date, end_date)
    entry: dict[str, object] = {
        "rule_type": rule_type,
        "sensor": sensor,
        "records_affected": records_affected,
        "applied_at": datetime.utcnow().isoformat(timespec="seconds"),
        "params": parsed,
        "start_date": start_date,
        "end_date": end_date,
    }
    state.cleaning_log.append(entry)
    return {"status": "ok", "rule": rule_type, "sensor": sensor, "records_affected": records_affected}


def _get_cleaning_log(state: SessionState) -> dict:
    """Return the recorded cleaning operations applied to the active session timeseries."""
    return {"entries": [entry.copy() for entry in state.cleaning_log]}


def _undo_cleaning_rule(state: SessionState, entry_index: int) -> dict:
    """Restore raw data and replay all cleaning steps except the selected log entry."""
    if state.raw_timeseries_df is None:
        raise ValueError("Raw timeseries backup is not available")
    if entry_index < 0 or entry_index >= len(state.cleaning_log):
        raise ValueError(f"Cleaning log entry_index out of range: {entry_index}")
    retained = [entry.copy() for idx, entry in enumerate(state.cleaning_log) if idx != entry_index]
    state.timeseries_df = state.raw_timeseries_df.copy(deep=True)
    state.cleaning_log = []
    for entry in retained:
        params = json.dumps(entry.get("params", {}))
        _apply_cleaning_rule(
            state,
            str(entry["rule_type"]),
            str(entry["sensor"]),
            params,
            str(entry.get("start_date", "")),
            str(entry.get("end_date", "")),
        )
    state.cleaning_log = retained
    return {"status": "ok", "remaining_rules": len(state.cleaning_log)}


@mcp.tool()
def list_cleaning_rules() -> dict:
    """List supported cleaning rules and default parameters for the GoKaatru Phase 2 cleaning workflow."""
    return _list_cleaning_rules(session)


@mcp.tool()
def apply_cleaning_rule(rule_type: str, sensor: str, params: str, start_date: str = "", end_date: str = "") -> dict:
    """Apply one named cleaning rule to the active timeseries and log the operation for undo."""
    return _apply_cleaning_rule(session, rule_type, sensor, params, start_date, end_date)


@mcp.tool()
def get_cleaning_log() -> dict:
    """Return the recorded cleaning operations applied to the active session timeseries."""
    return _get_cleaning_log(session)


@mcp.tool()
def undo_cleaning_rule(entry_index: int) -> dict:
    """Restore raw data and replay all cleaning steps except the selected log entry."""
    return _undo_cleaning_rule(session, entry_index)
