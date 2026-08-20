"""Wind-speed-to-energy sensitivity factor and its conversion guidance.

GoKaatru reports uncertainty on a wind-speed basis. This covers the factor that turns it
into an energy uncertainty — measured on the session's own long-term distribution against
a generic power curve — and the guidance that travels with it.

No energy uncertainty is published as a project number, and no energy-specific uncertainty
components are modelled; see `docs/audit/10-uncertainty-energy.md` (F-34).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.powercurve import (
    GENERIC_3MW,
    GENERIC_4_2MW,
    GENERIC_RATED_KW,
    HOURS_PER_YEAR,
    energy_sensitivity_factor,
    get_power_curve,
    indicative_aep_mwh,
    indicative_capacity_factor,
    power_curve_names,
    turbine_power_kw,
)
from server.state.session import SessionState
from server.tools.uncertainty import (
    _calculate_uncertainty,
    _compute_energy_sensitivity,
    _long_term_speed_series,
)
from tests import oracles


def _weibull_site(mean_speed: float, n: int = 100_000, seed: int = 11) -> np.ndarray:
    """Return a Weibull(k=2) series with the requested mean, as a site distribution."""
    rng = np.random.default_rng(seed)
    return (mean_speed / 0.88623) * rng.weibull(2.0, n)


def _state_with_ensemble(speed: np.ndarray) -> SessionState:
    """Return a session whose ensemble output is the given long-term series."""
    index = pd.date_range("2003-01-01", periods=len(speed), freq="h", tz="UTC")
    state = SessionState()
    state.reset()
    state.ensemble_df = pd.DataFrame({"Timestamp": index, "Ensemble_Speed": speed})
    return state


# ---------------------------------------------------------------------------
# The generic power curve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("curve", [GENERIC_3MW, GENERIC_4_2MW])
def test_power_curve_is_linear_between_bins_with_hard_cutoffs(curve):
    """Linear interpolation on published bins is the IEC convention; a spline would overshoot."""
    assert turbine_power_kw(np.array([curve.cut_in_mps - 0.01]), curve)[0] == 0.0
    assert turbine_power_kw(np.array([curve.cut_out_mps + 0.01]), curve)[0] == 0.0
    assert turbine_power_kw(np.array([13.0]), curve)[0] == pytest.approx(curve.rated_kw)
    # Midway between two published bins is the mean of them, on every curve.
    midpoint = turbine_power_kw(np.array([7.5]), curve)[0]
    assert midpoint == pytest.approx((curve.power_kw[7] + curve.power_kw[8]) / 2.0)


def test_default_curve_is_the_generic_three_megawatt_machine():
    """The engine reports AEP on a generic 3 MW machine (design doc S7.12, S11)."""
    assert get_power_curve().name == "generic-3.0MW-130m-IIA"
    assert GENERIC_RATED_KW == 3000.0
    assert set(power_curve_names()) == {"generic-3.0MW-130m-IIA", "generic-4.2MW-150m-IIA"}
    # Specific power places it in the modern onshore class it claims.
    assert GENERIC_3MW.specific_power_w_m2 == pytest.approx(226.0, abs=1.0)


def test_unknown_power_curve_is_rejected_by_name():
    with pytest.raises(ValueError, match="power curve must be one of"):
        get_power_curve("vestas-v150")


@pytest.mark.parametrize("curve", [GENERIC_3MW, GENERIC_4_2MW])
def test_implied_cp_peaks_in_the_expected_band(curve):
    """A curve with a plausible shape peaks near Cp 0.4-0.45 in the 6-9 m/s range.

    This is what makes the curve generic-but-physical rather than made up: Betz caps
    Cp at 0.593 and a real machine of this class runs a little over two-thirds of it.
    """
    area = np.pi * (curve.rotor_diameter_m / 2.0) ** 2
    speeds = np.arange(5.0, 10.0)
    available_kw = 0.5 * 1.225 * area * speeds**3 / 1000.0
    cp = turbine_power_kw(speeds, curve) / available_kw
    assert cp.max() == pytest.approx(0.41, abs=0.04)
    assert cp.max() < 0.593  # Betz


@pytest.mark.parametrize("curve", [GENERIC_3MW, GENERIC_4_2MW])
def test_indicative_aep_uses_leap_averaged_hours(curve):
    """A turbine held at rated power all year must show a 100% capacity factor."""
    always_rated = np.full(5_000, 13.0)
    assert indicative_aep_mwh(always_rated, curve) == pytest.approx(
        curve.rated_kw / 1000.0 * HOURS_PER_YEAR
    )
    assert indicative_capacity_factor(always_rated, curve) == pytest.approx(1.0)


def test_production_curve_agrees_with_the_independent_oracle():
    """The production module must match the audit oracle, which shares no code with it.

    `tests/oracles.py` carries its own power curve and sensitivity implementation precisely
    so it can check this one. Agreement across a range of site means is the cross-check.
    """
    for curve_name in (oracles.CURVE_3MW, oracles.CURVE_4_2MW):
        for mean_speed in (5.5, 7.5, 9.5):
            speed = _weibull_site(mean_speed)
            assert energy_sensitivity_factor(speed, curve=curve_name) == pytest.approx(
                oracles.energy_sensitivity_factor(speed, curve=curve_name), rel=1e-9
            )
            assert indicative_aep_mwh(speed, curve_name) == pytest.approx(
                oracles.gross_aep_mwh(speed, curve_name), rel=1e-9
            )


def test_sensitivity_depends_on_the_machine_which_is_why_one_curve_must_serve_both_uses():
    """S differs between machines at the same site, so AEP and S must share a curve.

    Reporting energy off one curve while converting speed uncertainty with S from
    another would describe two different turbines (design doc S7.12).

    The measured gap between these two curves is small - about 0.018 at an 8.5 m/s
    site - because 226 and 238 W/m2 are similar specific powers. It is not negligible
    against a factor reported to four decimal places, and a machine of genuinely
    different specific power would diverge much further. Note also that the sign
    flips below roughly 6 m/s, where neither curve has meaningful time at rated
    power, so this asserts the ordering only at a windy site.
    """
    speed = _weibull_site(8.5)
    s_3mw = energy_sensitivity_factor(speed, curve=GENERIC_3MW)
    s_4_2mw = energy_sensitivity_factor(speed, curve=GENERIC_4_2MW)

    # Above rated-power onset the smaller machine spends more hours flat-topped, so
    # its elasticity is the lower of the two.
    assert s_3mw < s_4_2mw
    assert abs(s_3mw - s_4_2mw) == pytest.approx(0.018, abs=0.005)

    # At a low-wind site almost no hours reach rated power on either curve and the
    # ordering is not guaranteed - the shapes differ more than the ratings do.
    calm = _weibull_site(5.5)
    assert energy_sensitivity_factor(calm, curve=GENERIC_3MW) == pytest.approx(2.11, abs=0.02)
    assert energy_sensitivity_factor(calm, curve=GENERIC_4_2MW) == pytest.approx(2.10, abs=0.02)


# ---------------------------------------------------------------------------
# The sensitivity factor
# ---------------------------------------------------------------------------


def test_sensitivity_is_a_genuine_elasticity():
    """S must reproduce a direct finite perturbation of the series, not a rule of thumb."""
    speed = _weibull_site(7.5)
    sensitivity = energy_sensitivity_factor(speed)
    baseline = indicative_aep_mwh(speed)

    for pct in (-5.0, -1.0, 1.0, 5.0):
        perturbed = indicative_aep_mwh(speed * (1.0 + pct / 100.0))
        implied = (perturbed / baseline - 1.0) / (pct / 100.0)
        assert implied == pytest.approx(sensitivity, abs=0.1)


def test_sensitivity_falls_as_the_site_climbs_the_power_curve():
    """S is not a constant: more hours at rated power means extra speed buys less energy.

    Measured on the generic curve: about 2.1 at a 5.5 m/s site down to about 0.6 at
    10.5 m/s. Any fixed multiplier would be wrong in both directions.
    """
    factors = {mean: energy_sensitivity_factor(_weibull_site(mean)) for mean in (5.5, 7.5, 10.5)}

    assert factors[5.5] == pytest.approx(2.1, abs=0.15)
    assert factors[7.5] == pytest.approx(1.37, abs=0.15)
    assert factors[10.5] == pytest.approx(0.64, abs=0.15)
    assert factors[5.5] > factors[7.5] > factors[10.5]


# ---------------------------------------------------------------------------
# Integration with the uncertainty response
# ---------------------------------------------------------------------------


def test_uncertainty_response_carries_the_factor_and_the_conversion():
    """The speed-basis result must ship the factor and the arithmetic beside it."""
    state = _state_with_ensemble(_weibull_site(7.6))
    result = _calculate_uncertainty(state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0)

    assert result["basis"] == "wind_speed"
    block = result["energy_sensitivity"]
    assert block["available"] is True
    assert block["measured_on"] == "ensemble"
    assert 1.0 < block["factor"] < 1.8
    assert block["power_curve"]["basis"] == "generic"
    # AEP and S come from one machine, named in the response beside both.
    assert block["power_curve"]["name"] == "generic-3.0MW-130m-IIA"
    assert block["indicative_gross_aep_mwh"] > 0.0

    guidance = block["how_to_convert"]
    speed_pct = float(result["total_uncertainty_pct"])
    energy_pct = block["factor"] * speed_pct

    # The arithmetic in the text is the arithmetic the numbers imply. Compared
    # numerically rather than by string match: `factor` is rounded to 4 dp while the
    # guidance text is rendered from the unrounded value, so the last displayed digit
    # can legitimately differ by one.
    assert f"{speed_pct:.2f}%" in guidance["steps"][0]
    quoted = float(guidance["steps"][2].split("The result, ")[1].split("%")[0])
    assert quoted == pytest.approx(energy_pct, abs=0.01)
    # And the caveats a reader needs are all present.
    assert "do not" in guidance["do_not"].lower()
    assert "floor" in guidance["not_included"]
    assert "turbine-specific" in guidance["factor_is_specific"]

    # No energy uncertainty is published as a number of its own.
    assert "total_uncertainty_energy_pct" not in result
    assert "energy" not in result["components"]


def test_sensitivity_is_unavailable_and_says_so_before_the_long_term_stages_run():
    """Without a long-term series there is nothing to measure S on, and the response says why."""
    state = SessionState()
    state.reset()
    result = _calculate_uncertainty(state, 3.0, 100.0, 150.0, "simple_power_law", 0.95, 8760.0)

    block = result["energy_sensitivity"]
    assert block["available"] is False
    assert "LTC" in block["reason"]
    assert "must not be applied" in block["reason"]

    with pytest.raises(ValueError, match="No long-term corrected series"):
        _compute_energy_sensitivity(state)


def test_the_series_used_follows_the_pipeline_preference_order():
    """Ensemble first, then any LTC result, then the measured hub column."""
    index = pd.date_range("2003-01-01", periods=5_000, freq="h", tz="UTC")
    speed = _weibull_site(7.5, n=len(index))

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame({"Spd_150m_hub": speed}, index=index)
    state.set_hub_height_m(150.0)
    _series, source = _long_term_speed_series(state)
    assert source == "measured:Spd_150m_hub"

    state.ltc_results["variance_ratio"] = {
        "df": pd.DataFrame({"Timestamp": index, "corrected_wind_speed": speed}),
        "metrics": {},
    }
    _series, source = _long_term_speed_series(state)
    assert source == "ltc:variance_ratio"

    state.ensemble_df = pd.DataFrame({"Timestamp": index, "Ensemble_Speed": speed})
    _series, source = _long_term_speed_series(state)
    assert source == "ensemble"


def test_standalone_tool_works_a_supplied_uncertainty_through_the_conversion():
    """`compute_energy_sensitivity` must convert whatever speed uncertainty it is handed."""
    state = _state_with_ensemble(_weibull_site(7.6))
    result = _compute_energy_sensitivity(state, speed_uncertainty_pct=5.0)

    assert result["status"] == "ok"
    expected_energy = result["factor"] * 5.0
    assert f"{expected_energy:.2f}%" in result["how_to_convert"]["steps"][2]
    assert "5.00%" in result["how_to_convert"]["steps"][0]
