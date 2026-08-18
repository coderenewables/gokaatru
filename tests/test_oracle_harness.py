"""Analytic-truth verification of the core physics — Step 1 of the logic audit.

These tests assert that core functions reproduce closed-form answers, and pin the
cross-module *conventions* (sector origin, clock, height datum) that every later
audit step depends on. Where a convention is currently inconsistent the test
records the actual behaviour and names the finding, so a fix flips the assertion
rather than discovering the issue again.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.core.formulas import (
    air_density_iec,
    log_law_extrapolate,
    power_law_extrapolate,
    roughness_from_two_heights,
    shear_from_two_heights,
)
from server.core.momm import compute_weighted_momm_table
from server.core.validators import detect_timestep_minutes, to_utc_index
from server.state.session import SessionState
from server.tools.shear import _fit_rowwise_log_profile
from server.tools.statistics import (
    _compute_diurnal_profile,
    _compute_weibull_params,
    _compute_wind_climate,
)
from tests.oracles import (
    ISA_DRY_DENSITY,
    ISA_PRESSURE_PA,
    ISA_TEMPERATURE_K,
    complete_year_index,
    diurnal_series,
    directional_series,
    dry_air_density,
    log_law_profile,
    moist_air_density,
    power_law_profile,
    timestamp_index,
    weibull_series,
)


def _state_with(frame: pd.DataFrame) -> SessionState:
    """Return a SessionState seeded directly with a timeseries frame."""
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    return state


# ---------------------------------------------------------------------------
# Vertical profile: power law
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alpha", [-0.05, 0.0, 0.14, 0.28, 0.45])
def test_power_law_shear_recovered_exactly(alpha: float) -> None:
    """shear_from_two_heights must invert an exact power-law profile to machine precision."""
    heights = np.array([60.0, 100.0])
    speeds = power_law_profile(heights, v_ref=8.0, h_ref=100.0, alpha=alpha)
    recovered = shear_from_two_heights(speeds[0], heights[0], speeds[1], heights[1])
    assert recovered == pytest.approx(alpha, abs=1e-12)


def test_power_law_extrapolation_round_trips():
    """Extrapolating with the recovered alpha must reproduce the profile's own third height."""
    heights = np.array([60.0, 100.0, 150.0])
    speeds = power_law_profile(heights, v_ref=8.0, h_ref=100.0, alpha=0.21)
    alpha = shear_from_two_heights(speeds[0], heights[0], speeds[1], heights[1])
    predicted = power_law_extrapolate(speeds[1], heights[1], heights[2], alpha)
    assert predicted == pytest.approx(speeds[2], rel=1e-12)


def test_shear_returns_nan_not_zero_for_degenerate_input():
    """A calm or equal-height pair must yield NaN, so it drops out of means rather than biasing them."""
    assert np.isnan(shear_from_two_heights(0.0, 60.0, 8.0, 100.0))
    assert np.isnan(shear_from_two_heights(8.0, 100.0, 8.5, 100.0))


def test_narrow_height_separation_amplifies_alpha_noise():
    """Quantify why the shear pair must be widely separated, not merely near hub height.

    A 1% speed error becomes an alpha error of 0.01 / ln(h2/h1). Across a 60->100 m
    pair that is ~0.02; across a 118->120 m pair it is ~0.6 — a hub-height swing
    of tens of percent. The default plan picks the two sensors *nearest hub
    height*, which does not bound this ratio.
    """
    speed_error = 0.01
    wide = speed_error / np.log(100.0 / 60.0)
    narrow = speed_error / np.log(120.0 / 118.0)
    assert wide < 0.03
    assert narrow > 0.5
    assert narrow / wide > 20.0


# ---------------------------------------------------------------------------
# Vertical profile: log law
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("z0", [0.0002, 0.03, 0.4, 1.2])
def test_roughness_recovered_from_exact_log_profile(z0: float) -> None:
    """roughness_from_two_heights must invert an exact log profile inside the clamp band."""
    heights = np.array([60.0, 100.0])
    speeds = log_law_profile(heights, z0_m=z0)
    recovered, was_clamped = roughness_from_two_heights(speeds[0], heights[0], speeds[1], heights[1])
    assert not was_clamped
    assert recovered == pytest.approx(z0, rel=1e-9)


def test_log_law_extrapolation_round_trips():
    """Extrapolating with the recovered z0 must reproduce the profile's own third height."""
    heights = np.array([60.0, 100.0, 150.0])
    speeds = log_law_profile(heights, z0_m=0.05)
    z0, _ = roughness_from_two_heights(speeds[0], heights[0], speeds[1], heights[1])
    predicted = log_law_extrapolate(speeds[1], heights[1], heights[2], z0)
    assert predicted == pytest.approx(speeds[2], rel=1e-9)


def test_roughness_clamp_ceiling_excludes_forest_and_urban():
    """FINDING (Step 5 lead): the 1.5 m z0 ceiling silently truncates forest/urban roughness.

    WAsP roughness class 3 and dense forest/urban terrain reach z0 of 1.5-2.0 m.
    A site whose profile genuinely implies z0 = 1.8 m is clamped to 1.5 m, which
    *raises* the log-law extrapolation to hub height. The clamp flag is returned,
    but the number is still produced.
    """
    heights = np.array([60.0, 100.0])
    speeds = log_law_profile(heights, z0_m=1.8)
    recovered, was_clamped = roughness_from_two_heights(speeds[0], heights[0], speeds[1], heights[1])
    assert was_clamped is True
    assert recovered == pytest.approx(1.5)
    # And the clamp biases hub-height speed upward, so it is not a safe backstop.
    truth = log_law_extrapolate(speeds[1], 100.0, 150.0, 1.8)
    clamped = log_law_extrapolate(speeds[1], 100.0, 150.0, recovered)
    assert clamped < truth


def test_rowwise_log_fit_recovers_roughness_from_three_heights():
    """The multi-height row-wise fit must recover z0 from an exact three-level log profile."""
    heights = np.array([40.0, 80.0, 120.0])
    speeds = log_law_profile(heights, z0_m=0.08)
    matrix = np.tile(speeds, (5, 1))
    recovered = _fit_rowwise_log_profile(matrix, heights)
    assert np.allclose(recovered, 0.08, rtol=1e-9)


# ---------------------------------------------------------------------------
# Air density
# ---------------------------------------------------------------------------


def test_air_density_matches_isa_when_dry():
    """With negligible vapour the IEC relation must return the ISA sea-level density."""
    density, clamped = air_density_iec(ISA_PRESSURE_PA, ISA_TEMPERATURE_K, 200.0)
    assert clamped is False
    assert density == pytest.approx(ISA_DRY_DENSITY, abs=5e-4)


def test_air_density_matches_independent_partial_pressure_calculation():
    """Saturated 15 C air must match an independently computed moist density and be lighter than dry."""
    density, _ = air_density_iec(ISA_PRESSURE_PA, ISA_TEMPERATURE_K, ISA_TEMPERATURE_K)
    expected = moist_air_density(ISA_PRESSURE_PA, ISA_TEMPERATURE_K, ISA_TEMPERATURE_K)
    assert density == pytest.approx(expected, rel=1e-12)
    assert density < dry_air_density(ISA_PRESSURE_PA, ISA_TEMPERATURE_K)


def test_air_density_clamps_supersaturated_dewpoint():
    """A dewpoint above temperature is a sensor fault; it must be clamped and reported."""
    density, clamped = air_density_iec(ISA_PRESSURE_PA, 283.15, 293.15)
    saturated, _ = air_density_iec(ISA_PRESSURE_PA, 283.15, 283.15)
    assert clamped is True
    assert density == pytest.approx(saturated, rel=1e-12)


def test_air_density_uses_over_water_vapour_pressure_below_freezing():
    """FINDING (Step 6 lead): no ice-phase treatment of saturation vapour pressure.

    Below 0 C the Magnus coefficients used are the over-water set. Over ice the
    saturation vapour pressure is lower, so vapour pressure is over-estimated and
    density slightly under-estimated at cold sites. The bias is small but
    systematic and undisclosed.
    """
    cold_k = 263.15  # -10 C, saturated
    density, _ = air_density_iec(90000.0, cold_k, cold_k)
    over_water = moist_air_density(90000.0, cold_k, cold_k)
    assert density == pytest.approx(over_water, rel=1e-12)
    # Over ice, e_s(-10 C) is ~9% lower than over water, so true density is higher.
    ice_vapour_ratio = 0.91
    vapour_water = 100.0 * 6.1078 * 10.0 ** (7.5 * -10.0 / (237.3 - 10.0))
    vapour_ice = vapour_water * ice_vapour_ratio
    density_over_ice = (90000.0 - vapour_ice) / (287.05 * cold_k) + vapour_ice / (461.5 * cold_k)
    assert density < density_over_ice


def test_air_density_timeseries_tool_runs_and_matches_the_scalar_path():
    """F-00 (HIGH) / F-04 — FIXED. Regression test: the vectorised density path must work.

    The bug: ``server/tools/air_density.py`` used ``np.minimum`` at the dewpoint clamp
    but never imported numpy, so ``compute_air_density_timeseries`` raised ``NameError``
    on every call. It is registered as both an MCP tool and a canvas template, so it was
    reachable from Copilot and from a workflow graph and had simply never been run.

    Fixing the import alone would have been worse than the bug: F-04 sat in the same
    function, which assumed Kelvin while measured temperature is stored in Celsius, so a
    working import would have divided by ~15 instead of ~288 and overstated density
    nineteenfold in silence. Both were fixed together — the function now shares
    ``saturation_vapour_pressure_pa`` and ``moist_air_density`` with the scalar path and
    detects the recorded unit instead of assuming it.
    """
    from server.state.session import bind_session
    from server.tools.air_density import compute_air_density_timeseries

    index = timestamp_index("2021-01-01", periods=48, step_minutes=60)
    state = SessionState()
    state.reset()
    state.era5_interpolated_df = pd.DataFrame(
        {
            "sp": np.full(len(index), ISA_PRESSURE_PA),
            "t2m": np.full(len(index), ISA_TEMPERATURE_K),
            "d2m": np.full(len(index), 283.15),
        },
        index=index,
    )

    with bind_session(state):
        result = compute_air_density_timeseries("sp", "t2m", "d2m", "era5")

    scalar, _ = air_density_iec(ISA_PRESSURE_PA, ISA_TEMPERATURE_K, 283.15)
    assert result["mean_density"] == pytest.approx(scalar, rel=1e-12)
    assert result["record_count"] == len(index)
    assert result["units_detected"] == {"temperature": "K", "dewpoint": "K", "pressure": "Pa"}
    assert result["height_basis"] == "pressure_sensor_height"


# ---------------------------------------------------------------------------
# Timebase conventions
# ---------------------------------------------------------------------------


def test_internal_storage_is_utc():
    """The session contract stores UTC; a naive index is assumed already UTC (D8)."""
    naive = pd.DataFrame({"x": [1.0, 2.0]}, index=pd.date_range("2021-01-01", periods=2, freq="h"))
    converted = to_utc_index(naive)
    assert str(converted.index.tz) == "UTC"


def test_cadence_detection_is_modal_not_mean():
    """One large gap must not shift the inferred cadence away from the modal spacing."""
    index = list(pd.date_range("2021-01-01", periods=50, freq="10min"))
    index.append(index[-1] + pd.Timedelta(hours=37))
    frame = pd.DataFrame({"x": np.ones(len(index))}, index=pd.DatetimeIndex(index))
    assert detect_timestep_minutes(frame) == 10


def test_diurnal_profile_bins_on_utc_not_site_local_time():
    """FINDING (Step 2/4): diurnal binning uses the UTC index hour, never site-local time.

    Ingest converts to UTC (data_io._apply_timezone_to_index) and no consumer
    converts back, so every `.hour` grouping in the codebase is a UTC-hour bin.
    The physical cycle survives as a constant relabelling, but the reported hours
    are wrong by the site offset: a series peaking at 14:00 local at a UTC+5:30
    site is reported as peaking at 08:00-09:00. The 12x24 shear table carries the
    same mislabelling.
    """
    utc_offset = 5.5  # India Standard Time
    index = complete_year_index(2021, step_minutes=60)
    series = diurnal_series(index, peak_hour_local=14, utc_offset_hours=utc_offset)
    state = _state_with(series.to_frame(name="Spd_80m"))

    profile = _compute_diurnal_profile(state, "Spd_80m")
    reported_peak_hour = int(np.nanargmax(profile["mean_speeds"]))

    expected_utc_peak = (14 - utc_offset) % 24  # 08:30 UTC
    assert reported_peak_hour in {int(np.floor(expected_utc_peak)), int(np.ceil(expected_utc_peak)) % 24}
    # The reported hour is NOT the local peak the analyst asked about.
    assert reported_peak_hour != 14
    # The response carries no clock label, so the reader cannot correct it.
    assert "timezone" not in profile
    assert "utc_offset_hours" not in profile


# ---------------------------------------------------------------------------
# Directional conventions
# ---------------------------------------------------------------------------


def test_circular_mean_wraps_across_north():
    """The mean of 350 deg and 10 deg is 0 deg, not 180 — vector averaging is required."""
    index = timestamp_index("2021-01-01", periods=1000, step_minutes=60)
    frame = pd.DataFrame(
        {
            "Spd_80m": np.full(len(index), 8.0),
            "Dir_80m": directional_series(index, [350.0, 10.0]).to_numpy(),
        },
        index=index,
    )
    state = _state_with(frame)
    climate = _compute_wind_climate(state, "Spd_80m", "Dir_80m")
    mean_direction = float(climate["direction"]["mean_direction_deg"])
    assert min(mean_direction, 360.0 - mean_direction) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(
    ("direction_deg", "expected_centre_deg"),
    [(0.0, 0.0), (11.0, 0.0), (349.0, 0.0), (355.0, 0.0), (23.0, 22.5), (180.0, 180.0)],
)
def test_windrose_sector_zero_is_centred_on_north(direction_deg: float, expected_centre_deg: float) -> None:
    """Sector 0 must be centred on north (348.75-11.25 deg for 16 sectors), the industry convention."""
    index = timestamp_index("2021-01-01", periods=10, step_minutes=60)
    frame = pd.DataFrame(
        {"Spd_80m": np.full(10, 8.0), "Dir_80m": np.full(10, direction_deg)},
        index=index,
    )
    state = _state_with(frame)
    climate = _compute_wind_climate(state, "Spd_80m", "Dir_80m")
    occupied = [s for s in climate["sectors"] if float(s["occurrence_pct"]) > 0.0]
    assert len(occupied) == 1
    assert float(occupied[0]["center_deg"]) == pytest.approx(expected_centre_deg)


def test_compare_tab_windrose_uses_a_different_sector_origin():
    """FINDING (Step 1): the Compare-tab windrose bins from north instead of centring on it.

    Every analysis windrose uses ``(dir + width/2) % 360 // width`` so sector 0 is
    centred on north. ``workflow_execution._build_windrose_plots`` uses
    ``(dir % 360) // 30`` with labels at ``index * 30 + 15``, so its sectors are
    offset by half a width. The same data therefore renders as two different
    roses depending on which tab is open. Presentational, but it breaks the
    ledger invariant that one convention holds application-wide.
    """
    direction = 5.0
    analysis_sector_centre = ((direction + 15.0) % 360.0 // 30.0) * 30.0
    compare_sector_centre = (direction % 360.0 // 30.0) * 30.0 + 15.0
    assert analysis_sector_centre == pytest.approx(0.0)
    assert compare_sector_centre == pytest.approx(15.0)
    assert analysis_sector_centre != compare_sector_centre


# ---------------------------------------------------------------------------
# Distribution and aggregation oracles
# ---------------------------------------------------------------------------


def test_weibull_wasp_fit_recovers_known_distribution():
    """The WAsP m1/m3 fit must recover A and k from a large exact Weibull sample."""
    pytest.importorskip("windkit")
    index = timestamp_index("2015-01-01", periods=200_000, step_minutes=10)
    series = weibull_series(index, scale_a=8.0, shape_k=2.1, seed=7)
    state = _state_with(series.to_frame(name="Spd_80m"))
    result = _compute_weibull_params(state, "Spd_80m")
    assert result["A"] == pytest.approx(8.0, rel=0.02)
    assert result["k"] == pytest.approx(2.1, rel=0.05)
    assert result["fit_excludes_calms"] is False


def test_mean_speed_is_calm_inclusive_in_weibull_but_calm_exclusive_in_wind_climate():
    """FINDING (Step 1, confirmed): two tools report `mean_speed` under one key with two definitions.

    The documented contract is that ``mean_speed`` is always the full-series mean
    including calms, "consistent with MoMM and the monthly means".
    ``_compute_weibull_params`` honours that. ``_compute_wind_climate`` computes
    ``positive.mean()`` — calms excluded — and also draws ``record_count`` and the
    whole ``exceedance`` block from the positive subset only. For a site with a
    real calm fraction the two tools disagree about the same sensor's mean wind
    speed, and nothing in either response says which basis was used.
    """
    pytest.importorskip("windkit")
    index = timestamp_index("2021-01-01", periods=20_000, step_minutes=10)
    rng = np.random.default_rng(11)
    speeds = rng.weibull(2.0, len(index)) * 8.0
    speeds[speeds < 1.0] = 0.0  # ~1.5% calms, unremarkable for a real site
    calm_fraction = float((speeds == 0).mean())
    assert calm_fraction > 0.005

    state = _state_with(pd.DataFrame({"Spd_80m": speeds, "Dir_80m": np.full(len(index), 200.0)}, index=index))

    weibull = _compute_weibull_params(state, "Spd_80m")
    climate = _compute_wind_climate(state, "Spd_80m", "Dir_80m")

    full_series_mean = float(np.mean(speeds))
    positive_only_mean = float(np.mean(speeds[speeds > 0]))

    assert weibull["mean_speed"] == pytest.approx(full_series_mean, rel=1e-12)
    assert climate["mean_speed"] == pytest.approx(positive_only_mean, rel=1e-12)
    assert climate["mean_speed"] > weibull["mean_speed"]
    # Neither response labels its basis, so the disagreement is undetectable downstream.
    assert "calm_fraction" not in climate
    assert "mean_speed_basis" not in climate


def test_momm_of_a_complete_constant_year_equals_that_constant():
    """With uniform completeness, MoMM weighting must be a no-op on a constant series."""
    index = complete_year_index(2021, step_minutes=60)
    series = pd.Series(np.full(len(index), 7.5), index=index)
    table = compute_weighted_momm_table(series.to_frame(name="Spd_80m"), "Spd_80m")
    assert table.shape == (12, 24)
    assert np.allclose(table.to_numpy(dtype=float), 7.5)


def test_momm_table_is_month_by_hour_and_fully_populated_for_a_complete_year():
    """A gapless year must leave no NaN cell, so any NaN downstream signals real absence."""
    index = complete_year_index(2021, step_minutes=10)
    rng = np.random.default_rng(3)
    series = pd.Series(rng.weibull(2.0, len(index)) * 8.0, index=index)
    table = compute_weighted_momm_table(series.to_frame(name="Spd_80m"), "Spd_80m")
    assert not table.isna().to_numpy().any()


def test_momm_infers_samples_per_hour_only_down_to_hourly():
    """FINDING (Step 2 lead): the samples-per-hour floor of 1.0 mis-weights sub-hourly cadences.

    ``_infer_samples_per_hour`` returns ``max(1.0, 3600 / spacing)``, so any
    cadence coarser than hourly reports 1.0. Expected counts are then too high,
    completeness is under-estimated for every month-hour cell, and the
    completeness weighting silently stops discriminating. A daily or monthly
    derived series is exactly the case a long-term MoMM would hit.
    """
    from server.core.momm import _infer_samples_per_hour

    hourly = pd.DatetimeIndex(pd.date_range("2021-01-01", periods=100, freq="h", tz="UTC"))
    daily = pd.DatetimeIndex(pd.date_range("2021-01-01", periods=100, freq="D", tz="UTC"))
    ten_min = pd.DatetimeIndex(pd.date_range("2021-01-01", periods=100, freq="10min", tz="UTC"))

    assert _infer_samples_per_hour(ten_min) == pytest.approx(6.0)
    assert _infer_samples_per_hour(hourly) == pytest.approx(1.0)
    # Daily data is 1/24 samples per hour, but the floor reports 1.0 — a 24x error.
    assert _infer_samples_per_hour(daily) == pytest.approx(1.0)


def test_momm_reports_the_month_hour_cells_it_synthesised():
    """F-14 — FIXED. Regression test: a partial-year MoMM must declare what it invented.

    The bug: ``compute_momm`` did ``table.fillna(series.mean())``, so a campaign that never
    observed a month still reported a 12-month MoMM. A six-month winter campaign had its
    six missing summer months synthesised from the winter mean and reported a number
    indistinguishable from a full-year one, with no fill count returned.

    The fill is kept — the 12x24 table must resolve — but `filled_cells`,
    `months_observed`, `months_missing` and `fill_value` now travel with the result, and a
    table missing whole months carries a warning. MoMM weights months by length to
    represent a full year, so a partial year is exactly where it misleads.
    """
    from server.tools.statistics import compute_momm
    from server.state.session import bind_session

    # Jan-Jun only, deliberately seasonal: a real site's absent months are not
    # equal to the observed mean.
    index = pd.date_range("2021-01-01", "2021-06-30 23:00", freq="h", tz="UTC")
    series = pd.Series(np.full(len(index), 6.0), index=index)
    state = _state_with(series.to_frame(name="Spd_80m"))

    with bind_session(state):
        result = compute_momm("Spd_80m")

    table = np.asarray(result["table"], dtype=float)
    assert table.shape == (12, 24)
    # Jul-Dec were never measured and still carry the Jan-Jun mean...
    assert np.allclose(table[6:, :], 6.0)
    assert result["momm_speed"] == pytest.approx(6.0)
    # ...but the response now says so.
    assert result["filled_cells"] == 144
    assert result["filled_fraction"] == pytest.approx(0.5)
    assert result["months_observed"] == [1, 2, 3, 4, 5, 6]
    assert result["months_missing"] == [7, 8, 9, 10, 11, 12]
    assert result["fill_value"] == pytest.approx(6.0)
    assert "warning" in result
