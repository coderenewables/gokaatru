"""Vertical profile physics — Step 5 of the logic audit.

Hub-height wind speed is the most sensitive number in the assessment, and it is
produced here. Closed-form verification of the four profile inversions lives in
`test_oracle_harness.py`; this file covers the estimators, the 12x24 lookup
tables, and the extrapolation path — where the physics is correct but the
*application* of it is not always guarded or disclosed.

Findings are recorded with the behaviour they exhibit today, so a fix flips the
assertion. Magnitudes in the docstrings were measured, not estimated.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401  — establishes tool-module import order
from server.state.session import SessionState
from server.tools.extrapolation import (
    _extrapolate_to_hub_height,
    _log_linear_interpolation,
    _power_extrapolate_array,
)
from server.tools.shear import (
    _build_sector_shear_tables,
    _build_shear_table,
    _calculate_shear_timeseries,
    _compute_pairwise_shear,
    _compute_veer,
    _compute_vertical_structure,
    _profile_fit_metrics,
)

YEAR = ("2021-01-01", "2021-12-31 23:50")


def _mast_state(
    heights: tuple[float, ...],
    alpha: float | np.ndarray,
    index: pd.DatetimeIndex,
    seed: int = 3,
) -> SessionState:
    """Return a session holding an exact power-law mast at the given heights."""
    rng = np.random.default_rng(seed)
    top = max(heights)
    top_speed = 6.0 + rng.weibull(2.0, len(index)) * 3.5
    frame = pd.DataFrame(
        {f"Spd_{int(h)}m": top_speed * (h / top) ** alpha for h in heights},
        index=index,
    )
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        float(h): {"speed_col": f"Spd_{int(h)}m", "dir_col": None} for h in heights
    }
    return state


def _height_json(heights: tuple[float, ...]) -> str:
    return json.dumps({str(int(h)): f"Spd_{int(h)}m" for h in heights})


# ---------------------------------------------------------------------------
# Estimator correctness — verified, not findings
# ---------------------------------------------------------------------------


def test_pairwise_shear_recovers_alpha_across_four_heights():
    """The multi-height estimator must be exact on a clean profile, not just on a pair."""
    heights = np.array([40.0, 60.0, 80.0, 100.0])
    speeds = 9.0 * (heights / 100.0) ** 0.27
    alpha, stats = _compute_pairwise_shear(np.tile(speeds, (3, 1)), heights, min_speed_mps=3.0)
    assert np.allclose(alpha, 0.27, atol=1e-12)
    assert stats["records_clamped"] == 0


def test_pairwise_weighting_is_statistically_equivalent_to_log_log_ols():
    """VERIFIED (not a finding): the |ln(h2/h1)| weighting matches direct log-log OLS.

    ``_compute_pairwise_shear`` fits over all n(n-1)/2 height pairs weighted by
    |ln(h2/h1)|, which is not the textbook log-log least-squares slope that
    WAsP and IEC 61400-12-1 B.2 describe. Measured on 200 k records of a 4-height
    mast with 1% independent per-level noise, the two agree closely enough that
    the choice does not matter: bias < 1e-5 for both, SD ratio 1.002, rho 0.998.
    For two heights they are algebraically identical.
    """
    rng = np.random.default_rng(7)
    heights = np.array([40.0, 60.0, 80.0, 100.0])
    n = 40_000
    top = 8.0 + rng.weibull(2.0, n) * 3.0
    clean = top[:, None] * (heights[None, :] / 100.0) ** 0.22
    noisy = clean * (1.0 + rng.normal(0.0, 0.01, clean.shape))

    code_alpha, _ = _compute_pairwise_shear(noisy, heights, min_speed_mps=3.0)

    log_h = np.log(heights)
    centred = log_h - log_h.mean()
    log_v = np.log(noisy)
    ols_alpha = (log_v - log_v.mean(axis=1, keepdims=True)) @ centred / np.sum(centred**2)

    assert abs(code_alpha.mean() - 0.22) < 5e-4
    assert abs(ols_alpha.mean() - 0.22) < 5e-4
    assert code_alpha.std() / ols_alpha.std() == pytest.approx(1.0, abs=0.01)
    assert np.corrcoef(code_alpha, ols_alpha)[0, 1] > 0.99

    # Two heights: one pair, so the weighting cancels entirely.
    pair = noisy[:, [0, 3]]
    pair_heights = heights[[0, 3]]
    code_pair, _ = _compute_pairwise_shear(pair, pair_heights, 3.0)
    centred_pair = np.log(pair_heights) - np.log(pair_heights).mean()
    log_pair = np.log(pair)
    ols_pair = (log_pair - log_pair.mean(axis=1, keepdims=True)) @ centred_pair / np.sum(centred_pair**2)
    assert np.nanmax(np.abs(code_pair - ols_pair)) < 1e-12


def test_alpha_clamp_is_applied_after_the_speed_gate():
    """Order matters: gating first means the clamp only ever sees profile-bearing records."""
    heights = np.array([60.0, 100.0])
    # Row 0 is near-calm at the lower height: its ln ratio would imply alpha ~ 4.
    # Row 1 is an ordinary sheared record.
    speeds = np.array([[0.5, 4.0], [4.0, 5.0]])
    alpha, stats = _compute_pairwise_shear(speeds, heights, min_speed_mps=3.0)

    assert np.isnan(alpha[0])  # excluded by the gate, so it never reaches the clamp
    assert stats["records_used"] == 1
    assert stats["records_clamped"] == 0
    assert alpha[1] == pytest.approx(np.log(1.25) / np.log(100.0 / 60.0))

    # With the gate disabled, that same record clamps instead of being dropped —
    # which is what the 3.0 m/s default exists to prevent.
    ungated, ungated_stats = _compute_pairwise_shear(speeds, heights, min_speed_mps=0.1)
    assert ungated[0] == pytest.approx(1.0)
    assert ungated_stats["records_clamped"] == 1


def test_veer_is_wrap_safe_across_north():
    """Veer across the 0/360 boundary must be signed and small, not ~350 deg."""
    heights = np.array([60.0, 100.0])
    directions = np.array([[355.0, 5.0], [5.0, 355.0]])
    veer = _compute_veer(directions, heights)
    assert veer[0] == pytest.approx(10.0 / 40.0 * 100.0)
    assert veer[1] == pytest.approx(-10.0 / 40.0 * 100.0)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_hub_extrapolation_reports_its_lever_and_warns_when_it_is_severe():
    """F-17 (HIGH) — FIXED. Regression test: the extrapolation ratio must be reported.

    The finding: a 40/60 m mast extrapolated to a 200 m hub — a 3.33x lever, where
    industry practice caps near 1.5x the top measurement height — produced a full
    52 560-record series with a mean 27% above the 60 m mean, with no refusal, no
    warning, and neither the reference height nor the ratio in the response.

    The fix reports `reference_height_m` (min/max/most-common, because
    `_nearest_indices` picks it per record and it drops to a lower sensor whenever the
    top one is missing), `extrapolation_ratio`, the count above the 1.5x threshold, and
    a warning that escalates past 2.0x. It still does not refuse — the analyst may have
    good reason — but the lever can no longer be invisible.
    """
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    state = _mast_state((40.0, 60.0), 0.20, index)
    _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    _build_shear_table(state, "mean")

    result = _extrapolate_to_hub_height(state, 200.0, "power_law")
    hub = state.timeseries_df["Spd_200m_hub"]

    assert int(hub.notna().sum()) == len(index)
    assert hub.mean() / state.timeseries_df["Spd_60m"].mean() > 1.25

    # Both sensors are valid throughout, so the reference is always the nearer 60 m.
    assert result["reference_height_m"]["most_common"] == pytest.approx(60.0)
    assert result["extrapolation_ratio"]["min"] == pytest.approx(200.0 / 60.0)
    assert result["extrapolation_ratio"]["max"] == pytest.approx(200.0 / 60.0)
    assert result["records_above_warn_threshold"] == int(hub.notna().sum())
    assert "warning" in result
    assert "3.33x" in result["warning"]  # escalated past the severe threshold


def test_extrapolation_lever_widens_when_the_top_sensor_drops_out():
    """The varying reference height (Step 5's F-24) is now visible in the response.

    ``_nearest_indices`` picks the reference per record, so whenever the top sensor
    fails the lever silently grows for those records. With the 60 m sensor absent for
    part of the campaign the ratio spans 200/60 to 200/40, and the response now reports
    both ends rather than presenting one undifferentiated series.
    """
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    state = _mast_state((40.0, 60.0), 0.20, index)
    outage = np.zeros(len(index), dtype=bool)
    outage[: len(index) // 4] = True
    state.timeseries_df.loc[outage, "Spd_60m"] = np.nan

    _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    _build_shear_table(state, "mean")
    result = _extrapolate_to_hub_height(state, 200.0, "power_law")

    assert result["extrapolation_ratio"]["min"] == pytest.approx(200.0 / 60.0)
    assert result["extrapolation_ratio"]["max"] == pytest.approx(200.0 / 40.0)
    assert result["reference_height_m"]["min"] == pytest.approx(40.0)
    assert result["reference_height_m"]["max"] == pytest.approx(60.0)


def test_hub_extrapolation_within_the_defensible_ratio_raises_no_warning():
    """The counterpart: a hub at 1.25x the top height must report the lever without alarm."""
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    state = _mast_state((80.0, 100.0), 0.20, index)
    _calculate_shear_timeseries(state, _height_json((80.0, 100.0)))
    _build_shear_table(state, "mean")

    result = _extrapolate_to_hub_height(state, 125.0, "power_law")

    assert result["extrapolation_ratio"]["min"] == pytest.approx(1.25)
    assert result["records_above_warn_threshold"] == 0
    assert result["warning"] is None


def test_profile_fit_alpha_uses_per_column_means_not_concurrent_records():
    """FINDING F-18 (HIGH): the reported profile alpha averages each height over its own records.

    ``_profile_fit_metrics`` builds the mean profile as ``df[col].mean()`` per
    column, so when the top sensor has a seasonal gap the two means describe
    different periods. Measured on a site with 0.10 summer / 0.32 winter shear
    whose 100 m sensor is lost for one summer: the reported alpha is 0.244 where
    the concurrent-record answer is 0.320 — an error of -0.076 in alpha, worth
    -3.0% on hub-height speed at 150 m.

    Scope: this is the *reporting* path (`compute_vertical_structure`, Sensor
    Overview). Extrapolation itself uses ``_compute_pairwise_shear``, which does
    require both heights valid per record, so AEP is not affected — but this is
    the alpha an analyst reads to sanity-check the site or to configure a manual
    extrapolation.
    """
    rng = np.random.default_rng(11)
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    summer = np.isin(index.month.to_numpy(), [5, 6, 7, 8])
    alpha_true = np.where(summer, 0.10, 0.32)

    v100 = 6.0 + rng.weibull(2.0, len(index)) * 3.5
    frame = pd.DataFrame({"Spd_60m": v100 * (60 / 100.0) ** alpha_true, "Spd_100m": v100}, index=index)
    height_map = {60.0: "Spd_60m", 100.0: "Spd_100m"}

    gappy = frame.copy()
    gappy.loc[summer, "Spd_100m"] = np.nan

    from_code = _profile_fit_metrics(height_map, gappy)["power_law_alpha"]
    from_concurrent = _profile_fit_metrics(height_map, gappy.dropna())["power_law_alpha"]

    assert from_concurrent == pytest.approx(0.32, abs=1e-6)
    assert from_code == pytest.approx(0.244, abs=0.005)
    assert from_code - from_concurrent < -0.05

    hub_error = (150 / 100.0) ** from_code / (150 / 100.0) ** from_concurrent - 1.0
    assert hub_error < -0.02  # 3% low


def test_vertical_structure_reports_two_unlabelled_alphas():
    """FINDING F-18b: one response carries two differently-derived alphas, neither labelled.

    ``power_law_alpha`` is the log-log slope through the *mean* profile;
    ``alpha.mean`` is the mean of the *per-record* alphas. They are different
    estimators of different quantities and they disagree on real data. Nothing in
    either field states its basis, so a reader cannot tell which one to quote.
    """
    rng = np.random.default_rng(11)
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    alpha_true = np.where(np.isin(index.month.to_numpy(), [5, 6, 7, 8]), 0.10, 0.32)
    v100 = 6.0 + rng.weibull(2.0, len(index)) * 3.5
    frame = pd.DataFrame({"Spd_60m": v100 * (60 / 100.0) ** alpha_true, "Spd_100m": v100}, index=index)

    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.sensor_mapping = {
        60.0: {"speed_col": "Spd_60m", "dir_col": None},
        100.0: {"speed_col": "Spd_100m", "dir_col": None},
    }
    result = _compute_vertical_structure(state)

    assert result["power_law_alpha"] != pytest.approx(result["alpha"]["mean"], abs=1e-6)
    assert "power_law_alpha_basis" not in result
    assert "basis" not in result["alpha"]


def test_shear_table_reports_the_month_hour_cells_it_never_observed():
    """F-19 (HIGH) — FIXED. Regression test: a synthesised table must say how much is synthetic.

    The finding: on a six-month (Jan-Jun) campaign, 144 of the 288 cells were never
    observed, every one came out finite carrying the series-mean alpha, and the response
    reported no fill count and no observed-month list — so a half-year table was
    indistinguishable from a full-year one. It bites downstream because the same table is
    applied to the *reanalysis* series, which covers all twelve months.

    The fill itself is kept deliberately (the lookup must resolve for every long-term
    record), but `table_coverage` now reports the observed and filled cell counts, the
    months present and absent, and a warning; `fallback_alpha` and `fallback_source`
    expose the value substituted.
    """
    index = pd.date_range("2021-01-01", "2021-06-30 23:50", freq="10min", tz="UTC")
    state = _mast_state((40.0, 60.0), 0.20, index)
    _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    result = _build_shear_table(state, "mean")

    table = np.asarray(result["table"], dtype=float)
    assert table.shape == (12, 24)
    assert np.isfinite(table).all()  # the lookup still resolves everywhere

    observed_mean = float(np.nanmean(table[:6, :]))
    assert np.allclose(table[6:, :], observed_mean, atol=1e-9)  # Jul-Dec still synthesised

    coverage = result["table_coverage"]
    assert coverage["cells_observed"] == 144
    assert coverage["filled_cells"] == 144
    assert coverage["filled_fraction"] == pytest.approx(0.5)
    assert coverage["months_observed"] == [1, 2, 3, 4, 5, 6]
    assert coverage["months_missing"] == [7, 8, 9, 10, 11, 12]
    assert "warning" in result
    assert result["fallback_source"] == "series_mean"


def test_full_year_shear_table_reports_complete_coverage():
    """The counterpart: a gapless year must report no filled cells and raise no warning."""
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    state = _mast_state((40.0, 60.0), 0.20, index)
    _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    result = _build_shear_table(state, "mean")

    coverage = result["table_coverage"]
    assert coverage["cells_observed"] == 288
    assert coverage["filled_cells"] == 0
    assert coverage["months_missing"] == []
    assert "warning" not in result


def test_sector_shear_tables_have_no_minimum_record_count():
    """FINDING F-20: sector shear tables silently drop empty sectors and never report thinness.

    Measured: with 20 records in one direction sector and the rest in another,
    ``_build_sector_shear_tables`` returns 2 of 12 sectors. The 10 absent ones are
    not listed, and the 20-record sector receives a full 288-cell table in which
    285 cells are that sector's own mean. There is no per-sector count in the
    response and no minimum-record gate anywhere in the function.

    Compare the guards the same codebase applies elsewhere: SpeedSort requires 200
    records per sector before trusting a sector fit, and mast-shadow detection
    requires 50. Directional shear — which drives hub-height speed — requires none.
    """
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    state = _mast_state((40.0, 60.0), 0.20, index)
    directions = np.full(len(index), 90.0)
    directions[:20] = 270.0
    state.timeseries_df["Dir_60m"] = directions

    _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    result = _build_sector_shear_tables(state, "Dir_60m", 12, "mean")

    assert len(result["sectors"]) == 2  # 10 sectors vanish without trace
    thin = np.asarray(result["sectors"]["270-300"], dtype=float)
    assert thin.size == 288
    assert np.isfinite(thin).all()

    assert "sector_record_counts" not in result
    assert "empty_sectors" not in result
    assert set(result) == {"sectors", "shear_clamping"}


def test_hub_inside_the_mast_uses_a_different_physical_model():
    """FINDING F-21: two physical laws produce hub speed in one session, undisclosed.

    When the hub falls between two measured heights the code interpolates linearly
    in ln(z) (`_log_linear_interpolation`); when it falls outside it applies the
    power law with the alpha table. Both are defensible, but they are different
    models and the divergence grows with shear — measured at hub 80 m between
    60 m and 100 m: +0.03% at alpha 0.10, +0.13% at 0.20, +0.39% at 0.35.

    `method_counts` reports how many records took each path but never says the two
    paths use different physics, so a single hub series can be a blend of both.
    """
    reference = np.array([10.0])
    divergence = {}
    for alpha in (0.10, 0.20, 0.35):
        lower = reference * (60 / 100.0) ** alpha
        interpolated = _log_linear_interpolation(
            lower, reference, np.array([60.0]), np.array([100.0]), 80.0
        )[0]
        power_law = _power_extrapolate_array(reference, np.array([100.0]), 80.0, np.array([alpha]))[0]
        divergence[alpha] = interpolated / power_law - 1.0

    assert divergence[0.10] == pytest.approx(0.00032, abs=5e-5)
    assert divergence[0.35] == pytest.approx(0.00391, abs=5e-5)
    # Systematically positive and monotone in shear: log-linear over-reads the power law.
    assert 0 < divergence[0.10] < divergence[0.20] < divergence[0.35]


def test_extrapolation_ignores_the_shear_speed_gate():
    """FINDING F-23: hub speeds are produced for records the shear gate excluded.

    ``_calculate_shear_timeseries`` gates at ``min_speed_mps`` (3.0 m/s default)
    because below it ln(v2/v1) is anemometer noise. ``_extrapolate_to_hub_height``
    uses its own mask of ``> 0.1`` m/s, so near-calm records get a hub speed built
    from the month-hour mean alpha — an alpha derived exclusively from records
    above 3 m/s. Measured: 5 256 near-calm records had no alpha yet all received a
    hub speed, leaving the hub series 5 256 records longer than the shear series
    with nothing in either response explaining the difference.
    """
    rng = np.random.default_rng(4)
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    v60 = 6.0 + rng.weibull(2.0, len(index)) * 3.0
    v40 = v60 * (40 / 60.0) ** 0.20
    calm = np.zeros(len(index), dtype=bool)
    calm[::10] = True
    v60[calm], v40[calm] = 0.4, 0.35

    state = SessionState()
    state.reset()
    frame = pd.DataFrame({"Spd_40m": v40, "Spd_60m": v60}, index=index)
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        40.0: {"speed_col": "Spd_40m", "dir_col": None},
        60.0: {"speed_col": "Spd_60m", "dir_col": None},
    }

    shear = _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    _build_shear_table(state, "mean")
    _extrapolate_to_hub_height(state, 100.0, "power_law")

    alpha = state.shear_timeseries_df["shear_coefficient"]
    hub = state.timeseries_df["Spd_100m_hub"]

    assert int(alpha[calm].notna().sum()) == 0  # gate worked
    assert int(hub[calm].notna().sum()) == int(calm.sum())  # extrapolated anyway
    assert int(hub.notna().sum()) > int(shear["records"])


def test_reanalysis_hub_extrapolation_no_ops_and_reports_ok():
    """FINDING F-22: the reanalysis leg can do nothing at all and still report success.

    ``_extrapolate_all_reanalysis_nodes`` only touches the interpolated series when
    the reference column ``Spd_100m`` is present, and the interpolated series is
    never added to ``skipped_nodes`` — that list only ever collects ERA5/MERRA node
    keys. With ERA5 present but carrying only 10 m winds it returns
    ``status: "ok"`` with empty ``extrapolated_nodes`` *and* empty ``skipped_nodes``,
    having written nothing. The caller additionally wraps the whole leg in
    ``except (ValueError, KeyError): pass``, so genuine failures are also silent.

    Downstream, LTC then either fails on a missing column or — with the Step 1
    staleness gap (F-11) — silently reuses a hub column from an earlier run.
    """
    index = pd.date_range(*YEAR, freq="10min", tz="UTC")
    state = _mast_state((40.0, 60.0), 0.20, index)
    _calculate_shear_timeseries(state, _height_json((40.0, 60.0)))
    _build_shear_table(state, "mean")

    state.era5_interpolated_df = pd.DataFrame({"Spd_10m": np.full(len(index), 5.0)}, index=index)

    result = _extrapolate_to_hub_height(state, 120.0, "power_law")
    reanalysis = result["reanalysis"]

    assert result["status"] == "ok"
    assert reanalysis["status"] == "ok"
    assert reanalysis["extrapolated_nodes"] == []
    assert reanalysis["skipped_nodes"] == []  # the interpolated series is not recorded as skipped
    assert reanalysis["interpolated_extrapolated"] is False
    assert "Spd_120m_hub" not in state.era5_interpolated_df.columns


def test_month_hour_mean_alpha_smooths_the_hub_distribution():
    """FINDING F-25 (LOW, quantified): the 12x24 table is unbiased in the mean but smooths records.

    Extrapolation applies each record's *month-hour mean* alpha, not its own. On a
    two-year series with a realistic diurnal stability cycle (0.12 daytime / 0.34
    nocturnal, sigma_alpha 0.125) extrapolated 100 m -> 150 m, measured against
    per-record truth: mean speed bias -0.03%, mean-of-v-cubed bias -0.27%, but
    per-record RMS error 0.28 m/s with a P90 absolute error of 0.45 m/s.

    So the mean is safe and the 12x24 approach is justified — but the hub-height
    *distribution* is narrower than reality, which is what the Weibull fit, the
    turbulence statistics and the LTC regression all consume. Not disclosed.
    """
    rng = np.random.default_rng(20260817)
    index = pd.date_range("2021-01-01", "2022-12-31 23:50", freq="10min", tz="UTC")
    hour = index.hour.to_numpy()
    night = ((hour < 6) | (hour >= 19)).astype(float)
    alpha_true = np.clip(0.12 + 0.22 * night + rng.normal(0, 0.06, len(index)), -0.2, 0.9)
    v100 = np.clip(6.5 + 2.2 * night + rng.weibull(2.0, len(index)) * 3.0, 0.3, None)

    state = SessionState()
    state.reset()
    frame = pd.DataFrame({"Spd_60m": v100 * (60 / 100.0) ** alpha_true, "Spd_100m": v100}, index=index)
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        60.0: {"speed_col": "Spd_60m", "dir_col": None},
        100.0: {"speed_col": "Spd_100m", "dir_col": None},
    }

    _calculate_shear_timeseries(state, _height_json((60.0, 100.0)))
    _build_shear_table(state, "mean")
    _extrapolate_to_hub_height(state, 150.0, "power_law")

    produced = state.timeseries_df["Spd_150m_hub"].to_numpy()
    truth = v100 * (150 / 100.0) ** alpha_true
    valid = np.isfinite(produced) & np.isfinite(truth)

    speed_bias = produced[valid].mean() / truth[valid].mean() - 1.0
    energy_bias = np.mean(produced[valid] ** 3) / np.mean(truth[valid] ** 3) - 1.0
    rms = float(np.sqrt(np.mean((produced[valid] - truth[valid]) ** 2)))

    assert abs(speed_bias) < 0.001            # mean is safe
    assert -0.005 < energy_bias < 0.0         # energy systematically low, sub-0.5%
    assert rms > 0.2                          # individual records are materially smoothed
    assert np.std(produced[valid]) < np.std(truth[valid])
