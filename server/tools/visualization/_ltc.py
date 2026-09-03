"""visualization._ltc — Plotly builders for LTC results, uncertainty and scenario comparison.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import norm

from server.state.session import SessionState
from server.tools.visualization._common import (
    MONTH_LABELS,
    _annual_mean,
    _expanding_annual_mean,
    _indexed_frame,
    _ltc_overlap_frame,
    _monthly_mean,
    _plot_result,
    _preferred_measured_speed_column,
    _require_series,
    _scatter_metrics,
    _scenario_series,
)


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
            f"<sup>R²={metrics['r2']:.3f}, RMSE={metrics['rmse']:.3f}, "
            f"MBE={float((overlap['corrected'] - overlap['measured']).mean()):.3f}</sup>"
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
    figure.update_layout(
        title="Monthly LTC Comparison",
        xaxis_title="Month",
        yaxis_title="Mean Speed (m/s)",
        barmode="group",
    )
    return _plot_result(figure, "Monthly LTC Comparison")


def _plot_ltc_annual_convergence(state: SessionState) -> dict:
    """Plot expanding annual-mean convergence for all LTC algorithms and the ensemble when available."""
    if not state.ltc_results and state.ensemble_df is None:
        raise ValueError("Annual convergence plotting requires at least one LTC or ensemble result")
    figure = go.Figure()
    for algorithm, payload in sorted(state.ltc_results.items()):
        years, running_mean, final_mean = _expanding_annual_mean(
            _indexed_frame(payload["df"])["corrected_wind_speed"].dropna()
        )
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
        years, running_mean, final_mean = _expanding_annual_mean(
            _indexed_frame(state.ensemble_df)["Ensemble_Speed"].dropna()
        )
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
    figure.update_layout(
        title="Annual Convergence",
        xaxis_title="Years Included",
        yaxis_title="Running Mean Speed (m/s)",
    )
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


def _plot_scenario_comparison(state: SessionState) -> dict:
    """Plot saved scenario mean speeds with P-factor bars and total uncertainty overlay."""
    names, means, p75_values, p90_values, uncertainties = _scenario_series(state)
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(go.Bar(x=names, y=means, name="LT Mean"), secondary_y=False)
    figure.add_trace(go.Bar(x=names, y=p75_values, name="P75 speed"), secondary_y=False)
    figure.add_trace(go.Bar(x=names, y=p90_values, name="P90 speed"), secondary_y=False)
    figure.add_trace(
        go.Scatter(
            x=names,
            y=uncertainties,
            mode="lines+markers",
            name="Total uncertainty",
            line=dict(color="#c86a2a", width=3),
        ),
        secondary_y=True,
    )
    figure.update_layout(title="Scenario Comparison", barmode="group")
    figure.update_yaxes(title_text="Wind Speed (m/s)", secondary_y=False)
    figure.update_yaxes(title_text="Total Uncertainty (%)", secondary_y=True)
    return _plot_result(figure, "Scenario Comparison")
