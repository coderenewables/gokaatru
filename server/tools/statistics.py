"""statistics — Phase 1 statistical MCP tools for wind data summaries.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import weibull_min

from server.core.momm import MEAN_DAYS_IN_MONTH, compute_weighted_momm_table
from server.core.validators import detect_timestep_minutes
from server.main import mcp
from server.state.session import SessionState, session

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _require_series_from_state(state: SessionState, sensor_name: str) -> pd.Series:
    """Return a loaded sensor series using the Phase 1 timeseries access contract."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    if sensor_name not in state.timeseries_df.columns:
        raise ValueError(f"Sensor column '{sensor_name}' not found in loaded timeseries")
    return state.timeseries_df[sensor_name]


def _require_series(sensor_name: str) -> pd.Series:
    """Return a loaded sensor series using the Phase 1 timeseries access contract."""
    return _require_series_from_state(session, sensor_name)


def _align_pair_from_state(state: SessionState, sensor_a: str, sensor_b: str) -> pd.DataFrame:
    """Build an inner-joined two-column dataset per the Phase 1 scatter-statistics workflow."""
    pair = pd.concat(
        [_require_series_from_state(state, sensor_a), _require_series_from_state(state, sensor_b)],
        axis=1,
        join="inner",
    )
    pair.columns = [sensor_a, sensor_b]
    aligned = pair.dropna()
    if aligned.empty:
        raise ValueError(f"No concurrent valid data between '{sensor_a}' and '{sensor_b}'")
    return aligned


def _align_pair(sensor_a: str, sensor_b: str) -> pd.DataFrame:
    """Build an inner-joined two-column dataset per the Phase 1 scatter-statistics workflow."""
    return _align_pair_from_state(session, sensor_a, sensor_b)


def _sector_label(index: int, num_sectors: int) -> str:
    """Return a direction-sector label using standard 16-point compass naming when available."""
    if num_sectors == 16:
        return COMPASS_16[index]
    if num_sectors == 8:
        return COMPASS_16[index * 2]
    sector_width = 360.0 / num_sectors
    start = index * sector_width
    end = start + sector_width
    return f"{start:.0f}-{end:.0f}"


def _r_squared(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Compute coefficient of determination using the standard least-squares definition."""
    residual_ss = float(np.sum((observed - predicted) ** 2))
    total_ss = float(np.sum((observed - observed.mean()) ** 2))
    if total_ss == 0:
        return 1.0
    return 1.0 - residual_ss / total_ss


def _flat_month_weights() -> np.ndarray:
    """Broadcast month-length weights across all 24 hours for Windographer-style MoMM aggregation."""
    return np.repeat([MEAN_DAYS_IN_MONTH[month] for month in range(1, 13)], 24)


def _compute_weibull_params(state: SessionState, sensor_name: str) -> dict:
    """Fit Weibull A and k using scipy.stats.weibull_min.fit with floc = 0 for wind-speed analysis."""
    series = _require_series_from_state(state, sensor_name).dropna()
    positive = series[series > 0]
    if positive.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no positive wind-speed values for Weibull fitting")
    shape_k, _, scale_a = weibull_min.fit(positive.to_numpy(), floc=0)
    return {
        "sensor": sensor_name,
        "k": float(shape_k),
        "A": float(scale_a),
        "mean_speed": float(positive.mean()),
        "record_count": int(len(positive)),
    }


def _compute_diurnal_profile(state: SessionState, sensor_name: str) -> dict:
    """Compute hour-of-day mean wind speed using the Phase 1 diurnal profile convention."""
    series = _require_series_from_state(state, sensor_name)
    hourly = series.groupby(series.index.hour).mean().reindex(range(24))
    return {
        "sensor": sensor_name,
        "hours": list(range(24)),
        "mean_speeds": [float(value) if pd.notna(value) else float("nan") for value in hourly.tolist()],
    }


def _compute_monthly_stats(state: SessionState, sensor_name: str) -> dict:
    """Compute monthly mean, min, max, and coverage using the Phase 1 monthly-summary specification."""
    series = _require_series_from_state(state, sensor_name)
    timestep_minutes = detect_timestep_minutes(series.to_frame())
    full_index = pd.date_range(series.index.min(), series.index.max(), freq=f"{timestep_minutes}min")
    reindexed = series.reindex(full_index)
    months: list[dict[str, object]] = []
    for month in range(1, 13):
        monthly = reindexed[reindexed.index.month == month]
        valid = monthly.dropna()
        months.append(
            {
                "month": month,
                "mean": float(valid.mean()) if not valid.empty else float("nan"),
                "min": float(valid.min()) if not valid.empty else float("nan"),
                "max": float(valid.max()) if not valid.empty else float("nan"),
                "coverage_pct": 0.0 if monthly.empty else float(valid.count() / len(monthly) * 100.0),
            }
        )
    return {"sensor": sensor_name, "months": months}


def _compute_scatter_stats(state: SessionState, sensor_a: str, sensor_b: str) -> dict:
    """Compute OLS scatter metrics using standard regression diagnostics from least-squares analysis."""
    aligned = _align_pair_from_state(state, sensor_a, sensor_b)
    x_values = aligned[sensor_a].to_numpy(dtype=float)
    y_values = aligned[sensor_b].to_numpy(dtype=float)
    mean_x = float(np.mean(x_values))
    mean_y = float(np.mean(y_values))
    centered_x = x_values - mean_x
    centered_y = y_values - mean_y
    denominator = float(np.sum(centered_x**2))
    slope = 0.0 if denominator <= 1e-12 else float(np.sum(centered_x * centered_y) / denominator)
    intercept = float(mean_y - slope * mean_x)
    predicted = slope * x_values + intercept
    residuals = y_values - predicted
    return {
        "sensor_a": sensor_a,
        "sensor_b": sensor_b,
        "r2": _r_squared(y_values, predicted),
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "mae": float(np.mean(np.abs(residuals))),
        "mbe": float(np.mean(residuals)),
        "slope": float(slope),
        "intercept": float(intercept),
        "count": int(len(aligned)),
    }


def _compute_wind_climate(state: SessionState, speed_sensor: str, direction_sensor: str = "") -> dict:
    """Summarize fit quality, exceedance levels, and optional directional energy for the overview."""
    speed = _require_series_from_state(state, speed_sensor).dropna()
    positive = speed[speed > 0]
    if positive.empty:
        raise ValueError(f"Sensor '{speed_sensor}' has no positive wind-speed values")
    shape_k, _, scale_a = weibull_min.fit(positive.to_numpy(dtype=float), floc=0)
    bin_edges = np.histogram_bin_edges(positive.to_numpy(dtype=float), bins="auto")
    observed, _ = np.histogram(positive.to_numpy(dtype=float), bins=bin_edges, density=True)
    bin_centres = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    fitted = weibull_min.pdf(bin_centres, shape_k, loc=0, scale=scale_a)
    rmse = float(np.sqrt(np.mean((observed - fitted) ** 2)))
    direction: dict[str, object] | None = None
    sectors: list[dict[str, object]] = []
    if direction_sensor:
        aligned = _align_pair_from_state(state, speed_sensor, direction_sensor)
        directions = np.mod(aligned[direction_sensor].to_numpy(dtype=float), 360.0)
        radians = np.deg2rad(directions)
        mean_direction = float(np.rad2deg(np.arctan2(np.mean(np.sin(radians)), np.mean(np.cos(radians)))) % 360.0)
        resultant_length = float(np.hypot(np.mean(np.cos(radians)), np.mean(np.sin(radians))))
        sector_width = 22.5
        sector_index = (((directions + sector_width / 2.0) % 360.0) // sector_width).astype(int)
        cube_speeds = aligned[speed_sensor].to_numpy(dtype=float) ** 3
        total_cube_speed = float(cube_speeds.sum())
        for index in range(16):
            mask = sector_index == index
            occurrence = float(mask.sum() / len(aligned) * 100.0)
            energy_pct = 0.0 if total_cube_speed == 0 else float(cube_speeds[mask].sum() / total_cube_speed * 100.0)
            sectors.append(
                {
                    "center_deg": float(index * sector_width),
                    "label": _sector_label(index, 16),
                    "occurrence_pct": occurrence,
                    "mean_speed": float(aligned.loc[mask, speed_sensor].mean()) if mask.any() else 0.0,
                    "energy_pct": energy_pct,
                }
            )
        direction = {
            "sensor_name": direction_sensor,
            "mean_direction_deg": mean_direction,
            "circular_variance": float(1.0 - resultant_length),
            "prevailing_sector": max(sectors, key=lambda sector: float(sector["occurrence_pct"]))["label"],
        }
    exceedance = {f"p{level}": float(positive.quantile(1.0 - level / 100.0)) for level in (50, 75, 90, 95)}
    return {
        "speed_sensor": speed_sensor,
        "record_count": int(len(positive)),
        "mean_speed": float(positive.mean()),
        "cube_mean_speed": float(np.cbrt(np.mean(positive.to_numpy(dtype=float) ** 3))),
        "weibull_k": float(shape_k),
        "weibull_A": float(scale_a),
        "weibull_rmse": rmse,
        "exceedance": exceedance,
        "direction": direction,
        "sectors": sectors,
    }


def _find_turbulence_sd_sensor(state: SessionState, speed_sensor: str) -> str:
    """Find the conventional standard-deviation channel associated with a speed sensor."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    candidates = [f"{speed_sensor}_sd", f"{speed_sensor}_std", f"{speed_sensor}_stdev"]
    for candidate in candidates:
        if candidate in state.timeseries_df.columns:
            return candidate
    raise ValueError(f"No standard-deviation channel is available for '{speed_sensor}'")


def _compute_turbulence_analysis(state: SessionState, speed_sensor: str) -> dict:
    """Compute IEC-style TI metrics from a speed sensor and its matching standard-deviation channel."""
    sd_sensor = _find_turbulence_sd_sensor(state, speed_sensor)
    aligned = _align_pair_from_state(state, speed_sensor, sd_sensor)
    valid = aligned[(aligned[speed_sensor] > 3.0) & (aligned[sd_sensor] >= 0.0)].copy()
    valid["ti"] = valid[sd_sensor] / valid[speed_sensor]
    valid = valid.replace([np.inf, -np.inf], np.nan).dropna(subset=["ti"])
    if valid.empty:
        raise ValueError("No speed > 3 m/s records with non-negative standard deviation are available for TI")
    valid["speed_bin"] = np.floor(valid[speed_sensor]).astype(int)
    grouped = valid.groupby("speed_bin", observed=False)["ti"]
    representative = grouped.mean() + 1.28 * grouped.std(ddof=0).fillna(0.0)
    at_15 = representative.iloc[(representative.index.to_numpy(dtype=float) - 15.0).argmin()]
    return {
        "speed_sensor": speed_sensor,
        "sd_sensor": sd_sensor,
        "record_count": int(len(valid)),
        "mean_ti": float(valid["ti"].mean()),
        "p90_ti": float(valid["ti"].quantile(0.90)),
        "representative_ti": float(representative.mean()),
        "iec_ti_at_15ms": float(at_15),
    }


def _sensor_statistics(state: SessionState, sensor_name: str) -> dict:
    """Build a comprehensive per-sensor statistics payload for the browser data-explorer workflow."""
    series = _require_series_from_state(state, sensor_name)
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    coverage_pct = float(series.notna().sum() / len(state.timeseries_df) * 100.0) if len(state.timeseries_df) else 0.0
    valid = series.dropna()
    if valid.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no valid observations")
    is_wind_speed = any(mapping.get("speed_col") == sensor_name for mapping in state.sensor_mapping.values())
    weibull = _compute_weibull_params(state, sensor_name) if is_wind_speed else None
    monthly_stats = _compute_monthly_stats(state, sensor_name)
    diurnal = _compute_diurnal_profile(state, sensor_name)
    percentiles = valid.quantile([0.10, 0.25, 0.50, 0.75, 0.90, 0.99])
    return {
        "sensor_name": sensor_name,
        "mean": float(valid.mean()),
        "median": float(valid.median()),
        "std": float(valid.std(ddof=0)),
        "min_value": float(valid.min()),
        "max_value": float(valid.max()),
        "count": int(valid.count()),
        "coverage_pct": coverage_pct,
        "weibull_k": float(weibull["k"]) if weibull else None,
        "weibull_A": float(weibull["A"]) if weibull else None,
        "monthly_means": [float(month["mean"]) for month in monthly_stats["months"]],
        "diurnal_means": [float(value) for value in diurnal["mean_speeds"]],
        "percentiles": {
            "p10": float(percentiles.loc[0.10]),
            "p25": float(percentiles.loc[0.25]),
            "p50": float(percentiles.loc[0.50]),
            "p75": float(percentiles.loc[0.75]),
            "p90": float(percentiles.loc[0.90]),
            "p99": float(percentiles.loc[0.99]),
        },
    }


@mcp.tool()
def compute_weibull_params(sensor_name: str) -> dict:
    """Fit Weibull A and k using scipy.stats.weibull_min.fit with floc = 0 for wind-speed analysis."""
    return _compute_weibull_params(session, sensor_name)


@mcp.tool()
def compute_wind_climate(speed_sensor: str, direction_sensor: str = "") -> dict:
    """Summarize Weibull fit quality, exceedance levels, and optional directional energy contribution."""
    return _compute_wind_climate(session, speed_sensor, direction_sensor)


@mcp.tool()
def compute_turbulence_analysis(speed_sensor: str) -> dict:
    """Compute mean, P90, representative, and 15 m/s IEC turbulence intensity metrics."""
    return _compute_turbulence_analysis(session, speed_sensor)


@mcp.tool()
def compute_windrose_data(speed_sensor: str, direction_sensor: str, num_sectors: int = 16) -> dict:
    """Aggregate windrose sector frequency and mean speed per IEC 61400-12-1 directional binning practice."""
    if num_sectors <= 0:
        raise ValueError(f"num_sectors must be positive, got {num_sectors}")
    aligned = _align_pair(speed_sensor, direction_sensor)
    sector_width = 360.0 / num_sectors
    sector_index = (((aligned[direction_sensor] + sector_width / 2.0) % 360.0) // sector_width).astype(int)
    sectors: list[dict[str, object]] = []
    for index in range(num_sectors):
        mask = sector_index == index
        subset = aligned.loc[mask, speed_sensor]
        sectors.append(
            {
                "center_deg": float((index * sector_width) % 360.0),
                "label": _sector_label(index, num_sectors),
                "frequency_pct": float(mask.sum() / len(aligned) * 100.0),
                "mean_speed": 0.0 if subset.empty else float(subset.mean()),
            }
        )
    return {"sectors": sectors}


@mcp.tool()
def compute_diurnal_profile(sensor_name: str) -> dict:
    """Compute hour-of-day mean wind speed using the Phase 1 diurnal profile convention."""
    return _compute_diurnal_profile(session, sensor_name)


@mcp.tool()
def compute_monthly_stats(sensor_name: str) -> dict:
    """Compute monthly mean, min, max, and coverage using the Phase 1 monthly-summary specification."""
    return _compute_monthly_stats(session, sensor_name)


@mcp.tool()
def compute_turbulence_intensity(speed_sensor: str, sd_sensor: str) -> dict:
    """Compute mean and representative TI by 1 m/s bins per IEC 61400-1 Ed.4 Section 6.3."""
    aligned = _align_pair(speed_sensor, sd_sensor)
    valid = aligned[(aligned[speed_sensor] > 0) & (aligned[sd_sensor] >= 0)].copy()
    valid["ti"] = valid[sd_sensor] / valid[speed_sensor]
    valid = valid.replace([np.inf, -np.inf], np.nan).dropna()
    valid["speed_bin"] = np.floor(valid[speed_sensor]).astype(int)
    bins: list[dict[str, object]] = []
    for speed_bin, group in valid.groupby("speed_bin", observed=False):
        mean_ti = float(group["ti"].mean())
        representative = mean_ti + 1.28 * float(group["ti"].std(ddof=0))
        bins.append(
            {
                "bin_center": float(speed_bin) + 0.5,
                "mean_ti": mean_ti,
                "representative_ti": representative,
                "count": int(len(group)),
            }
        )
    return {"bins": bins}


@mcp.tool()
def compute_momm(sensor_name: str) -> dict:
    """Compute Windographer-style MoMM using completeness and month-length weighting from TR6."""
    series = _require_series(sensor_name)
    table = compute_weighted_momm_table(series.to_frame(name=sensor_name), sensor_name)
    fallback = float(series.dropna().mean()) if not series.dropna().empty else 0.0
    filled = table.fillna(fallback)
    flat_values = filled.to_numpy(dtype=float).reshape(-1)
    weights = _flat_month_weights()
    momm_speed = float(np.sum(flat_values * weights) / np.sum(weights))
    return {"sensor": sensor_name, "momm_speed": momm_speed, "table": filled.values.tolist()}


@mcp.tool()
def compute_scatter_stats(sensor_a: str, sensor_b: str) -> dict:
    """Compute OLS scatter metrics using standard regression diagnostics from least-squares analysis."""
    return _compute_scatter_stats(session, sensor_a, sensor_b)
