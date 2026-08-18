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
    CUT_IN_MPS,
    CUT_OUT_MPS,
    GENERIC_RATED_KW,
    HOURS_PER_YEAR,
    energy_sensitivity_factor,
    indicative_aep_mwh,
    indicative_capacity_factor,
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


def test_power_curve_is_linear_between_bins_with_hard_cutoffs():
    """Linear interpolation on published bins is the IEC convention; a spline would overshoot."""
    assert turbine_power_kw(np.array([CUT_IN_MPS - 0.01]))[0] == 0.0
    assert turbine_power_kw(np.array([CUT_OUT_MPS + 0.01]))[0] == 0.0
    assert turbine_power_kw(np.array([7.5]))[0] == pytest.approx((1600.0 + 2300.0) / 2.0)
    assert turbine_power_kw(np.array([13.0]))[0] == pytest.approx(GENERIC_RATED_KW)


def test_indicative_aep_uses_leap_averaged_hours():
    """A turbine held at rated power all year must show a 100% capacity factor."""
    always_rated = np.full(5_000, 13.0)
    assert indicative_aep_mwh(always_rated) == pytest.approx(GENERIC_RATED_KW / 1000.0 * HOURS_PER_YEAR)
    assert indicative_capacity_factor(always_rated) == pytest.approx(1.0)


def test_production_curve_agrees_with_the_independent_oracle():
    """The production module must match the audit oracle, which shares no code with it.

    `tests/oracles.py` carries its own power curve and sensitivity implementation precisely
    so it can check this one. Agreement across a range of site means is the cross-check.
    """
    for mean_speed in (5.5, 7.5, 9.5):
        speed = _weibull_site(mean_speed)
        assert energy_sensitivity_factor(speed) == pytest.approx(
            oracles.energy_sensitivity_factor(speed), rel=1e-9
        )
        assert indicative_aep_mwh(speed) == pytest.approx(oracles.gross_aep_mwh(speed), rel=1e-9)


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

    guidance = block["how_to_convert"]
    speed_pct = float(result["total_uncertainty_pct"])
    energy_pct = block["factor"] * speed_pct

    # The arithmetic in the text is the arithmetic the numbers imply.
    assert f"{speed_pct:.2f}%" in guidance["steps"][0]
    assert f"{energy_pct:.2f}%" in guidance["steps"][2]
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
