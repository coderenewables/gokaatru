"""Measurement-system diagnostics for the Sensor Overview."""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.core.validators import detect_timestep_minutes, rolling_median_mad_spike_mask
from server.main import mcp
from server.state.session import SessionState, session

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _require_frame(state: SessionState) -> pd.DataFrame:
    """Return the loaded measured frame required by sensor diagnostics."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return state.timeseries_df


def _speed_candidates(state: SessionState) -> list[str]:
    """Return parsed wind-speed inventory columns in deterministic height/name order."""
    frame = _require_frame(state)
    candidates = [
        (float(metadata.get("height_m", 0.0)), name)
        for name, metadata in state.sensor_inventory.items()
        if metadata.get("sensor_type") == "wind_speed" and name in frame.columns
    ]
    if not candidates:
        candidates = [(float(height), str(mapping["speed_col"])) for height, mapping in state.sensor_mapping.items() if mapping.get("speed_col") in frame.columns]
    return [name for _height, name in sorted(candidates, reverse=True)]


def _default_comparison_pair(state: SessionState) -> tuple[str, str]:
    """Choose a same-height pair when available, otherwise the two tallest speed measurements."""
    frame = _require_frame(state)
    grouped: dict[float, list[str]] = {}
    for name, metadata in state.sensor_inventory.items():
        if metadata.get("sensor_type") == "wind_speed" and name in frame.columns:
            grouped.setdefault(float(metadata.get("height_m", 0.0)), []).append(name)
    for names in grouped.values():
        if len(names) >= 2:
            ordered = sorted(names)
            return ordered[0], ordered[1]
    candidates = _speed_candidates(state)
    if len(candidates) < 2:
        raise ValueError("Sensor comparison requires at least two wind-speed sensors")
    return candidates[0], candidates[1]


def _aligned_pair(state: SessionState, sensor_a: str, sensor_b: str) -> pd.DataFrame:
    """Align two valid measured sensor series for comparison diagnostics."""
    frame = _require_frame(state)
    if sensor_a not in frame.columns or sensor_b not in frame.columns:
        raise ValueError("Both comparison sensor columns must exist in the loaded timeseries")
    pair = frame[[sensor_a, sensor_b]].dropna()
    if pair.empty:
        raise ValueError("No concurrent valid records exist for the selected sensor pair")
    return pair


def _comparison_metrics(pair: pd.DataFrame, sensor_a: str, sensor_b: str) -> dict[str, float]:
    """Compute regression, correlation, residual, and bias metrics for an aligned sensor pair."""
    x_values = pair[sensor_a].to_numpy(dtype=float)
    y_values = pair[sensor_b].to_numpy(dtype=float)
    centered_x = x_values - x_values.mean()
    centered_y = y_values - y_values.mean()
    denominator = float(np.sum(centered_x**2))
    slope = 0.0 if denominator <= 1e-12 else float(np.sum(centered_x * centered_y) / denominator)
    offset = float(y_values.mean() - slope * x_values.mean())
    residuals = y_values - x_values
    correlation = 0.0 if np.std(x_values) == 0 or np.std(y_values) == 0 else float(np.corrcoef(x_values, y_values)[0, 1])
    return {
        "correlation": correlation,
        "r_squared": correlation**2,
        "slope": slope,
        "offset": offset,
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "bias": float(residuals.mean()),
        "record_count": int(len(pair)),
    }


def _compute_sensor_comparison(state: SessionState, sensor_a: str = "", sensor_b: str = "") -> dict:
    """Return concurrent sensor-comparison metrics and a downsampled residual series."""
    default_a, default_b = _default_comparison_pair(state) if not (sensor_a and sensor_b) else (sensor_a, sensor_b)
    pair = _aligned_pair(state, default_a, default_b)
    residual = (pair[default_b] - pair[default_a]).rename("residual")
    sampled = residual.resample("D").mean() if len(residual) > 50_000 else residual.iloc[:: max(1, len(residual) // 10_000)]
    return {
        "sensor_a": default_a,
        "sensor_b": default_b,
        **_comparison_metrics(pair, default_a, default_b),
        "residuals": [{"timestamp": timestamp.isoformat(), "value": float(value)} for timestamp, value in sampled.items()],
    }


def _default_direction_sensor(state: SessionState) -> str:
    """Choose the tallest available wind-direction sensor for sector diagnostics."""
    frame = _require_frame(state)
    candidates = [
        (float(metadata.get("height_m", 0.0)), name)
        for name, metadata in state.sensor_inventory.items()
        if metadata.get("sensor_type") == "wind_direction" and name in frame.columns
    ]
    if not candidates:
        candidates = [(float(height), str(mapping["dir_col"])) for height, mapping in state.sensor_mapping.items() if mapping.get("dir_col") in frame.columns]
    if not candidates:
        raise ValueError("Mast-effect analysis requires a wind-direction sensor")
    return max(candidates)[1]


def _compute_mast_effects(state: SessionState, sensor_a: str = "", sensor_b: str = "", direction_sensor: str = "") -> dict:
    """Compare speed ratio by direction to identify potential mast-shadow sectors."""
    if not (sensor_a and sensor_b):
        sensor_a, sensor_b = _default_comparison_pair(state)
    if not direction_sensor:
        direction_sensor = _default_direction_sensor(state)
    frame = _require_frame(state)
    if direction_sensor not in frame.columns:
        raise ValueError(f"Direction sensor '{direction_sensor}' not found in loaded timeseries")
    aligned = frame[[sensor_a, sensor_b, direction_sensor]].dropna()
    aligned = aligned[(aligned[sensor_a] > 0.1) & (aligned[sensor_b] > 0.1)]
    if aligned.empty:
        raise ValueError("Mast-effect analysis requires concurrent positive speed records")
    sector_index = (((np.mod(aligned[direction_sensor], 360.0) + 11.25) % 360.0) // 22.5).astype(int)
    ratios = aligned[sensor_b] / aligned[sensor_a]
    sectors = []
    for index in range(16):
        sector = ratios[sector_index == index]
        ratio = float(sector.mean()) if not sector.empty else float("nan")
        sectors.append({"label": COMPASS_16[index], "speed_ratio": ratio, "record_count": int(len(sector))})
    valid_ratios = [row["speed_ratio"] for row in sectors if np.isfinite(row["speed_ratio"])]
    baseline = float(np.median(valid_ratios)) if valid_ratios else 1.0
    affected = [row["label"] for row in sectors if np.isfinite(row["speed_ratio"]) and float(row["speed_ratio"]) < baseline * 0.95]
    return {
        "sensor_a": sensor_a,
        "sensor_b": sensor_b,
        "direction_sensor": direction_sensor,
        "baseline_speed_ratio": baseline,
        "affected_sectors": affected,
        "sectors": sectors,
    }


def _spike_count(series: pd.Series, window: int = 11, sigma: float = 4.0) -> int:
    """Count spikes using robust median/MAD outlier detection (same algorithm as spike_filter)."""
    return int(rolling_median_mad_spike_mask(series, window=window, sigma=sigma).fillna(False).sum())


def _flatline_count(series: pd.Series, minimum_count: int = 6) -> int:
    """Count repeated-value records in flat-line runs using the cleaning-stage convention."""
    groups = series.ne(series.shift()) | series.isna()
    sizes = series.groupby(groups.cumsum()).transform("size")
    return int((series.notna() & (sizes >= minimum_count)).sum())


def _compute_qc_diagnostics(state: SessionState) -> dict:
    """Report non-mutating range, spike, flat-line, and existing-cleaning diagnostics per speed sensor."""
    frame = _require_frame(state)
    raw = state.raw_timeseries_df if state.raw_timeseries_df is not None else frame
    rows = []
    for sensor in _speed_candidates(state):
        values = raw[sensor].astype(float)
        removed = int((raw[sensor].notna() & frame[sensor].isna()).sum()) if sensor in frame.columns else 0
        rows.append(
            {
                "sensor": sensor,
                "range_failures": int(((values < 0) | (values > 50)).fillna(False).sum()),
                "spike_failures": _spike_count(values),
                "flatline_records": _flatline_count(values),
                "removed_after_cleaning": removed,
            }
        )
    return {
        "cleaning_rules_applied": len(state.cleaning_log),
        "cleaning_log": [entry.copy() for entry in state.cleaning_log],
        "sensors": rows,
    }


def _compute_mcp_readiness(state: SessionState, speed_sensor: str, reference_sensor: str = "") -> dict:
    """Assess concurrent measured/reference correlation prior to long-term correction."""
    frame = _require_frame(state)
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolation is required before MCP readiness can be assessed")
    reference = reference_sensor or "Spd_100m"
    if reference not in state.era5_interpolated_df.columns:
        raise ValueError(f"Reference column '{reference}' is not available in interpolated ERA5 data")
    measured = frame[[speed_sensor]].resample("h").mean()
    concurrent = measured.join(state.era5_interpolated_df[[reference]], how="inner").dropna()
    if len(concurrent) < 10:
        raise ValueError("MCP readiness requires at least 10 concurrent hourly points")
    concurrent.columns = [speed_sensor, reference]
    metrics = _comparison_metrics(concurrent, reference, speed_sensor)
    adjustment = float(concurrent[reference].mean() / concurrent[speed_sensor].mean()) if concurrent[speed_sensor].mean() > 0 else float("nan")
    return {
        "speed_sensor": speed_sensor,
        "reference_sensor": reference,
        "concurrent_hours": int(len(concurrent)),
        **metrics,
        "long_term_adjustment_factor": adjustment,
        "ready": bool(metrics["r_squared"] >= 0.5 and len(concurrent) >= 720),
    }


@mcp.tool()
def compute_sensor_comparison(sensor_a: str = "", sensor_b: str = "") -> dict:
    """Compute correlation, residual, bias, and regression metrics for two measured speed sensors."""
    return _compute_sensor_comparison(session, sensor_a, sensor_b)


@mcp.tool()
def compute_mast_effects(sensor_a: str = "", sensor_b: str = "", direction_sensor: str = "") -> dict:
    """Identify potential mast-shadow sectors from directional speed-ratio diagnostics."""
    return _compute_mast_effects(session, sensor_a, sensor_b, direction_sensor)


@mcp.tool()
def compute_qc_diagnostics() -> dict:
    """Report non-mutating range, spike, flat-line, and cleaning-removal diagnostics."""
    return _compute_qc_diagnostics(session)


@mcp.tool()
def compute_mcp_readiness(speed_sensor: str, reference_sensor: str = "") -> dict:
    """Assess ERA5 concurrent-period correlation and long-term adjustment readiness."""
    return _compute_mcp_readiness(session, speed_sensor, reference_sensor)