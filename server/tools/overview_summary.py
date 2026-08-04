"""Consolidated bankable Sensor Overview summary table generation."""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from server.state.session import SessionState
from server.tools.advanced_analysis import _compute_energy_metrics, _compute_extremes, _compute_persistence
from server.tools.atmosphere import _compute_atmospheric_conditions
from server.tools.diagnostics import _compute_mcp_readiness, _compute_qc_diagnostics
from server.tools.shear import _compute_vertical_structure
from server.tools.statistics import _compute_turbulence_analysis, _compute_wind_climate


def _primary_speed_sensor(state: SessionState, requested: str) -> str:
    """Resolve an explicit primary speed sensor or select the highest-coverage loaded speed sensor."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if requested:
        if requested not in state.timeseries_df.columns:
            raise ValueError(f"Sensor column '{requested}' not found in loaded timeseries")
        return requested
    candidates = [
        name for name, metadata in state.sensor_inventory.items()
        if metadata.get("sensor_type") == "wind_speed" and name in state.timeseries_df.columns
    ]
    if not candidates:
        candidates = [str(mapping["speed_col"]) for mapping in state.sensor_mapping.values() if mapping.get("speed_col") in state.timeseries_df.columns]
    if not candidates:
        raise ValueError("No wind-speed sensor is available")
    return max(candidates, key=lambda name: int(state.timeseries_df[name].notna().sum()))


def _first_direction_sensor(state: SessionState, requested: str) -> str:
    """Resolve an optional direction sensor for directional summary metrics."""
    if state.timeseries_df is None:
        return ""
    if requested:
        return requested if requested in state.timeseries_df.columns else ""
    candidates = [
        name for name, metadata in state.sensor_inventory.items()
        if metadata.get("sensor_type") == "wind_direction" and name in state.timeseries_df.columns
    ]
    return candidates[0] if candidates else ""


def _entry(category: str, metric: str, value: object, unit: str = "", status: str = "available") -> dict[str, object]:
    """Create a normalized summary-table item for browser rendering."""
    return {"category": category, "metric": metric, "value": value, "unit": unit, "status": status}


def _add_optional(items: list[dict[str, object]], build: Callable[[], dict], add: Callable[[dict], None]) -> None:
    """Append optional diagnostics while retaining the summary when a prerequisite is absent."""
    try:
        add(build())
    except ValueError as exc:
        items.append(_entry("Availability", "Optional analysis", str(exc), status="unavailable"))


def _compute_overview_summary(state: SessionState, speed_sensor: str = "", direction_sensor: str = "") -> dict:
    """Build concise WRA summary rows from all currently available Sensor Overview analyses."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    speed = _primary_speed_sensor(state, speed_sensor)
    direction = _first_direction_sensor(state, direction_sensor)
    frame = state.timeseries_df
    series = frame[speed]
    items: list[dict[str, object]] = [
        _entry("Data quality", "Primary speed sensor", speed),
        _entry("Data quality", "Primary coverage", round(float(series.notna().mean() * 100.0), 2), "%"),
        _entry("Data quality", "Cleaning rules applied", len(state.cleaning_log)),
        _entry("Measurement", "Wind-speed sensors", sum(1 for metadata in state.sensor_inventory.values() if metadata.get("sensor_type") == "wind_speed")),
    ]

    climate = _compute_wind_climate(state, speed, direction)
    items.extend([
        _entry("Wind climate", "Mean wind speed", round(float(climate["mean_speed"]), 3), "m/s"),
        _entry("Wind climate", "Weibull k", round(float(climate["weibull_k"]), 3)),
        _entry("Wind climate", "Weibull A", round(float(climate["weibull_A"]), 3), "m/s"),
        _entry("Wind climate", "P90 exceedance", round(float(climate["exceedance"]["p90"]), 3), "m/s"),
    ])
    if climate["direction"]:
        items.append(_entry("Direction", "Prevailing sector", climate["direction"]["prevailing_sector"]))

    _add_optional(items, lambda: _compute_vertical_structure(state), lambda result: items.extend([
        _entry("Vertical structure", "Mean alpha", round(float(result["alpha"]["mean"]), 3)),
        _entry("Vertical structure", "Power-law R²", round(float(result["power_law_r_squared"]), 3)),
        _entry("Vertical structure", "Mean veer", "N/A" if result["veer"] is None else round(float(result["veer"]["mean_deg_per_100m"]), 3), "deg / 100 m"),
    ]))
    _add_optional(items, lambda: _compute_turbulence_analysis(state, speed), lambda result: items.extend([
        _entry("Turbulence", "Mean TI", round(float(result["mean_ti"]), 3)),
        _entry("Turbulence", "IEC TI near 15 m/s", round(float(result["iec_ti_at_15ms"]), 3)),
    ]))
    _add_optional(items, lambda: _compute_atmospheric_conditions(state), lambda result: items.extend([
        _entry("Atmosphere", "Mean air density", round(float(result["air_density"]["mean"]), 3), "kg/m³"),
        _entry("Atmosphere", "Density correction factor", round(float(result["air_density"]["density_correction_factor"]), 3)),
    ]))
    _add_optional(items, lambda: _compute_energy_metrics(state, speed, direction), lambda result: items.extend([
        _entry("Energy", "Wind power density", round(float(result["wind_power_density_w_m2"]), 1), "W/m²"),
        _entry("Energy", "Cube mean speed", round(float(result["mean_cube_speed_m_s"]), 3), "m/s"),
    ]))
    _add_optional(items, lambda: _compute_extremes(state, speed), lambda result: items.extend([
        _entry("Extremes", "GEV 50-year wind", round(float(result["gev"]["wind_50_year"]), 2), "m/s"),
        _entry("Extremes", "GEV 100-year wind", round(float(result["gev"]["wind_100_year"]), 2), "m/s"),
    ]))
    _add_optional(items, lambda: _compute_persistence(state, speed), lambda result: items.extend([
        _entry("Persistence", "Calm frequency", round(float(result["calm_pct"]), 2), "%"),
        _entry("Persistence", "Longest calm period", round(float(result["max_calm_duration_minutes"]) / 60.0, 2), "h"),
    ]))
    _add_optional(items, lambda: _compute_qc_diagnostics(state), lambda result: items.extend([
        _entry("QC", "Range failures", sum(int(row["range_failures"]) for row in result["sensors"])),
        _entry("QC", "Spike failures", sum(int(row["spike_failures"]) for row in result["sensors"])),
    ]))
    _add_optional(items, lambda: _compute_mcp_readiness(state, speed), lambda result: items.extend([
        _entry("MCP readiness", "Concurrent hours", int(result["concurrent_hours"])),
        _entry("MCP readiness", "Concurrent R²", round(float(result["r_squared"]), 3)),
        _entry("MCP readiness", "Ready", "Yes" if result["ready"] else "Needs review"),
    ]))
    return {"speed_sensor": speed, "direction_sensor": direction or None, "items": items}