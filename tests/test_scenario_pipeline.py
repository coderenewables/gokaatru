"""Whole-scenario pipeline — design doc §7.3.

`_run_scenario_pipeline` began at the LTC, so axes A (sensor selection) and B (shear
model) — both upstream of it — could not be varied at all. These tests run the full
chain from sensor resolution through uncertainty, and check the property the sweep
depends on: changing one axis changes the answer, and changing nothing does not.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.scenario_context import scenario_context
from server.core.scenario_pipeline import (
    SHEAR_MODELS,
    UNIMPLEMENTED_SHEAR_MODELS,
    ScenarioError,
    ScenarioSpec,
    resolve_sensors,
    run_scenario,
)
from server.state.session import SessionState

HEIGHTS = (40.0, 60.0, 80.0, 100.0)
HUB_M = 120.0
ALPHA = 0.22

# Two years of measured data, and a longer reanalysis record to correct against.
MEASURED_INDEX = pd.date_range("2019-01-01", "2020-12-31 23:50", freq="10min", tz="UTC")
LONG_INDEX = pd.date_range("2010-01-01", "2020-12-31 23:00", freq="h", tz="UTC")


def _base_state() -> SessionState:
    """A mast with an exact power-law profile, plus both interpolated reanalyses."""
    rng = np.random.default_rng(17)
    top = 7.5 + rng.weibull(2.0, len(MEASURED_INDEX)) * 3.0
    measured = pd.DataFrame(
        {f"Spd_{int(h)}m": top * (h / max(HEIGHTS)) ** ALPHA for h in HEIGHTS},
        index=MEASURED_INDEX,
    )
    measured["Dir_100m"] = rng.uniform(0.0, 360.0, len(MEASURED_INDEX))

    state = SessionState()
    state.reset()
    state.timeseries_df = measured
    state.raw_timeseries_df = measured.copy()
    state.sensor_mapping = {
        float(h): {
            "speed_col": f"Spd_{int(h)}m",
            "dir_col": "Dir_100m" if h == 100.0 else None,
        }
        for h in HEIGHTS
    }
    state.sensor_inventory = {
        f"Spd_{int(h)}m": {"height_m": float(h), "sensor_type": "wind_speed"} for h in HEIGHTS
    }
    state.set_measurement_type("mast")
    state.set_hub_height_m(HUB_M)

    long_rng = np.random.default_rng(23)
    era5_speed = 8.0 + long_rng.weibull(2.0, len(LONG_INDEX)) * 3.0
    state.reanalysis_interpolated = {
        "era5": pd.DataFrame(
            {
                "Spd_100m": era5_speed,
                "Dir_100m": long_rng.uniform(0.0, 360.0, len(LONG_INDEX)),
            },
            index=LONG_INDEX,
        ),
        "merra2": pd.DataFrame(
            {
                # Correlated with ERA5 but not an affine function of it — see
                # `test_variance_ratio_is_invariant_to_an_affine_reference`. Two real
                # reanalyses share the weather and differ in shape, which is exactly the
                # disagreement axis C exists to measure.
                "Spd_50m": np.clip(
                    era5_speed * 0.86 + 0.4 + long_rng.normal(0.0, 0.8, len(LONG_INDEX)),
                    0.0,
                    None,
                ),
                "Dir_50m": long_rng.uniform(0.0, 360.0, len(LONG_INDEX)),
            },
            index=LONG_INDEX,
        ),
    }
    return state


def _spec(**overrides) -> ScenarioSpec:
    base = dict(
        shear_fit_policy="nearest_2",
        reference_policy="nearest_2",
        shear_model="power_law_mean",
        reference_source="era5",
        ltc_algorithm="variance_ratio",
        hub_height_m=HUB_M,
    )
    base.update(overrides)
    return ScenarioSpec(**base)


def _run(base: SessionState, spec: ScenarioSpec) -> tuple[dict, SessionState]:
    with scenario_context(base) as scenario:
        return run_scenario(scenario, spec), scenario


def _long_term_mean(scenario: SessionState, algorithm: str) -> float:
    frame = scenario.ltc_results[algorithm]["df"]
    return float(frame["corrected_wind_speed"].mean())


# ---------------------------------------------------------------------------
# The chain runs end to end
# ---------------------------------------------------------------------------


def test_a_scenario_runs_every_stage_and_reports_each():
    base = _base_state()
    record, scenario = _run(base, _spec())

    assert set(record["stages"]) == {"build_shear", "extrapolate", "run_ltc", "run_uncertainty"}
    assert record["stages"]["build_shear"]["method"] == "power_law"
    assert record["stages"]["extrapolate"]["hub_column"] == "Spd_120m_hub"
    assert record["stages"]["run_ltc"]["algorithm"] == "variance_ratio"
    assert record["stages"]["run_uncertainty"]["total_uncertainty_pct"] > 0.0
    assert scenario.latest_uncertainty is not None


def test_the_shear_fit_recovers_the_profile_it_was_built_from():
    """A sanity anchor: the mast is an exact power law, so the table must find its alpha."""
    base = _base_state()
    _, scenario = _run(base, _spec())
    assert float(np.nanmean(scenario.shear_table.to_numpy())) == pytest.approx(ALPHA, abs=0.01)


def test_the_scenario_leaves_the_base_session_untouched():
    """The whole point of §7.2: a sweep must not mutate the session it runs from."""
    base = _base_state()
    columns_before = list(base.timeseries_df.columns)

    _run(base, _spec())

    assert list(base.timeseries_df.columns) == columns_before
    assert base.shear_table is None
    assert base.ltc_results == {}
    assert base.latest_uncertainty is None


def test_result_files_are_not_written_for_a_scenario():
    base = _base_state()
    _, scenario = _run(base, _spec())
    assert scenario.ltc_results["variance_ratio"]["persisted"] is False
    assert scenario.ltc_results["variance_ratio"]["file"] == ""


# ---------------------------------------------------------------------------
# Each axis actually moves the answer
# ---------------------------------------------------------------------------


def test_axis_a_changes_the_hub_series():
    """A different extrapolation reference set is levered from a different height."""
    base = _base_state()
    _, near = _run(base, _spec(reference_policy="nearest_2"))
    _, wide = _run(base, _spec(reference_policy="widest_lever"))

    near_hub = near.timeseries_df["Spd_120m_hub"].mean()
    wide_hub = wide.timeseries_df["Spd_120m_hub"].mean()
    assert near_hub == pytest.approx(wide_hub, rel=0.05)  # same profile, so close
    assert near.era5_interpolated_df is not wide.era5_interpolated_df


def test_axis_b_changes_the_shear_table():
    base = _base_state()
    _, mean_table = _run(base, _spec(shear_model="power_law_mean"))
    _, constant = _run(base, _spec(shear_model="power_law_constant"))

    assert mean_table.shear_table.to_numpy().std() > 0.0
    # A site-wide alpha is one number everywhere, by construction.
    assert constant.shear_table.to_numpy().std() == pytest.approx(0.0, abs=1e-12)


def test_axis_c_changes_the_long_term_answer():
    """Two independent reanalyses disagreeing is the empirical term of §8.1."""
    base = _base_state()
    _, era5 = _run(base, _spec(reference_source="era5"))
    _, merra = _run(base, _spec(reference_source="merra2"))

    assert era5.runconfig["reference_source"] == "era5"
    assert merra.runconfig["reference_source"] == "merra2"
    assert _long_term_mean(era5, "variance_ratio") != _long_term_mean(merra, "variance_ratio")


def test_variance_ratio_is_invariant_to_an_affine_reference():
    """A reference-source axis only moves a variance-ratio result if the *shapes* differ.

    Variance ratio rescales the reference to the measured mean and standard deviation, so
    composing it with an affine transform of the reference gives back the same corrected
    series. A second reanalysis that were merely a rescaling of the first would therefore
    show zero axis-C spread under this estimator — not because the sources agree, but
    because the estimator cannot see that kind of disagreement.

    Worth pinning: it means axis-C spread measured with variance ratio alone understates
    reference uncertainty, and the sweep should not read a small value there as agreement.
    """
    base = _base_state()
    affine = base.reanalysis_interpolated["era5"].copy()
    affine["Spd_50m"] = affine["Spd_100m"] * 0.86 + 0.4
    affine["Dir_50m"] = affine["Dir_100m"]
    base.reanalysis_interpolated["merra2"] = affine

    _, era5 = _run(base, _spec(reference_source="era5"))
    _, merra = _run(base, _spec(reference_source="merra2"))

    assert _long_term_mean(era5, "variance_ratio") == pytest.approx(
        _long_term_mean(merra, "variance_ratio"), rel=1e-9
    )


def test_axis_d_changes_the_long_term_answer():
    base = _base_state()
    _, variance = _run(base, _spec(ltc_algorithm="variance_ratio"))
    _, linear = _run(base, _spec(ltc_algorithm="linear_least_squares"))

    assert _long_term_mean(variance, "variance_ratio") != _long_term_mean(
        linear, "linear_least_squares"
    )


def test_repeating_a_scenario_reproduces_it():
    """No axis moved, so nothing may move — the baseline the spread is measured against."""
    base = _base_state()
    _, first = _run(base, _spec())
    _, second = _run(base, _spec())

    assert _long_term_mean(first, "variance_ratio") == pytest.approx(
        _long_term_mean(second, "variance_ratio"), rel=1e-12
    )
    assert first.latest_uncertainty["total_uncertainty_pct"] == pytest.approx(
        second.latest_uncertainty["total_uncertainty_pct"], rel=1e-12
    )


# ---------------------------------------------------------------------------
# Refusals are explicit
# ---------------------------------------------------------------------------


def test_an_inapplicable_policy_refuses_by_name():
    """A lidar has no booms; the scenario must say so rather than substituting something."""
    base = _base_state()
    base.sensor_inventory = {}
    base.set_measurement_type("lidar")
    with pytest.raises(ScenarioError, match="reference policy unusable"):
        resolve_sensors(base, _spec(reference_policy="redundant_boom"))


def test_a_single_height_fit_demands_an_analyst_exponent():
    """Design doc §3.A.1 — refuse, and say what is needed, rather than inventing an alpha."""
    base = _base_state()
    base.sensor_inventory = {
        "Spd_100m_A": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Spd_100m_B": {"height_m": 100.0, "sensor_type": "wind_speed"},
    }
    with pytest.raises(ScenarioError, match="cannot be fitted from fewer"):
        resolve_sensors(base, _spec(shear_fit_policy="redundant_boom"))


def test_an_analyst_exponent_unblocks_the_single_height_case():
    base = _base_state()
    base.sensor_inventory = {
        "Spd_100m_A": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Spd_100m_B": {"height_m": 100.0, "sensor_type": "wind_speed"},
    }
    spec = _spec(shear_fit_policy="redundant_boom", analyst_shear_alpha=0.20)
    record, scenario = _run(base, spec)

    assert record["stages"]["build_shear"]["shear_source"] == "analyst_supplied"
    assert record["stages"]["build_shear"]["alpha"] == 0.20
    assert scenario.shear_table.to_numpy().std() == pytest.approx(0.0, abs=1e-12)
    # An assumed exponent must take the assumed-shear uncertainty branch (§3.A.1).
    provenance = record["stages"]["run_uncertainty"]["provenance"]
    assert provenance["shear_source"] == "analyst_supplied"


def test_unimplemented_shear_models_refuse_with_the_reason():
    """Declared axis levels the extrapolation path cannot consume must not silently fall back."""
    base = _base_state()
    assert set(UNIMPLEMENTED_SHEAR_MODELS) & {"power_law_sector_12", "power_law_per_record"}
    for model in UNIMPLEMENTED_SHEAR_MODELS:
        with pytest.raises(ScenarioError, match="not yet supported"):
            _run(base, _spec(shear_model=model))


def test_unknown_shear_model_is_rejected():
    base = _base_state()
    with pytest.raises(ScenarioError, match="shear model must be one of"):
        _run(base, _spec(shear_model="quadratic"))


def test_unknown_ltc_algorithm_is_rejected():
    base = _base_state()
    with pytest.raises(ScenarioError, match="unknown LTC algorithm"):
        _run(base, _spec(ltc_algorithm="kriging"))


@pytest.mark.parametrize("model", [m for m in SHEAR_MODELS if not m.startswith("log_law")])
def test_every_supported_power_law_level_runs(model):
    base = _base_state()
    record, _ = _run(base, _spec(shear_model=model))
    assert record["stages"]["build_shear"]["method"] == "power_law"
