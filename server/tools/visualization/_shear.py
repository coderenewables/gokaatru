"""visualization._shear — Plotly builders for the vertical profile: shear/roughness tables, alpha and air density.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from server.state.session import SessionState
from server.tools.atmosphere import _atmospheric_series
from server.tools.shear import _vertical_structure_series
from server.tools.visualization._common import (
    MONTH_LABELS,
    _downsample_timeseries,
    _fit_power_law,
    _indexed_frame,
    _plot_result,
    _scattergl_mode,
    _speed_sensor_pairs,
    _timeseries_frame,
)


def _plot_air_density(
    state: SessionState,
    temperature_sensor: str,
    pressure_sensor: str,
    humidity_sensor: str = "",
) -> dict:
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
    seasonal = [
        valid[valid.index.month.isin(months)].mean()
        for months in ([12, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11])
    ]
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=("Density Time Series", "Monthly Density", "Diurnal Density", "Seasonal Density"),
    )
    figure.add_trace(go.Scatter(x=time_series.index, y=time_series, mode="lines", name="Density"), row=1, col=1)
    figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly, name="Monthly density"), row=1, col=2)
    figure.add_trace(
        go.Scatter(x=list(range(24)), y=diurnal, mode="lines+markers", name="Diurnal density"),
        row=2,
        col=1,
    )
    figure.add_trace(go.Bar(x=["DJF", "MAM", "JJA", "SON"], y=seasonal, name="Seasonal density"), row=2, col=2)
    inputs = f"T: {temperature_name}, P: {pressure_name}" + (
        f", RH: {humidity_name}" if humidity_name else " (dry-air assumption)"
    )
    figure.update_layout(title=f"Air Density — {inputs}", showlegend=False)
    figure.update_yaxes(title_text="kg/m³", row=1, col=1)
    figure.update_yaxes(title_text="kg/m³", row=1, col=2)
    figure.update_yaxes(title_text="kg/m³", row=2, col=1)
    figure.update_yaxes(title_text="kg/m³", row=2, col=2)
    return _plot_result(figure, "Air Density")


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
