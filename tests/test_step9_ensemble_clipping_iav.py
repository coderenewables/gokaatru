"""Ensemble, clipping representativeness and IAV — Step 9 of the logic audit.

This is where the long-term series becomes a *reported* long-term period: which years
count, how variable they are, and how confident the blend is. The arithmetic is
mostly sound; the failures are in what reaches the reader and in an objective whose
coefficients have no stated origin.

F-44 (ensemble weight renormalisation) was found and fixed in Step 8; its regression
tests live in `test_step8_ltc_estimators.py`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.state.session import SessionState
from server.tools.clipping import (
    CLIMATE_FLOOR,
    CLIMATE_MAX,
    CLIMATE_SCALE,
    REFERENCE_WINDOW_YEARS,
    _run_clipping_analysis,
)
from server.tools.ensemble import _run_ensemble


def _annual_series_state(
    n_years: int,
    iav: float = 0.06,
    trend: float = 0.0,
    seed: int = 1,
) -> SessionState:
    """Return a session whose ensemble series has a known inter-annual structure."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(f"{2023 - n_years}-01-01", "2022-12-31 23:00", freq="h", tz="UTC")
    years = np.unique(index.year)
    base = 7.5 * (1 + trend * np.arange(len(years)) / len(years))
    year_means = dict(zip(years, base * (1 + iav * rng.standard_normal(len(years))), strict=True))
    state = SessionState()
    state.reset()
    state.ensemble_df = pd.DataFrame(
        {"Timestamp": index, "Ensemble_Speed": np.array([year_means[y] for y in index.year])}
    )
    return state


def _selected(result: dict) -> dict:
    """Return the analysis_data row for the window the objective chose."""
    return next(row for row in result["analysis_data"] if row["start_year"] == result["optimal_start_year"])


# ---------------------------------------------------------------------------
# Verified correct
# ---------------------------------------------------------------------------


def test_historic_uncertainty_is_the_standard_error_of_the_annual_means():
    """VERIFIED: historic uncertainty = IAV / sqrt(n), the standard error of n annual means."""
    state = _annual_series_state(20)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")
    for row in result["analysis_data"]:
        expected = float(row["iav"]) / np.sqrt(float(row["n_years"]))
        assert float(row["historic_uncertainty"]) == pytest.approx(expected, rel=1e-12)


def test_combined_uncertainty_is_the_quadrature_of_its_two_terms():
    """VERIFIED: the objective combines the historic and climate terms in quadrature."""
    state = _annual_series_state(20)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")
    for row in result["analysis_data"]:
        expected = float(
            np.sqrt(float(row["historic_uncertainty"]) ** 2 + float(row["climate_uncertainty"]) ** 2)
        )
        assert float(row["combined_uncertainty"]) == pytest.approx(expected, rel=1e-12)
    assert result["min_uncertainty"] == pytest.approx(
        min(float(row["combined_uncertainty"]) for row in result["analysis_data"]), rel=1e-12
    )


def test_clipping_refuses_below_six_complete_annual_means():
    """VERIFIED: the documented refusal fires, and names the completeness threshold."""
    state = _annual_series_state(5)
    with pytest.raises(ValueError, match="complete annual means"):
        _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")


def test_ensemble_blends_time_series_not_summary_means():
    """VERIFIED: the blend operates record by record on aligned series."""
    rng = np.random.default_rng(4)
    index = pd.date_range("2021-01-01", periods=3000, freq="h", tz="UTC")
    truth = 7.5 + rng.normal(0, 2.0, 3000)
    high = truth + 1.0
    low = truth - 1.0

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_hub": truth}, index=index)
    state.ltc_results = {
        "high": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": high}), "metrics": {}},
        "low": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": low}), "metrics": {}},
    }
    result = _run_ensemble(state, "Spd_hub")
    blended = pd.DataFrame(state.ensemble_df)["Ensemble_Speed"].to_numpy()

    assert sum(result["weights"].values()) == pytest.approx(1.0)
    # Equal-and-opposite bias corrections mean the blend tracks the truth per record.
    assert np.corrcoef(blended, truth)[0, 1] > 0.999
    assert blended.mean() == pytest.approx(truth.mean(), abs=0.05)


# ---------------------------------------------------------------------------
# Findings — what reaches the reader
# ---------------------------------------------------------------------------


def test_clipping_reports_percent_denominated_mirrors_of_its_fractions():
    """F-46 (HIGH) — FIXED. Regression test: the unit must not be guessable.

    The finding: the response returns fractions (0.028, not 2.8), and the Results tab
    (`ClippingScenariosSection.tsx`) appended a literal ``%`` with no x100 — so a true
    2.8% combined uncertainty rendered as **"0.03%"** and a 3.9% IAV as **"0.04%"**.
    The Stepper's `ClippingView.tsx` scaled correctly, so the two views disagreed by
    100x on the same field, and the wrong one was the read-only aggregate report.

    Fixed on both sides: the front end now scales through a named `asPercent` helper,
    and the response carries `*_pct` mirrors so a consumer never has to infer the unit.
    """
    state = _annual_series_state(20)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")

    # The bare fractions are retained for compatibility.
    assert 0.0 < result["iav"] < 0.5
    assert 0.0 < result["min_uncertainty"] < 0.5

    # And each now has an unambiguous percent mirror.
    assert result["iav_pct"] == pytest.approx(result["iav"] * 100.0)
    assert result["min_uncertainty_pct"] == pytest.approx(result["min_uncertainty"] * 100.0)
    assert result["selected_iav_pct"] == pytest.approx(result["selected_iav"] * 100.0)
    assert result["iav_pct"] > 1.0  # i.e. reads as a percentage, not a fraction


def test_measured_iav_reaches_the_uncertainty_model():
    """F-47 (HIGH) — FIXED. Regression test: u_future must use the site's own IAV.

    The finding: clipping derived the site IAV and both views displayed it, but
    `clipping.py` performed no `state.*` assignment, so nothing downstream could find
    it. ``u_future = iav_pct / sqrt(20)`` therefore used a generic 6.0 hard-coded in
    three places including the front end's `defaultConfig.ts`, where it is a hand-typed
    field in a different tab from the one showing the measured value.

    The fix persists the clipping payload to `state.clipping_result` and has
    `_calculate_uncertainty` prefer `state.get_measured_iav_pct()` — the **selected
    window's** IAV, not the full series (F-49) — whenever the caller left `iav_pct` at
    its default. An explicit caller value still wins, and `inputs.iav_source` records
    which path was taken.
    """
    from server.tools.uncertainty import _calculate_uncertainty

    state = _annual_series_state(20)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")

    # The payload is now discoverable from session state.
    assert state.clipping_result is not None
    assert state.get_measured_iav_pct() == pytest.approx(result["selected_iav_pct"])

    measured = _calculate_uncertainty(state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0)
    assert measured["inputs"]["iav_source"] == "clipping_selected_window"
    assert measured["inputs"]["iav_pct"] == pytest.approx(result["selected_iav_pct"], abs=0.01)
    assert measured["components"]["future_variability"] == pytest.approx(
        result["selected_iav_pct"] / np.sqrt(20.0), abs=0.01
    )

    # An explicit caller value still takes precedence over the measured one.
    override = _calculate_uncertainty(
        state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0, iav_pct=9.5
    )
    assert override["inputs"]["iav_source"] == "caller"
    assert override["components"]["future_variability"] == pytest.approx(9.5 / np.sqrt(20.0), abs=0.005)

    # With no clipping run, the generic default is used and says so.
    fresh = SessionState()
    fresh.reset()
    generic = _calculate_uncertainty(fresh, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0)
    assert generic["inputs"]["iav_source"] == "default"
    assert generic["components"]["future_variability"] == pytest.approx(6.0 / np.sqrt(20.0), abs=0.005)


def test_years_dropped_by_the_objective_are_reported_separately():
    """F-48 — FIXED. Regression test: an objective exclusion must not look like a data gap.

    The finding: ``years_used`` listed every completeness-passing year, not the years
    inside the chosen window. On a 10-year series the window was 6 years while
    ``years_used`` listed all ten, ``years_excluded`` was empty and ``excluded_reason``
    blank — so four years dropped by the representativeness objective were
    indistinguishable from years the data actually supported.

    The fix reports `selected_years`, `selected_n_years` and
    `years_dropped_by_objective`, and `excluded_reason` now names the objective as a
    distinct cause from the completeness gate.
    """
    state = _annual_series_state(10)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")
    selected = _selected(result)

    assert len(result["years_used"]) == 10
    assert result["selected_n_years"] == selected["n_years"]
    assert result["selected_years"] == [
        y for y in result["years_used"] if y >= result["optimal_start_year"]
    ]
    assert len(result["years_dropped_by_objective"]) == 10 - selected["n_years"]

    # Completeness exclusions are still separate, and the reason now names the objective.
    assert result["years_excluded"] == []
    assert "objective" in result["excluded_reason"]
    assert "completeness" not in result["excluded_reason"]


def test_selected_window_iav_is_reported_alongside_the_full_series_iav():
    """F-49 — FIXED. Regression test: the window's own IAV must be available.

    The finding: top-level ``iav`` is ``full_iav`` over every completeness-passing year,
    while the selected window has a different IAV buried in ``analysis_data``. Measured:
    3.93% full-series against 2.83% for the chosen window — 28% higher — and the
    top-level figure was the one displayed and the one an analyst would copy into the
    uncertainty model.

    The fix adds `selected_iav` / `selected_iav_pct`, and `get_measured_iav_pct()`
    prefers them, so the uncertainty term now describes the period actually chosen.
    """
    state = _annual_series_state(10)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")
    selected = _selected(result)

    # The two remain genuinely different quantities; both are now reported.
    assert float(result["selected_iav"]) == pytest.approx(float(selected["iav"]), rel=1e-12)
    assert abs(float(result["selected_iav"]) / float(result["iav"]) - 1.0) > 0.10
    assert state.get_measured_iav_pct() == pytest.approx(float(selected["iav"]) * 100.0)


# ---------------------------------------------------------------------------
# Findings — the objective itself
# ---------------------------------------------------------------------------


def test_objective_can_select_a_window_far_shorter_than_the_record():
    """FINDING F-50: on a 10-year record the objective selected 6 years, and 5 is permitted.

    Candidate start years run to ``[:-(REFERENCE_WINDOW_YEARS - 1)]``, so the shortest
    candidate window is 5 years — not a long-term period by any published standard.

    There is also a structural bias. Every candidate ends at the final year, so every
    candidate *contains* the 5-year reference window, and the shortest candidate **is**
    that window: its ``lta_ratio`` is exactly 1.0, its deviation exactly 0, and its
    climate term pinned at the exact minimum. Short windows therefore start with an
    advantage on the climate term that they did not earn from the data.
    """
    state = _annual_series_state(10)
    result = _run_clipping_analysis(state, "Ensemble_Speed", "ensemble")
    selected = _selected(result)

    assert selected["n_years"] <= 6
    assert selected["n_years"] < 10

    shortest = result["analysis_data"][-1]
    assert shortest["n_years"] == REFERENCE_WINDOW_YEARS
    assert float(shortest["lta_ratio"]) == pytest.approx(1.0, abs=1e-12)
    floor_value = CLIMATE_FLOOR + CLIMATE_SCALE * float(np.exp(-1.0))
    assert float(shortest["climate_uncertainty"]) == pytest.approx(floor_value, rel=1e-9)
    # No candidate can beat it on the climate term.
    assert float(shortest["climate_uncertainty"]) == pytest.approx(
        min(float(row["climate_uncertainty"]) for row in result["analysis_data"]), rel=1e-9
    )
    assert "min_window_years" not in result


def test_climate_term_is_a_near_step_function_of_deviation():
    """FINDING F-51: `deviation**5` makes the climate penalty effectively binary.

    Measured across the deviation range, the climate term is within 3% of its floor
    until deviation reaches about 0.6, and **78% of the total rise happens above 0.9**:

        0.0 -> 0.008679    0.6 -> 0.009383    0.9 -> 0.018913
        0.4 -> 0.008765    0.8 -> 0.012697    1.0 -> 0.040000

    So for most real data the objective reduces to minimising IAV/sqrt(n) — "take the
    longest window" — until deviation crosses a threshold, at which point it flips
    hard. The fifth power is the most consequential choice in the formulation and,
    like the four coefficients Step 1 flagged, has no stated provenance.
    """
    log_term = float(np.log((CLIMATE_MAX - CLIMATE_FLOOR) / CLIMATE_SCALE))

    def climate(deviation: float) -> float:
        return float(CLIMATE_FLOOR + CLIMATE_SCALE * np.exp(-1.0 + (1.0 + log_term) * deviation**5))

    floor_value, ceiling = climate(0.0), climate(1.0)
    assert floor_value == pytest.approx(0.008679, abs=1e-6)
    assert ceiling == pytest.approx(CLIMATE_MAX, rel=1e-9)

    # Flat over most of the range.
    assert climate(0.6) / floor_value - 1.0 < 0.10
    # And most of the rise concentrated in the top decile.
    rise_above_0_9 = (ceiling - climate(0.9)) / (ceiling - floor_value)
    assert rise_above_0_9 > 0.6


def test_inverse_rmse_weighting_is_monotone_through_zero_rmse():
    """F-52 — FIXED. Regression test: a perfect fit must earn the blend, not be excluded.

    The bug: ``inverse_rmse = 0.0 if rmse <= 0.0 else 1.0 / rmse`` guarded the
    reciprocal in the wrong direction. A component reproducing the measured series
    exactly received weight **0.0** while its worse peer took the whole blend, yet a
    component with RMSE 1e-9 received ~1.0 — discontinuous at the one point where a
    component is beyond reproach.

    The fix floors the RMSE (relative to the worst component, with an absolute
    minimum) instead of zeroing the weight, so weighting stays monotone and continuous
    through zero.
    """
    rng = np.random.default_rng(7)
    n = 2000
    index = pd.date_range("2021-01-01", periods=n, freq="h", tz="UTC")
    truth = 7.5 + rng.normal(0, 2.0, n)
    poor = truth + rng.normal(0, 2.5, n)

    def weights_for(perfect_values: np.ndarray) -> dict[str, float]:
        state = SessionState()
        state.reset()
        state.timeseries_df = pd.DataFrame({"Spd_hub": truth}, index=index)
        state.ltc_results = {
            "candidate": {
                "df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": perfect_values}),
                "metrics": {},
            },
            "poor": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": poor}), "metrics": {}},
        }
        return _run_ensemble(state, "Spd_hub")["weights"]

    exact = weights_for(truth.copy())
    near = weights_for(truth + rng.normal(0, 1e-9, n))
    ordinary = weights_for(truth + rng.normal(0, 1.0, n))

    # A perfect fit now dominates, and lands where a near-perfect one does.
    assert exact["candidate"] > 0.99
    assert exact["candidate"] == pytest.approx(near["candidate"], abs=0.01)
    # And the ordering is still monotone in fit quality.
    assert exact["candidate"] > ordinary["candidate"] > 0.5
    for weights in (exact, near, ordinary):
        assert sum(weights.values()) == pytest.approx(1.0)


def test_inter_component_spread_is_never_computed():
    """FINDING F-53: the free model-uncertainty signal in the ensemble is discarded.

    The disagreement between LTC algorithms over the long-term period is a direct
    empirical estimate of MCP model uncertainty, and the uncertainty model carries no
    LTC-method term at all. ``_run_ensemble`` returns weights, blended metrics and now
    coverage — but no spread, standard deviation or range across components, even
    though it has every component series aligned on one index at that moment.

    Note what the bias correction already does: each component is shifted by its own
    mean error against the measured overlap, so a pure *level* disagreement between
    components is absorbed and contributes no spread. What survives is the **shape**
    disagreement — exactly the part a slope method and a variance-ratio method differ
    on (Step 8's F-38). Measured here with components of slope 1.15 and 0.90: a
    per-timestamp spread of **0.20 m/s, about 2.6% of the blended mean**. That is
    comparable to the whole MCP term the uncertainty model currently carries (0.9–1.5%),
    and it is discarded.
    """
    rng = np.random.default_rng(4)
    index = pd.date_range("2021-01-01", periods=3000, freq="h", tz="UTC")
    truth = 7.5 + rng.normal(0, 2.0, 3000)

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_hub": truth}, index=index)
    state.ltc_results = {
        "steep": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": 1.15 * truth}), "metrics": {}},
        "shallow": {"df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": 0.90 * truth}), "metrics": {}},
    }
    result = _run_ensemble(state, "Spd_hub")

    assert set(result["metrics"]) == {"rmse", "r2", "bias"}
    for absent in ("component_spread", "spread_std", "component_range", "model_uncertainty_pct"):
        assert absent not in result
        assert absent not in result["metrics"]

    # The signal is sitting in the saved frame, unused.
    frame = pd.DataFrame(state.ensemble_df)
    spread = frame[["steep", "shallow"]].std(axis=1, ddof=0)
    assert spread.mean() > 0.15
    assert spread.mean() / frame["Ensemble_Speed"].mean() > 0.02
