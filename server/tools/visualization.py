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
from server.state.session import session
from server.tools.statistics import compute_scatter_stats

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _timeseries_frame() -> pd.DataFrame:
    """Return the loaded measured dataframe required by Phase 4 visualization tools."""
    if session.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return session.timeseries_df


def _indexed_frame(frame_like: object) -> pd.DataFrame:
    """Normalize stored payloads to a datetime-indexed dataframe for Plotly time-series rendering."""
    frame = pd.DataFrame(frame_like).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(frame.index)
    return frame.sort_index()


def _require_series(sensor_name: str) -> pd.Series:
    """Return a measured sensor series for direct visualization from the loaded timeseries dataframe."""
    frame = _timeseries_frame()
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


def _preferred_measured_speed_column() -> str:
    """Choose the most relevant measured speed column for LTC comparison figures."""
    frame = _timeseries_frame()
    hub_height = session.get_hub_height_m()
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


@mcp.tool()
def plot_windrose(speed_sensor: str, direction_sensor: str) -> dict:
    """Plot a 16-sector wind rose with stacked speed bins using directional frequency percentages."""
    frame = pd.concat([_require_series(speed_sensor), _require_series(direction_sensor)], axis=1).dropna()
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


@mcp.tool()
def plot_weibull(sensor_name: str) -> dict:
    """Plot the measured speed histogram with a fitted Weibull PDF using $f(v;k,A)$ from wind climatology."""
    series = _require_series(sensor_name).dropna()
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


@mcp.tool()
def plot_diurnal(sensor_names: str) -> dict:
    """Plot mean diurnal wind-speed profiles by hour of day for one or more measured sensors."""
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        series = _require_series(sensor_name)
        profile = series.groupby(series.index.hour).mean().reindex(range(24))
        figure.add_trace(go.Scatter(x=list(range(24)), y=profile.tolist(), mode="lines+markers", name=sensor_name))
    figure.update_layout(title="Diurnal Profile", xaxis_title="Hour", yaxis_title="Mean Speed (m/s)")
    return _plot_result(figure, "Diurnal Profile")


@mcp.tool()
def plot_scatter(sensor_a: str, sensor_b: str) -> dict:
    """Plot a measured scatter comparison with OLS line and regression metrics derived from least squares."""
    frame = pd.concat([_require_series(sensor_a), _require_series(sensor_b)], axis=1, join="inner").dropna()
    if frame.empty:
        raise ValueError(f"No concurrent valid data between '{sensor_a}' and '{sensor_b}'")
    if len(frame) > 10000:
        frame = frame.iloc[:: max(1, len(frame) // 10000)]
    metrics = compute_scatter_stats(sensor_a, sensor_b)
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


@mcp.tool()
def plot_timeseries(sensor_names: str) -> dict:
    """Plot one or more measured sensor series, downsampling to daily means for large datasets."""
    frame = _timeseries_frame()[_sensor_names(sensor_names)].copy()
    plot_frame = frame.resample("D").mean() if len(frame) > 50000 else frame
    figure = go.Figure()
    for column in plot_frame.columns:
        figure.add_trace(go.Scatter(x=plot_frame.index, y=plot_frame[column], mode="lines", name=column))
    figure.update_layout(title="Timeseries", xaxis_title="Timestamp", yaxis_title="Value")
    return _plot_result(figure, "Timeseries")


@mcp.tool()
def plot_data_coverage() -> dict:
    """Plot sensor availability as a presence-absence heatmap over time for loaded measured data columns."""
    frame = _timeseries_frame().copy()
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


@mcp.tool()
def plot_shear_table(table_type: str = "shear") -> dict:
    """Plot the monthly-hourly shear or roughness lookup table as a heatmap for hub extrapolation review."""
    if table_type == "shear":
        table = session.shear_table
        colorscale = "Viridis"
        title = "Shear Table"
    elif table_type == "roughness":
        table = session.roughness_table
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


@mcp.tool()
def plot_monthly_means(sensor_names: str) -> dict:
    """Plot grouped monthly means for one or more measured sensors using calendar-month aggregation."""
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        monthly = _monthly_mean(_require_series(sensor_name))
        figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly.tolist(), name=sensor_name))
    figure.update_layout(title="Monthly Means", xaxis_title="Month", yaxis_title="Mean Speed (m/s)", barmode="group")
    return _plot_result(figure, "Monthly Means")


@mcp.tool()
def plot_ltc_comparison() -> dict:
    """Plot monthly mean and measured-vs-corrected LTC comparisons across all completed correction algorithms."""
    if not session.ltc_results:
        raise ValueError("At least one LTC result is required for LTC comparison plotting")
    measured = _require_series(_preferred_measured_speed_column())
    figure = make_subplots(rows=2, cols=1, subplot_titles=("Monthly Mean Comparison", "Measured vs Corrected"))
    figure.add_trace(
        go.Scatter(x=MONTH_LABELS, y=_monthly_mean(measured).tolist(), mode="lines+markers", name="Measured"),
        row=1,
        col=1,
    )
    for algorithm, payload in sorted(session.ltc_results.items()):
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


@mcp.tool()
def plot_annual_means() -> dict:
    """Plot annual mean corrected wind speed for all LTC algorithms and the ensemble over the long-term record."""
    if not session.ltc_results and session.ensemble_df is None:
        raise ValueError("Annual means plotting requires at least one LTC or ensemble result")
    figure = go.Figure()
    for algorithm, payload in sorted(session.ltc_results.items()):
        frame = _indexed_frame(payload["df"])
        annual = _annual_mean(frame["corrected_wind_speed"].dropna())
        figure.add_trace(go.Scatter(x=annual.index.tolist(), y=annual.tolist(), mode="lines+markers", name=algorithm))
    if session.ensemble_df is not None:
        ensemble = _indexed_frame(session.ensemble_df)
        annual = _annual_mean(ensemble["Ensemble_Speed"].dropna())
        figure.add_trace(go.Scatter(x=annual.index.tolist(), y=annual.tolist(), mode="lines+markers", name="ensemble"))
    figure.update_layout(title="Annual Mean Wind Speed", xaxis_title="Year", yaxis_title="Mean Speed (m/s)")
    return _plot_result(figure, "Annual Mean Wind Speed")


@mcp.tool()
def plot_uncertainty_breakdown(
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
