"""visualization — Phase 4 MCP tools for Plotly-based wind-resource visual output.

The figure builders live in themed submodules (_measured, _reanalysis, _shear, _ltc)
over shared helpers in _common; this package root wires them to the MCP tool surface
and re-exports every builder so ``server.tools.visualization._plot_*`` keeps working.
"""
from __future__ import annotations

from server.main import mcp
from server.state.session import session
from server.tools.visualization._common import (
    COMPASS_16,
    MONTH_LABELS,
    _annual_mean,
    _directional_frame,
    _downsample_timeseries,
    _era5_monthly_speed,
    _expanding_annual_mean,
    _fit_power_law,
    _indexed_frame,
    _ltc_overlap_frame,
    _ltc_result_series,
    _monthly_mean,
    _plot_result,
    _preferred_measured_speed_column,
    _reference_speed_column,
    _require_series,
    _sample_for_boxplot,
    _scatter_metrics,
    _scattergl_mode,
    _scenario_series,
    _selected_sensor_columns,
    _sensor_names,
    _speed_sensor_pairs,
    _timeseries_frame,
    _wind_speed_bins,
)
from server.tools.visualization._ltc import (
    _plot_annual_means,
    _plot_ltc_annual_convergence,
    _plot_ltc_comparison,
    _plot_ltc_monthly_comparison,
    _plot_ltc_residuals,
    _plot_ltc_scatter,
    _plot_scenario_comparison,
    _plot_uncertainty_breakdown,
    _plot_uncertainty_tornado,
)
from server.tools.visualization._measured import (
    _plot_cleaning_overlay,
    _plot_coverage_timeline,
    _plot_data_coverage,
    _plot_direction_distribution,
    _plot_diurnal,
    _plot_diurnal_boxplot,
    _plot_duration_curve,
    _plot_energy_rose,
    _plot_exceedance_curve,
    _plot_extremes_fit,
    _plot_mast_shadow,
    _plot_mcp_readiness,
    _plot_monthly_boxplot,
    _plot_monthly_means,
    _plot_power_density,
    _plot_qc_flags,
    _plot_ramp_histogram,
    _plot_scatter,
    _plot_seasonal_profile,
    _plot_sector_speed,
    _plot_sensor_distribution,
    _plot_sensor_residuals,
    _plot_speed_distribution,
    _plot_timeseries,
    _plot_timeseries_preview,
    _plot_turbulence_intensity,
    _plot_turbulence_windrose,
    _plot_weibull,
    _plot_wind_veer,
    _plot_windrose,
)
from server.tools.visualization._reanalysis import (
    _plot_era5_comparison,
    _plot_era5_measured_overlay,
    _plot_era5_scatter,
)
from server.tools.visualization._shear import (
    _plot_air_density,
    _plot_shear_alpha,
    _plot_shear_profile,
    _plot_shear_table,
    _plot_shear_timeseries,
)


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


__all__ = [
    "COMPASS_16",
    "MONTH_LABELS",
    "_annual_mean",
    "_directional_frame",
    "_downsample_timeseries",
    "_era5_monthly_speed",
    "_expanding_annual_mean",
    "_fit_power_law",
    "_indexed_frame",
    "_ltc_overlap_frame",
    "_ltc_result_series",
    "_monthly_mean",
    "_plot_air_density",
    "_plot_annual_means",
    "_plot_cleaning_overlay",
    "_plot_coverage_timeline",
    "_plot_data_coverage",
    "_plot_direction_distribution",
    "_plot_diurnal",
    "_plot_diurnal_boxplot",
    "_plot_duration_curve",
    "_plot_energy_rose",
    "_plot_era5_comparison",
    "_plot_era5_measured_overlay",
    "_plot_era5_scatter",
    "_plot_exceedance_curve",
    "_plot_extremes_fit",
    "_plot_ltc_annual_convergence",
    "_plot_ltc_comparison",
    "_plot_ltc_monthly_comparison",
    "_plot_ltc_residuals",
    "_plot_ltc_scatter",
    "_plot_mast_shadow",
    "_plot_mcp_readiness",
    "_plot_monthly_boxplot",
    "_plot_monthly_means",
    "_plot_power_density",
    "_plot_qc_flags",
    "_plot_ramp_histogram",
    "_plot_result",
    "_plot_scatter",
    "_plot_scenario_comparison",
    "_plot_seasonal_profile",
    "_plot_sector_speed",
    "_plot_sensor_distribution",
    "_plot_sensor_residuals",
    "_plot_shear_alpha",
    "_plot_shear_profile",
    "_plot_shear_table",
    "_plot_shear_timeseries",
    "_plot_speed_distribution",
    "_plot_timeseries",
    "_plot_timeseries_preview",
    "_plot_turbulence_intensity",
    "_plot_turbulence_windrose",
    "_plot_uncertainty_breakdown",
    "_plot_uncertainty_tornado",
    "_plot_weibull",
    "_plot_wind_veer",
    "_plot_windrose",
    "_preferred_measured_speed_column",
    "_reference_speed_column",
    "_require_series",
    "_sample_for_boxplot",
    "_scatter_metrics",
    "_scattergl_mode",
    "_scenario_series",
    "_selected_sensor_columns",
    "_sensor_names",
    "_speed_sensor_pairs",
    "_timeseries_frame",
    "_wind_speed_bins",
    "plot_annual_means",
    "plot_data_coverage",
    "plot_diurnal",
    "plot_ltc_comparison",
    "plot_monthly_means",
    "plot_scatter",
    "plot_shear_table",
    "plot_timeseries",
    "plot_uncertainty_breakdown",
    "plot_weibull",
    "plot_windrose",
]
