"""visualization._common — shared frame/series helpers and result envelope for the Plotly plot builders.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import base64
import json
from typing import cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from server.core.reanalysis import get_reference_source, reference_source_names
from server.core.validators import to_utc_index
from server.state.session import SessionState

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _timeseries_frame(state: SessionState) -> pd.DataFrame:
    """Return the loaded measured dataframe required by Phase 4 visualization tools."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return to_utc_index(state.timeseries_df)


def _indexed_frame(frame_like: object) -> pd.DataFrame:
    """Normalize stored payloads to a datetime-indexed dataframe for Plotly time-series rendering."""
    frame = pd.DataFrame(frame_like).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(frame.index)
    # LTC results carry tz-aware UTC timestamps while directly-seeded measured
    # frames can be naive; normalize both so the inner joins below actually overlap.
    return to_utc_index(frame.sort_index())


def _require_series(state: SessionState, sensor_name: str) -> pd.Series:
    """Return a measured sensor series for direct visualization from the loaded timeseries dataframe."""
    frame = _timeseries_frame(state)
    if sensor_name not in frame.columns:
        raise ValueError(f"Sensor column '{sensor_name}' not found in loaded timeseries")
    return frame[sensor_name]


def _sensor_names(sensor_names: str) -> list[str]:
    """Parse sensor-name arguments from JSON array or comma-separated string formats."""
    payload = sensor_names.strip()
    parsed: list[str] = []

    if payload.startswith("["):
        decoded = json.loads(payload)
        if not isinstance(decoded, list):
            raise ValueError("sensor_names JSON payload must be a list of sensor names")
        parsed = [str(name).strip() for name in decoded if str(name).strip()]
    else:
        parsed = [name.strip() for name in sensor_names.split(",") if name.strip()]

    if not parsed:
        raise ValueError("At least one sensor name is required")
    return parsed


def _plot_result(fig: go.Figure, title: str) -> dict:
    """Serialize Plotly figures to JSON with optional PNG fallback using Kaleido when installed."""
    png_base64: str | None = None
    try:
        png_bytes = cast(bytes, fig.to_image(format="png", width=900, height=500))
        png_base64 = base64.b64encode(png_bytes).decode("ascii")
    except Exception:
        png_base64 = None
    return {"plotly_json": fig.to_json(), "png_base64": png_base64, "title": title}


def _speed_sensor_pairs(state: SessionState) -> list[tuple[float, str]]:
    """Return mapped wind-speed sensors sorted from tallest to shortest measurement height."""
    pairs = [
        (float(height), str(mapping["speed_col"]))
        for height, mapping in sorted(state.sensor_mapping.items(), reverse=True)
        if mapping.get("speed_col") is not None
    ]
    if not pairs:
        raise ValueError("Sensor mapping with wind-speed columns is required")
    return pairs


def _selected_sensor_columns(state: SessionState) -> list[str]:
    """Return timeseries column names for sensors the analyst has kept in the inventory.

    After the Stage-1 sensor-deletion feature removes unwanted sensors from
    ``sensor_inventory`` / ``sensor_mapping``, this helper ensures plots that
    scan all columns (e.g. ``_plot_data_coverage``) only show the selected set.
    Falls back to all mapped columns when no inventory is loaded (timeseries-only
    sessions before datamodel parse).
    """
    frame = state.timeseries_df
    if frame is None:
        return []
    # Prefer sensor_inventory (the authoritative pruned list after deletions).
    if state.sensor_inventory:
        return [name for name in state.sensor_inventory if name in frame.columns]
    # Fallback: derive from sensor_mapping column slots.
    cols: list[str] = []
    for mapping in state.sensor_mapping.values():
        for key in ("speed_col", "dir_col", "temp_col", "pressure_col"):
            col = mapping.get(key)
            if col and col in frame.columns and col not in cols:
                cols.append(col)
    return cols


def _downsample_timeseries(series: pd.Series) -> pd.Series:
    """Downsample dense time series to daily means to keep browser plots responsive."""
    return series.resample("D").mean() if len(series) > 50000 else series


def _scattergl_mode(length: int) -> str:
    """Choose a suitable Plotly trace mode for dense or sparse line series."""
    return "lines+markers" if length <= 300 else "lines"


def _monthly_mean(series: pd.Series) -> pd.Series:
    """Aggregate monthly mean wind speed for seasonal comparison plots."""
    return series.groupby(series.index.month).mean().reindex(range(1, 13))


def _annual_mean(series: pd.Series) -> pd.Series:
    """Aggregate annual mean wind speed for long-term corrected history plots."""
    annual = series.resample("YE").mean().dropna()
    annual.index = annual.index.year
    return annual


def _wind_speed_bins() -> list[tuple[float, float | None, str]]:
    """Return the standard windrose speed bins used for directional frequency stacking."""
    return [(0.0, 5.0, "0-5"), (5.0, 10.0, "5-10"), (10.0, 15.0, "10-15"), (15.0, 20.0, "15-20"), (20.0, None, "20+")]


def _scatter_metrics(frame: pd.DataFrame, sensor_a: str, sensor_b: str) -> dict[str, float]:
    """Compute OLS scatter metrics from an already aligned two-column dataframe."""
    x_values = frame[sensor_a].to_numpy(dtype=float)
    y_values = frame[sensor_b].to_numpy(dtype=float)
    mean_x = float(np.mean(x_values))
    mean_y = float(np.mean(y_values))
    centered_x = x_values - mean_x
    centered_y = y_values - mean_y
    denominator = float(np.sum(centered_x**2))
    slope = 0.0 if denominator <= 1e-12 else float(np.sum(centered_x * centered_y) / denominator)
    intercept = float(mean_y - slope * mean_x)
    predicted = slope * x_values + intercept
    residuals = y_values - predicted
    ss_res = float(np.sum((y_values - predicted) ** 2))
    ss_tot = float(np.sum((y_values - y_values.mean()) ** 2))
    r2 = 1.0 if ss_tot == 0.0 else float(1.0 - ss_res / ss_tot)
    return {
        "r2": r2,
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "slope": slope,
        "intercept": intercept,
    }


def _preferred_measured_speed_column(state: SessionState) -> str:
    """Choose the most relevant measured speed column for LTC comparison figures."""
    frame = _timeseries_frame(state)
    hub_height = state.get_hub_height_m()
    if hub_height is not None:
        hub_name = f"Spd_{int(hub_height)}m_hub" if float(hub_height).is_integer() else f"Spd_{hub_height}m_hub"
        if hub_name in frame.columns:
            return hub_name
    hub_columns = [column for column in frame.columns if column.startswith("Spd_") and column.endswith("_hub")]
    if hub_columns:
        return sorted(hub_columns)[0]
    speed_columns = [column for column in frame.columns if column.startswith("Spd_")]
    if speed_columns:
        return sorted(speed_columns)[-1]
    raise ValueError("No measured wind-speed column is available for LTC comparison plotting")


def _ltc_result_series(state: SessionState, algorithm: str) -> pd.Series:
    """Return one corrected LTC series indexed by timestamp for diagnostic plotting."""
    payload = state.ltc_results.get(algorithm)
    if payload is None:
        raise ValueError(f"LTC result '{algorithm}' is not available")
    frame = _indexed_frame(payload["df"])
    if "corrected_wind_speed" not in frame.columns:
        raise ValueError(f"LTC result '{algorithm}' is missing the corrected_wind_speed column")
    return frame["corrected_wind_speed"].dropna()


def _ltc_overlap_frame(state: SessionState, algorithm: str) -> pd.DataFrame:
    """Align measured and corrected LTC series on concurrent timestamps for diagnostics."""
    measured = _require_series(state, _preferred_measured_speed_column(state)).rename("measured")
    corrected = _ltc_result_series(state, algorithm).rename("corrected")
    overlap = pd.concat([measured, corrected], axis=1, join="inner").dropna()
    if overlap.empty:
        raise ValueError(f"LTC result '{algorithm}' has no overlap with the measured timeseries")
    return overlap


def _expanding_annual_mean(series: pd.Series) -> tuple[list[int], list[float], float]:
    """Compute expanding annual-mean convergence for long-term corrected speed series."""
    annual = series.resample("YE").mean().dropna()
    if annual.empty:
        raise ValueError("Annual convergence requires at least one annual mean value")
    years = annual.index.year.tolist()
    running = annual.expanding().mean().to_numpy(dtype=float).tolist()
    return years, running, float(running[-1])


def _reference_speed_column(state: SessionState, frame: pd.DataFrame) -> str:
    """Return the reference speed column present on an interpolated site series.

    The series may be ERA5 (100 m) or MERRA-2 (50 m) depending on the active reference
    source, so the column is resolved from the descriptor rather than assumed to be
    ``Spd_100m`` (design doc S6.3). Falls back to any known source column so a frame
    carried over from a previous source still plots.
    """
    preferred = state.get_active_reference_source().speed_col
    if preferred in frame.columns:
        return preferred
    for name in reference_source_names():
        candidate = get_reference_source(name).speed_col
        if candidate in frame.columns:
            return candidate
    known = ", ".join(get_reference_source(n).speed_col for n in reference_source_names())
    raise ValueError(f"Interpolated site data must contain one of: {known}")


def _era5_monthly_speed(frame_like: object, speed_col: str = "Spd_100m") -> pd.Series:
    """Return monthly mean reference wind speed from one node or interpolated dataframe."""
    frame = _indexed_frame(frame_like)
    if speed_col not in frame.columns:
        raise ValueError(f"Reference speed plotting requires a {speed_col} column")
    series = frame[speed_col].dropna()
    monthly = series.groupby(series.index.month).mean().reindex(range(1, 13))
    if monthly.dropna().empty:
        raise ValueError(f"Reference speed plotting requires at least one non-null {speed_col} value")
    return monthly


def _sample_for_boxplot(values: pd.Series, maximum_points: int = 24000) -> pd.Series:
    """Bound raw boxplot points while retaining temporal coverage on long 10-minute records."""
    if len(values) <= maximum_points:
        return values
    return values.iloc[:: max(1, len(values) // maximum_points)]


def _directional_frame(
    state: SessionState, speed_sensor: str, direction_sensor: str
) -> tuple[pd.DataFrame, np.ndarray]:
    """Return concurrent speed/direction records and 16-sector indices for directional plots."""
    frame = pd.concat([_require_series(state, speed_sensor), _require_series(state, direction_sensor)], axis=1).dropna()
    if frame.empty:
        raise ValueError("Directional analysis requires concurrent non-null speed and direction values")
    frame.columns = [speed_sensor, direction_sensor]
    sector_index = (((np.mod(frame[direction_sensor], 360.0) + 11.25) % 360.0) // 22.5).astype(int).to_numpy()
    return frame, sector_index


def _scenario_series(state: SessionState) -> tuple[list[str], list[float], list[float], list[float], list[float]]:
    """Extract scenario comparison series for long-term mean, P75, P90, and total uncertainty."""
    if not state.scenarios:
        raise ValueError("Scenario comparison requires at least one saved scenario")
    names: list[str] = []
    means: list[float] = []
    p75_values: list[float] = []
    p90_values: list[float] = []
    uncertainties: list[float] = []
    for scenario in state.scenarios:
        results = scenario.get("results")
        if not isinstance(results, dict):
            raise ValueError("Scenario comparison requires each scenario to include a results payload")
        mean_speed = float(results.get("long_term_mean_speed", 0.0))
        names.append(str(scenario.get("name", f"Scenario {len(names) + 1}")))
        means.append(mean_speed)
        p75_values.append(mean_speed * float(results.get("p75", 1.0)))
        p90_values.append(mean_speed * float(results.get("p90", 1.0)))
        uncertainties.append(float(results.get("total_uncertainty_pct", 0.0)))
    return names, means, p75_values, p90_values, uncertainties


def _fit_power_law(heights: np.ndarray, speeds: np.ndarray) -> tuple[float, float] | None:
    """Fit a power law (log-log OLS) to a height/speed profile, returning (alpha, intercept)."""
    valid = np.isfinite(speeds) & (speeds > 0.0) & np.isfinite(heights) & (heights > 0.0)
    if valid.sum() < 2:
        return None
    log_heights = np.log(heights[valid])
    log_speeds = np.log(speeds[valid])
    centered_x = log_heights - float(np.mean(log_heights))
    centered_y = log_speeds - float(np.mean(log_speeds))
    denominator = float(np.sum(centered_x**2))
    if denominator <= 1e-12:
        return None
    alpha = float(np.sum(centered_x * centered_y) / denominator)
    intercept = float(np.mean(log_speeds) - alpha * np.mean(log_heights))
    return alpha, intercept
