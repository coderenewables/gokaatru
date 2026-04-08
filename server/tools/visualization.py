"""visualization — Phase 4 MCP tools for Plotly-based wind-resource visual outputs.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import base64
from typing import cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import weibull_min

from server.main import mcp
from server.state.session import SessionState, session

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
    """Parse comma-separated sensor-name arguments used by multi-series visualization tools."""
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
    figure.update_layout(title="Wind Rose", polar=dict(radialaxis=dict(ticksuffix="%")))
    return _plot_result(figure, "Wind Rose")


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


def _plot_diurnal(state: SessionState, sensor_names: str) -> dict:
    """Plot mean diurnal wind-speed profiles by hour of day for one or more measured sensors."""
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        series = _require_series(state, sensor_name)
        profile = series.groupby(series.index.hour).mean().reindex(range(24))
        figure.add_trace(go.Scatter(x=list(range(24)), y=profile.tolist(), mode="lines+markers", name=sensor_name))
    figure.update_layout(title="Diurnal Profile", xaxis_title="Hour", yaxis_title="Mean Speed (m/s)")
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
    """Plot sensor availability as a presence-absence heatmap over time for loaded measured data columns."""
    frame = _timeseries_frame(state).copy()
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
    for label, value, color in [("IEC Class A", 0.16, "#c86a2a"), ("IEC Class B", 0.14, "#756c4f"), ("IEC Class C", 0.12, "#5f716a")]:
        figure.add_trace(
            go.Scatter(
                x=[x_min, x_max],
                y=[value, value],
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


def _plot_shear_profile(state: SessionState) -> dict:
    """Plot mean measured wind-speed profile across heights with a fitted power-law curve."""
    frame = _timeseries_frame(state)
    speed_pairs = [(height, column) for height, column in _speed_sensor_pairs(state) if column in frame.columns]
    if len(speed_pairs) < 2:
        raise ValueError("Shear profile plotting requires at least two mapped wind-speed sensors")
    heights = np.asarray([height for height, _ in speed_pairs], dtype=float)
    means = np.asarray([frame[column].dropna().mean() for _, column in speed_pairs], dtype=float)
    valid = np.isfinite(means) & (means > 0.0)
    if valid.sum() < 2:
        raise ValueError("Shear profile plotting requires at least two sensors with positive mean wind speeds")
    log_heights = np.log(heights[valid])
    log_speeds = np.log(means[valid])
    centered_x = log_heights - float(np.mean(log_heights))
    centered_y = log_speeds - float(np.mean(log_speeds))
    denominator = float(np.sum(centered_x**2))
    if denominator <= 1e-12:
        raise ValueError("Shear profile fit requires distinct measurement heights")
    alpha = float(np.sum(centered_x * centered_y) / denominator)
    intercept = float(np.mean(log_speeds) - alpha * np.mean(log_heights))
    curve_heights = np.linspace(float(heights.min()), float(heights.max()), 100)
    curve_speeds = np.exp(intercept) * np.power(curve_heights, alpha)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=means[valid],
            y=heights[valid],
            mode="markers",
            name="Measured",
            marker=dict(size=10, color="#0b7a6f"),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=curve_speeds,
            y=curve_heights,
            mode="lines",
            name="Power-law fit",
            line=dict(color="#c86a2a", width=3),
        )
    )
    figure.update_layout(
        title="Shear Profile",
        xaxis_title="Mean Wind Speed (m/s)",
        yaxis_title="Height (m)",
        annotations=[
            dict(
                xref="paper",
                yref="paper",
                x=0.98,
                y=0.04,
                text=f"α = {alpha:.3f}",
                showarrow=False,
                bgcolor="rgba(255,250,240,0.92)",
            )
        ],
    )
    return _plot_result(figure, "Shear Profile")


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
