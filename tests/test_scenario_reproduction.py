"""A sweep scenario loaded as a pipeline and run reproduces its row (P3-7, decisions/0015.1).

The sweep runs each scenario in a leaf whose other results are cleared; the canvas runs the
same steps on the campaign as it stands, with its ensemble, its clipping run and the tables
of earlier runs. Every metric of every completed row must come out the same, exactly.
"""
from __future__ import annotations

import copy
import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from server.core.sweep import SweepSpec, load_sweep, run_sweep
from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import run_pipeline

SPEC = SweepSpec(
    shear_fit_policies=("nearest_2", "widest_lever"),
    reference_policies=("nearest_2",),
    shear_models=("power_law_mean", "power_law_constant", "log_law_median"),
    reference_sources=("era5", "merra2"),
    ltc_algorithms=("variance_ratio", "speedsort"),
    hub_height_m=120.0,
)
ANALYST = SweepSpec(
    shear_fit_policies=("nearest_2",),
    reference_policies=("nearest_2",),
    shear_models=("power_law_mean",),
    reference_sources=("era5",),
    ltc_algorithms=("linear_least_squares",),
    hub_height_m=120.0,
    analyst_shear_alpha=0.18,
)
METRICS = (
    "long_term_mean_speed_mps", "total_uncertainty_pct", "u_measurement_pct", "u_vertical_pct", "u_mcp_pct",
    "u_future_pct", "indicative_gross_aep_mwh", "energy_sensitivity_factor", "capacity_factor",
    "ltc_r_squared", "concurrent_months", "mean_shear_alpha", "extrapolation_ratio_max",
)


@pytest.fixture(scope="module")
def campaign(tmp_path_factory: pytest.TempPathFactory) -> SessionState:
    state, _ = run_pipeline(tmp_path_factory.mktemp("reproduction") / "pipeline")
    era5 = state.reanalysis_interpolated["era5"]
    state.reanalysis_interpolated["merra2"] = pd.DataFrame(
        {"Spd_50m": era5["Spd_100m"] * 0.92, "Dir_50m": (era5["Dir_100m"] + 8.0) % 360.0}, index=era5.index
    )
    return state


@pytest.fixture(scope="module")
def sweeps(campaign: SessionState) -> dict[str, list[dict[str, Any]]]:
    found = {}
    for sweep_id, spec in (("reproduce", SPEC), ("reproduce-analyst", ANALYST)):
        run_sweep(campaign, spec, sweep_id=sweep_id, persist=True)
        found[sweep_id] = [row for row in load_sweep(campaign, sweep_id)["results"] if row.get("status") == "ok"]
    return found


def _call(state: SessionState, operation: str, /, **arguments):
    with bind_session(state):
        return REGISTRY.get(operation).fn(**arguments)


def _run(state: SessionState, pipeline: dict[str, Any]) -> dict[str, Any]:
    """Run the steps one at a time, in the order the server gives (decisions/0015.4)."""
    steps = {step["id"]: step for step in pipeline["steps"]}
    responses = {}
    for step_id in _call(state, "order_pipeline", steps=pipeline["steps"])["order"]:
        responses[step_id] = _call(state, steps[step_id]["operation"], **steps[step_id]["parameters"])
    return responses


def _metrics(state: SessionState, pipeline: dict[str, Any], responses: dict[str, Any]) -> dict[str, Any]:
    """The row's metrics, read off what the pipeline built (scenario_result._collect_metrics)."""
    algorithm = pipeline["scenario"]["ltc_algorithm"]
    series, _ = state.long_term_speed_series(f"ltc:{algorithm}")
    uncertainty = state.latest_uncertainty
    energy = uncertainty["energy_sensitivity"]
    metrics = responses["correction"].get("metrics", {})
    builds_table = any(step["operation"].startswith("build_") and "shear" in step["operation"]
                       for step in pipeline["steps"])
    return {
        "long_term_mean_speed_mps": float(series.mean()),
        "total_uncertainty_pct": uncertainty["total_uncertainty_pct"],
        "u_measurement_pct": uncertainty["components"]["measurement"],
        "u_vertical_pct": uncertainty["components"]["vertical_extrapolation"],
        "u_mcp_pct": uncertainty["components"]["mcp"],
        "u_future_pct": uncertainty["components"]["future_variability"],
        "indicative_gross_aep_mwh": energy["indicative_gross_aep_mwh"],
        "energy_sensitivity_factor": energy["factor"],
        "capacity_factor": energy["power_curve"]["indicative_capacity_factor"],
        "ltc_r_squared": metrics.get("r_squared"),
        "concurrent_months": float(metrics["concurrent_points"]) / 730.0,
        # The scenario's own table; a log-law scenario builds none.
        "mean_shear_alpha": float(np.nanmean(state.shear_table.to_numpy(dtype=float))) if builds_table else None,
        "extrapolation_ratio_max": responses["hub"]["extrapolation_ratio"]["max"],
    }


def test_the_sweeps_have_rows_of_every_kind(sweeps) -> None:
    rows = sweeps["reproduce"]
    assert {row["shear_model"] for row in rows} == set(SPEC.shear_models)
    assert {row["reference_source"] for row in rows} == {"era5", "merra2"}
    assert {row["ltc_algorithm"] for row in rows} == {"variance_ratio", "speedsort"}
    assert len(sweeps["reproduce-analyst"]) == 1


@pytest.mark.parametrize("sweep_id", ["reproduce", "reproduce-analyst"])
def test_every_completed_row_is_reproduced_by_its_pipeline(campaign, sweeps, sweep_id: str) -> None:
    for row in sweeps[sweep_id]:
        pipeline = _call(campaign, "pipeline_from_scenario", sweep_id=sweep_id, config_hash=row["config_hash"])
        assert pipeline["prefix_matches"] is True
        state = copy.deepcopy(campaign)
        assert state.ensemble_df is not None and state.clipping_result is not None
        got = _metrics(state, pipeline, _run(state, pipeline))
        expected = {name: row.get(name) for name in METRICS}
        moved = {name: (got[name], expected[name]) for name in METRICS if got[name] != expected[name]}
        assert moved == {}, row["config_hash"]


def test_a_loaded_scenario_reads_current_once_run(campaign, sweeps) -> None:
    row = sweeps["reproduce"][0]
    pipeline = _call(campaign, "pipeline_from_scenario", sweep_id="reproduce", config_hash=row["config_hash"])
    state = copy.deepcopy(campaign)
    before = _call(state, "order_pipeline", steps=pipeline["steps"])
    assert before["to_run"]
    _run(state, pipeline)
    after = _call(state, "order_pipeline", steps=pipeline["steps"])
    assert after["to_run"] == [] and {entry["status"] for entry in after["steps"].values()} == {"current"}


def test_a_changed_campaign_says_the_row_will_not_be_reproduced(campaign, sweeps) -> None:
    state = copy.deepcopy(campaign)
    _call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_80m", params=json.dumps({"max": 12.0}))
    row = sweeps["reproduce"][0]
    pipeline = _call(state, "pipeline_from_scenario", sweep_id="reproduce", config_hash=row["config_hash"])
    assert pipeline["prefix_matches"] is False and "will not reproduce" in pipeline["prefix_note"]


def test_a_scenario_pipeline_gives_back_its_own_sweep_levels(campaign, sweeps) -> None:
    for row in sweeps["reproduce"]:
        pipeline = _call(campaign, "pipeline_from_scenario", sweep_id="reproduce", config_hash=row["config_hash"])
        around = _call(campaign, "sweep_spec_from_pipeline", steps=pipeline["steps"])
        spec = around["spec"]
        assert around["unmatched"] == []
        assert row["shear_fit_policy"] in spec["shear_fit_policies"]
        assert row["reference_policy"] in spec["reference_policies"]
        assert spec["shear_models"] == [row["shear_model"]]
        assert spec["reference_sources"] == [row["reference_source"]]
        assert spec["ltc_algorithms"] == [row["ltc_algorithm"]]
        assert spec["hub_height_m"] == 120.0


def test_choices_no_sweep_level_expresses_are_listed(campaign) -> None:
    steps = [
        {"id": "momm", "operation": "build_aggr_momm_shear_table",
         "parameters": {"height_sensors": json.dumps({"60": "Spd_60m", "80": "Spd_80m"})}},
        {"id": "w", "operation": "compute_weibull_params", "parameters": {"sensor_name": "Spd_100m"}},
    ]
    around = _call(campaign, "sweep_spec_from_pipeline", steps=steps)
    axes = {entry["axis"] for entry in around["unmatched"]}
    assert {"shear_model", "shear_fit_policy", "ltc_algorithm"} <= axes
    assert around["spec"]["shear_fit_policies"] == ["nearest_2"]


def test_every_scenario_step_is_a_canvas_operation() -> None:
    for name in ("build_constant_shear_table", "calculate_scenario_uncertainty", "extrapolate_to_hub_height"):
        assert REGISTRY.get(name).canvas
