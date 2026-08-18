"""Focused API-helper coverage for Sensor Overview wind-climate analytics."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from server.state.session import session
from server.tools.atmosphere import _compute_atmospheric_conditions
from server.tools.advanced_analysis import _compute_energy_metrics, _compute_extremes, _compute_persistence, _compute_ramps
from server.tools.data_io import _parse_datamodel, _parse_timeseries
from server.tools.data_io import _get_data_coverage
from server.tools.diagnostics import _compute_mast_effects, _compute_mcp_readiness, _compute_qc_diagnostics, _compute_sensor_comparison
from server.tools.overview_summary import _compute_overview_summary
from server.tools.shear import _compute_vertical_structure
from server.tools.statistics import _compute_turbulence_analysis, _compute_wind_climate
from server.tools.visualization import (
    _plot_direction_distribution,
    _plot_energy_rose,
    _plot_duration_curve,
    _plot_extremes_fit,
    _plot_exceedance_curve,
    _plot_air_density,
    _plot_diurnal_boxplot,
    _plot_monthly_boxplot,
    _plot_power_density,
    _plot_ramp_histogram,
    _plot_mast_shadow,
    _plot_mcp_readiness,
    _plot_qc_flags,
    _plot_sensor_residuals,
    _plot_seasonal_profile,
    _plot_sensor_distribution,
    _plot_shear_alpha,
    _plot_sector_speed,
    _plot_speed_distribution,
    _plot_turbulence_intensity,
    _plot_wind_veer,
)


def test_wind_climate_summary_returns_bankable_speed_and_direction_metrics(uploaded_dataset_session) -> None:
    """A mapped mast speed/direction pair returns fit, exceedance, and sector metrics."""
    summary = _compute_wind_climate(uploaded_dataset_session, "Spd_100m", "Dir_100m")

    assert summary["speed_sensor"] == "Spd_100m"
    assert summary["record_count"] > 0
    assert summary["weibull_k"] > 0
    assert summary["weibull_A"] > 0
    assert math.isfinite(summary["weibull_rmse"])
    assert summary["exceedance"]["p50"] > summary["exceedance"]["p90"]
    assert summary["direction"] is not None
    assert summary["direction"]["prevailing_sector"]
    assert len(summary["sectors"]) == 16
    assert pytest.approx(sum(float(sector["occurrence_pct"]) for sector in summary["sectors"]), abs=0.01) == 100.0
    assert pytest.approx(sum(float(sector["energy_pct"]) for sector in summary["sectors"]), abs=0.01) == 100.0


@pytest.mark.parametrize(
    ("plot", "args"),
    [
        (_plot_speed_distribution, ("Spd_100m",)),
        (_plot_exceedance_curve, ("Spd_100m",)),
        (_plot_direction_distribution, ("Dir_100m",)),
        (_plot_sector_speed, ("Spd_100m", "Dir_100m")),
        (_plot_energy_rose, ("Spd_100m", "Dir_100m")),
    ],
)
def test_wind_climate_plots_return_serialized_figures(uploaded_dataset_session, plot, args) -> None:
    """Each P2 plot returns a valid Plotly JSON figure for the real mast dataset."""
    result = plot(uploaded_dataset_session, *args)

    figure = json.loads(result["plotly_json"])
    assert result["title"]
    assert figure["data"]


def test_vertical_structure_summary_returns_alpha_profile_and_veer(uploaded_dataset_session) -> None:
    """The multi-height lidar fixture yields profile-fit, alpha, and veer statistics."""
    summary = _compute_vertical_structure(uploaded_dataset_session)

    assert len(summary["mean_profile"]) == 8
    assert summary["alpha"]["record_count"] > 0
    assert summary["alpha"]["p10"] < summary["alpha"]["p90"]
    assert 0.0 <= summary["power_law_r_squared"] <= 1.0
    assert summary["veer"] is not None
    assert summary["veer"]["record_count"] > 0


@pytest.mark.parametrize(
    ("plot", "args"),
    [
        (_plot_shear_alpha, ("Spd_80m,Spd_100m,Spd_120m,Spd_140m",)),
        (_plot_wind_veer, ("Dir_80m,Dir_100m,Dir_120m,Dir_140m",)),
    ],
)
def test_vertical_structure_plots_return_serialized_figures(uploaded_dataset_session, plot, args) -> None:
    """Alpha and veer overview plots serialize against the real multi-height lidar fixture."""
    result = plot(uploaded_dataset_session, *args)

    figure = json.loads(result["plotly_json"])
    assert result["title"]
    assert figure["data"]


def test_turbulence_metrics_and_plot_use_matching_standard_deviation_channel(sample_timeseries_df) -> None:
    """TI uses the conventional speed-name `_sd` channel and produces IEC-style metrics."""
    session.timeseries_df = sample_timeseries_df
    summary = _compute_turbulence_analysis(session, "Spd_100m")
    result = _plot_turbulence_intensity(session, "Spd_100m", summary["sd_sensor"])

    assert summary["sd_sensor"] == "Spd_100m_sd"
    assert summary["record_count"] > 0
    assert summary["mean_ti"] == pytest.approx(0.1)
    assert summary["p90_ti"] == pytest.approx(0.1)
    assert json.loads(result["plotly_json"])["data"]


@pytest.fixture
def horns_rev_dataset_session():
    """Load the checked-in Horns Rev mast fixture, including measured atmospheric channels."""
    uploads_dir = Path(__file__).resolve().parents[1] / "data" / "uploads"
    _parse_timeseries(session, str(uploads_dir / "HornsRev-MAST_timeseries_data.csv"))
    _parse_datamodel(session, str(uploads_dir / "HornsRev-MAST_data_model.json"))
    return session


def test_atmospheric_conditions_derive_density_from_real_mast_inputs(horns_rev_dataset_session) -> None:
    """Temperature, pressure, and RH channels produce a finite moist-air density summary."""
    summary = _compute_atmospheric_conditions(horns_rev_dataset_session)

    assert summary["temperature_sensor"] == "Tmp2_55m"
    assert summary["pressure_sensor"] == "Prs_55m"
    assert summary["humidity_sensor"] == "Hum_13m"
    assert summary["air_density"]["record_count"] > 0
    assert 0.9 < summary["air_density"]["mean"] < 1.4
    assert summary["humidity"] is not None


@pytest.mark.parametrize(
    ("plot", "args"),
    [
        (_plot_sensor_distribution, ("Tmp2_55m",)),
        (_plot_diurnal_boxplot, ("Tmp2_55m",)),
        (_plot_monthly_boxplot, ("Tmp2_55m",)),
        (_plot_seasonal_profile, ("Spd_58m",)),
        (_plot_air_density, ("Tmp2_55m", "Prs_55m", "Hum_13m")),
    ],
)
def test_p4_atmospheric_and_climatology_plots_serialize(horns_rev_dataset_session, plot, args) -> None:
    """P4 generic, seasonal, and density charts serialize for the real mast fixture."""
    result = plot(horns_rev_dataset_session, *args)

    assert result["title"]
    assert json.loads(result["plotly_json"])["data"]


def test_p5_energy_and_advanced_metrics_use_real_mast_records(horns_rev_dataset_session) -> None:
    """Energy, ramps, and persistence report finite diagnostics for the Horns Rev mast."""
    energy = _compute_energy_metrics(horns_rev_dataset_session, "Spd_58m", "Dir_58m")
    ramps = _compute_ramps(horns_rev_dataset_session, "Spd_58m")
    persistence = _compute_persistence(horns_rev_dataset_session, "Spd_58m")

    assert energy["density_source"] == "measured"
    assert energy["wind_power_density_w_m2"] > 0
    assert len(energy["sectors"]) == 16
    assert ramps["record_count"] > 0
    assert ramps["p95_absolute_ramp_m_s"] >= ramps["mean_absolute_ramp_m_s"]
    assert persistence["calm_period_count"] > 0
    assert persistence["max_calm_duration_minutes"] > 0


def test_extreme_winds_refuse_a_campaign_with_no_complete_year(horns_rev_dataset_session) -> None:
    """F-78 (HIGH) — FIXED, on the real fixture. A 10.5-month campaign has no annual maximum.

    The Horns Rev mast runs 1999-05-14 to 2000-04-01. That is two *calendar* years and not
    one complete one: 1999 covers May-December (63.6% of the calendar) and 2000 covers
    January-April (25.1%).

    ``resample("YE").max()`` called those two annual maxima and fitted a 50- and a 100-year
    wind to them, which is exactly the defect F-78 describes — the two "annual maxima" are a
    summer-half maximum and a winter-half maximum from a single 10.5-month campaign.

    The tool now refuses and says why, rather than publishing a design value that cannot
    exist. `_compute_overview_summary` treats extremes as optional, so the Sensor Overview
    degrades to omitting the panel instead of failing.
    """
    with pytest.raises(ValueError, match="at least 2 calendar years"):
        _compute_extremes(horns_rev_dataset_session, "Spd_58m")

    # The gate is a parameter, so the old screening estimate is still reachable — but only
    # by asking for it explicitly, which is the whole point.
    screening = _compute_extremes(horns_rev_dataset_session, "Spd_58m", min_year_coverage=0.0)
    assert screening["sample_years"] == 2
    assert screening["screening_only"] is True
    # And even then no GEV is fitted to two points.
    assert screening["gev"]["available"] is False
    assert "screening basis only" in screening["warning"]


@pytest.mark.parametrize(
    ("plot", "args"),
    [
        (_plot_power_density, ("Spd_58m", "Dir_58m")),
        (_plot_ramp_histogram, ("Spd_58m",)),
        (_plot_duration_curve, ("Spd_58m",)),
    ],
)
def test_p5_plots_serialize_for_real_mast_records(horns_rev_dataset_session, plot, args) -> None:
    """All P5 charts serialize from the same real mast records used by the metric summaries."""
    result = plot(horns_rev_dataset_session, *args)

    assert result["title"]
    assert json.loads(result["plotly_json"])["data"]


def test_extremes_plot_follows_the_same_refusal(horns_rev_dataset_session) -> None:
    """The chart cannot draw a return-level curve the fit refused to produce.

    Drawing one anyway would put the number the guard exists to suppress back on the screen,
    so `_plot_extremes_fit` inherits the refusal rather than working around it. Where the
    fit does run but the GEV is withheld for want of years, the chart draws Gumbel alone and
    labels itself.
    """
    with pytest.raises(ValueError, match="at least 2 calendar years"):
        _plot_extremes_fit(horns_rev_dataset_session, "Spd_58m")


def test_p6_comparison_mast_effects_and_qc_use_real_mast_records(horns_rev_dataset_session) -> None:
    """Paired anemometers support comparison/mast diagnostics and all speed sensors support QC checks."""
    comparison = _compute_sensor_comparison(horns_rev_dataset_session)
    mast_effects = _compute_mast_effects(horns_rev_dataset_session)
    qc = _compute_qc_diagnostics(horns_rev_dataset_session)

    assert comparison["sensor_a"] == "Spd_NE_45m"
    assert comparison["sensor_b"] == "Spd_SW_45m"
    assert comparison["record_count"] > 0
    assert -1.0 <= comparison["correlation"] <= 1.0
    assert len(mast_effects["sectors"]) == 16
    assert len(qc["sensors"]) == 8


def test_p6_mcp_readiness_uses_hourly_concurrent_era5(horns_rev_dataset_session) -> None:
    """MCP readiness reports correlation and adjustment using hourly measured/reference overlap."""
    hourly = horns_rev_dataset_session.timeseries_df[["Spd_58m"]].resample("h").mean().dropna().iloc[:1000]
    horns_rev_dataset_session.era5_interpolated_df = pd.DataFrame(
        {"Spd_100m": hourly["Spd_58m"].to_numpy(dtype=float) * 0.96 + 0.35},
        index=hourly.index,
    )
    readiness = _compute_mcp_readiness(horns_rev_dataset_session, "Spd_58m")

    assert readiness["concurrent_hours"] == len(hourly)
    assert readiness["r_squared"] > 0.99
    assert readiness["ready"] is True


@pytest.mark.parametrize(
    ("plot", "args"),
    [
        (_plot_sensor_residuals, ("Spd_NE_45m", "Spd_SW_45m")),
        (_plot_mast_shadow, ("Spd_NE_45m", "Spd_SW_45m", "Dir_43m")),
        (_plot_qc_flags, ()),
    ],
)
def test_p6_diagnostic_plots_serialize_for_real_mast_records(horns_rev_dataset_session, plot, args) -> None:
    """Comparison, mast-effect, and QC plots serialize for the real Horns Rev mast fixture."""
    result = plot(horns_rev_dataset_session, *args)

    assert result["title"]
    assert json.loads(result["plotly_json"])["data"]


def test_p6_mcp_plot_serializes_with_concurrent_era5(horns_rev_dataset_session) -> None:
    """The MCP readiness plot serializes after a concurrent interpolated ERA5 reference is present."""
    hourly = horns_rev_dataset_session.timeseries_df[["Spd_58m"]].resample("h").mean().dropna().iloc[:1000]
    horns_rev_dataset_session.era5_interpolated_df = pd.DataFrame(
        {"Spd_100m": hourly["Spd_58m"].to_numpy(dtype=float) * 0.96 + 0.35},
        index=hourly.index,
    )
    result = _plot_mcp_readiness(horns_rev_dataset_session, "Spd_58m")

    assert result["title"]
    assert json.loads(result["plotly_json"])["data"]


def test_p7_overview_summary_consolidates_available_and_unavailable_metrics(horns_rev_dataset_session) -> None:
    """The consolidated table retains core WRA metrics when optional MCP inputs are absent."""
    summary = _compute_overview_summary(horns_rev_dataset_session, "Spd_58m", "Dir_58m")
    categories = {item["category"] for item in summary["items"]}

    assert summary["speed_sensor"] == "Spd_58m"
    assert {"Data quality", "Wind climate", "Energy", "QC"}.issubset(categories)
    assert any(item["status"] == "unavailable" for item in summary["items"])


def test_wb_esmap_coverage_uses_dominant_ten_minute_timestamp_phase() -> None:
    """A partial first interval and sub-minute clock drift must not invalidate an otherwise complete series."""
    uploads_dir = Path(__file__).resolve().parents[1] / "data" / "uploads"
    _parse_timeseries(session, str(uploads_dir / "WB-ESMAP_Launakalana_timeseries_data.csv"))
    _parse_datamodel(session, str(uploads_dir / "WB-ESMAP_Launakalana_data_model.json"))
    coverage = _get_data_coverage(session, "Spd1_80m_25deg")

    assert coverage["total_records"] == 54532
    assert coverage["valid_records"] == 54530
    assert coverage["coverage_pct"] == pytest.approx(99.9963329791667)
    assert coverage["largest_gap_minutes"] == 20
    assert coverage["gaps_over_1_hour"] == 0