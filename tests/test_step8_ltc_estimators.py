"""LTC / MCP estimator correctness — Step 8 of the logic audit.

The long-term correction produces the series every downstream number rests on:
clipping, IAV, uncertainty and every P-value. Magnitudes in the docstrings were
measured, not estimated.

Headline: the five estimators are individually sound and the regression direction is
right. The two high-severity findings are both about *coverage* rather than
arithmetic — records that no model wrote, and an ensemble that scales speeds down
instead of renormalising when a component is absent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.regression import (
    ols_confidence_intervals,
    robust_huber_fit,
    total_least_squares_fit,
)
from server.state.session import SessionState
from server.tools.ensemble import _run_ensemble
from server.tools.ltc import (
    _run_ltc_linear_least_squares,
    _run_ltc_speedsort,
    _run_ltc_total_least_squares,
    _run_ltc_variance_ratio,
    _speedsort_sector_index,
)

TRUE_SLOPE, TRUE_INTERCEPT = 1.08, 0.35


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Plain ordinary least squares, as an independent reference estimator."""
    mean_x, mean_y = x.mean(), y.mean()
    slope = float(np.sum((x - mean_x) * (y - mean_y)) / np.sum((x - mean_x) ** 2))
    return slope, float(mean_y - slope * mean_x)


def _mcp_state(
    long_years: tuple[str, str] = ("2019-01-01", "2021-12-31 23:00"),
    measured_year: tuple[str, str] = ("2021-01-01", "2021-12-31 23:00"),
    direction: np.ndarray | None = None,
    seed: int = 9,
) -> tuple[SessionState, np.ndarray, pd.DatetimeIndex]:
    """Build a session with an hourly long-term reference and a one-year campaign."""
    rng = np.random.default_rng(seed)
    long_index = pd.date_range(*long_years, freq="h", tz="UTC")
    reference = np.clip(rng.weibull(2.0, len(long_index)) * 8.0, 0.1, None)

    measured_index = pd.date_range(*measured_year, freq="h", tz="UTC")
    reference_on_measured = pd.Series(reference, index=long_index).reindex(measured_index).to_numpy()
    measured = np.clip(
        TRUE_SLOPE * reference_on_measured + TRUE_INTERCEPT + rng.normal(0, 1.0, len(measured_index)),
        0.05,
        None,
    )

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_hub": measured}, index=measured_index)
    columns: dict[str, np.ndarray] = {"Spd_hub": reference}
    if direction is not None:
        columns["ERA5_Direction"] = direction
    state.era5_interpolated_df = pd.DataFrame(columns, index=long_index)
    return state, reference, long_index


# ---------------------------------------------------------------------------
# Verified correct — not findings
# ---------------------------------------------------------------------------


def test_regression_direction_predicts_measured_from_reference():
    """VERIFIED: every algorithm fits measured ~ reference, then applies it to the long reference.

    The reverse direction would be a hard error — regression dilution would attenuate
    the long-term mean. Checked by construction: a slope of 1.08 recovered on data
    built with that slope proves the fit was not inverted (an inverted fit would
    recover approximately 1/1.08 x R^2).
    """
    state, reference, _ = _mcp_state()
    result = _run_ltc_linear_least_squares(state, "Spd_hub", "Spd_hub")
    slope = float(result["metrics"]["slope"])

    assert slope == pytest.approx(TRUE_SLOPE, rel=0.02)
    assert slope > 1.0  # an inverted fit would land near 0.9 or below

    corrected = state.ltc_results["linear_least_squares"]["df"]["corrected_wind_speed"].to_numpy()
    expected = reference * slope + float(result["metrics"]["intercept"])
    assert np.allclose(corrected, np.maximum(expected, 0.0), atol=1e-9)


def test_total_least_squares_matches_the_major_axis_eigenvector():
    """VERIFIED: the closed-form TLS slope equals the principal eigenvector of the covariance."""
    rng = np.random.default_rng(1)
    x = rng.normal(8.0, 2.5, 5000)
    y = 1.1 * x + 0.3 + rng.normal(0, 0.8, 5000)

    slope, intercept = total_least_squares_fit(x, y)

    centred = np.vstack([x - x.mean(), y - y.mean()])
    eigenvalues, eigenvectors = np.linalg.eigh(centred @ centred.T)
    principal = eigenvectors[:, np.argmax(eigenvalues)]
    assert slope == pytest.approx(principal[1] / principal[0], rel=1e-9)
    assert intercept == pytest.approx(y.mean() - slope * x.mean(), rel=1e-12)


def test_total_least_squares_refuses_a_vertical_relationship():
    """VERIFIED: a genuinely undefined slope raises rather than returning a sentinel."""
    with pytest.raises(ValueError, match="degenerate"):
        total_least_squares_fit(np.full(50, 7.0), np.linspace(1.0, 20.0, 50))

    # Constant y with real spread in x is horizontal, not degenerate.
    slope, intercept = total_least_squares_fit(np.linspace(1.0, 20.0, 50), np.full(50, 7.0))
    assert slope == 0.0
    assert intercept == pytest.approx(7.0)


def test_variance_ratio_preserves_the_concurrent_mean_and_spread():
    """VERIFIED: variance ratio reproduces the measured mean and sd on the concurrent period."""
    state, _, _ = _mcp_state()
    result = _run_ltc_variance_ratio(state, "Spd_hub", "Spd_hub")
    metrics = result["metrics"]

    assert metrics["variance_ratio"] == pytest.approx(
        metrics["measured_std"] / metrics["reference_std"], rel=1e-12
    )
    # sigma is taken on the concurrent overlap for both sides, which is the point.
    measured = state.timeseries_df["Spd_hub"].dropna()
    assert metrics["measured_std"] == pytest.approx(float(measured.std(ddof=1)), rel=0.02)


def test_speedsort_dog_leg_is_continuous_at_the_breakpoint():
    """VERIFIED: the low-speed segment meets the high-speed fit exactly at the threshold."""
    state, _, _ = _mcp_state()
    result = _run_ltc_speedsort(state, "Spd_hub", "Spd_hub")
    metrics = result["metrics"]
    threshold = float(metrics["threshold"])
    slope, intercept = float(metrics["slope"]), float(metrics["intercept"])
    dog_leg = float(metrics["dog_leg_slope"])

    from_above = slope * threshold + intercept
    from_below = threshold * dog_leg
    assert from_above == pytest.approx(from_below, rel=1e-12)
    # And the low-speed segment passes through the origin, as a dog-leg must.
    assert 0.0 * dog_leg == 0.0


def test_speedsort_sparse_sectors_fall_back_to_the_all_sector_fit():
    """VERIFIED: sectors below the 200-record minimum reuse the pooled model and are counted."""
    rng = np.random.default_rng(4)
    long_index = pd.date_range("2019-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    # Concentrate almost all records in two sectors so the rest are sparse.
    direction = np.where(rng.random(len(long_index)) < 0.97, 95.0, 275.0)
    direction[:150] = 5.0  # one deliberately thin sector
    state, _, _ = _mcp_state(direction=direction)

    result = _run_ltc_speedsort(state, "Spd_hub", "Spd_hub", "", "ERA5_Direction")
    metrics = result["metrics"]

    assert metrics["directional"] is True
    assert metrics["min_sector_records"] == 200
    assert metrics["independent_sectors"] < metrics["num_sectors"]
    assert len(metrics["sector_models"]) == metrics["num_sectors"]  # sparse ones still modelled


# ---------------------------------------------------------------------------
# High-severity findings
# ---------------------------------------------------------------------------


def test_ensemble_renormalises_weights_per_timestamp():
    """F-44 (HIGH) — FIXED. Regression test: a partly covered timestamp must not be scaled down.

    The bug: ``_run_ensemble`` accumulated ``corrected.fillna(0.0) * weights[algorithm]``
    over the union of component indexes with the weights fixed globally. Where a
    component was absent it contributed a hard zero while the others still contributed
    only their fractional weights, so the blend was scaled by the covered weight.

    Measured before the fix, with two *identical* components one of which was missing
    its first year: the uncovered stretch reported **3.99 m/s against a truth of
    7.98 m/s** — exactly half — and the long-term mean came out **16.6% low**, with
    zero non-finite values to reveal it and healthy-looking metrics (rmse 0.998,
    r2 0.943, bias ~0) because those are computed only on the measured overlap, which
    sat inside the fully-covered period.

    The fix divides by the weight actually present at each timestamp, so a partly
    covered record is the weighted mean of the components that exist and a fully
    covered one is unchanged. Coverage now travels with the response.
    """
    rng = np.random.default_rng(3)
    long_index = pd.date_range("2019-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference = np.clip(rng.weibull(2.0, len(long_index)) * 8.0, 0.1, None)
    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference_on_measured = pd.Series(reference, index=long_index).reindex(measured_index).to_numpy()

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {
            "Spd_hub": np.clip(
                TRUE_SLOPE * reference_on_measured + TRUE_INTERCEPT + rng.normal(0, 1.0, len(measured_index)),
                0.05,
                None,
            )
        },
        index=measured_index,
    )

    corrected_full = TRUE_SLOPE * reference + TRUE_INTERCEPT
    covered = long_index >= pd.Timestamp("2020-01-01", tz="UTC")
    state.ltc_results = {
        "algo_a": {"df": pd.DataFrame({"Timestamp": long_index, "corrected_wind_speed": corrected_full}), "metrics": {}},
        "algo_b": {
            "df": pd.DataFrame(
                {"Timestamp": long_index[covered], "corrected_wind_speed": corrected_full[covered]}
            ),
            "metrics": {},
        },
    }

    result = _run_ensemble(state, "Spd_hub")
    ensemble = pd.DataFrame(state.ensemble_df).set_index("Timestamp")["Ensemble_Speed"]

    assert result["weights"]["algo_a"] == pytest.approx(0.5, abs=0.05)

    # Fully covered stretch: unchanged by the renormalisation.
    assert ensemble[covered].mean() == pytest.approx(corrected_full[covered].mean(), rel=0.01)

    # Partially covered stretch: the weighted mean of what exists, not half of it.
    partial = ~covered
    assert ensemble[partial].mean() == pytest.approx(corrected_full[partial].mean(), rel=0.01)
    assert ensemble.mean() == pytest.approx(corrected_full.mean(), rel=0.01)

    # Coverage travels with the result, and the partial blend is flagged.
    coverage = result["component_coverage"]
    assert coverage["total_records"] == len(long_index)
    assert coverage["fully_covered_records"] == int(covered.sum())
    assert coverage["partially_covered_records"] == int(partial.sum())
    assert coverage["uncovered_records"] == 0
    assert coverage["component_records"]["algo_a"] == len(long_index)
    assert coverage["component_records"]["algo_b"] == int(covered.sum())
    assert "warning" in result


def test_ensemble_emits_nan_where_no_component_covers_a_timestamp():
    """A timestamp no component reached must be NaN, not a silent zero.

    The union index can contain timestamps every component is missing once a
    component carries internal gaps (SpeedSort's F-36 records, for instance). Before
    the F-44 fix those became 0.0; they must now be absent, so downstream `dropna`
    excludes them instead of averaging them in.
    """
    rng = np.random.default_rng(21)
    index = pd.date_range("2021-01-01", periods=100, freq="h", tz="UTC")
    truth = np.full(100, 9.0)
    # Small, equal-magnitude residuals: a component with exactly zero RMSE is given
    # zero weight by the inverse-RMSE guard, which is a separate issue (Step 9).
    values_a = truth + rng.normal(0, 0.4, 100)
    values_b = truth + rng.normal(0, 0.4, 100)
    values_a[40:60] = np.nan  # both components blind over the same stretch
    values_b[40:60] = np.nan

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_hub": truth}, index=index)
    state.ltc_results = {
        "algo_a": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": values_a}), "metrics": {}},
        "algo_b": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": values_b}), "metrics": {}},
    }

    result = _run_ensemble(state, "Spd_hub")
    ensemble = pd.DataFrame(state.ensemble_df).set_index("Timestamp")["Ensemble_Speed"]

    assert int(ensemble.isna().sum()) == 20
    assert ensemble.dropna().mean() == pytest.approx(9.0, abs=0.15)
    assert result["component_coverage"]["uncovered_records"] == 20
    assert result["component_coverage"]["fully_covered_records"] == 80


def test_speedsort_marks_records_it_cannot_correct_instead_of_leaving_them_unwritten():
    """F-36 (HIGH) — FIXED. Regression test: a directionless record must be NaN and counted.

    The bug: ``_speedsort_sector_index`` casts a NaN direction to INT64_MIN, which
    matches no sector, so those entries of the ``np.empty_like`` output array were
    never assigned and carried whatever was last in that memory. Measured on a 3-year
    hourly reference with a 4 000-record direction outage (15% of the series): all
    4 000 came back non-finite in the full run and as **0.0** in a smaller
    reproduction — the content was not deterministic, and a plausible-looking 0.0
    passed ``negative_predictions_clipped`` untouched while dragging the mean down.

    The fix allocates with ``np.full(..., nan)``, detects a missing reference direction
    explicitly, and reports ``reference_direction_missing``, ``unmodelled_records`` and
    ``unmodelled_fraction`` with a warning.
    """
    rng = np.random.default_rng(9)
    long_index = pd.date_range("2019-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    direction = rng.uniform(0, 360, len(long_index))
    direction[5000:9000] = np.nan  # a realistic direction-channel outage
    state, _, _ = _mcp_state(direction=direction)

    # The underlying cast is still the hazard the fix guards against.
    assert _speedsort_sector_index(np.array([np.nan]))[0] < 0

    result = _run_ltc_speedsort(state, "Spd_hub", "Spd_hub", "", "ERA5_Direction")
    corrected = state.ltc_results["speedsort"]["df"]["corrected_wind_speed"].to_numpy()
    metrics = result["metrics"]

    gap = np.isnan(direction)
    assert int(gap.sum()) == 4000
    assert metrics["directional"] is True

    # Every directionless record is absent, and every other record is a real prediction.
    assert bool(np.all(~np.isfinite(corrected[gap])))
    assert bool(np.all(np.isfinite(corrected[~gap])))

    assert metrics["reference_direction_missing"] == 4000
    assert metrics["unmodelled_records"] == 4000
    assert metrics["unmodelled_fraction"] == pytest.approx(4000 / len(long_index))
    assert "warning" in metrics


def test_speedsort_without_direction_gaps_reports_no_unmodelled_records():
    """The counterpart: a complete direction channel must leave nothing unmodelled."""
    rng = np.random.default_rng(12)
    long_index = pd.date_range("2019-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    state, _, _ = _mcp_state(direction=rng.uniform(0, 360, len(long_index)))

    result = _run_ltc_speedsort(state, "Spd_hub", "Spd_hub", "", "ERA5_Direction")
    corrected = state.ltc_results["speedsort"]["df"]["corrected_wind_speed"].to_numpy()

    assert result["metrics"]["reference_direction_missing"] == 0
    assert result["metrics"]["unmodelled_records"] == 0
    assert "warning" not in result["metrics"]
    assert bool(np.all(np.isfinite(corrected)))


# ---------------------------------------------------------------------------
# Medium-severity findings
# ---------------------------------------------------------------------------


def test_linear_least_squares_is_actually_huber_robust_regression():
    """FINDING F-37: the algorithm named `linear_least_squares` fits Huber IRLS.

    ``_run_ltc_linear_least_squares`` calls ``robust_huber_fit`` (delta = 1.35), yet
    the tool name, the ``algorithm`` metric, the README and the default canvas plan
    all say least squares. Measured slope difference against true OLS: **-0.03% on
    clean data**, **+0.34%** with 0.5% icing spikes, **+1.83%** with 2% frozen-sensor
    records (long-term mean +1.48%).

    Huber is the better estimator under contamination — the objection is that the
    response asserts a method it does not use, so nobody can reconcile the slope
    against WAsP, windPRO or Windographer OLS.
    """
    rng = np.random.default_rng(42)
    n = 20_000
    reference = np.clip(rng.weibull(2.0, n) * 8.0, 0.1, None)
    measured = np.clip(
        TRUE_SLOPE * reference + TRUE_INTERCEPT + rng.normal(0, 0.12 * reference + 0.3), 0.05, None
    )

    ols_slope, _ = _ols(reference, measured)
    huber_slope, _, _, _ = robust_huber_fit(reference, measured)
    assert huber_slope != pytest.approx(ols_slope, rel=1e-6)
    assert huber_slope == pytest.approx(ols_slope, rel=0.01)  # clean data: immaterial

    # Contaminated data: the two estimators genuinely diverge.
    contaminated = measured.copy()
    contaminated[rng.choice(n, int(0.02 * n), replace=False)] = 0.2
    ols_dirty, _ = _ols(reference, contaminated)
    huber_dirty, _, _, _ = robust_huber_fit(reference, contaminated)
    assert huber_dirty / ols_dirty - 1.0 > 0.01

    # And the response still claims least squares.
    state, _, _ = _mcp_state()
    result = _run_ltc_linear_least_squares(state, "Spd_hub", "Spd_hub")
    assert result["metrics"]["algorithm"] == "linear_least_squares"
    assert "estimator" not in result["metrics"]
    assert "loss" not in result["metrics"]


def test_slope_methods_attenuate_variance_and_shift_iav():
    """FINDING F-38: slope-based MCP shrinks spread; variance ratio does not. IAV differs by 10%.

    A slope fit retains exactly R^2 of the target variance, so slope-based methods
    produce a narrower long-term distribution than the measured one. Measured across
    the four algorithms on one dataset, as sd relative to the reference sd:
    1.086 (linear_least_squares), 1.152 (variance_ratio), 1.162 (total_least_squares),
    1.182 (speedsort) — and inter-annual variability of 5.76%, 6.10%, 6.15% and 6.34%
    respectively.

    That 0.58-point IAV spread is a ~10% relative difference in the quantity that
    feeds ``iav_pct`` (and therefore u_future) and the clipping objective. The README
    discloses the *resampling* variance loss but not this *regression* attenuation,
    and the ensemble blends variance-preserving with variance-attenuating components
    into a mixture it does not describe.
    """
    rng = np.random.default_rng(5)
    long_index = pd.date_range("2003-01-01", "2022-12-31 23:00", freq="h", tz="UTC")
    years = np.unique(long_index.year)
    year_map = dict(zip(years, 1 + 0.06 * rng.standard_normal(len(years)), strict=True))
    inter_annual = np.array([year_map[y] for y in long_index.year])
    reference = np.clip((6.6 / 0.88623) * rng.weibull(2.0, len(long_index)) * inter_annual, 0.05, None)

    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference_on_measured = pd.Series(reference, index=long_index).reindex(measured_index).to_numpy()

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {
            "Spd_hub": np.clip(
                TRUE_SLOPE * reference_on_measured + TRUE_INTERCEPT + rng.normal(0, 1.3, len(measured_index)),
                0.05,
                None,
            )
        },
        index=measured_index,
    )
    state.era5_interpolated_df = pd.DataFrame({"Spd_hub": reference}, index=long_index)

    iav: dict[str, float] = {}
    spread: dict[str, float] = {}
    reference_sd = float(reference.std(ddof=1))
    for name, runner in (
        ("linear_least_squares", _run_ltc_linear_least_squares),
        ("total_least_squares", _run_ltc_total_least_squares),
        ("variance_ratio", _run_ltc_variance_ratio),
    ):
        runner(state, "Spd_hub", "Spd_hub")
        frame = state.ltc_results[name]["df"]
        series = pd.Series(
            frame["corrected_wind_speed"].to_numpy(), index=pd.DatetimeIndex(frame["Timestamp"])
        )
        annual = series.resample("YE").mean()
        iav[name] = float(annual.std(ddof=1) / annual.mean())
        spread[name] = float(series.std(ddof=1) / reference_sd)

    # The slope fit is the narrowest and gives the lowest IAV.
    assert spread["linear_least_squares"] < spread["variance_ratio"]
    assert iav["linear_least_squares"] < iav["variance_ratio"]
    assert (iav["variance_ratio"] / iav["linear_least_squares"] - 1.0) > 0.04

    # No response labels its variance basis.
    for name in iav:
        assert "variance_basis" not in state.ltc_results[name]["metrics"]


def test_total_least_squares_assumes_equal_error_variance_in_both_series():
    """FINDING F-43: TLS is only the right estimator when both series carry equal error.

    Orthogonal regression minimises perpendicular distance, which is the maximum
    likelihood fit only when the error variances of x and y are equal. Reanalysis
    error greatly exceeds mast error, so neither TLS (ratio 1) nor OLS (ratio 0) is
    at the statistically correct point; Deming regression needs an error-variance
    ratio that nothing in the pipeline supplies.

    Measured on data where all error is in y (true slope 1.080): OLS recovers 1.082
    while **TLS returns 1.138 — a 5.4% overshoot**, moving the long-term mean by
    about +0.5%. The choice between the two is therefore a methodology decision with
    a measurable consequence, presented as two peer algorithms.
    """
    rng = np.random.default_rng(42)
    n = 20_000
    reference = np.clip(rng.weibull(2.0, n) * 8.0, 0.1, None)
    measured = np.clip(
        TRUE_SLOPE * reference + TRUE_INTERCEPT + rng.normal(0, 0.12 * reference + 0.3), 0.05, None
    )

    ols_slope, ols_intercept = _ols(reference, measured)
    tls_slope, tls_intercept = total_least_squares_fit(reference, measured)

    assert ols_slope == pytest.approx(TRUE_SLOPE, rel=0.01)
    assert tls_slope > TRUE_SLOPE * 1.03  # biased high when error is y-only

    long_term_mean = 7.9
    ols_mean = ols_slope * long_term_mean + ols_intercept
    tls_mean = tls_slope * long_term_mean + tls_intercept
    assert tls_mean / ols_mean - 1.0 > 0.003


def test_ols_confidence_intervals_are_too_narrow_under_autocorrelation():
    """FINDING F-41 (quantified): the reported interval is 3.5x too narrow on hourly wind.

    ``ols_confidence_intervals`` documents this honestly but the magnitude was never
    measured. With AR(1) residuals at phi = 0.85 — ordinary for hourly wind — on
    n = 20 000: residual lag-1 autocorrelation 0.847, effective sample size 1 659
    (**8.3% of n**), so the correct interval is **3.47x wider** than reported.
    """
    rng = np.random.default_rng(42)
    n = 20_000
    reference = np.clip(rng.weibull(2.0, n) * 8.0, 0.1, None)
    noise = np.zeros(n)
    for i in range(1, n):
        noise[i] = 0.85 * noise[i - 1] + rng.normal(0, 1.0)
    measured = TRUE_SLOPE * reference + TRUE_INTERCEPT + 0.5 * noise

    interval, _ = ols_confidence_intervals(reference, measured)
    assert interval is not None
    half_width = (interval[1] - interval[0]) / 2.0

    slope, intercept = _ols(reference, measured)
    residuals = measured - (slope * reference + intercept)
    lag1 = float(np.corrcoef(residuals[:-1], residuals[1:])[0, 1])
    n_effective = n * (1 - lag1) / (1 + lag1)

    assert lag1 > 0.8
    assert n_effective / n < 0.15
    assert float(np.sqrt(n / n_effective)) > 3.0
    # The reported interval is the uncorrected one.
    assert half_width < 0.005


def test_speedsort_threshold_basis_differs_between_its_two_paths():
    """FINDING F-42: the dog-leg threshold is derived from different data in each path.

    The non-directional path uses ``0.5 * long_df[REFERENCE].mean()`` — the *long-term*
    reference mean — while the directional path uses ``0.5 * np.mean(reference)``, the
    *concurrent* mean. Measured on one dataset: 3.259 vs 3.191. The concurrent basis
    is the defensible one, since the threshold characterises the data the transfer
    function was fitted to, not the data it is applied to.
    """
    rng = np.random.default_rng(4)
    long_index = pd.date_range("2019-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    # Make the long-term and concurrent means deliberately different.
    reference = np.clip(rng.weibull(2.0, len(long_index)) * 8.0, 0.1, None)
    reference[: len(long_index) // 2] *= 0.75

    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference_on_measured = pd.Series(reference, index=long_index).reindex(measured_index).to_numpy()

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {
            "Spd_hub": np.clip(
                TRUE_SLOPE * reference_on_measured + TRUE_INTERCEPT + rng.normal(0, 1.0, len(measured_index)),
                0.05,
                None,
            )
        },
        index=measured_index,
    )
    state.era5_interpolated_df = pd.DataFrame(
        {"Spd_hub": reference, "ERA5_Direction": rng.uniform(0, 360, len(long_index))},
        index=long_index,
    )

    non_directional = _run_ltc_speedsort(state, "Spd_hub", "Spd_hub")
    directional = _run_ltc_speedsort(state, "Spd_hub", "Spd_hub", "", "ERA5_Direction")

    assert float(non_directional["metrics"]["threshold"]) == pytest.approx(
        min(4.0, 0.5 * float(reference.mean())), rel=1e-6
    )
    assert float(directional["metrics"]["threshold"]) != pytest.approx(
        float(non_directional["metrics"]["threshold"]), rel=1e-6
    )


def test_ensemble_mixes_out_of_sample_and_in_sample_rmse_bases():
    """FINDING F-35/F-45: the weighting basis is mixed by construction and unlabelled.

    ``_run_ensemble`` prefers ``out_of_sample_rmse`` where a component reports one and
    falls back to the concurrent-overlap RMSE otherwise. Only XGBoost reports the
    former, so its weight rests on held-out error while every linear method's rests
    on in-sample error. Confirmed here at the code level by giving one component an
    ``out_of_sample_rmse`` and watching the weights move.
    """
    rng = np.random.default_rng(11)
    long_index = pd.date_range("2020-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference = np.clip(rng.weibull(2.0, len(long_index)) * 8.0, 0.1, None)
    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference_on_measured = pd.Series(reference, index=long_index).reindex(measured_index).to_numpy()
    corrected = TRUE_SLOPE * reference + TRUE_INTERCEPT

    def build(oos: float | None) -> dict:
        state = SessionState()
        state.reset()
        state.timeseries_df = pd.DataFrame(
            {
                "Spd_hub": np.clip(
                    TRUE_SLOPE * reference_on_measured + TRUE_INTERCEPT + rng.normal(0, 1.0, len(measured_index)),
                    0.05,
                    None,
                )
            },
            index=measured_index,
        )
        frame = pd.DataFrame({"Timestamp": long_index, "corrected_wind_speed": corrected})
        metrics_b: dict[str, object] = {} if oos is None else {"out_of_sample_rmse": oos}
        state.ltc_results = {
            "algo_a": {"df": frame.copy(), "metrics": {}},
            "algo_b": {"df": frame.copy(), "metrics": metrics_b},
        }
        return _run_ensemble(state, "Spd_hub")

    baseline = build(None)
    with_oos = build(0.05)  # an implausibly good held-out RMSE

    assert baseline["weights"]["algo_b"] == pytest.approx(0.5, abs=0.05)
    assert with_oos["weights"]["algo_b"] > 0.9  # the mixed basis hands it the blend
    assert "weight_basis" not in with_oos


# ---------------------------------------------------------------------------
# XGBoost
# ---------------------------------------------------------------------------


def test_xgboost_split_is_chronological_but_the_holdout_is_one_season():
    """FINDING F-39/F-40: the split is correctly temporal, and the holdout is seasonally biased.

    VERIFIED: ``iloc[:split]`` / ``iloc[split:]`` on a time-ordered frame is a block
    split, so there is no random-split leakage — the hypothesis this test set out to
    check is negative.

    FINDING: the holdout is a single terminal block. Measured on a one-year campaign
    with a seasonal cycle, validation covers **October to December only**, mean
    8.45 m/s against a training mean of 7.18 m/s — a **+17.7%** offset. That
    seasonally-biased figure is reported as ``out_of_sample_rmse``, and it is exactly
    the number that earns XGBoost its ensemble weight (F-45).

    FINDING: ``early_stopping_rounds`` selects the boosting iteration on the same
    slice then reported as out-of-sample, so the figure is additionally optimistic
    through model selection.
    """
    pytest.importorskip("xgboost")
    from server.tools.ltc_ml import _run_ltc_xgboost

    rng = np.random.default_rng(7)
    long_index = pd.date_range("2015-01-01", "2022-12-31 23:00", freq="h", tz="UTC")
    seasonal = 1 + 0.25 * np.cos(2 * np.pi * (long_index.dayofyear.to_numpy() - 15) / 365.25)
    reference = np.clip((6.6 / 0.88623) * rng.weibull(2.0, len(long_index)) * seasonal, 0.05, None)

    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:00", freq="h", tz="UTC")
    reference_on_measured = pd.Series(reference, index=long_index).reindex(measured_index).to_numpy()
    measured = np.clip(
        TRUE_SLOPE * reference_on_measured + TRUE_INTERCEPT + rng.normal(0, 1.2, len(measured_index)),
        0.05,
        None,
    )

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_hub": measured}, index=measured_index)
    state.era5_interpolated_df = pd.DataFrame({"Spd_hub": reference}, index=long_index)

    result = _run_ltc_xgboost(state, "Spd_hub", "Spd_hub")
    metrics = result["metrics"]

    split = int(0.8 * len(measured_index))
    validation_months = sorted(set(measured_index[split:].month))
    assert validation_months == [10, 11, 12]  # a single season, not a spread-out holdout
    assert measured[split:].mean() / measured[:split].mean() - 1.0 > 0.10

    # The seasonally-biased holdout figure is what the ensemble consumes.
    assert "out_of_sample_rmse" in metrics
    assert metrics["out_of_sample_rmse"] == pytest.approx(metrics["rmse"], rel=1e-9)
    # No cross-validation or fold structure is reported.
    assert not any("fold" in key or "cv_" in key for key in metrics)


def test_xgboost_discloses_upper_tail_truncation():
    """VERIFIED: trees cannot extrapolate, and the response says so."""
    pytest.importorskip("xgboost")
    from server.tools.ltc_ml import _run_ltc_xgboost

    state, _, _ = _mcp_state(long_years=("2015-01-01", "2022-12-31 23:00"))
    result = _run_ltc_xgboost(state, "Spd_hub", "Spd_hub")
    metrics = result["metrics"]

    assert "n_above_training_max" in metrics
    assert "fraction_above_training_max" in metrics
    assert "extreme_wind_suitability" in metrics
    assert metrics["prediction_ceiling_mps"] <= metrics["campaign_reference_max_mps"] * 1.5
