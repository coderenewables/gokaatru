"""visualization._measured — Plotly builders for measured-mast climatology, distribution and QC plots.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import genextreme, gumbel_r, weibull_min

from server.core.validators import to_utc_index
from server.state.session import SessionState
from server.tools.advanced_analysis import (
    _compute_energy_metrics,
    _compute_extremes,
    _compute_persistence,
    _consecutive_ramps,
)
from server.tools.diagnostics import (
    _compute_mast_effects,
    _compute_mcp_readiness,
    _compute_qc_diagnostics,
    _compute_sensor_comparison,
)
from server.tools.shear import _vertical_structure_series
from server.tools.visualization._common import (
    COMPASS_16,
    MONTH_LABELS,
    _directional_frame,
    _monthly_mean,
    _plot_result,
    _require_series,
    _sample_for_boxplot,
    _scatter_metrics,
    _scattergl_mode,
    _selected_sensor_columns,
    _sensor_names,
    _speed_sensor_pairs,
    _timeseries_frame,
    _wind_speed_bins,
)


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
    """Plot the measured speed histogram with a fitted Weibull PDF using $f(v;k,A)$ from wind climatology.

    Routes through ``statistics._compute_weibull_params`` so the plot legend
    always agrees with the tabulated k/A/mean — fixing the same fit in one
    place only (see D24/D31).
    """
    series = _require_series(state, sensor_name).dropna()
    positive = series[series > 0.0]
    if positive.empty:
        raise ValueError(f"Sensor '{sensor_name}' has no positive values for Weibull plotting")
    # Lazy import to avoid circular dependency (visualization → statistics → main → visualization)
    from server.tools.statistics import _compute_weibull_params

    params = _compute_weibull_params(state, sensor_name)
    shape_k = params["k"]
    scale_a = params["A"]
    x_values = np.linspace(0.0, float(positive.max()), 250)
    pdf_values = weibull_min.pdf(x_values, shape_k, loc=0, scale=scale_a)
    fit_method = params.get("fit_method", "wasp_m1_m3")
    trace_name = (
        f"Weibull k={shape_k:.2f}, A={scale_a:.2f}, "
        f"mean={params.get('mean_speed', 0):.2f} ({fit_method})"
    )
    figure = go.Figure()
    figure.add_trace(go.Histogram(x=positive, histnorm="probability density", nbinsx=40, name=sensor_name, opacity=0.7))
    figure.add_trace(
        go.Scatter(
            x=x_values,
            y=pdf_values,
            mode="lines",
            name=trace_name,
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
    figure.add_trace(
        go.Histogram(x=speed, histnorm="probability density", nbinsx=40, name="Density", opacity=0.72),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=sorted_speed, y=exceedance, mode="lines", name="Exceedance", line=dict(color="#c86a2a")
        ),
        secondary_y=True,
    )
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
    figure.add_trace(
        go.Histogram(x=values, histnorm="probability density", nbinsx=40, name="Density", opacity=0.72),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=ordered, y=cumulative, mode="lines", name="Cumulative", line=dict(color="#c86a2a")
        ),
        secondary_y=True,
    )
    figure.update_layout(title=f"Distribution — {sensor_name}", bargap=0.04)
    figure.update_xaxes(title_text="Measured Value")
    figure.update_yaxes(title_text="Probability Density", secondary_y=False)
    figure.update_yaxes(title_text="Cumulative (%)", range=[0, 100], secondary_y=True)
    return _plot_result(figure, f"Distribution — {sensor_name}")


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
    figure.update_layout(
        title=f"Monthly Distribution — {sensor_name}",
        xaxis_title="Month",
        yaxis_title="Measured Value",
    )
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
        subplot_titles=(
            "Power-Density Distribution",
            "Monthly Power Density",
            "Directional Energy",
            "Directional Power Density",
        ),
    )
    figure.add_trace(go.Histogram(x=instantaneous, nbinsx=50, name="Power density"), row=1, col=1)
    figure.add_trace(go.Bar(x=MONTH_LABELS, y=metrics["monthly_power_density_w_m2"], name="Monthly WPD"), row=1, col=2)
    sectors = metrics["sectors"]
    if sectors:
        sector_rows = list(sectors)
        figure.add_trace(
            go.Barpolar(
                r=[row["energy_pct"] for row in sector_rows],
                theta=[row["label"] for row in sector_rows],
                name="Energy contribution",
            ),
            row=2,
            col=1,
        )
        figure.add_trace(
            go.Barpolar(
                r=[row["power_density_w_m2"] for row in sector_rows],
                theta=[row["label"] for row in sector_rows],
                name="Sector WPD",
            ),
            row=2,
            col=2,
        )
    figure.update_layout(
        title=f"Wind Power Density — {speed_sensor} ({metrics['density_source']} density)",
        showlegend=False,
    )
    figure.update_yaxes(title_text="W/m²", row=1, col=2)
    return _plot_result(figure, "Wind Power Density")


def _plot_extremes_fit(state: SessionState, speed_sensor: str) -> dict:
    """Plot annual maxima with fitted GEV/Gumbel return-level curves."""
    extremes = _compute_extremes(state, speed_sensor)
    maxima = list(extremes["annual_maxima"])
    periods = np.array([2, 5, 10, 20, 50, 100], dtype=float)
    gev = extremes["gev"]
    gumbel = extremes["gumbel"]
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Annual Maxima", "Return-Level Fit"))
    figure.add_trace(
        go.Bar(
            x=[row["year"] for row in maxima],
            y=[row["max_speed"] for row in maxima],
            name="Annual maxima",
        ),
        row=1,
        col=1,
    )
    # The GEV curve is only drawn when the fit was identifiable (F-77). Below the year
    # threshold `_compute_extremes` does not fit it at all, and drawing a curve from absent
    # parameters would put the very number the guard exists to suppress back on the screen.
    if gev.get("available"):
        gev_levels = genextreme.isf(
            1.0 / periods, float(gev["shape"]), loc=float(gev["location"]), scale=float(gev["scale"])
        )
        figure.add_trace(go.Scatter(x=periods, y=gev_levels, mode="lines+markers", name="GEV"), row=1, col=2)
    gumbel_levels = gumbel_r.isf(1.0 / periods, loc=float(gumbel["location"]), scale=float(gumbel["scale"]))
    figure.add_trace(
        go.Scatter(
            x=periods, y=gumbel_levels, mode="lines+markers", name="Gumbel", line=dict(dash="dash")
        ),
        row=1,
        col=2,
    )
    subtitle = " — Screening Only" if extremes["screening_only"] else ""
    if not gev.get("available"):
        subtitle += f" — Gumbel only ({extremes['sample_years']} annual maxima)"
    figure.update_layout(title="Extreme Wind Analysis" + subtitle)
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
    figure.update_layout(
        title=f"Wind Persistence — {speed_sensor}",
        xaxis_title="Ranked Period",
        yaxis_title="Duration (minutes)",
    )
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
    figure.add_trace(
        go.Scatter(x=residuals["timestamp"], y=residuals["value"], mode="lines", name="B - A"),
        row=1,
        col=1,
    )
    figure.add_trace(go.Histogram(x=residuals["value"], nbinsx=50, name="Residuals"), row=1, col=2)
    figure.update_layout(title=f"Sensor Residuals — {result['sensor_a']} vs {result['sensor_b']}", showlegend=False)
    figure.update_yaxes(title_text="Residual (m/s)", row=1, col=1)
    return _plot_result(figure, "Sensor Residuals")


def _plot_mast_shadow(state: SessionState, sensor_a: str, sensor_b: str, direction_sensor: str) -> dict:
    """Plot measured speed ratio by direction to review potential mast-shadow sectors."""
    result = _compute_mast_effects(state, sensor_a, sensor_b, direction_sensor)
    sectors = result["sectors"]
    figure = go.Figure(
        go.Barpolar(
            r=[row["speed_ratio"] for row in sectors],
            theta=[row["label"] for row in sectors],
            name="Speed ratio",
        )
    )
    figure.add_trace(
        go.Scatterpolar(
            r=[result["baseline_speed_ratio"]] * 16,
            theta=[row["label"] for row in sectors],
            mode="lines",
            name="Median ratio",
            line=dict(dash="dash"),
        )
    )
    figure.update_layout(
        title=f"Mast-Effect Speed Ratio — {result['sensor_b']} / {result['sensor_a']}",
        polar=dict(radialaxis=dict(title="Speed Ratio")),
    )
    return _plot_result(figure, "Mast-Effect Speed Ratio")


def _plot_qc_flags(state: SessionState) -> dict:
    """Plot non-mutating QC diagnostic counts per measured wind-speed sensor."""
    result = _compute_qc_diagnostics(state)
    rows = result["sensors"]
    figure = go.Figure()
    for key, label in [
        ("range_failures", "Range"),
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
    measured = to_utc_index(state.timeseries_df[[speed_sensor]]).resample("h").mean()
    concurrent = measured.join(to_utc_index(state.era5_interpolated_df[[reference]]), how="inner").dropna()
    sampled = concurrent.iloc[:: max(1, len(concurrent) // 10_000)]
    monthly = concurrent.resample("MS").mean()
    figure = make_subplots(rows=1, cols=2, subplot_titles=("Concurrent Scatter", "Monthly Mean Comparison"))
    figure.add_trace(
        go.Scattergl(
            x=sampled[reference],
            y=sampled[speed_sensor],
            mode="markers",
            marker=dict(opacity=0.35),
            name="Concurrent",
        ),
        row=1,
        col=1,
    )
    line = np.linspace(float(sampled[reference].min()), float(sampled[reference].max()), 100)
    figure.add_trace(
        go.Scatter(
            x=line,
            y=float(readiness["slope"]) * line + float(readiness["offset"]),
            mode="lines",
            name="OLS",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(x=monthly.index, y=monthly[speed_sensor], mode="lines+markers", name="Measured"),
        row=1,
        col=2,
    )
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
    figure.update_layout(
        title=f"Exceedance Probability — {sensor_name}",
        xaxis_title="Exceedance Probability (%)",
        yaxis_title="Wind Speed (m/s)",
    )
    figure.update_xaxes(autorange="reversed")
    return _plot_result(figure, f"Exceedance Probability — {sensor_name}")


def _plot_direction_distribution(state: SessionState, direction_sensor: str) -> dict:
    """Plot the circular directional-frequency distribution for one wind vane."""
    direction = np.mod(_require_series(state, direction_sensor).dropna().to_numpy(dtype=float), 360.0)
    if len(direction) == 0:
        raise ValueError(f"Sensor '{direction_sensor}' has no valid values for direction plotting")
    counts, _ = np.histogram(direction, bins=np.arange(-11.25, 371.25, 22.5))
    figure = go.Figure(go.Barpolar(r=counts / counts.sum() * 100.0, theta=COMPASS_16, name=direction_sensor))
    figure.update_layout(
        title=f"Direction Distribution — {direction_sensor}",
        polar=dict(radialaxis=dict(ticksuffix="%")),
    )
    return _plot_result(figure, f"Direction Distribution — {direction_sensor}")


def _plot_sector_speed(state: SessionState, speed_sensor: str, direction_sensor: str) -> dict:
    """Plot sector mean wind speed for a selected speed/direction pair."""
    frame, sector_index = _directional_frame(state, speed_sensor, direction_sensor)
    speeds = [
        float(frame.loc[sector_index == index, speed_sensor].mean())
        if (sector_index == index).any()
        else 0.0
        for index in range(16)
    ]
    figure = go.Figure(go.Bar(x=COMPASS_16, y=speeds, name="Mean speed", marker_color="#0b7a6f"))
    figure.update_layout(
        title=f"Sector Mean Wind Speed — {speed_sensor}",
        xaxis_title="Direction sector",
        yaxis_title="Mean Speed (m/s)",
    )
    return _plot_result(figure, f"Sector Mean Wind Speed — {speed_sensor}")


def _plot_energy_rose(state: SessionState, speed_sensor: str, direction_sensor: str) -> dict:
    """Plot directional wind-energy contribution proportional to the cube of measured speed."""
    frame, sector_index = _directional_frame(state, speed_sensor, direction_sensor)
    cube_speed = frame[speed_sensor].to_numpy(dtype=float) ** 3
    total = float(cube_speed.sum())
    contribution = [
        0.0 if total == 0 else float(cube_speed[sector_index == index].sum() / total * 100.0)
        for index in range(16)
    ]
    figure = go.Figure(
        go.Barpolar(r=contribution, theta=COMPASS_16, name="Energy contribution", marker_color="#c86a2a")
    )
    figure.update_layout(
        title=f"Directional Energy Contribution — {speed_sensor}",
        polar=dict(radialaxis=dict(ticksuffix="%")),
    )
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


def _plot_monthly_means(state: SessionState, sensor_names: str) -> dict:
    """Plot grouped monthly means for one or more measured sensors using calendar-month aggregation."""
    figure = go.Figure()
    for sensor_name in _sensor_names(sensor_names):
        monthly = _monthly_mean(_require_series(state, sensor_name))
        figure.add_trace(go.Bar(x=MONTH_LABELS, y=monthly.tolist(), name=sensor_name))
    figure.update_layout(title="Monthly Means", xaxis_title="Month", yaxis_title="Mean Speed (m/s)", barmode="group")
    return _plot_result(figure, "Monthly Means")


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
    for label, reference_ti, color in [
        ("IEC Class A", 0.16, "#c86a2a"),
        ("IEC Class B", 0.14, "#756c4f"),
        ("IEC Class C", 0.12, "#5f716a"),
    ]:
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
        [
            _require_series(state, speed_sensor),
            _require_series(state, sd_sensor),
            _require_series(state, direction_sensor),
        ],
        axis=1,
    ).dropna()
    valid = frame[(frame[speed_sensor] > 3.0) & (frame[sd_sensor] >= 0.0)].copy()
    if valid.empty:
        raise ValueError(
            "Turbulence wind rose requires concurrent speed > 3 m/s, non-negative SD, and direction values"
        )
    valid["ti"] = valid[sd_sensor] / valid[speed_sensor]
    valid = valid.replace([np.inf, -np.inf], np.nan).dropna(subset=["ti"])
    sector_width = 360.0 / 16.0
    valid["sector"] = (((valid[direction_sensor] + sector_width / 2.0) % 360.0) // sector_width).astype(int)
    grouped = valid.groupby("sector", observed=False)["ti"]
    mean_ti = grouped.mean().reindex(range(16), fill_value=0.0)
    p90_ti = grouped.quantile(0.90).reindex(range(16), fill_value=0.0)
    title = f"Turbulence Wind Rose — {speed_sensor} by {direction_sensor}"
    figure = go.Figure()
    figure.add_trace(
        go.Barpolar(
            r=mean_ti.tolist(), theta=COMPASS_16, name="Mean TI", marker_color="#0b7a6f", opacity=0.8
        )
    )
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
