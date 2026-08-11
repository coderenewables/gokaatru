"""visualization — Phase 4 MCP tools for Plotly-based wind-resource visual outputs.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import base64
import json
from typing import cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import genextreme, gumbel_r, norm, weibull_min

from server.main import mcp
from server.tools.advanced_analysis import _compute_energy_metrics, _compute_extremes, _compute_persistence, _consecutive_ramps
from server.tools.atmosphere import _atmospheric_series
from server.tools.diagnostics import _compute_mast_effects, _compute_mcp_readiness, _compute_qc_diagnostics, _compute_sensor_comparison
from server.state.session import SessionState, session
from server.tools.shear import _vertical_structure_series

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _timeseries_frame(state: SessionState) -> pd.DataFrame:
    """Return the loaded measured dataframe required by Phase 4 visualization tools."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return state.timeseries_df


def _indexed_frame(frame_like: object) -> pd.DataFrame:
    """Normalize stored payloads to a datetime-indexed dataframe for Plotly time-series rendering."""
    frame = pd.DataFrame(frame_like).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(frame.index)
    return frame.sort_index()


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


def _era5_monthly_speed(frame_like: object) -> pd.Series:
    """Return monthly mean ERA5 100 m wind speed from one node or interpolated dataframe."""
    frame = _indexed_frame(frame_like)
    if "Spd_100m" not in frame.columns:
        raise ValueError("ERA5 speed plotting requires a Spd_100m column")
    series = frame["Spd_100m"].dropna()
    monthly = series.groupby(series.index.month).mean().reindex(range(1, 13))
    if monthly.dropna().empty:
        raise ValueError("ERA5 speed plotting requires at least one non-null Spd_100m value")
    return monthly


def _plot_era5_comparison(state: SessionState) -> dict:
    """Plot monthly mean wind speed for each ERA5 node against the interpolated site estimate."""
    if not state.era5_data:
        raise ValueError("ERA5 node data is not available")
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolated site data is not available")
    figure = go.Figure()
    for index, (_node_name, frame_like) in enumerate(sorted(state.era5_data.items()), start=1):
        monthly = _era5_monthly_speed(frame_like)
        figure.add_trace(go.Scatter(x=MONTH_LABELS, y=monthly.tolist(), mode="lines+markers", name=f"Node {index}"))
    site_monthly = _era5_monthly_speed(state.era5_interpolated_df)
    figure.add_trace(
        go.Scatter(
            x=MONTH_LABELS,
            y=site_monthly.tolist(),
            mode="lines+markers",
            name="Interpolated site",
            line=dict(color="#c86a2a", width=4),
        )
    )
    figure.update_layout(title="ERA5 Annual Profile — Nodes vs Site", xaxis_title="Month", yaxis_title="Mean Speed (m/s)")
    return _plot_result(figure, "ERA5 Annual Profile — Nodes vs Site")


def _plot_era5_measured_overlay(state: SessionState) -> dict:
    """Plot concurrent measured and interpolated ERA5 monthly means with overlap diagnostics."""
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolated site data is not available")
    measured = _require_series(state, _preferred_measured_speed_column(state)).rename("measured")
    era5_frame = _indexed_frame(state.era5_interpolated_df)
    if "Spd_100m" not in era5_frame.columns:
        raise ValueError("ERA5 interpolated site data must contain Spd_100m")
    overlap = pd.concat([measured, era5_frame["Spd_100m"].rename("era5")], axis=1, join="inner").dropna()
    if overlap.empty:
        raise ValueError("Measured and ERA5 interpolated series do not overlap")
    monthly = overlap.resample("ME").mean().dropna()
    if monthly.empty:
        raise ValueError("Measured and ERA5 overlap does not contain enough data for monthly plotting")
    metrics = _scatter_metrics(monthly, "era5", "measured")
    overlap_start = monthly.index.min().strftime("%Y-%m")
    overlap_end = monthly.index.max().strftime("%Y-%m")
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=monthly.index,
            y=monthly["measured"],
            mode="lines+markers",
            name="Measured",
            line=dict(color="#c86a2a", width=3),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=monthly.index,
            y=monthly["era5"],
            mode="lines+markers",
            name="ERA5 site",
            line=dict(color="#0b7a6f", width=3),
        )
    )
    figure.update_layout(
        title="Measured vs ERA5 — Concurrent Period",
        xaxis_title="Month",
        yaxis_title="Mean Speed (m/s)",
        annotations=[
            dict(
                xref="paper",
                yref="paper",
                x=0.01,
                y=1.1,
                text=f"R²={metrics['r2']:.3f} | Overlap {overlap_start} to {overlap_end}",
                showarrow=False,
            )
        ],
    )
    return _plot_result(figure, "Measured vs ERA5 — Concurrent Period")


def _plot_windrose(state: SessionState, speed_sensor: str, direction_sensor: str) -> dict:
    """Plot a 16-sector wind rose with stacked speed bins using directional frequency percentages."""
    frame = pd.concat([_require_series(state, speed_sensor), _require_series(state, direction_sensor)], axis=1).dropna()
    if frame.empty:
        raise ValueError("Wind rose requires concurrent non-null speed and direction values")
    sector_width = 360.0 / 16.0
    sector_index = (((frame[direction_sensor] + sector_width / 2.0) % 360.0) // sector_width).astype(int)
    figure = go.Figure()
    for lower, upper, label in _wind_speed_bins():
        if upper is None:
            mask = frame[speed_sensor] >= lower
        else:
            mask = frame[speed_sensor].between(lower, upper, inclusive="left")
        radii = []
        for sector in range(16):
            count = int((mask & (sector_index == sector)).sum())
            radii.append(float(count / len(frame) * 100.0))
        figure.add_trace(go.Barpolar(r=radii, theta=COMPASS_16, name=label, opacity=0.8))
    title = f"Wind Rose - {speed_sensor} by {direction_sensor}"
    figure.update_layout(title=title, polar=dict(radialaxis=dict(ticksuffix="%")))
    return _plot_result(figure, title)


def _plot_weibull(state: SessionState, sensor_name: str) -> dict:
    """Plot the measured speed histogram with a fitted Weibull PDF using $f(v;k,A)$ from wind climatology."""
    series = _require_series(state, sensor_name).dropna()
    positive = series[series > 0.0]
    if positive.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no positive values for Weibull plotting")
    shape_k, _, scale_a = weibull_min.fit(positive.to_numpy(dtype=float), floc=0)
    x_values = np.linspace(0.0, float(positive.max()), 250)
    pdf_values = weibull_min.pdf(x_values, shape_k, loc=0, scale=scale_a)
    figure = go.Figure()
    figure.add_trace(go.Histogram(x=positive, histnorm="probability density", nbinsx=40, name=sensor_name, opacity=0.7))
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=pdf_values,
            mode="lines",
            name=f"Weibull k={shape_k:.2f}, A={scale_a:.2f}, mean={positive.mean():.2f}",
        )
    )
    figure.update_layout(title=f"Weibull Fit — {sensor_name}", xaxis_title="Wind Speed (m/s)", yaxis_title="Density")
    return _plot_result(figure, f"Weibull Fit — {sensor_name}")


def _plot_speed_distribution(state: SessionState, sensor_name: str) -> dict:
    """Plot wind-speed probability density and cumulative distribution for one sensor."""
    speed = _require_series(state, sensor_name).dropna()
    if speed.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no valid values for distribution plotting")
    sorted_speed = np.sort(speed.to_numpy(dtype=float))
    exceedance = 100.0 * (1.0 - (np.arange(len(sorted_speed)) + 0.5) / len(sorted_speed))
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(go.Histogram(x=speed, histnorm="probability density", nbinsx=40, name="Density", opacity=0.72), secondary_y=False)
    figure.add_trace(go.Scatter(x=sorted_speed, y=exceedance, mode="lines", name="Exceedance", line=dict(color="#c86a2a")), secondary_y=True)
    figure.update_layout(title=f"Wind-Speed Distribution — {sensor_name}", bargap=0.04)
    figure.update_xaxes(title_text="Wind Speed (m/s)")
    figure.update_yaxes(title_text="Probability Density", secondary_y=False)
    figure.update_yaxes(title_text="Exceedance (%)", range=[100, 0], secondary_y=True)
    return _plot_result(figure, f"Wind-Speed Distribution — {sensor_name}")


def _plot_sensor_distribution(state: SessionState, sensor_name: str) -> dict:
    """Plot a generic measured-variable probability density and cumulative distribution."""
    values = _require_series(state, sensor_name).dropna()
    if values.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no valid values for distribution plotting")
    ordered = np.sort(values.to_numpy(dtype=float))
    cumulative = 100.0 * (np.arange(len(ordered)) + 0.5) / len(ordered)
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(go.Histogram(x=values, histnorm="probability density", nbinsx=40, name="Density", opacity=0.72), secondary_y=False)
    figure.add_trace(go.Scatter(x=ordered, y=cumulative, mode="lines", name="Cumulative", line=dict(color="#c86a2a")), secondary_y=True)
    figure.update_layout(title=f"Distribution — {sensor_name}", bargap=0.04)
    figure.update_xaxes(title_text="Measured Value")
    figure.update_yaxes(title_text="Probability Density", secondary_y=False)
    figure.update_yaxes(title_text="Cumulative (%)", range=[0, 100], secondary_y=True)
    return _plot_result(figure, f"Distribution — {sensor_name}")


def _sample_for_boxplot(values: pd.Series, maximum_points: int = 24000) -> pd.Series:
    """Bound raw boxplot points while retaining temporal coverage on long 10-minute records."""
    if len(values) <= maximum_points:
        return values
    return values.iloc[:: max(1, len(values) // maximum_points)]


def _plot_diurnal_boxplot(state: SessionState, sensor_name: str) -> dict:
    """Plot measured values as hour-of-day distributions for diurnal variability review."""
    raw_values = _require_series(state, sensor_name).dropna()
    total_count = len(raw_values)
    values = _sample_for_boxplot(raw_values)
    sampled_count = len(values)
    if values.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no valid values for diurnal plotting")
    figure = go.Figure()
    for hour in range(24):
        group = values[values.index.hour == hour]
        if not group.empty:
            figure.add_trace(go.Box(y=group, name=str(hour), boxpoints=False, showlegend=False))
    title = f"Diurnal Distribution — {sensor_name}"
    if sampled_count < total_count:
        title += f"  (sampled: {sampled_count:,} of {total_count:,} records)"
    figure.update_layout(title=title, xaxis_title="Hour", yaxis_title="Measured Value")
    result = _plot_result(figure, title)
    result["total_count"] = total_count
    result["sampled_count"] = sampled_count
    return result


def _plot_monthly_boxplot(state: SessionState, sensor_name: str) -> dict:
    """Plot measured values as monthly distributions for seasonal variability review."""
    values = _sample_for_boxplot(_require_series(state, sensor_name).dropna())
    if values.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no valid values for monthly plotting")
    figure = go.Figure()
    for month in range(1, 13):
        group = values[values.index.month == month]
        if not group.empty:
            figure.add_trace(go.Box(y=group, name=MONTH_LABELS[month - 1], boxpoints=False, showlegend=False))
    figure.update_layout(title=f"Monthly Distribution — {sensor_name}", xaxis_title="Month", yaxis_title="Measured Value")
    return _plot_result(figure, f"Monthly Distribution — {sensor_name}")


def _plot_seasonal_profile(state: SessionState, sensor_names: str) -> dict:
    """Compare mean measured values across DJF, MAM, JJA, and SON seasons."""
    seasons = {"DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]}
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        values = _require_series(state, sensor_name)
        means = [values[values.index.month.isin(months)].mean() for months in seasons.values()]
        figure.add_trace(go.Bar(x=list(seasons), y=means, name=sensor_name))
    figure.update_layout(title="Seasonal Profile", xaxis_title="Season", yaxis_title="Mean Value", barmode="group")
    return _plot_result(figure, "Seasonal Profile")


def _plot_air_density(state: SessionState, temperature_sensor: str, pressure_sensor: str, humidity_sensor: str = "") -> dict:
    """Plot measured air density over time with monthly and diurnal climatology."""
    density, temperature_name, pressure_name, humidity_name = _atmospheric_series(
        state,
        temperature_sensor,
        pressure_sensor,
        humidity_sensor,
    )
    valid = density.dropna()
    if valid.empty:
        raise ValueError("No valid air-density values are available for plotting")
    time_series = valid.resample("D").mean() if len(valid) > 50000 else valid
    monthly = valid.groupby(valid.index.month).mean().reindex(range(1, 13))
    diurnal = valid.groupby(valid.index.hour).mean().reindex(range(24))
    seasonal = [valid[valid.index.month.isin(months)].mean() for months in ([12, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11])]
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=("Density Time Series", "Monthly Density", "Diurnal Density", "Seasonal Density"),
    )
    figure.add_trace(go.Scatter(x=time_series.index, y=time_series, mode="lines", name="Density"), row=1, col=1)
    figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly, name="Monthly density"), row=1, col=2)
    figure.add_trace(go.Scatter(x=list(range(24)), y=diurnal, mode="lines+markers", name="Diurnal density"), row=2, col=1)
    figure.add_trace(go.Bar(x=["DJF", "MAM", "JJA", "SON"], y=seasonal, name="Seasonal density"), row=2, col=2)
    inputs = f"T: {temperature_name}, P: {pressure_name}" + (f", RH: {humidity_name}" if humidity_name else " (dry-air assumption)")
    figure.update_layout(title=f"Air Density — {inputs}", showlegend=False)
    figure.update_yaxes(title_text="kg/m³", row=1, col=1)
    figure.update_yaxes(title_text="kg/m³", row=1, col=2)
    figure.update_yaxes(title_text="kg/m³", row=2, col=1)
    figure.update_yaxes(title_text="kg/m³", row=2, col=2)
    return _plot_result(figure, "Air Density")


def _plot_power_density(state: SessionState, speed_sensor: str, direction_sensor: str = "") -> dict:
    """Plot instantaneous, monthly, and optional directional wind-power density from measured speed."""
    metrics = _compute_energy_metrics(state, speed_sensor, direction_sensor)
    speed = _require_series(state, speed_sensor).dropna()
    air_density = float(metrics["air_density_kg_m3"])
    instantaneous = 0.5 * air_density * speed.clip(lower=0.0).pow(3)
    figure = make_subplots(
        rows=2,
        cols=2,
        specs=[[{}, {}], [{"type": "polar"}, {"type": "polar"}]],
        subplot_titles=("Power-Density Distribution", "Monthly Power Density", "Directional Energy", "Directional Power Density"),
    )
    figure.add_trace(go.Histogram(x=instantaneous, nbinsx=50, name="Power density"), row=1, col=1)
    figure.add_trace(go.Bar(x=MONTH_LABELS, y=metrics["monthly_power_density_w_m2"], name="Monthly WPD"), row=1, col=2)
    sectors = metrics["sectors"]
    if sectors:
        sector_rows = list(sectors)
        figure.add_trace(go.Barpolar(r=[row["energy_pct"] for row in sector_rows], theta=[row["label"] for row in sector_rows], name="Energy contribution"), row=2, col=1)
        figure.add_trace(go.Barpolar(r=[row["power_density_w_m2"] for row in sector_rows], theta=[row["label"] for row in sector_rows], name="Sector WPD"), row=2, col=2)
    figure.update_layout(title=f"Wind Power Density — {speed_sensor} ({metrics['density_source']} density)", showlegend=False)
    figure.update_yaxes(title_text="W/m²", row=1, col=2)
    return _plot_result(figure, "Wind Power Density")


def _plot_extremes_fit(state: SessionState, speed_sensor: str) -> dict:
    """Plot annual maxima with fitted GEV/Gumbel return-level curves."""
    extremes = _compute_extremes(state, speed_sensor)
    maxima = list(extremes["annual_maxima"])
    periods = np.array([2, 5, 10, 20, 50, 100], dtype=float)
    gev = extremes["gev"]
    gumbel = extremes["gumbel"]
    gev_levels = genextreme.isf(1.0 / periods, float(gev["shape"]), loc=float(gev["location"]), scale=float(gev["scale"]))
    gumbel_levels = gumbel_r.isf(1.0 / periods, loc=float(gumbel["location"]), scale=float(gumbel["scale"]))
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Annual Maxima", "Return-Level Fit"))
    figure.add_trace(go.Bar(x=[row["year"] for row in maxima], y=[row["max_speed"] for row in maxima], name="Annual maxima"), row=1, col=1)
    figure.add_trace(go.Scatter(x=periods, y=gev_levels, mode="lines+markers", name="GEV"), row=1, col=2)
    figure.add_trace(go.Scatter(x=periods, y=gumbel_levels, mode="lines+markers", name="Gumbel", line=dict(dash="dash")), row=1, col=2)
    figure.update_layout(title="Extreme Wind Analysis" + (" — Screening Only" if extremes["screening_only"] else ""))
    figure.update_xaxes(title_text="Year", row=1, col=1)
    figure.update_xaxes(title_text="Return Period (years)", type="log", row=1, col=2)
    figure.update_yaxes(title_text="Wind Speed (m/s)", row=1, col=1)
    figure.update_yaxes(title_text="Wind Speed (m/s)", row=1, col=2)
    return _plot_result(figure, "Extreme Wind Analysis")


def _plot_ramp_histogram(state: SessionState, speed_sensor: str) -> dict:
    """Plot signed consecutive-record ramp magnitudes and their daily event timing."""
    ramps, timestep_minutes = _consecutive_ramps(_require_series(state, speed_sensor))
    if ramps.empty:
        raise ValueError("No consecutive valid records are available for ramp plotting")
    daily_max = ramps.abs().resample("D").max()
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Ramp Magnitude Distribution", "Daily Maximum Ramp"))
    figure.add_trace(go.Histogram(x=ramps, nbinsx=60, name="Signed ramps"), row=1, col=1)
    figure.add_trace(go.Scatter(x=daily_max.index, y=daily_max, mode="lines", name="Daily max"), row=1, col=2)
    figure.update_layout(title=f"Wind Ramps — {speed_sensor} ({timestep_minutes}-minute changes)", showlegend=False)
    figure.update_xaxes(title_text="Ramp (m/s)", row=1, col=1)
    figure.update_yaxes(title_text="Count", row=1, col=1)
    figure.update_yaxes(title_text="Absolute Ramp (m/s)", row=1, col=2)
    return _plot_result(figure, "Wind Ramps")


def _plot_duration_curve(state: SessionState, speed_sensor: str) -> dict:
    """Plot sorted calm and high-wind persistence durations from consecutive measured records."""
    persistence = _compute_persistence(state, speed_sensor)
    calm = sorted(persistence["calm_durations_minutes"], reverse=True)
    high = sorted(persistence["high_wind_durations_minutes"], reverse=True)
    figure = go.Figure()
    if calm:
        figure.add_trace(go.Scatter(x=list(range(1, len(calm) + 1)), y=calm, mode="lines", name="Calm periods"))
    if high:
        figure.add_trace(go.Scatter(x=list(range(1, len(high) + 1)), y=high, mode="lines", name="High-wind periods"))
    figure.update_layout(title=f"Wind Persistence — {speed_sensor}", xaxis_title="Ranked Period", yaxis_title="Duration (minutes)")
    figure.update_yaxes(type="log")
    return _plot_result(figure, "Wind Persistence")


def _plot_sensor_residuals(state: SessionState, sensor_a: str, sensor_b: str) -> dict:
    """Plot a downsampled comparison residual time series and residual histogram."""
    result = _compute_sensor_comparison(state, sensor_a, sensor_b)
    residuals = pd.DataFrame(result["residuals"])
    if residuals.empty:
        raise ValueError("No comparison residuals are available for plotting")
    residuals["timestamp"] = pd.to_datetime(residuals["timestamp"])
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Residual Time Series", "Residual Distribution"))
    figure.add_trace(go.Scatter(x=residuals["timestamp"], y=residuals["value"], mode="lines", name="B - A"), row=1, col=1)
    figure.add_trace(go.Histogram(x=residuals["value"], nbinsx=50, name="Residuals"), row=1, col=2)
    figure.update_layout(title=f"Sensor Residuals — {result['sensor_a']} vs {result['sensor_b']}", showlegend=False)
    figure.update_yaxes(title_text="Residual (m/s)", row=1, col=1)
    return _plot_result(figure, "Sensor Residuals")


def _plot_mast_shadow(state: SessionState, sensor_a: str, sensor_b: str, direction_sensor: str) -> dict:
    """Plot measured speed ratio by direction to review potential mast-shadow sectors."""
    result = _compute_mast_effects(state, sensor_a, sensor_b, direction_sensor)
    sectors = result["sectors"]
    figure = go.Figure(go.Barpolar(r=[row["speed_ratio"] for row in sectors], theta=[row["label"] for row in sectors], name="Speed ratio"))
    figure.add_trace(go.Scatterpolar(r=[result["baseline_speed_ratio"]] * 16, theta=[row["label"] for row in sectors], mode="lines", name="Median ratio", line=dict(dash="dash")))
    figure.update_layout(title=f"Mast-Effect Speed Ratio — {result['sensor_b']} / {result['sensor_a']}", polar=dict(radialaxis=dict(title="Speed Ratio")))
    return _plot_result(figure, "Mast-Effect Speed Ratio")


def _plot_qc_flags(state: SessionState) -> dict:
    """Plot non-mutating QC diagnostic counts per measured wind-speed sensor."""
    result = _compute_qc_diagnostics(state)
    rows = result["sensors"]
    figure = go.Figure()
    for key, label in [
        ("range_failures", "Range"),
        ("spike_failures", "Spikes"),
        ("flatline_records", "Flat-line records"),
        ("removed_after_cleaning", "Removed by cleaning"),
    ]:
        figure.add_trace(go.Bar(x=[row["sensor"] for row in rows], y=[row[key] for row in rows], name=label))
    figure.update_layout(title="QC Diagnostic Counts", xaxis_title="Sensor", yaxis_title="Records", barmode="group")
    return _plot_result(figure, "QC Diagnostic Counts")


def _plot_mcp_readiness(state: SessionState, speed_sensor: str, reference_sensor: str = "") -> dict:
    """Plot concurrent hourly measured/reference scatter and monthly mean comparison for MCP readiness."""
    readiness = _compute_mcp_readiness(state, speed_sensor, reference_sensor)
    if state.era5_interpolated_df is None or state.timeseries_df is None:
        raise ValueError("MCP readiness requires measured and interpolated ERA5 data")
    reference = str(readiness["reference_sensor"])
    measured = state.timeseries_df[[speed_sensor]].resample("h").mean()
    concurrent = measured.join(state.era5_interpolated_df[[reference]], how="inner").dropna()
    sampled = concurrent.iloc[:: max(1, len(concurrent) // 10_000)]
    monthly = concurrent.resample("MS").mean()
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Concurrent Scatter", "Monthly Mean Comparison"))
    figure.add_trace(go.Scattergl(x=sampled[reference], y=sampled[speed_sensor], mode="markers", marker=dict(opacity=0.35), name="Concurrent"), row=1, col=1)
    line = np.linspace(float(sampled[reference].min()), float(sampled[reference].max()), 100)
    figure.add_trace(go.Scatter(x=line, y=float(readiness["slope"]) * line + float(readiness["offset"]), mode="lines", name="OLS"), row=1, col=1)
    figure.add_trace(go.Scatter(x=monthly.index, y=monthly[speed_sensor], mode="lines+markers", name="Measured"), row=1, col=2)
    figure.add_trace(go.Scatter(x=monthly.index, y=monthly[reference], mode="lines+markers", name="ERA5"), row=1, col=2)
    figure.update_layout(title=f"MCP Readiness — R²={float(readiness['r_squared']):.3f}")
    figure.update_xaxes(title_text=reference, row=1, col=1)
    figure.update_yaxes(title_text=speed_sensor, row=1, col=1)
    figure.update_yaxes(title_text="Mean Speed (m/s)", row=1, col=2)
    return _plot_result(figure, "MCP Readiness")


def _plot_exceedance_curve(state: SessionState, sensor_name: str) -> dict:
    """Plot wind-speed exceedance probability using ranked valid observations."""
    speed = _require_series(state, sensor_name).dropna()
    if speed.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no valid values for exceedance plotting")
    sorted_speed = np.sort(speed.to_numpy(dtype=float))
    exceedance = 100.0 * (1.0 - (np.arange(len(sorted_speed)) + 0.5) / len(sorted_speed))
    figure = go.Figure(go.Scatter(x=exceedance, y=sorted_speed, mode="lines", name=sensor_name))
    figure.update_layout(title=f"Exceedance Probability — {sensor_name}", xaxis_title="Exceedance Probability (%)", yaxis_title="Wind Speed (m/s)")
    figure.update_xaxes(autorange="reversed")
    return _plot_result(figure, f"Exceedance Probability — {sensor_name}")


def _plot_direction_distribution(state: SessionState, direction_sensor: str) -> dict:
    """Plot the circular directional-frequency distribution for one wind vane."""
    direction = np.mod(_require_series(state, direction_sensor).dropna().to_numpy(dtype=float), 360.0)
    if len(direction) == 0:
        raise ValueError(f"Sensor '{direction_sensor}' has no valid values for direction plotting")
    counts, _ = np.histogram(direction, bins=np.arange(-11.25, 371.25, 22.5))
    figure = go.Figure(go.Barpolar(r=counts / counts.sum() * 100.0, theta=COMPASS_16, name=direction_sensor))
    figure.update_layout(title=f"Direction Distribution — {direction_sensor}", polar=dict(radialaxis=dict(ticksuffix="%")))
    return _plot_result(figure, f"Direction Distribution — {direction_sensor}")


def _directional_frame(state: SessionState, speed_sensor: str, direction_sensor: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Return concurrent speed/direction records and 16-sector indices for directional plots."""
    frame = pd.concat([_require_series(state, speed_sensor), _require_series(state, direction_sensor)], axis=1).dropna()
    if frame.empty:
        raise ValueError("Directional analysis requires concurrent non-null speed and direction values")
    frame.columns = [speed_sensor, direction_sensor]
    sector_index = (((np.mod(frame[direction_sensor], 360.0) + 11.25) % 360.0) // 22.5).astype(int).to_numpy()
    return frame, sector_index


def _plot_sector_speed(state: SessionState, speed_sensor: str, direction_sensor: str) -> dict:
    """Plot sector mean wind speed for a selected speed/direction pair."""
    frame, sector_index = _directional_frame(state, speed_sensor, direction_sensor)
    speeds = [float(frame.loc[sector_index == index, speed_sensor].mean()) if (sector_index == index).any() else 0.0 for index in range(16)]
    figure = go.Figure(go.Bar(x=COMPASS_16, y=speeds, name="Mean speed", marker_color="#0b7a6f"))
    figure.update_layout(title=f"Sector Mean Wind Speed — {speed_sensor}", xaxis_title="Direction sector", yaxis_title="Mean Speed (m/s)")
    return _plot_result(figure, f"Sector Mean Wind Speed — {speed_sensor}")


def _plot_energy_rose(state: SessionState, speed_sensor: str, direction_sensor: str) -> dict:
    """Plot directional wind-energy contribution proportional to the cube of measured speed."""
    frame, sector_index = _directional_frame(state, speed_sensor, direction_sensor)
    cube_speed = frame[speed_sensor].to_numpy(dtype=float) ** 3
    total = float(cube_speed.sum())
    contribution = [0.0 if total == 0 else float(cube_speed[sector_index == index].sum() / total * 100.0) for index in range(16)]
    figure = go.Figure(go.Barpolar(r=contribution, theta=COMPASS_16, name="Energy contribution", marker_color="#c86a2a"))
    figure.update_layout(title=f"Directional Energy Contribution — {speed_sensor}", polar=dict(radialaxis=dict(ticksuffix="%")))
    return _plot_result(figure, f"Directional Energy Contribution — {speed_sensor}")


def _plot_diurnal(state: SessionState, sensor_names: str) -> dict:
    """Plot mean diurnal wind-speed profiles by hour of day for one or more measured sensors."""
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        series = _require_series(state, sensor_name)
        profile = series.groupby(series.index.hour).mean().reindex(range(24))
        figure.add_trace(go.Scatter(x=list(range(24)), y=profile.tolist(), mode="lines+markers", name=sensor_name))
    figure.update_layout(title="Diurnal Profile", xaxis_title="Hour", yaxis_title="Mean Value")
    return _plot_result(figure, "Diurnal Profile")


def _plot_scatter(state: SessionState, sensor_a: str, sensor_b: str) -> dict:
    """Plot a measured scatter comparison with OLS line and regression metrics derived from least squares."""
    frame = pd.concat(
        [_require_series(state, sensor_a), _require_series(state, sensor_b)],
        axis=1,
        join="inner",
    ).dropna()
    if frame.empty:
        raise ValueError(f"No concurrent valid data between '{sensor_a}' and '{sensor_b}'")
    if len(frame) > 10000:
        frame = frame.iloc[:: max(1, len(frame) // 10000)]
    metrics = _scatter_metrics(frame, sensor_a, sensor_b)
    x_values = frame[sensor_a].to_numpy(dtype=float)
    line_x = np.linspace(float(x_values.min()), float(x_values.max()), 100)
    line_y = metrics["slope"] * line_x + metrics["intercept"]
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=frame[sensor_a], y=frame[sensor_b], mode="markers", name="Samples", opacity=0.45))
    figure.add_trace(go.Scatter(x=line_x, y=line_y, mode="lines", name="OLS Fit"))
    title = (
        f"Scatter — {sensor_a} vs {sensor_b} | "
        f"R²={metrics['r2']:.3f}, RMSE={metrics['rmse']:.3f}, slope={metrics['slope']:.3f}"
    )
    figure.update_layout(title=title, xaxis_title=sensor_a, yaxis_title=sensor_b)
    return _plot_result(figure, title)


def _plot_timeseries(state: SessionState, sensor_names: str) -> dict:
    """Plot one or more measured sensor series, downsampling to daily means for large datasets."""
    frame = _timeseries_frame(state)[_sensor_names(sensor_names)].copy()
    plot_frame = frame.resample("D").mean() if len(frame) > 50000 else frame
    figure = go.Figure()
    for column in plot_frame.columns:
        figure.add_trace(go.Scatter(x=plot_frame.index, y=plot_frame[column], mode="lines", name=column))
    figure.update_layout(title="Timeseries", xaxis_title="Timestamp", yaxis_title="Value")
    return _plot_result(figure, "Timeseries")


def _plot_data_coverage(state: SessionState) -> dict:
    """Plot sensor availability as a presence-absence heatmap over time for **selected** sensors only."""
    frame = _timeseries_frame(state).copy()
    # Filter to only the sensors the analyst has kept in the inventory/mapping.
    # This prevents deleted/unwanted sensors from appearing in the coverage plot.
    selected_columns = _selected_sensor_columns(state)
    if selected_columns:
        frame = frame[selected_columns]
    plot_frame = frame.resample("D").mean() if len(frame) > 50000 else frame
    availability = plot_frame.notna().astype(int).T
    figure = go.Figure(
        data=go.Heatmap(
            x=availability.columns,
            y=availability.index.tolist(),
            z=availability.to_numpy(dtype=int),
            colorscale=[[0.0, "#f3efe6"], [1.0, "#083434"]],
            showscale=False,
        )
    )
    figure.update_layout(title="Data Coverage", xaxis_title="Timestamp", yaxis_title="Sensor")
    return _plot_result(figure, "Data Coverage")


def _plot_shear_table(state: SessionState, table_type: str = "shear") -> dict:
    """Plot the monthly-hourly shear or roughness lookup table as a heatmap for hub extrapolation review."""
    if table_type == "shear":
        table = state.shear_table
        colorscale = "Viridis"
        title = "Shear Table"
    elif table_type == "roughness":
        table = state.roughness_table
        colorscale = "Earth"
        title = "Roughness Table"
    else:
        raise ValueError(f"table_type must be 'shear' or 'roughness', got '{table_type}'")
    if table is None:
        raise ValueError(f"Session {table_type} table is not available")
    figure = go.Figure(
        data=go.Heatmap(z=table.to_numpy(dtype=float), x=list(range(24)), y=MONTH_LABELS, colorscale=colorscale)
    )
    figure.update_layout(title=title, xaxis_title="Hour", yaxis_title="Month")
    return _plot_result(figure, title)


def _plot_shear_timeseries(state: SessionState) -> dict:
    """Plot the shear coefficient (or roughness) timeseries produced by the shear stage."""
    frame: pd.DataFrame | None = None
    column = ""
    label = ""
    if state.shear_timeseries_df is not None:
        frame = _indexed_frame(state.shear_timeseries_df)
        column = "shear_coefficient"
        label = "Shear coefficient (α)"
    elif state.roughness_timeseries_df is not None:
        frame = _indexed_frame(state.roughness_timeseries_df)
        column = frame.columns[0] if len(frame.columns) else ""
        label = "Roughness length (z₀)"
    if frame is None or column not in frame.columns:
        raise ValueError("Shear/roughness timeseries is not available. Run the shear stage first")
    series = _downsample_timeseries(frame[column].dropna())
    if series.empty:
        raise ValueError("Shear/roughness timeseries contains no valid values")
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=series.index,
            y=series.to_numpy(dtype=float),
            mode=_scattergl_mode(len(series)),
            name=label,
            line=dict(color="#0b7a6f", width=2),
        )
    )
    mean_value = float(series.mean())
    figure.update_layout(
        title=f"{label} Timeseries (mean {mean_value:.3f})",
        xaxis_title="Time",
        yaxis_title=label,
    )
    return _plot_result(figure, f"{label} Timeseries")


def _plot_era5_scatter(state: SessionState) -> dict:
    """Scatter measured vs ERA5 site series over the concurrent (overlap) period, with OLS fit and R²."""
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolated site data is not available")
    measured = _require_series(state, _preferred_measured_speed_column(state)).rename("measured")
    era5_frame = _indexed_frame(state.era5_interpolated_df)
    if "Spd_100m" not in era5_frame.columns:
        raise ValueError("ERA5 interpolated site data must contain Spd_100m")
    overlap = pd.concat([measured, era5_frame["Spd_100m"].rename("era5")], axis=1, join="inner").dropna()
    if overlap.empty:
        raise ValueError("Measured and ERA5 interpolated series do not overlap")
    monthly = overlap.resample("ME").mean().dropna()
    if monthly.empty:
        raise ValueError("Measured and ERA5 overlap does not contain enough data for a scatter")
    metrics = _scatter_metrics(monthly, "era5", "measured")
    x = monthly["era5"].to_numpy(dtype=float)
    y = monthly["measured"].to_numpy(dtype=float)
    line_min = float(min(x.min(), y.min()))
    line_max = float(max(x.max(), y.max()))
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="markers",
            name="Monthly concurrent",
            marker=dict(color="#0b7a6f", size=8, opacity=0.75),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[line_min, line_max],
            y=[line_min, line_max],
            mode="lines",
            name="1:1",
            line=dict(color="#888888", dash="dash"),
        )
    )
    fit_x = [line_min, line_max]
    fit_y = [metrics["slope"] * line_min + metrics["intercept"], metrics["slope"] * line_max + metrics["intercept"]]
    figure.add_trace(
        go.Scatter(
            x=fit_x,
            y=fit_y,
            mode="lines",
            name=f"OLS fit (R²={metrics['r2']:.3f})",
            line=dict(color="#c86a2a", width=3),
        )
    )
    figure.update_layout(
        title=(
            f"Measured vs ERA5 (concurrent period) — R²={metrics['r2']:.3f}, "
            f"RMSE={metrics['rmse']:.3f} m/s, slope={metrics['slope']:.3f}"
        ),
        xaxis_title="ERA5 site mean speed (m/s)",
        yaxis_title="Measured mean speed (m/s)",
    )
    return _plot_result(figure, "Measured vs ERA5 — Scatter")


def _plot_monthly_means(state: SessionState, sensor_names: str) -> dict:
    """Plot grouped monthly means for one or more measured sensors using calendar-month aggregation."""
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        monthly = _monthly_mean(_require_series(state, sensor_name))
        figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly.tolist(), name=sensor_name))
    figure.update_layout(title="Monthly Means", xaxis_title="Month", yaxis_title="Mean Speed (m/s)", barmode="group")
    return _plot_result(figure, "Monthly Means")


def _plot_ltc_comparison(state: SessionState) -> dict:
    """Plot monthly mean and measured-vs-corrected LTC comparisons across all completed correction algorithms."""
    if not state.ltc_results:
        raise ValueError("At least one LTC result is required for LTC comparison plotting")
    measured = _require_series(state, _preferred_measured_speed_column(state))
    figure = make_subplots(rows=2, cols=1, subplot_titles=("Monthly Mean Comparison", "Measured vs Corrected"))
    figure.add_trace(
        go.Scatter(x=MONTH_LABELS, y=_monthly_mean(measured).tolist(), mode="lines+markers", name="Measured"),
        row=1,
        col=1,
    )
    for algorithm, payload in sorted(state.ltc_results.items()):
        frame = _indexed_frame(payload["df"])
        series = frame["corrected_wind_speed"].dropna()
        figure.add_trace(
            go.Scatter(x=MONTH_LABELS, y=_monthly_mean(series).tolist(), mode="lines+markers", name=algorithm),
            row=1,
            col=1,
        )
        overlap = pd.concat([measured.rename("measured"), series.rename("corrected")], axis=1, join="inner").dropna()
        if len(overlap) > 4000:
            overlap = overlap.iloc[:: max(1, len(overlap) // 4000)]
        figure.add_trace(
            go.Scatter(
                x=overlap["measured"],
                y=overlap["corrected"],
                mode="markers",
                name=f"{algorithm} scatter",
                opacity=0.4,
            ),
            row=2,
            col=1,
        )
    figure.update_xaxes(title_text="Month", row=1, col=1)
    figure.update_yaxes(title_text="Mean Speed (m/s)", row=1, col=1)
    figure.update_xaxes(title_text="Measured Speed (m/s)", row=2, col=1)
    figure.update_yaxes(title_text="Corrected Speed (m/s)", row=2, col=1)
    figure.update_layout(title="LTC Comparison", height=850)
    return _plot_result(figure, "LTC Comparison")


def _plot_annual_means(state: SessionState) -> dict:
    """Plot annual mean corrected wind speed for all LTC algorithms and the ensemble over the long-term record."""
    if not state.ltc_results and state.ensemble_df is None:
        raise ValueError("Annual means plotting requires at least one LTC or ensemble result")
    figure = go.Figure()
    for algorithm, payload in sorted(state.ltc_results.items()):
        frame = _indexed_frame(payload["df"])
        annual = _annual_mean(frame["corrected_wind_speed"].dropna())
        figure.add_trace(go.Scatter(x=annual.index.tolist(), y=annual.tolist(), mode="lines+markers", name=algorithm))
    if state.ensemble_df is not None:
        ensemble = _indexed_frame(state.ensemble_df)
        annual = _annual_mean(ensemble["Ensemble_Speed"].dropna())
        figure.add_trace(go.Scatter(x=annual.index.tolist(), y=annual.tolist(), mode="lines+markers", name="ensemble"))
    figure.update_layout(title="Annual Mean Wind Speed", xaxis_title="Year", yaxis_title="Mean Speed (m/s)")
    return _plot_result(figure, "Annual Mean Wind Speed")


def _plot_uncertainty_breakdown(
    _state: SessionState,
    total_pct: float,
    measurement_pct: float,
    vertical_pct: float,
    mcp_pct: float,
    future_pct: float,
) -> dict:
    """Plot stacked uncertainty components contributing to total percent uncertainty by RSS convention."""
    figure = go.Figure()
    components = [measurement_pct, vertical_pct, mcp_pct, future_pct]
    labels = ["Measurement", "Vertical", "MCP", "Future"]
    figure.add_trace(go.Bar(x=components, y=["Uncertainty"] * 4, orientation="h", name="Components", text=labels))
    figure.add_vline(x=total_pct, line_dash="dash", annotation_text=f"Total {total_pct:.2f}%")
    figure.update_layout(title="Uncertainty Breakdown", xaxis_title="Percent", yaxis_title="")
    return _plot_result(figure, "Uncertainty Breakdown")


def _plot_ltc_scatter(state: SessionState, algorithm: str) -> dict:
    """Plot measured vs corrected LTC scatter with OLS fit and a 1:1 reference line."""
    overlap = _ltc_overlap_frame(state, algorithm)
    if len(overlap) > 6000:
        overlap = overlap.iloc[:: max(1, len(overlap) // 6000)]
    metrics = _scatter_metrics(overlap, "measured", "corrected")
    line_start = float(min(overlap["measured"].min(), overlap["corrected"].min()))
    line_end = float(max(overlap["measured"].max(), overlap["corrected"].max()))
    fit_x = np.linspace(line_start, line_end, 120)
    fit_y = metrics["slope"] * fit_x + metrics["intercept"]
    figure = go.Figure()
    figure.add_trace(
        go.Scattergl(
            x=overlap["measured"],
            y=overlap["corrected"],
            mode="markers",
            name="Samples",
            marker=dict(color="rgba(11, 122, 111, 0.28)", size=6),
        )
    )
    figure.add_trace(go.Scatter(x=fit_x, y=fit_y, mode="lines", name="OLS fit", line=dict(color="#c86a2a", width=3)))
    figure.add_trace(
        go.Scatter(
            x=[line_start, line_end],
            y=[line_start, line_end],
            mode="lines",
            name="1:1 reference",
            line=dict(color="#5f716a", dash="dash"),
        )
    )
    figure.update_layout(
        title=(
            f"LTC Scatter — {algorithm}<br>"
            f"<sup>R²={metrics['r2']:.3f}, RMSE={metrics['rmse']:.3f}, MBE={float((overlap['corrected'] - overlap['measured']).mean()):.3f}</sup>"
        ),
        xaxis_title="Measured Speed (m/s)",
        yaxis_title="Corrected Speed (m/s)",
    )
    return _plot_result(figure, f"LTC Scatter — {algorithm}")


def _plot_ltc_residuals(state: SessionState, algorithm: str) -> dict:
    """Plot residual-vs-predicted and histogram diagnostics for one LTC algorithm."""
    overlap = _ltc_overlap_frame(state, algorithm)
    predicted = overlap["corrected"].to_numpy(dtype=float)
    residuals = predicted - overlap["measured"].to_numpy(dtype=float)
    if len(overlap) > 6000:
        sampled = overlap.iloc[:: max(1, len(overlap) // 6000)]
        sampled_predicted = sampled["corrected"].to_numpy(dtype=float)
        sampled_residuals = sampled_predicted - sampled["measured"].to_numpy(dtype=float)
    else:
        sampled_predicted = predicted
        sampled_residuals = residuals
    mean_residual, std_residual = norm.fit(residuals)
    x_values = np.linspace(float(residuals.min()), float(residuals.max()), 200)
    y_values = norm.pdf(x_values, mean_residual, std_residual if std_residual > 0 else 1.0)
    figure = make_subplots(rows=2, cols=1, subplot_titles=("Residuals vs Predicted", "Residual Distribution"))
    figure.add_trace(
        go.Scattergl(
            x=sampled_predicted,
            y=sampled_residuals,
            mode="markers",
            name="Residuals",
            marker=dict(color="rgba(11, 122, 111, 0.28)", size=6),
        ),
        row=1,
        col=1,
    )
    figure.add_hline(y=0.0, line_dash="dash", line_color="#5f716a", row=1, col=1)
    figure.add_trace(
        go.Histogram(x=residuals, histnorm="probability density", name="Residual histogram", opacity=0.75),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=x_values, y=y_values, mode="lines", name="Normal fit", line=dict(color="#c86a2a", width=3)),
        row=2,
        col=1,
    )
    figure.update_xaxes(title_text="Predicted Speed (m/s)", row=1, col=1)
    figure.update_yaxes(title_text="Corrected - Measured (m/s)", row=1, col=1)
    figure.update_xaxes(title_text="Residual (m/s)", row=2, col=1)
    figure.update_yaxes(title_text="Density", row=2, col=1)
    figure.update_layout(title=f"LTC Residuals — {algorithm}", height=820, barmode="overlay")
    return _plot_result(figure, f"LTC Residuals — {algorithm}")


def _plot_ltc_monthly_comparison(state: SessionState) -> dict:
    """Plot grouped monthly corrected means for all LTC algorithms with measured seasonal context."""
    if not state.ltc_results:
        raise ValueError("At least one LTC result is required for monthly LTC comparison plotting")
    measured = _require_series(state, _preferred_measured_speed_column(state))
    figure = go.Figure()
    for algorithm, payload in sorted(state.ltc_results.items()):
        frame = _indexed_frame(payload["df"])
        monthly = _monthly_mean(frame["corrected_wind_speed"].dropna())
        figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly.tolist(), name=algorithm))
    figure.add_trace(
        go.Scatter(
            x=MONTH_LABELS,
            y=_monthly_mean(measured).tolist(),
            mode="lines+markers",
            name="Measured",
            line=dict(color="#c86a2a", width=3),
        )
    )
    figure.update_layout(title="Monthly LTC Comparison", xaxis_title="Month", yaxis_title="Mean Speed (m/s)", barmode="group")
    return _plot_result(figure, "Monthly LTC Comparison")


def _plot_ltc_annual_convergence(state: SessionState) -> dict:
    """Plot expanding annual-mean convergence for all LTC algorithms and the ensemble when available."""
    if not state.ltc_results and state.ensemble_df is None:
        raise ValueError("Annual convergence plotting requires at least one LTC or ensemble result")
    figure = go.Figure()
    for algorithm, payload in sorted(state.ltc_results.items()):
        years, running_mean, final_mean = _expanding_annual_mean(_indexed_frame(payload["df"])["corrected_wind_speed"].dropna())
        figure.add_trace(go.Scatter(x=years, y=running_mean, mode="lines+markers", name=algorithm))
        figure.add_trace(
            go.Scatter(
                x=years,
                y=[final_mean] * len(years),
                mode="lines",
                name=f"{algorithm} final mean",
                line=dict(dash="dash"),
                opacity=0.45,
            )
        )
    if state.ensemble_df is not None:
        years, running_mean, final_mean = _expanding_annual_mean(_indexed_frame(state.ensemble_df)["Ensemble_Speed"].dropna())
        figure.add_trace(go.Scatter(x=years, y=running_mean, mode="lines+markers", name="ensemble"))
        figure.add_trace(
            go.Scatter(
                x=years,
                y=[final_mean] * len(years),
                mode="lines",
                name="ensemble final mean",
                line=dict(dash="dash"),
                opacity=0.45,
            )
        )
    figure.update_layout(title="Annual Convergence", xaxis_title="Years Included", yaxis_title="Running Mean Speed (m/s)")
    return _plot_result(figure, "Annual Convergence")


def _plot_uncertainty_tornado(
    _state: SessionState,
    total_pct: float,
    measurement_pct: float,
    vertical_pct: float,
    mcp_pct: float,
    future_pct: float,
) -> dict:
    """Plot sorted uncertainty components with the total RSS uncertainty highlighted."""
    components = [
        ("Measurement", float(measurement_pct)),
        ("Vertical", float(vertical_pct)),
        ("MCP", float(mcp_pct)),
        ("Future", float(future_pct)),
    ]
    components.sort(key=lambda item: item[1], reverse=True)
    labels = ["Total", *[label for label, _ in components]]
    values = [float(total_pct), *[value for _, value in components]]
    colors = ["#c86a2a", "#0b7a6f", "#0b7a6f", "#0b7a6f", "#0b7a6f"]
    figure = go.Figure(
        data=go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors),
            text=[f"{value:.2f}%" for value in values],
            textposition="outside",
        )
    )
    figure.update_layout(
        title="Uncertainty Tornado",
        xaxis_title="Percent",
        yaxis_title="",
        annotations=[
            dict(
                xref="paper",
                yref="paper",
                x=1.0,
                y=1.08,
                text=f"Total = √(Σ uᵢ²) = {float(total_pct):.2f}%",
                showarrow=False,
            )
        ],
    )
    return _plot_result(figure, "Uncertainty Tornado")


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


def _plot_scenario_comparison(state: SessionState) -> dict:
    """Plot saved scenario mean speeds with P-factor bars and total uncertainty overlay."""
    names, means, p75_values, p90_values, uncertainties = _scenario_series(state)
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(go.Bar(x=names, y=means, name="LT Mean"), secondary_y=False)
    figure.add_trace(go.Bar(x=names, y=p75_values, name="P75 speed"), secondary_y=False)
    figure.add_trace(go.Bar(x=names, y=p90_values, name="P90 speed"), secondary_y=False)
    figure.add_trace(
        go.Scatter(x=names, y=uncertainties, mode="lines+markers", name="Total uncertainty", line=dict(color="#c86a2a", width=3)),
        secondary_y=True,
    )
    figure.update_layout(title="Scenario Comparison", barmode="group")
    figure.update_yaxes(title_text="Wind Speed (m/s)", secondary_y=False)
    figure.update_yaxes(title_text="Total Uncertainty (%)", secondary_y=True)
    return _plot_result(figure, "Scenario Comparison")


def _plot_timeseries_preview(state: SessionState, max_sensors: int = 5) -> dict:
    """Plot the first 7 days of mapped wind-speed sensors for immediate post-upload data review."""
    frame = _timeseries_frame(state)
    selected = _speed_sensor_pairs(state)[:max_sensors]
    start = frame.index.min()
    end = start + pd.Timedelta(days=7)
    preview = frame.loc[(frame.index >= start) & (frame.index < end), [column for _, column in selected]]
    if preview.empty:
        raise ValueError("Preview plot requires at least one week of loaded timeseries data")
    figure = go.Figure()
    for height, column in selected:
        figure.add_trace(
            go.Scattergl(
                x=preview.index,
                y=preview[column],
                mode=_scattergl_mode(len(preview)),
                name=f"{column} ({height:.0f} m)",
                connectgaps=False,
            )
        )
    figure.update_xaxes(rangeslider_visible=True, title="Timestamp")
    figure.update_yaxes(title="Wind Speed (m/s)")
    figure.update_layout(title="Data Preview — First 7 Days")
    return _plot_result(figure, "Data Preview — First 7 Days")


def _plot_cleaning_overlay(state: SessionState, sensor_name: str) -> dict:
    """Overlay raw and cleaned sensor values, highlighting points removed by cleaning rules."""
    if state.raw_timeseries_df is None or state.timeseries_df is None:
        raise ValueError("Both raw and cleaned timeseries are required for cleaning overlay plotting")
    if sensor_name not in state.raw_timeseries_df.columns or sensor_name not in state.timeseries_df.columns:
        raise ValueError(f"Sensor column '{sensor_name}' not found in loaded timeseries")
    raw = state.raw_timeseries_df[sensor_name]
    cleaned = state.timeseries_df[sensor_name]
    removed = raw.notna() & cleaned.isna()
    if len(raw) > 50000:
        cleaned_plot = cleaned.resample("D").mean()
        removed_plot = raw.where(removed).resample("D").mean().dropna()
    else:
        cleaned_plot = cleaned
        removed_plot = raw.where(removed).dropna()
    figure = go.Figure()
    figure.add_trace(
        go.Scattergl(
            x=cleaned_plot.index,
            y=cleaned_plot,
            mode="lines",
            name="Cleaned",
            line=dict(color="#0b7a6f"),
            connectgaps=False,
        )
    )
    figure.add_trace(
        go.Scattergl(
            x=removed_plot.index,
            y=removed_plot,
            mode="markers",
            name="Removed",
            marker=dict(color="red", opacity=0.4, size=7),
        )
    )
    figure.update_layout(title=f"Cleaning Overlay — {sensor_name}", xaxis_title="Timestamp", yaxis_title="Value")
    return _plot_result(figure, f"Cleaning Overlay — {sensor_name}")


def _plot_coverage_timeline(state: SessionState) -> dict:
    """Plot monthly per-sensor availability as a horizontal heatmap timeline for mapped sensors."""
    frame = _timeseries_frame(state)
    timestep_minutes = pd.Timedelta(minutes=1)
    if len(frame.index) >= 2:
        timestep_minutes = pd.Series(frame.index.to_series().diff().dropna()).mode().iloc[0]
    full_index = pd.date_range(frame.index.min(), frame.index.max(), freq=timestep_minutes)
    sensor_rows = []
    sensor_labels = []
    month_labels: list[str] = []
    for height, mapping in sorted(state.sensor_mapping.items(), reverse=True):
        for field_name, sensor_type in {
            "speed_col": "wind_speed",
            "dir_col": "wind_direction",
            "temp_col": "temperature",
            "pressure_col": "pressure",
        }.items():
            column = mapping.get(field_name)
            if column is None or column not in frame.columns:
                continue
            series = frame[column].reindex(full_index)
            monthly = series.resample("MS").apply(lambda values: float(values.notna().mean()))
            if not month_labels:
                month_labels = [timestamp.strftime("%Y-%m") for timestamp in monthly.index]
            sensor_rows.append(monthly.to_list())
            sensor_labels.append(f"{column} ({sensor_type}, {height:.0f} m)")
    if not sensor_rows:
        raise ValueError("Coverage timeline requires mapped sensors and loaded timeseries data")
    figure = go.Figure(
        data=go.Heatmap(
            x=month_labels,
            y=sensor_labels,
            z=np.asarray(sensor_rows, dtype=float),
            colorscale=[[0.0, "#f3efe6"], [0.5, "#e5dbc5"], [1.0, "#0b7a6f"]],
            zmin=0.0,
            zmax=1.0,
            colorbar=dict(title="Availability"),
        )
    )
    figure.update_layout(title="Data Coverage Timeline", xaxis_title="Month", yaxis_title="Sensor")
    return _plot_result(figure, "Data Coverage Timeline")


def _plot_shear_alpha(state: SessionState, sensor_names: str = "") -> dict:
    """Plot timestamp-wise alpha with distribution and diurnal structure for selected speed heights."""
    alpha, _veer, _profile = _vertical_structure_series(state, speed_sensors=sensor_names)
    valid = alpha.dropna()
    if valid.empty:
        raise ValueError("No valid shear alpha values are available for plotting")
    time_series = valid.resample("D").mean() if len(valid) > 50000 else valid
    diurnal = valid.groupby(valid.index.hour).mean().reindex(range(24))
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=("Alpha Time Series", "Alpha Distribution", "Diurnal Alpha", "Monthly Alpha"),
    )
    figure.add_trace(go.Scatter(x=time_series.index, y=time_series, mode="lines", name="Alpha"), row=1, col=1)
    figure.add_trace(go.Histogram(x=valid, nbinsx=40, name="Alpha distribution"), row=1, col=2)
    figure.add_trace(go.Scatter(x=list(range(24)), y=diurnal, mode="lines+markers", name="Diurnal alpha"), row=2, col=1)
    monthly = valid.groupby(valid.index.month).mean().reindex(range(1, 13))
    figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly, name="Monthly alpha"), row=2, col=2)
    figure.update_layout(title="Wind Shear Alpha", showlegend=False)
    figure.update_xaxes(title_text="Timestamp", row=1, col=1)
    figure.update_xaxes(title_text="Alpha", row=1, col=2)
    figure.update_xaxes(title_text="Hour", row=2, col=1)
    figure.update_yaxes(title_text="Alpha", row=1, col=1)
    figure.update_yaxes(title_text="Count", row=1, col=2)
    figure.update_yaxes(title_text="Alpha", row=2, col=1)
    figure.update_yaxes(title_text="Alpha", row=2, col=2)
    return _plot_result(figure, "Wind Shear Alpha")


def _plot_wind_veer(state: SessionState, direction_sensors: str = "") -> dict:
    """Plot signed vertical wind veer in degrees per 100 m with distribution and diurnal structure."""
    _alpha, veer, _profile = _vertical_structure_series(state, direction_sensors=direction_sensors)
    if veer is None:
        raise ValueError("Wind veer requires at least two wind-direction heights")
    valid = veer.dropna()
    if valid.empty:
        raise ValueError("No valid wind-veer values are available for plotting")
    time_series = valid.resample("D").mean() if len(valid) > 50000 else valid
    diurnal = valid.groupby(valid.index.hour).mean().reindex(range(24))
    figure = make_subplots(
        rows=1,
        cols=3,
        subplot_titles=("Veer Time Series", "Veer Distribution", "Diurnal Veer"),
    )
    figure.add_trace(go.Scatter(x=time_series.index, y=time_series, mode="lines", name="Veer"), row=1, col=1)
    figure.add_trace(go.Histogram(x=valid, nbinsx=40, name="Veer distribution"), row=1, col=2)
    figure.add_trace(go.Scatter(x=list(range(24)), y=diurnal, mode="lines+markers", name="Diurnal veer"), row=1, col=3)
    figure.update_layout(title="Wind Veer", showlegend=False)
    figure.update_xaxes(title_text="Timestamp", row=1, col=1)
    figure.update_xaxes(title_text="Veer (deg / 100 m)", row=1, col=2)
    figure.update_xaxes(title_text="Hour", row=1, col=3)
    figure.update_yaxes(title_text="Veer (deg / 100 m)", row=1, col=1)
    figure.update_yaxes(title_text="Count", row=1, col=2)
    figure.update_yaxes(title_text="Veer (deg / 100 m)", row=1, col=3)
    return _plot_result(figure, "Wind Veer")


def _plot_turbulence_intensity(state: SessionState, speed_sensor: str, sd_sensor: str) -> dict:
    """Plot raw and representative turbulence intensity profiles with IEC reference classes."""
    frame = pd.concat([_require_series(state, speed_sensor), _require_series(state, sd_sensor)], axis=1).dropna()
    valid = frame[(frame[speed_sensor] > 3.0) & (frame[sd_sensor] >= 0.0)].copy()
    if valid.empty:
        raise ValueError("Turbulence intensity plotting requires concurrent speed > 3 m/s and non-negative SD values")
    valid["ti"] = valid[sd_sensor] / valid[speed_sensor]
    valid = valid.replace([np.inf, -np.inf], np.nan).dropna(subset=["ti"])
    valid["speed_bin"] = np.floor(valid[speed_sensor]).astype(int)
    grouped = valid.groupby("speed_bin", observed=False)
    bin_centers = [float(bin_value) + 0.5 for bin_value in grouped.groups.keys()]
    mean_ti = grouped["ti"].mean().to_numpy(dtype=float)
    std_ti = grouped["ti"].std(ddof=0).fillna(0.0).to_numpy(dtype=float)
    rep_ti = mean_ti + 1.28 * std_ti
    scatter = valid[[speed_sensor, "ti"]]
    if len(scatter) > 8000:
        step = max(1, len(scatter) // 8000)
        scatter = scatter.iloc[::step]
    x_min = min(bin_centers)
    x_max = max(bin_centers)
    figure = go.Figure()
    figure.add_trace(
        go.Scattergl(
            x=scatter[speed_sensor],
            y=scatter["ti"],
            mode="markers",
            name="Samples",
            marker=dict(color="rgba(11, 122, 111, 0.22)", size=6),
        )
    )
    figure.add_trace(go.Scatter(x=bin_centers, y=mean_ti, mode="lines+markers", name="Mean TI"))
    figure.add_trace(
        go.Scatter(
            x=bin_centers,
            y=rep_ti,
            mode="lines+markers",
            name="Representative TI",
            line=dict(dash="dash"),
        )
    )
    iec_speeds = np.linspace(x_min, x_max, 200)
    for label, reference_ti, color in [("IEC Class A", 0.16, "#c86a2a"), ("IEC Class B", 0.14, "#756c4f"), ("IEC Class C", 0.12, "#5f716a")]:
        figure.add_trace(
            go.Scatter(
                x=iec_speeds.tolist(),
                y=(reference_ti * (0.75 + 5.6 / iec_speeds)).tolist(),
                mode="lines",
                name=label,
                line=dict(dash="dot", color=color),
            )
        )
    figure.update_layout(
        title=f"Turbulence Intensity — {speed_sensor}",
        xaxis_title="Wind Speed (m/s)",
        yaxis_title="TI",
    )
    return _plot_result(figure, f"Turbulence Intensity — {speed_sensor}")


def _plot_turbulence_windrose(state: SessionState, speed_sensor: str, sd_sensor: str, direction_sensor: str) -> dict:
    """Plot mean and P90 turbulence intensity by 16 wind-direction sectors."""
    frame = pd.concat(
        [_require_series(state, speed_sensor), _require_series(state, sd_sensor), _require_series(state, direction_sensor)],
        axis=1,
    ).dropna()
    valid = frame[(frame[speed_sensor] > 3.0) & (frame[sd_sensor] >= 0.0)].copy()
    if valid.empty:
        raise ValueError("Turbulence wind rose requires concurrent speed > 3 m/s, non-negative SD, and direction values")
    valid["ti"] = valid[sd_sensor] / valid[speed_sensor]
    valid = valid.replace([np.inf, -np.inf], np.nan).dropna(subset=["ti"])
    sector_width = 360.0 / 16.0
    valid["sector"] = (((valid[direction_sensor] + sector_width / 2.0) % 360.0) // sector_width).astype(int)
    grouped = valid.groupby("sector", observed=False)["ti"]
    mean_ti = grouped.mean().reindex(range(16), fill_value=0.0)
    p90_ti = grouped.quantile(0.90).reindex(range(16), fill_value=0.0)
    title = f"Turbulence Wind Rose — {speed_sensor} by {direction_sensor}"
    figure = go.Figure()
    figure.add_trace(go.Barpolar(r=mean_ti.tolist(), theta=COMPASS_16, name="Mean TI", marker_color="#0b7a6f", opacity=0.8))
    figure.add_trace(
        go.Scatterpolar(
            r=p90_ti.tolist(),
            theta=COMPASS_16,
            mode="lines+markers",
            name="P90 TI",
            line=dict(color="#c86a2a", width=2),
        )
    )
    figure.update_layout(title=title, polar=dict(radialaxis=dict(tickformat=".0%")))
    return _plot_result(figure, title)


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


def _plot_shear_profile(state: SessionState) -> dict:
    """Plot mean measured wind-speed profile (plus day/night splits) with fitted power-law curves from 0 m."""
    frame = _timeseries_frame(state)
    speed_pairs = [(height, column) for height, column in _speed_sensor_pairs(state) if column in frame.columns]
    if len(speed_pairs) < 2:
        raise ValueError("Shear profile plotting requires at least two mapped wind-speed sensors")
    heights = np.asarray([height for height, _ in speed_pairs], dtype=float)

    # Day = 06:00-18:00 local; night = everything else. Fixed-hour split is
    # location-independent and works on already-loaded data (no solar-position
    # computation needed).
    hours = np.asarray(frame.index.hour)
    day_mask = (hours >= 6) & (hours < 18)
    subsets = {
        "all": np.ones(len(frame), dtype=bool),
        "day": day_mask,
        "night": ~day_mask,
    }
    means_by_subset = {
        key: np.asarray(
            [frame.loc[mask, column].dropna().mean() for _, column in speed_pairs], dtype=float
        )
        for key, mask in subsets.items()
    }

    all_fit = _fit_power_law(heights, means_by_subset["all"])
    if all_fit is None:
        raise ValueError("Shear profile plotting requires at least two sensors with positive mean wind speeds")

    # Draw fitted curves from ground level (0 m) up to the tallest sensor.
    curve_heights = np.linspace(0.0, float(heights.max()), 120)
    figure = go.Figure()

    # Measured markers for each subset.
    marker_styles = {
        "all": dict(size=10, color="#0b7a6f", symbol="circle"),
        "day": dict(size=9, color="#e2a13a", symbol="triangle-up"),
        "night": dict(size=9, color="#33526b", symbol="square"),
    }
    for key in ("all", "day", "night"):
        means = means_by_subset[key]
        valid = np.isfinite(means) & (means > 0.0)
        if valid.sum() < 2:
            continue
        figure.add_trace(
            go.Scatter(
                x=means[valid],
                y=heights[valid],
                mode="markers",
                name=f"Measured ({key})",
                marker=marker_styles[key],
            )
        )

    # Power-law fits from 0 m, coloured to match their markers.
    fit_styles = {
        "all": dict(color="#0b7a6f", width=3),
        "day": dict(color="#e2a13a", width=2, dash="dash"),
        "night": dict(color="#33526b", width=2, dash="dot"),
    }
    alphas: dict[str, float] = {}
    for key in ("all", "day", "night"):
        fit = _fit_power_law(heights, means_by_subset[key])
        if fit is None:
            continue
        alpha, intercept = fit
        alphas[key] = alpha
        figure.add_trace(
            go.Scatter(
                x=np.exp(intercept) * np.power(curve_heights, alpha),
                y=curve_heights,
                mode="lines",
                name=f"Power-law fit ({key})",
                line=fit_styles[key],
            )
        )

    alpha_text = " | ".join(f"{key}: α = {value:.3f}" for key, value in alphas.items())
    figure.update_layout(
        title="Shear Profile (day / night)",
        xaxis_title="Mean Wind Speed (m/s)",
        yaxis_title="Height (m)",
        yaxis=dict(range=[0, float(heights.max()) * 1.05]),
        annotations=[
            dict(
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.04,
                text=alpha_text,
                showarrow=False,
                bgcolor="rgba(255,250,240,0.92)",
            )
        ],
    )
    return _plot_result(figure, "Shear Profile (day / night)")


@mcp.tool()
def plot_windrose(speed_sensor: str, direction_sensor: str) -> dict:
    """Plot a 16-sector wind rose with stacked speed bins using directional frequency percentages."""
    return _plot_windrose(session, speed_sensor, direction_sensor)


@mcp.tool()
def plot_weibull(sensor_name: str) -> dict:
    """Plot the measured speed histogram with a fitted Weibull PDF using $f(v;k,A)$ from wind climatology."""
    return _plot_weibull(session, sensor_name)


@mcp.tool()
def plot_diurnal(sensor_names: str) -> dict:
    """Plot mean diurnal wind-speed profiles by hour of day for one or more measured sensors."""
    return _plot_diurnal(session, sensor_names)


@mcp.tool()
def plot_scatter(sensor_a: str, sensor_b: str) -> dict:
    """Plot a measured scatter comparison with OLS line and regression metrics derived from least squares."""
    return _plot_scatter(session, sensor_a, sensor_b)


@mcp.tool()
def plot_timeseries(sensor_names: str) -> dict:
    """Plot one or more measured sensor series, downsampling to daily means for large datasets."""
    return _plot_timeseries(session, sensor_names)


@mcp.tool()
def plot_data_coverage() -> dict:
    """Plot sensor availability as a presence-absence heatmap over time for loaded measured data columns."""
    return _plot_data_coverage(session)


@mcp.tool()
def plot_shear_table(table_type: str = "shear") -> dict:
    """Plot the monthly-hourly shear or roughness lookup table as a heatmap for hub extrapolation review."""
    return _plot_shear_table(session, table_type)


@mcp.tool()
def plot_monthly_means(sensor_names: str) -> dict:
    """Plot grouped monthly means for one or more measured sensors using calendar-month aggregation."""
    return _plot_monthly_means(session, sensor_names)


@mcp.tool()
def plot_ltc_comparison() -> dict:
    """Plot monthly mean and measured-vs-corrected LTC comparisons across all completed correction algorithms."""
    return _plot_ltc_comparison(session)


@mcp.tool()
def plot_annual_means() -> dict:
    """Plot annual mean corrected wind speed for all LTC algorithms and the ensemble over the long-term record."""
    return _plot_annual_means(session)


@mcp.tool()
def plot_uncertainty_breakdown(
    total_pct: float,
    measurement_pct: float,
    vertical_pct: float,
    mcp_pct: float,
    future_pct: float,
) -> dict:
    """Plot stacked uncertainty components contributing to total percent uncertainty by RSS convention."""
    return _plot_uncertainty_breakdown(session, total_pct, measurement_pct, vertical_pct, mcp_pct, future_pct)
