"""visualization._reanalysis — Plotly builders comparing measured masts against ERA5 reanalysis.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from server.state.session import SessionState
from server.tools.visualization._common import (
    MONTH_LABELS,
    _era5_monthly_speed,
    _indexed_frame,
    _plot_result,
    _preferred_measured_speed_column,
    _reference_speed_column,
    _require_series,
    _scatter_metrics,
)


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
    figure.update_layout(
        title="ERA5 Annual Profile — Nodes vs Site",
        xaxis_title="Month",
        yaxis_title="Mean Speed (m/s)",
    )
    return _plot_result(figure, "ERA5 Annual Profile — Nodes vs Site")


def _plot_era5_measured_overlay(state: SessionState) -> dict:
    """Plot concurrent measured and interpolated ERA5 monthly means with overlap diagnostics."""
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolated site data is not available")
    measured = _require_series(state, _preferred_measured_speed_column(state)).rename("measured")
    era5_frame = _indexed_frame(state.era5_interpolated_df)
    speed_col = _reference_speed_column(state, era5_frame)
    overlap = pd.concat([measured, era5_frame[speed_col].rename("era5")], axis=1, join="inner").dropna()
    if overlap.empty:
        raise ValueError("Measured and reference interpolated series do not overlap")
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


def _plot_era5_scatter(state: SessionState) -> dict:
    """Scatter measured vs ERA5 site series over the concurrent (overlap) period, with OLS fit and R²."""
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolated site data is not available")
    measured = _require_series(state, _preferred_measured_speed_column(state)).rename("measured")
    era5_frame = _indexed_frame(state.era5_interpolated_df)
    speed_col = _reference_speed_column(state, era5_frame)
    overlap = pd.concat([measured, era5_frame[speed_col].rename("era5")], axis=1, join="inner").dropna()
    if overlap.empty:
        raise ValueError("Measured and reference interpolated series do not overlap")
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
