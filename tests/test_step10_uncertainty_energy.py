"""Uncertainty propagation, energy conversion, end-to-end reconciliation — Step 10.

The plan's headline question was whether wind-speed-basis P-factors are ever applied
to energy. The answer is no, because the application computes no energy at all —
which relocates the problem rather than dissolving it: the P50/P75/P90/P99 it
publishes are speed exceedances carrying labels the wind industry reads as energy
exceedances.

This file reconciles the full pipeline end to end, measures the AEP sensitivity
factor on the long-term series the pipeline actually produces, and translates the
reported speed uncertainty onto an energy basis.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.state.session import SessionState
from server.tools.ensemble import _run_ensemble
from server.tools.extrapolation import _extrapolate_to_hub_height
from server.tools.ltc import _run_ltc_linear_least_squares, _run_ltc_variance_ratio
from server.tools.shear import _build_shear_table, _calculate_shear_timeseries
from server.tools.uncertainty import _calculate_uncertainty
from tests.oracles import (
    HOURS_PER_YEAR,
    WTG_RATED_KW,
    energy_sensitivity_factor,
    exceedance_factor,
    gross_aep_mwh,
    turbine_power_kw,
)

HUB_M = 150.0
LOWER_M, UPPER_M = 80.0, 100.0


# ---------------------------------------------------------------------------
# End-to-end fixture: the real pipeline, start to finish
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reconciled_run() -> dict:
    """Run shear -> hub -> LTC -> ensemble -> uncertainty on a synthetic but realistic site."""
    rng = np.random.default_rng(20260817)

    long_index = pd.date_range("2003-01-01", "2022-12-31 23:00", freq="h", tz="UTC")
    doy = long_index.dayofyear.to_numpy()
    hour = long_index.hour.to_numpy()
    seasonal = 1.0 + 0.18 * np.cos(2 * np.pi * (doy - 15) / 365.25)
    diurnal = 1.0 + 0.08 * np.cos(2 * np.pi * (hour - 15) / 24.0)
    years = np.unique(long_index.year)
    year_map = dict(zip(years, 1.0 + 0.06 * rng.standard_normal(len(years)), strict=True))
    inter_annual = np.array([year_map[y] for y in long_index.year])
    reference = np.clip(
        (6.6 / 0.88623) * rng.weibull(2.0, len(long_index)) * seasonal * diurnal * inter_annual,
        0.05,
        None,
    )

    meas_index = pd.date_range("2021-01-01", "2021-12-31 23:50", freq="10min", tz="UTC")
    ref_on_meas = pd.Series(reference, index=long_index).reindex(meas_index, method="ffill").to_numpy()
    m_hour = meas_index.hour.to_numpy()
    night = ((m_hour < 6) | (m_hour >= 19)).astype(float)
    alpha_true = np.clip(0.13 + 0.20 * night + rng.normal(0, 0.05, len(meas_index)), -0.2, 0.9)
    v100 = np.clip(1.06 * ref_on_meas + 0.35 + rng.normal(0, 0.85, len(meas_index)), 0.1, None)
    v80 = v100 * (LOWER_M / UPPER_M) ** alpha_true

    state = SessionState()
    state.reset()
    frame = pd.DataFrame({"Spd_80m": v80, "Spd_100m": v100}, index=meas_index)
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        LOWER_M: {"speed_col": "Spd_80m", "dir_col": None},
        UPPER_M: {"speed_col": "Spd_100m", "dir_col": None},
    }
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m": reference}, index=long_index)

    heights = json.dumps({"80": "Spd_80m", "100": "Spd_100m"})
    shear = _calculate_shear_timeseries(state, heights)
    _build_shear_table(state, "mean")
    _extrapolate_to_hub_height(state, HUB_M, "power_law")

    hub_col = f"Spd_{int(HUB_M)}m_hub"
    lls = _run_ltc_linear_least_squares(state, hub_col, hub_col)
    _run_ltc_variance_ratio(state, hub_col, hub_col)
    ensemble = _run_ensemble(state, hub_col)
    uncertainty = _calculate_uncertainty(
        state,
        measurement_uncertainty_pct=3.0,
        measurement_height_m=UPPER_M,
        hub_height_m=HUB_M,
        shear_method="calculate_shear",
        mcp_r_squared=float(lls["metrics"]["r_squared"]),
        concurrent_hours=float(lls["metrics"]["concurrent_points"]),
        algorithm="linear_least_squares",
        iav_pct=6.0,
        shear_std=float(shear["std_shear"]),
    )

    long_term = pd.DataFrame(state.ensemble_df)["Ensemble_Speed"].to_numpy(dtype=float)
    long_term = long_term[np.isfinite(long_term)]
    return {
        "state": state,
        "shear": shear,
        "lls": lls,
        "ensemble": ensemble,
        "uncertainty": uncertainty,
        "long_term": long_term,
        "hub_col": hub_col,
    }


def test_pipeline_reconciles_end_to_end(reconciled_run: dict) -> None:
    """The full chain must run and each stage's output must be reproducible by hand."""
    state = reconciled_run["state"]
    long_term = reconciled_run["long_term"]

    # Hub column: the power law applied to the 100 m series with the table alpha.
    hub = state.timeseries_df[reconciled_run["hub_col"]].to_numpy(dtype=float)
    v100 = state.timeseries_df["Spd_100m"].to_numpy(dtype=float)
    v80 = state.timeseries_df["Spd_80m"].to_numpy(dtype=float)
    table = state.shear_table.to_numpy(dtype=float)
    index = state.timeseries_df.index
    expected_alpha = table[index.month.to_numpy() - 1, index.hour.to_numpy()]

    implied_from_100 = np.log(hub / v100) / np.log(HUB_M / UPPER_M)
    valid = np.isfinite(implied_from_100)
    matches_100 = np.isclose(implied_from_100[valid], expected_alpha[valid], atol=1e-9)

    # Essentially every record reconciles exactly against the 100 m reference.
    assert matches_100.mean() > 0.9999

    # The residue is Step 5's F-24 firing in a real run: where the 100 m sensor
    # fails extrapolation's own `> 0.1 m/s` mask, `_nearest_indices` silently drops
    # to the 80 m sensor, so those records carry a 150/80 = 1.88x lever instead of
    # 1.50x. They reconcile only against the lower reference, and nothing in the
    # response distinguishes them from the rest of the series.
    residue = np.where(valid)[0][~matches_100]
    if residue.size:
        implied_from_80 = np.log(hub[residue] / v80[residue]) / np.log(HUB_M / LOWER_M)
        assert np.allclose(implied_from_80, expected_alpha[residue], atol=1e-9)
        assert "reference_height_m" not in reconciled_run["shear"]

    # Long-term series spans the full reference period at hourly resolution.
    assert len(long_term) == pytest.approx(20 * HOURS_PER_YEAR, rel=0.01)
    assert 7.0 < long_term.mean() < 9.5

    # The ensemble is a weighted blend of its components, so it must sit between them.
    weights = reconciled_run["ensemble"]["weights"]
    assert set(weights) == {"linear_least_squares", "variance_ratio"}
    assert sum(weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The headline question
# ---------------------------------------------------------------------------


def test_no_aep_or_power_curve_exists_anywhere_in_the_pipeline():
    """FINDING F-29 (HIGH): there is no energy yield calculation — only resource metrics.

    ``compute_energy_metrics`` returns wind power density (0.5*rho*v^3, W/m2) and a
    directional energy split. There is no power curve, no turbine, no AEP, no
    capacity factor and no loss model anywhere in the executable pipeline.
    ``windkit_wtg_power`` exists as a WindKit passthrough but no stage calls it.

    So the tool characterises the *resource* and stops short of the *yield*, while
    publishing P50/P75/P90/P99 — quantities that in wind resource assessment name
    energy exceedances. The gap is what F-28 measures.
    """
    from server.core.executor import _tool_registry
    from server.tools.advanced_analysis import _compute_energy_metrics

    registry = _tool_registry()
    energy_tools = [
        name
        for name in registry
        if any(token in name.lower() for token in ("aep", "capacity_factor", "annual_energy", "yield"))
    ]
    assert energy_tools == []

    index = pd.date_range("2021-01-01", periods=8760, freq="h", tz="UTC")
    rng = np.random.default_rng(2)
    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {"Spd_100m": 8.0 * rng.weibull(2.0, len(index))}, index=index
    )
    result = _compute_energy_metrics(state, "Spd_100m")

    assert "wind_power_density_w_m2" in result
    assert "aep_mwh" not in result
    assert "capacity_factor" not in result
    assert "power_curve" not in result


def test_p_factors_declare_a_wind_speed_basis(reconciled_run: dict) -> None:
    """F-28 (HIGH) — PARTLY FIXED. The exceedance factors now state their basis.

    The finding: ``p_factors`` is built from a wind-speed uncertainty with normal
    quantiles, and in wind resource assessment P50/P75/P90 name *energy* exceedances.
    The one place they were applied labelled them honestly ("P75 speed" traces), but
    the scenario snapshot and comparison report emitted bare ``p50``/``p90`` with unit
    "-" and nothing anywhere named the basis.

    Fixed: ``basis: "wind_speed"`` now appears both on the result and inside
    ``p_factors``, with a note stating that converting to energy requires the site's
    energy sensitivity factor first.

    Still open (F-29/F-34): the application computes no AEP, so it cannot supply the
    energy-basis equivalents itself, and the component list carries no energy-specific
    terms.
    """
    uncertainty = reconciled_run["uncertainty"]
    factors = uncertainty["p_factors"]
    u_speed = float(uncertainty["total_uncertainty_pct"])

    assert factors["p90"] == pytest.approx(1.0 - 1.282 * u_speed / 100.0, abs=1e-4)
    assert uncertainty["basis"] == "wind_speed"
    assert factors["basis"] == "wind_speed"
    assert "energy" in factors["note"].lower()

    # The energy basis itself is still absent, because no AEP exists to build it from.
    assert "energy_sensitivity_factor" not in uncertainty
    assert "total_uncertainty_energy_pct" not in uncertainty


def test_energy_sensitivity_factor_translates_speed_uncertainty_to_energy(reconciled_run: dict) -> None:
    """Compute S on the final long-term series and convert the reported uncertainty.

    S = d(ln AEP)/d(ln U) measured by central difference on the 20-year ensemble
    series the pipeline produced, through a representative 4.2 MW / 150 m turbine.
    The reported speed uncertainty times S is the energy uncertainty that the
    P-values should actually be built from.
    """
    long_term = reconciled_run["long_term"]
    u_speed = float(reconciled_run["uncertainty"]["total_uncertainty_pct"])

    aep = gross_aep_mwh(long_term)
    s_factor = energy_sensitivity_factor(long_term)
    u_energy = s_factor * u_speed

    # S must be a genuine elasticity, verified against direct finite perturbation.
    for pct in (-5.0, -1.0, 1.0, 5.0):
        perturbed = gross_aep_mwh(long_term * (1.0 + pct / 100.0))
        implied = (perturbed / aep - 1.0) / (pct / 100.0)
        assert implied == pytest.approx(s_factor, abs=0.08)

    assert 1.0 < s_factor < 1.5           # this site sits partly in the rated region
    assert u_energy > u_speed             # energy is always the more uncertain basis
    assert u_energy == pytest.approx(u_speed * s_factor, rel=1e-12)

    # The exceedance band is materially wider on the energy basis.
    p90_energy = exceedance_factor(u_energy, "p90")
    p90_speed = exceedance_factor(u_speed, "p90")
    assert p90_energy < p90_speed
    assert (1.0 - p90_energy) / (1.0 - p90_speed) == pytest.approx(s_factor, rel=1e-9)


def test_sensitivity_factor_is_site_specific_not_a_constant(reconciled_run: dict) -> None:
    """S cannot be a fixed multiplier: it falls as the site climbs the power curve.

    Measured on the same long-term series rescaled to different mean speeds, S runs
    from about 2.1 at 5.5 m/s to about 0.6 at 10.5 m/s. Any fix must compute S from
    the site's own distribution and turbine, not apply a rule-of-thumb factor.
    """
    long_term = reconciled_run["long_term"]
    base = long_term.mean()

    factors = {
        target: energy_sensitivity_factor(long_term * (target / base))
        for target in (5.5, 7.5, 10.5)
    }

    assert factors[5.5] > 2.0
    assert factors[10.5] < 0.8
    assert factors[5.5] > factors[7.5] > factors[10.5]


# ---------------------------------------------------------------------------
# Uncertainty model internals
# ---------------------------------------------------------------------------


def test_concurrent_months_disclosure_contradicts_the_math_it_reports():
    """FINDING F-30: the reported input is not the input used.

    ``u_mcp`` uses ``min(concurrent_months, 12)`` but ``inputs.concurrent_months``
    reports the uncapped value. A five-year concurrent period is disclosed as
    60 months while the arithmetic used 12, so a reviewer cannot reproduce the
    number from the response.
    """
    state = SessionState()
    state.reset()
    result = _calculate_uncertainty(state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 60 * 730.0)

    assert result["inputs"]["concurrent_months"] == pytest.approx(60.0)
    expected_capped = (3.0 / math.sqrt(12.0)) + (1.0 - 0.95) * 4.0
    assert result["components"]["mcp"] == pytest.approx(expected_capped, abs=0.01)

    # Now reproducible: the value the arithmetic used, and the cap, travel with it.
    assert result["inputs"]["concurrent_months_used"] == pytest.approx(12.0)
    assert result["inputs"]["concurrent_months_cap"] == pytest.approx(12.0)


def test_mcp_sampling_cap_is_visible_and_movable():
    """F-31 (MEDIUM) — FIXED. The 12-month cap is a parameter, and reports what it withheld.

    The bug: ``u_mcp`` gave no credit beyond twelve months and nothing said so. Measured at
    R2 = 0.95, it was 1.47% at six months, 1.12% at twelve, and exactly 1.12% at eighteen,
    twenty-four, thirty-six and sixty — a three-year campaign earned nothing over a one-year
    campaign, with no way to tell whether that was deliberate.

    The cap itself is kept as the default: beyond about a year the limit on an MCP is the
    stability of the transfer function, not the number of concurrent pairs, so the extra
    1/sqrt(n) credit would not be real. What changed is that the cap is now a parameter, the
    uncapped figure is reported beside the capped one, and a campaign longer than the cap
    gets a warning naming the difference.
    """
    state = SessionState()
    state.reset()

    def result_for(months: float, **kwargs: float) -> dict:
        return _calculate_uncertainty(
            state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, months * 730.0, **kwargs
        )

    def u_mcp(months: float, **kwargs: float) -> float:
        return float(result_for(months, **kwargs)["components"]["mcp"])

    # The default behaviour is unchanged.
    assert u_mcp(6) > u_mcp(12)
    assert u_mcp(12) == u_mcp(24) == u_mcp(60)

    # What the cap withheld is now a number on the page.
    long_campaign = result_for(36)
    cap = long_campaign["mcp_sampling_cap"]
    assert cap["cap_applied"] is True
    assert cap["months_available"] == pytest.approx(36.0, abs=0.1)
    assert cap["u_mcp_uncapped_pct"] < cap["u_mcp_pct"]
    assert cap["credit_withheld_pct"] > 0.3
    assert "concurrent months" in cap["note"]
    assert "36.0 concurrent months were supplied" in cap["warning"]

    # And the cap can be moved when the analyst judges the extra credit defensible.
    assert u_mcp(36, concurrent_months_cap=36.0) < u_mcp(36)
    assert u_mcp(36, concurrent_months_cap=36.0) == pytest.approx(
        cap["u_mcp_uncapped_pct"], abs=0.01
    )
    # A one-year campaign has nothing withheld and says so.
    assert result_for(12)["mcp_sampling_cap"]["cap_applied"] is False

    with pytest.raises(ValueError, match="concurrent_months_cap must be at least 1"):
        result_for(12, concurrent_months_cap=0.5)


def test_project_life_is_a_parameter():
    """F-32 (MEDIUM) — FIXED. The operating life is the project's fact, not the tool's.

    ``u_future = iav / sqrt(project_life_years)`` hardcoded a 20-year life. A 15-year life
    gives 1.55% for the same 6% IAV where 20 years gives 1.34%, and the constant was neither
    a parameter nor derivable from anything the caller supplied.

    Still open by design: the sqrt(n) assumes annual means are independent, which ignores
    inter-annual persistence and any climate trend. That is a modelling choice rather than a
    missing parameter, and it is recorded in the README's known limitations.
    """
    state = SessionState()
    state.reset()

    def u_future(**kwargs: float) -> float:
        return float(
            _calculate_uncertainty(
                state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0, iav_pct=6.0, **kwargs
            )["components"]["future_variability"]
        )

    assert u_future() == pytest.approx(6.0 / math.sqrt(20.0), abs=0.005)
    assert u_future(project_life_years=15.0) == pytest.approx(6.0 / math.sqrt(15.0), abs=0.005)
    assert u_future(project_life_years=15.0) > u_future()

    reported = _calculate_uncertainty(
        state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0,
        iav_pct=6.0, project_life_years=15.0,
    )
    assert reported["inputs"]["project_life_years"] == pytest.approx(15.0)

    with pytest.raises(ValueError, match="project_life_years must be positive"):
        u_future(project_life_years=0.0)


def test_total_uncertainty_reports_the_cost_of_its_independence_assumption():
    """F-33 (MEDIUM) — FIXED. Quadrature stays the default; its optimism is quantified.

    RSS treats all four components as independent, but measurement, vertical extrapolation
    and MCP all derive from the same measured series — a mast that reads low reads low in
    every one of them. At rho = 0.5 among those three the total is roughly 30% higher, and
    that flows straight into every P-value.

    Zero correlation is what published RSS practice assumes and what this model has always
    done, so it remains the default and existing results are unchanged. What is new is that
    the total at rho = 0.5 travels with every response, and the correlation is settable.
    """
    state = SessionState()
    state.reset()
    result = _calculate_uncertainty(
        state, 3.0, 100.0, 150.0, "calculate_shear", 0.95, 8760.0, shear_std=0.11
    )
    components = {k: float(v) for k, v in result["components"].items()}

    quadrature = math.sqrt(sum(v**2 for v in components.values()))
    assert float(result["total_uncertainty_pct"]) == pytest.approx(quadrature, abs=0.01)

    combination = result["combination"]
    assert combination["method"] == "root_sum_square"
    assert combination["component_correlation"] == 0.0
    assert combination["correlated_components"] == ["measurement", "vertical_extrapolation", "mcp"]
    assert combination["sensitivity_ratio"] > 1.25
    assert "independence is optimistic" in combination["note"]

    # The reported sensitivity is what setting the correlation actually produces.
    correlated = _calculate_uncertainty(
        state, 3.0, 100.0, 150.0, "calculate_shear", 0.95, 8760.0,
        shear_std=0.11, component_correlation=0.5,
    )
    assert float(correlated["total_uncertainty_pct"]) == pytest.approx(
        float(combination["total_at_rho_0.5_pct"]), abs=0.01
    )
    assert float(correlated["total_uncertainty_pct"]) > float(result["total_uncertainty_pct"])

    with pytest.raises(ValueError, match="component_correlation must lie between"):
        _calculate_uncertainty(
            state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0, component_correlation=1.5
        )


def test_uncertainty_has_no_energy_specific_components(reconciled_run: dict) -> None:
    """FINDING F-34: the component list is complete for speed and empty for energy.

    An energy uncertainty needs terms the model does not carry at all: power-curve
    uncertainty, wake and array losses, availability, electrical losses, flow
    modelling from the mast to the turbine positions, and air-density uncertainty.
    Every one of them would raise the energy uncertainty above S x u_speed, so the
    translated figure is a floor, not an estimate.
    """
    components = reconciled_run["uncertainty"]["components"]
    assert set(components) == {"measurement", "vertical_extrapolation", "mcp", "future_variability"}
    for absent in ("power_curve", "wake_losses", "availability", "electrical_losses", "flow_modelling", "air_density"):
        assert absent not in components


def test_ensemble_weights_label_their_rmse_basis(reconciled_run: dict) -> None:
    """F-35 (MEDIUM) — FIXED. The blend now declares which error each weight rests on.

    ``run_ensemble`` returned weights with no per-component note of whether the RMSE behind
    each one was held out or in sample, so the documented mixed basis could not be audited
    from the tool's own output. Only XGBoost reports an out-of-sample error, and in-sample
    error is systematically lower, so a mixed blend tilts for reasons unrelated to skill.
    """
    ensemble = reconciled_run["ensemble"]
    assert {"status", "weights", "metrics", "component_coverage", "result_file"} <= set(ensemble)

    assert set(ensemble["weight_basis"]) == set(ensemble["weights"])
    # This reconciliation uses two linear methods, so the basis is uniform and honest
    # about being in-sample.
    assert set(ensemble["weight_basis"].values()) == {"concurrent_overlap_in_sample"}
    assert ensemble["weight_basis_is_mixed"] is False
    assert "weight_basis_warning" not in ensemble
    assert "systematically lower" in ensemble["weight_basis_note"]
    assert set(ensemble["weight_rmse"]) == set(ensemble["weights"])


# ---------------------------------------------------------------------------
# Energy conversion sanity — the oracle itself
# ---------------------------------------------------------------------------


def test_power_curve_is_linear_between_bins_with_hard_cutoffs():
    """The energy oracle must interpolate linearly and respect cut-in/cut-out."""
    assert turbine_power_kw(np.array([2.99]))[0] == 0.0
    assert turbine_power_kw(np.array([25.01]))[0] == 0.0
    midpoint = turbine_power_kw(np.array([7.5]))[0]
    assert midpoint == pytest.approx((1600.0 + 2300.0) / 2.0)
    assert turbine_power_kw(np.array([13.0]))[0] == pytest.approx(WTG_RATED_KW)


def test_capacity_factor_uses_leap_averaged_hours():
    """A turbine held at rated power all year must show a 100% capacity factor."""
    always_rated = np.full(10_000, 13.0)
    aep = gross_aep_mwh(always_rated)
    assert aep == pytest.approx(WTG_RATED_KW / 1000.0 * HOURS_PER_YEAR)
    assert aep / (WTG_RATED_KW / 1000.0 * HOURS_PER_YEAR) == pytest.approx(1.0)
