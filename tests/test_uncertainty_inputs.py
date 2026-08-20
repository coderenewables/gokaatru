"""Per-scenario uncertainty inputs — design doc §7.5.

`_run_scenario_pipeline` used to build its uncertainty call from constants:
`mcp_r_squared` 0.85, `concurrent_hours` 8760, `shear_std` 0.0. Across a single run
that is approximate; across a sweep it is fatal, because every scenario would report
near-identical uncertainty however well its own fit actually performed, and the
spread built on that column would carry no information at all.

These tests pin that each input is measured from the scenario's own artefacts, and
that a fallback — which is legitimate — is never silent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.uncertainty_inputs import (
    FALLBACK_CONCURRENT_HOURS,
    FALLBACK_MCP_R_SQUARED,
    derive_concurrent_hours,
    derive_mcp_r_squared,
    derive_measurement_height,
    derive_shear_std,
    derive_uncertainty_inputs,
    is_hub_interpolated,
    uncertainty_call_args,
)
from server.state.session import SessionState
from server.tools.uncertainty import _calculate_uncertainty

INDEX = pd.date_range("2021-01-01", periods=3000, freq="10min", tz="UTC")


def _state(
    heights: tuple[float, ...] = (40.0, 80.0, 100.0),
    hub_height_m: float = 120.0,
    shear_values: np.ndarray | None = None,
    ltc_metrics: dict | None = None,
    algorithm: str = "variance_ratio",
) -> SessionState:
    rng = np.random.default_rng(4)
    frame = pd.DataFrame(
        {f"Spd_{int(h)}m": 8.0 + rng.normal(0, 1.0, len(INDEX)) for h in heights},
        index=INDEX,
    )
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.sensor_mapping = {
        float(h): {"speed_col": f"Spd_{int(h)}m", "dir_col": None} for h in heights
    }
    state.set_hub_height_m(hub_height_m)
    if shear_values is not None:
        state.shear_timeseries_df = pd.DataFrame(
            {"shear_coefficient": shear_values}, index=INDEX[: len(shear_values)]
        )
    if ltc_metrics is not None:
        state.ltc_results[algorithm] = {"df": pd.DataFrame(), "metrics": ltc_metrics}
    return state


# ---------------------------------------------------------------------------
# Each input is measured, or says it was not
# ---------------------------------------------------------------------------


def test_r_squared_comes_from_the_scenarios_own_fit():
    state = _state(ltc_metrics={"r_squared": 0.612, "concurrent_points": 9000})
    derived = derive_mcp_r_squared(state, "variance_ratio")
    assert derived.value == pytest.approx(0.612)
    assert derived.derived is True
    assert "ltc_metrics:variance_ratio" in derived.source


def test_r_squared_falls_back_visibly_when_the_algorithm_stored_none():
    state = _state(ltc_metrics={"concurrent_points": 100})
    derived = derive_mcp_r_squared(state, "variance_ratio")
    assert derived.value == FALLBACK_MCP_R_SQUARED
    assert derived.derived is False
    assert "no finite r_squared" in derived.source


def test_negative_r_squared_is_floored_and_the_floor_is_recorded():
    """A fit worse than the series mean is real information, but not a usable R^2 here."""
    state = _state(ltc_metrics={"r_squared": -0.4})
    derived = derive_mcp_r_squared(state, "variance_ratio")
    assert derived.value == 0.0
    assert derived.derived is True
    assert "clamped from -0.4000" in derived.source


def test_concurrent_hours_come_from_the_actual_overlap():
    state = _state(ltc_metrics={"r_squared": 0.8, "concurrent_points": 14_600})
    derived = derive_concurrent_hours(state, "variance_ratio")
    assert derived.value == 14_600.0
    assert derived.derived is True


def test_concurrent_hours_fall_back_visibly():
    state = _state(ltc_metrics={"r_squared": 0.8})
    derived = derive_concurrent_hours(state, "variance_ratio")
    assert derived.value == FALLBACK_CONCURRENT_HOURS
    assert derived.derived is False


def test_shear_std_is_measured_from_the_scenarios_own_series():
    values = np.random.default_rng(2).normal(0.22, 0.07, 2000)
    state = _state(shear_values=values)
    derived = derive_shear_std(state)
    assert derived.value == pytest.approx(float(pd.Series(values).std(ddof=1)), rel=1e-9)
    assert derived.derived is True


def test_shear_std_falls_back_when_no_series_exists():
    derived = derive_shear_std(_state())
    assert derived.value == 0.0
    assert derived.derived is False
    assert "no usable shear timeseries" in derived.source


def test_measurement_height_defaults_to_the_top_sensor_and_follows_an_a2_selection():
    state = _state(heights=(40.0, 80.0, 100.0))
    assert derive_measurement_height(state).value == 100.0
    # A scenario extrapolating from a narrower reference set is levered from that set.
    assert derive_measurement_height(state, [40.0, 80.0]).value == 80.0


# ---------------------------------------------------------------------------
# Interpolation vs extrapolation
# ---------------------------------------------------------------------------


def test_hub_above_the_mast_is_extrapolated():
    assert is_hub_interpolated(_state(heights=(40.0, 100.0), hub_height_m=150.0)) is False


def test_hub_inside_a_profiling_lidar_is_interpolated():
    """A bracketing lidar carries far less vertical uncertainty, and must say so."""
    heights = tuple(float(h) for h in range(40, 280, 20))
    assert is_hub_interpolated(_state(heights=heights, hub_height_m=150.0)) is True


def test_interpolated_hub_reports_lower_vertical_uncertainty_than_extrapolated():
    """The flag has to reach the model, not just the record — this checks it bites."""
    shared = dict(
        measurement_uncertainty_pct=2.0,
        measurement_height_m=100.0,
        hub_height_m=150.0,
        shear_method="simple_power_law",
        mcp_r_squared=0.9,
        concurrent_hours=8760.0,
    )
    extrapolated = _calculate_uncertainty(_state(), **shared, is_interpolation=False)
    interpolated = _calculate_uncertainty(_state(), **shared, is_interpolation=True)
    assert (
        interpolated["components"]["vertical_extrapolation"]
        < extrapolated["components"]["vertical_extrapolation"]
    )


# ---------------------------------------------------------------------------
# The assembled input set
# ---------------------------------------------------------------------------


def test_derived_inputs_carry_provenance_for_every_measured_value():
    values = np.random.default_rng(3).normal(0.2, 0.05, 2000)
    state = _state(
        shear_values=values,
        ltc_metrics={"r_squared": 0.77, "concurrent_points": 12_000},
    )
    inputs = derive_uncertainty_inputs(state, "variance_ratio")

    assert inputs["mcp_r_squared"] == pytest.approx(0.77)
    assert inputs["concurrent_hours"] == 12_000.0
    assert inputs["shear_std"] > 0.0
    assert inputs["shear_method"] == "calculate_shear"

    provenance = inputs["provenance"]
    assert provenance["mcp_r_squared"]["derived"] is True
    assert provenance["concurrent_hours"]["derived"] is True
    assert provenance["shear_std"]["derived"] is True
    assert provenance["shear_source"] == "fitted"


def test_analyst_supplied_shear_takes_the_assumed_branch():
    """A supplied exponent has no measured dispersion and must not inherit a fitted one.

    Left implicit, a single-height scenario would borrow a sibling's fitted-shear
    uncertainty and under-report (design doc §3.A.1).
    """
    values = np.random.default_rng(3).normal(0.2, 0.05, 2000)
    state = _state(shear_values=values, ltc_metrics={"r_squared": 0.8})
    inputs = derive_uncertainty_inputs(state, "variance_ratio", shear_source="analyst_supplied")

    assert inputs["shear_method"] == "simple_power_law"
    assert inputs["shear_std"] == 0.0
    assert inputs["provenance"]["shear_source"] == "analyst_supplied"
    assert "assumed-shear branch" in inputs["provenance"]["shear_method_basis"]


def test_a_fitted_request_without_dispersion_degrades_to_assumed_shear():
    """Claiming a fitted profile with zero spread would understate the vertical term."""
    state = _state(ltc_metrics={"r_squared": 0.8})
    inputs = derive_uncertainty_inputs(state, "variance_ratio", shear_source="fitted")
    assert inputs["shear_method"] == "simple_power_law"
    assert "no dispersion measured" in inputs["provenance"]["shear_method_basis"]


def test_unknown_shear_source_is_rejected():
    with pytest.raises(ValueError, match="shear_source must be"):
        derive_uncertainty_inputs(_state(), "variance_ratio", shear_source="guessed")


def test_call_args_drop_provenance_and_drive_the_uncertainty_model():
    """The derived set must be directly usable by `_calculate_uncertainty`."""
    values = np.random.default_rng(3).normal(0.2, 0.05, 2000)
    state = _state(
        shear_values=values,
        ltc_metrics={"r_squared": 0.77, "concurrent_points": 12_000},
    )
    inputs = derive_uncertainty_inputs(state, "variance_ratio")
    args = uncertainty_call_args(inputs)

    assert "provenance" not in args
    result = _calculate_uncertainty(state, **args)
    assert result["total_uncertainty_pct"] > 0.0
    assert result["inputs"]["mcp_r_squared"] == pytest.approx(0.77)


def test_two_scenarios_with_different_fits_get_different_uncertainty():
    """The whole point: the uncertainty column must vary with the scenario's own fit.

    Under the old hardcoded block both of these produced the same MCP term.
    """
    good = _state(ltc_metrics={"r_squared": 0.95, "concurrent_points": 17_500})
    poor = _state(ltc_metrics={"r_squared": 0.55, "concurrent_points": 9_000})

    good_result = _calculate_uncertainty(
        good, **uncertainty_call_args(derive_uncertainty_inputs(good, "variance_ratio"))
    )
    poor_result = _calculate_uncertainty(
        poor, **uncertainty_call_args(derive_uncertainty_inputs(poor, "variance_ratio"))
    )

    assert good_result["components"]["mcp"] < poor_result["components"]["mcp"]
    assert good_result["total_uncertainty_pct"] < poor_result["total_uncertainty_pct"]
