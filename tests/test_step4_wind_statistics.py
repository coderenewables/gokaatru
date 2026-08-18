"""Wind statistics and distributions — Step 4 of the logic audit.

These are the numbers an analyst reads off the screen and quotes: mean speed, Weibull A
and k, MoMM, the prevailing direction, turbulence intensity at 15 m/s, and the 50-year
extreme wind. Two of them leave GoKaatru and select hardware — the IEC turbulence class
and the extreme wind both decide which turbine may stand on the site — so an error here
is not a reporting error, it is a specification error.

Verified against `tests/oracles.py`, which shares no code with the production modules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.formulas import MEAN_DAYS_IN_MONTH
from server.state.session import SessionState
from server.tools.advanced_analysis import GEV_MIN_YEARS, _compute_extremes
from server.tools.statistics import (
    IEC_REFERENCE_SPEED_MPS,
    TI_MIN_BIN_RECORDS,
    TI_MIN_SPEED_MPS,
    _compute_turbulence_analysis,
    _compute_weibull_params,
    _compute_wind_climate,
    _weibull_wasp_fit,
)
from tests import oracles

YEAR = ("2021-01-01", "2021-12-31 23:50")
_SPEED_ONLY = {80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None, "temp_col": None}}


def _state(frame: pd.DataFrame, mapping: dict | None = None) -> SessionState:
    """Return a session holding one measured frame with a single mapped height."""
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = mapping or {
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": "Spd_80m_sd", "temp_col": None}
    }
    return state


def _ti_campaign(n: int = 52_560, seed: int = 3) -> pd.DataFrame:
    """A realistic turbulence campaign: sigma/U falls with speed, as it does on a real mast.

    In a neutral surface layer sigma scales with friction velocity rather than with mean
    speed, so TI falls roughly as 1/U. That shape is the whole reason the IEC characterises
    a site at a *specified* wind speed instead of averaging TI over all of them.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-01", periods=n, freq="10min", tz="UTC")
    speed = np.clip((8.0 / 0.88623) * rng.weibull(2.0, n), 0.3, None)
    ti_true = 0.10 + 0.55 / np.maximum(speed, 1.0)
    sigma = np.clip(speed * ti_true * (1.0 + rng.normal(0, 0.15, n)), 0.0, None)
    return pd.DataFrame({"Spd_80m": speed, "Spd_80m_sd": sigma}, index=index)


def _seasonal_campaign(start: str, end: str, seed: int = 9) -> pd.DataFrame:
    """A multi-year series with a northern-hemisphere storm season peaking in January."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(start, end, freq="10min", tz="UTC")
    seasonal = 1 + 0.30 * np.cos(2 * np.pi * (index.dayofyear.to_numpy() - 15) / 365.25)
    speed = np.clip((8.0 / 0.88623) * rng.weibull(2.0, len(index)) * seasonal, 0.1, None)
    return pd.DataFrame({"Spd_80m": speed}, index=index)


# ---------------------------------------------------------------------------
# Verified correct — hypotheses that measured away
# ---------------------------------------------------------------------------


def test_weibull_m1_m3_reproduces_the_moments_it_exists_to_preserve():
    """VERIFIED: the WAsP fit matches the 1st and 3rd raw moments to machine precision.

    The m1/m3 method exists to preserve mean speed *and* energy content, which is why the
    industry prefers it to MLE for resource assessment. If it did not reproduce those two
    moments it would have no claim over MLE at all. Measured across three (A, k) pairs on
    400 000 samples: both moments reproduced to better than 1e-12 relative.
    """
    pytest.importorskip("windkit")
    rng = np.random.default_rng(4)

    for true_k, true_a in ((1.8, 8.0), (2.0, 9.5), (2.4, 7.0)):
        sample = true_a * rng.weibull(true_k, 400_000)
        scale_a, shape_k = _weibull_wasp_fit(sample)

        m1_error, m3_error = oracles.weibull_m1_m3_residual(
            scale_a, shape_k, float(sample.mean()), float((sample**3).mean())
        )
        assert abs(m1_error) < 1e-11, f"m1 not preserved for k={true_k}"
        assert abs(m3_error) < 1e-11, f"m3 not preserved for k={true_k}"
        # And the recovered parameters are close to the ones the sample was drawn from.
        assert shape_k == pytest.approx(true_k, rel=0.01)
        assert scale_a == pytest.approx(true_a, rel=0.01)


def test_momm_month_weights_match_the_gregorian_calendar():
    """VERIFIED: the month-length weights are the Gregorian mean, not a 30-day idealisation.

    MoMM weights each month by its length so a 31-day January is not averaged as equal to a
    28-day February. Measured against the Gregorian calendar the worst month is February at
    28.24 against 28.2425 days — **0.009%** — and the twelve weights sum to 365.24 against a
    mean year of 365.2425. Immaterial, and worth recording so it is not re-investigated.
    """
    gregorian = {1: 31, 2: 28.2425, 3: 31, 4: 30, 5: 31, 6: 30,
                 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

    worst = max(
        abs(float(MEAN_DAYS_IN_MONTH[month]) / gregorian[month] - 1.0) for month in range(1, 13)
    )
    assert worst < 1e-4
    assert sum(float(MEAN_DAYS_IN_MONTH[m]) for m in range(1, 13)) == pytest.approx(365.2425, abs=0.01)


def test_circular_mean_and_variance_match_the_resultant_vector():
    """VERIFIED: direction statistics use the resultant vector, not an arithmetic mean.

    A naive mean of 350 deg and 10 deg gives 180 — the opposite of the answer. The
    implementation averages unit vectors and reports 1 - R as circular variance, which is
    the standard definition.
    """
    rng = np.random.default_rng(21)
    n = 40_000
    # A tight unimodal rose straddling north, which is where a naive mean breaks.
    direction = (rng.normal(0.0, 15.0, n)) % 360.0
    index = pd.date_range("2021-01-01", periods=n, freq="10min", tz="UTC")
    frame = pd.DataFrame(
        {"Spd_80m": np.clip(rng.weibull(2.0, n) * 8.0, 0.1, None), "Dir_80m": direction},
        index=index,
    )
    state = _state(frame, {80.0: {"speed_col": "Spd_80m", "dir_col": "Dir_80m", "sd_col": None, "temp_col": None}})

    climate = _compute_wind_climate(state, "Spd_80m", "Dir_80m")
    reported = float(climate["direction"]["mean_direction_deg"])

    assert reported == pytest.approx(oracles.circular_mean_deg(direction), abs=1e-9)
    assert float(climate["direction"]["circular_variance"]) == pytest.approx(
        oracles.circular_variance(direction), abs=1e-9
    )
    # Straddling north: the answer is near 0/360, and an arithmetic mean would say ~180.
    assert min(reported, 360.0 - reported) < 2.0
    assert 170.0 < float(np.mean(direction)) < 190.0


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_iec_ti_is_taken_from_the_bin_containing_fifteen_metres_per_second():
    """F-74 (HIGH) — FIXED. The turbulence class is selected from the right bin.

    The bug: the bin was chosen with ``(bins - 15.0).argmin()`` — ``argmin`` on a **signed**
    difference, which always returns the most negative element and therefore the lowest bin
    present, never the bin nearest 15 m/s. The absolute value was missing, so given the
    function's own ``> 3.0`` gate it reported the 3 m/s bin every time.

    TI falls roughly as 1/U, so the error was large and one-directional: **0.310 reported
    against 0.160 correct, +94.5%**. The correct value sits exactly on the IEC class A
    reference turbulence (Iref 0.16); the reported one was off the top of the scale.
    """
    frame = _ti_campaign()
    state = _state(frame)
    result = _compute_turbulence_analysis(state, "Spd_80m")

    correct = oracles.representative_ti_at(
        frame["Spd_80m"].to_numpy(), frame["Spd_80m_sd"].to_numpy(), target_speed=15.0
    )
    assert result["iec_ti_at_15ms"] == pytest.approx(correct, rel=1e-9)
    assert result["iec_ti_bin_mps"] == 15
    assert result["iec_ti_reference_speed_mps"] == IEC_REFERENCE_SPEED_MPS == 15.0
    # Right on the class A reference turbulence, and nowhere near the old 0.31.
    assert result["iec_ti_at_15ms"] == pytest.approx(0.16, abs=0.02)
    assert result["iec_ti_bin_records"] > 100
    assert "warning" not in result


def test_a_campaign_that_never_reaches_fifteen_says_so():
    """A low-wind site cannot supply the IEC number, and the response refuses to pretend.

    The bin actually used and its record count travel with the value, because on a campaign
    whose maximum is 11 m/s the "15 m/s" figure is a different quantity entirely.
    """
    frame = _ti_campaign()
    calm = frame[frame["Spd_80m"] < 11.0]
    result = _compute_turbulence_analysis(_state(calm), "Spd_80m")

    assert result["iec_ti_bin_mps"] == 10
    assert "never reached 15 m/s" in result["warning"]
    assert "turbulence class cannot be selected" in result["warning"]


def test_representative_ti_is_population_weighted_and_bins_report_their_counts():
    """F-75 (MEDIUM) — FIXED. A one-record bin no longer weighs as much as a five-thousand.

    ``representative.mean()`` was an unweighted mean across bins, so a 1-record bin at
    29 m/s counted equally with a 4 900-record bin at 5 m/s: **0.173 unweighted against
    0.211 population-weighted**, in a field with no stated definition. And
    ``mean + 1.28 * std(ddof=0)`` on a single-record bin has ``std = 0``, so the sparse tail
    contributed its raw value with no allowance for the uncertainty in it.

    ``representative_ti`` is now the population-weighted figure, its basis is named, the
    unweighted value is kept so an existing consumer can see what changed, and every bin
    reports its count against a stated minimum.
    """
    frame = _ti_campaign()
    result = _compute_turbulence_analysis(_state(frame), "Spd_80m")

    valid = frame[frame["Spd_80m"] > 3.0].copy()
    valid["ti"] = valid["Spd_80m_sd"] / valid["Spd_80m"]
    grouped = valid.groupby(np.floor(valid["Spd_80m"]).astype(int))["ti"]
    representative = grouped.mean() + 1.28 * grouped.std(ddof=0).fillna(0.0)
    counts = grouped.count()
    weighted = float((representative * counts).sum() / counts.sum())

    assert result["representative_ti_basis"] == "bin_population_weighted"
    assert result["representative_ti"] == pytest.approx(weighted, rel=1e-9)
    assert result["representative_ti_unweighted"] == pytest.approx(float(representative.mean()), rel=1e-9)
    assert abs(result["representative_ti"] / result["representative_ti_unweighted"] - 1.0) > 0.15

    # Every bin now carries its count and whether it clears the minimum.
    assert result["min_bin_records"] == TI_MIN_BIN_RECORDS == 20
    bins = result["bins"]
    assert len(bins) == len(counts)
    assert sum(row["count"] for row in bins) == result["record_count"]
    thin = [row for row in bins if not row["sufficient_records"]]
    assert thin and all(row["count"] < 20 for row in thin)
    assert all(row["bin_center_mps"] % 1 == 0.5 for row in bins)


def test_both_turbulence_tools_share_one_gate_and_declare_it():
    """F-76 (MEDIUM) — FIXED. One definition of `mean_ti`, named in both tools.

    ``compute_turbulence_analysis`` gated at ``speed > 3.0`` m/s and
    ``compute_turbulence_intensity`` at ``speed > 0``. Both published a TI over whatever
    survived, neither named its gate, and they differed by **13.8%** for the same sensor on
    the same day.

    The 3 m/s gate is the defensible one — below cut-in, sigma/U is the ratio of two small
    numbers — so it is now the shared default, it is a parameter, and both responses name it.
    Same resolution as F-03, where `mean_speed` had two definitions under one key.
    """
    frame = _ti_campaign()
    result = _compute_turbulence_analysis(_state(frame), "Spd_80m")

    ti = frame["Spd_80m_sd"] / frame["Spd_80m"]
    above_three = float(ti[frame["Spd_80m"] > 3.0].mean())
    above_zero = float(ti[frame["Spd_80m"] > 0.0].mean())

    # The default is the defensible gate, and the response says which it used.
    assert result["mean_ti"] == pytest.approx(above_three, rel=1e-9)
    assert result["speed_gate_mps"] == TI_MIN_SPEED_MPS == 3.0
    assert "above 3 m/s" in result["ti_basis"]

    # The gate is worth this much, which is why leaving it unnamed mattered.
    assert above_zero / above_three - 1.0 > 0.10

    # And it is movable, so the old population is still reachable — explicitly.
    ungated = _compute_turbulence_analysis(_state(frame), "Spd_80m", min_speed_mps=0.0)
    assert ungated["mean_ti"] == pytest.approx(above_zero, rel=1e-9)
    assert ungated["speed_gate_mps"] == 0.0


@pytest.mark.parametrize("seed", list(range(12)))
def test_a_short_campaign_gets_no_gev_fit_at_all(seed: int):
    """F-77 (HIGH) — FIXED. Three GEV parameters are no longer fitted to a handful of points.

    The bug: ``_compute_extremes`` required two annual maxima and fitted a 3-parameter GEV
    to them. Three parameters are not identifiable from two points, and across twelve seeds
    **twelve of twelve** fits were useless in one of two ways:

    - **Collapsed** (10 of 12): the shape pinned the tail to a bound at the data, so V50
      landed at or below the largest maximum already observed — ratios 0.876 to 0.9999 — and
      a further fifty years of return period bought under 0.04 m/s.
    - **Divergent** (2 of 12): V50 of 3.0e9 and 2.7e12 m/s. The strongest surface gust ever
      recorded on Earth is 113 m/s.

    Below ``GEV_MIN_YEARS`` the GEV is now not fitted at all rather than fitted and
    disclaimed, because what it produced was not an uncertain answer but a meaningless one.
    The two-parameter Gumbel fit is still reported, and both fits carry a plausibility
    verdict against the largest observation.
    """
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-01", "2022-02-28 23:50", freq="10min", tz="UTC")
    seasonal = 1 + 0.30 * np.cos(2 * np.pi * (index.dayofyear.to_numpy() - 15) / 365.25)
    speed = np.clip((8.0 / 0.88623) * rng.weibull(2.0, len(index)) * seasonal, 0.1, None)
    frame = pd.DataFrame({"Spd_80m": speed}, index=index)

    result = _compute_extremes(_state(frame, _SPEED_ONLY), "Spd_80m", min_year_coverage=0.0)

    assert result["sample_years"] == 2
    assert result["gev_minimum_years"] == GEV_MIN_YEARS == 10
    assert result["gev"]["available"] is False
    assert "identifiable" in result["gev"]["reason"]
    # No divergent or collapsed number is published under any key.
    assert "wind_50_year" not in result["gev"]
    assert "wind_100_year" not in result["gev"]

    # Gumbel is still offered, and a 2-year basis is called what it is.
    gumbel = result["gumbel"]
    assert gumbel["wind_50_year"] > gumbel["wind_100_year"] * 0.5
    assert result["screening_only"] is True
    assert "screening basis only" in result["warning"]


def test_a_long_record_gets_a_gev_fit_and_a_plausibility_verdict():
    """Above the threshold the GEV returns, and both fits are checked against the data.

    A return level at or below the largest maximum already observed has the extrapolation
    running backwards; one above any recorded wind speed has diverged. Neither is silently
    returned as an ordinary number any more.
    """
    frame = _seasonal_campaign("2003-01-01", "2022-12-31 23:50")
    result = _compute_extremes(_state(frame, _SPEED_ONLY), "Spd_80m")

    assert result["sample_years"] == 20
    assert result["screening_only"] is False
    assert result["gev"]["available"] is True
    assert result["gev"]["plausible"] is True
    assert result["gumbel"]["plausible"] is True

    # A real extrapolation: rising with return period, and physically possible. Note it is
    # NOT required to exceed the largest observed maximum — the largest of twenty annual
    # maxima is roughly a twenty-year event, and ordinary sampling variation puts it above a
    # fitted V50 often enough that treating it as a failure would reject good fits.
    for fit in ("gev", "gumbel"):
        assert result[fit]["wind_100_year"] > result[fit]["wind_50_year"] + 0.5
        assert result[fit]["wind_50_year"] > float(np.median(
            [row["max_speed"] for row in result["annual_maxima"]]
        ))
        assert result[fit]["wind_50_year"] < 120.0

    # And it cross-checks against an independent method-of-moments Gumbel.
    maxima = np.array([row["max_speed"] for row in result["annual_maxima"]], dtype=float)
    assert result["gumbel"]["wind_50_year"] == pytest.approx(
        oracles.gumbel_return_level(maxima, 50.0), rel=0.05
    )


def test_partial_calendar_years_are_excluded_from_the_extreme_fit():
    """F-78 (HIGH) — FIXED. A partial year no longer enters the fit as a full one.

    ``resample("YE").max()`` treated any calendar year holding one record as a year, so a
    campaign starting or ending mid-year contributed a partial-season maximum to a fit whose
    whole premise is that each point is an *annual* maximum.

    I expected a small one-directional bias and it is neither. A low outlier pulls the
    Gumbel location down but pushes its scale up, and at the 50-year quantile the scale
    dominates, so the sign depends on how much of the storm season survives — measured on
    eight complete years with the last truncated: Jun-Dec **-8.3%**, May-Sep **+17.5%**,
    July only **+40.9%** on V50.

    The gate is the one the clipping analysis has always had, and excluded years are
    reported with their completeness rather than dropped silently.
    """
    full = _seasonal_campaign("2015-01-01", "2022-12-31 23:50")
    july_only = full[~((full.index.year == 2022) & (full.index.month != 7))]

    baseline = _compute_extremes(_state(full, _SPEED_ONLY), "Spd_80m")
    guarded = _compute_extremes(_state(july_only, _SPEED_ONLY), "Spd_80m")

    # The one-month year is excluded, and the remaining seven are unaffected.
    assert baseline["sample_years"] == 8
    assert guarded["sample_years"] == 7
    assert [row["year"] for row in guarded["annual_maxima"]] == list(range(2015, 2022))

    excluded = guarded["years_excluded"]
    assert len(excluded) == 1
    assert excluded[0]["year"] == 2022
    assert excluded[0]["day_coverage"] < 0.1
    assert excluded[0]["records"] == int((july_only.index.year == 2022).sum())
    assert "partial-season maximum" in guarded["warning"]

    # The +40.9% swing is gone: excluding the partial year gives exactly the answer that
    # never having had it gives. (It does NOT match the 8-complete-year baseline, and should
    # not — dropping 2022 removes a real year's information along with the bias.)
    seven_complete = full[full.index.year <= 2021]
    reference = _compute_extremes(_state(seven_complete, _SPEED_ONLY), "Spd_80m")
    assert reference["sample_years"] == 7
    assert guarded["gumbel"]["wind_50_year"] == pytest.approx(
        reference["gumbel"]["wind_50_year"], rel=1e-9
    )

    # The gate is a parameter, so the old behaviour is still reachable — explicitly.
    ungated = _compute_extremes(_state(july_only, _SPEED_ONLY), "Spd_80m", min_year_coverage=0.0)
    assert ungated["sample_years"] == 8
    assert ungated["gumbel"]["wind_50_year"] / baseline["gumbel"]["wind_50_year"] - 1.0 > 0.30


def test_extreme_winds_prefer_the_long_term_corrected_series():
    """F-79 (MEDIUM) — FIXED. V50 is fitted to the long-term series when one exists.

    ``_compute_extremes`` read ``state.timeseries_df``. The pipeline's entire purpose is to
    build a twenty-year corrected series, and the extreme wind — the one output that most
    needs a long record — was the only major result that never saw it. A 50-year level from
    two annual maxima extrapolates 25x beyond its data; from twenty years it extrapolates
    2.5x, which is the difference between an estimate and a guess.

    ``source="auto"`` now prefers ensemble, then any LTC result, then the campaign, and the
    series actually used is reported.
    """
    campaign = _seasonal_campaign("2021-01-01", "2022-12-31 23:50")
    state = _state(campaign, _SPEED_ONLY)

    # Campaign only: it still works, and it says what it fell back to.
    measured = _compute_extremes(state, "Spd_80m")
    assert measured["series_basis"] == "measured:Spd_80m"
    assert measured["sample_years"] == 2
    assert "rather than the long-term corrected series" in measured["warning"]

    # Give the session what a real run would have by this stage.
    long_frame = _seasonal_campaign("2003-01-01", "2022-12-31 23:50", seed=11)
    hourly = long_frame["Spd_80m"].resample("h").mean().dropna()
    state.ensemble_df = pd.DataFrame(
        {"Timestamp": hourly.index, "Ensemble_Speed": hourly.to_numpy()}
    )

    corrected = _compute_extremes(state, "Spd_80m")
    assert corrected["series_basis"] == "ensemble"
    assert corrected["sample_years"] == 20
    assert corrected["screening_only"] is False
    assert corrected["gev"]["available"] is True
    assert "rather than the long-term corrected series" not in corrected.get("warning", "")

    # And the choice is explicit when the caller wants it to be.
    assert _compute_extremes(state, "Spd_80m", source="measured")["sample_years"] == 2
    assert _compute_extremes(state, "Spd_80m", source="long_term")["series_basis"] == "ensemble"
    with pytest.raises(ValueError, match="source must be one of"):
        _compute_extremes(state, "Spd_80m", source="reanalysis")
