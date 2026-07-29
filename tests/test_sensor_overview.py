"""Focused API-helper coverage for Sensor Overview wind-climate analytics."""
from __future__ import annotations

import json
import math

import pytest

from server.state.session import session
from server.tools.shear import _compute_vertical_structure
from server.tools.statistics import _compute_turbulence_analysis, _compute_wind_climate
from server.tools.visualization import (
    _plot_direction_distribution,
    _plot_energy_rose,
    _plot_exceedance_curve,
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