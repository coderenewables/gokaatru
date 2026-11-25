"""Pipelines: order, status per step, named copies (P3-6, decisions/0015.1, 0015.4, 0015.5)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.operations import REGISTRY
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import run_pipeline

PAIR = json.dumps({"80": "Spd_80m", "100": "Spd_100m"})
HUB = "Spd_120m_hub"
UNCERTAINTY = {
    "measurement_uncertainty_pct": 2.0, "measurement_height_m": 100.0, "hub_height_m": 120.0,
    "shear_method": "calculate_shear", "mcp_r_squared": 0.8, "concurrent_hours": 8760.0, "shear_std": 0.05,
}
#: The chain the synthetic pipeline ran, in a scrambled order.
CHAIN = [
    {"id": "uncertainty", "operation": "calculate_uncertainty", "parameters": UNCERTAINTY},
    {"id": "ensemble", "operation": "run_ensemble", "parameters": {"measured_col": HUB}},
    {"id": "hub", "operation": "extrapolate_to_hub_height", "parameters": {"hub_height_m": 120.0}},
    {"id": "table", "operation": "build_shear_table", "parameters": {}},
    {"id": "clip", "operation": "run_clipping_analysis",
     "parameters": {"speed_col": "Ensemble_Speed", "source": "ensemble"}},
    {"id": "series", "operation": "calculate_shear_timeseries", "parameters": {"height_sensors": PAIR}},
    *(
        {"id": name, "operation": f"run_ltc_{name}", "parameters": {"short_col": HUB, "long_col": "Spd_100m"}}
        for name in ("linear_least_squares", "total_least_squares", "variance_ratio")
    ),
    {"id": "speedsort", "operation": "run_ltc_speedsort",
     "parameters": {"short_col": HUB, "long_col": "Spd_100m", "long_dir_col": "Dir_100m"}},
    {"id": "xgboost", "operation": "run_ltc_xgboost", "parameters": {"short_col": HUB, "long_col": "Spd_100m"}},
]


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> SessionState:
    state, _ = run_pipeline(tmp_path_factory.mktemp("pipelines") / "pipeline")
    return state


def _call(state: SessionState, operation: str, /, **arguments):
    with bind_session(state):
        return REGISTRY.get(operation).fn(**arguments)


def _ordered(state: SessionState, steps: list[dict]) -> dict:
    return _call(state, "order_pipeline", steps=steps)


def test_the_order_follows_the_dependencies(analysed) -> None:
    report = _ordered(analysed, CHAIN)
    order = report["order"]
    for edge in report["edges"]:
        assert order.index(edge["source"]) < order.index(edge["target"]), edge
    assert order[:3] == ["series", "table", "hub"]
    assert order[-3:] == ["ensemble", "clip", "uncertainty"]
    assert report["steps"]["table"]["inputs"]["shear_timeseries"] == ["series"]


def test_the_chain_the_session_ran_is_current(analysed) -> None:
    report = _ordered(analysed, CHAIN)
    assert {step_id: entry["status"] for step_id, entry in report["steps"].items()} == {
        step["id"]: "current" for step in CHAIN
    }
    assert report["to_run"] == []


def test_changed_parameters_mark_the_step_changed_and_what_follows_upstream(analysed) -> None:
    steps = copy.deepcopy(CHAIN)
    next(step for step in steps if step["id"] == "table")["parameters"] = {"aggregation": "median"}
    report = _ordered(analysed, steps)
    status = {step_id: entry["status"] for step_id, entry in report["steps"].items()}
    assert status["series"] == "current"
    assert status["table"] == "changed"
    assert status["hub"] == "upstream" and report["steps"]["hub"]["waiting_on"] == ["table"]
    assert all(status[step_id] == "upstream" for step_id in ("ensemble", "clip", "uncertainty"))
    assert report["to_run"][0] == "table"


def test_a_result_rebuilt_upstream_makes_the_steps_after_it_stale(analysed, tmp_path: Path) -> None:
    state = copy.deepcopy(analysed)
    _call(state, "build_shear_table", aggregation="median")
    status = {step_id: entry["status"] for step_id, entry in _ordered(state, CHAIN)["steps"].items()}
    assert status["table"] == "changed"
    assert status["hub"] == "stale"


def test_two_producers_of_one_result_are_refused(analysed) -> None:
    steps = [*CHAIN, {"id": "momm", "operation": "build_aggr_momm_shear_table", "parameters": {"height_sensors": PAIR}}]
    with pytest.raises(ValueError, match="shear_table by"):
        _ordered(analysed, steps)


def test_parameters_that_do_not_fit_are_reported_not_refused(analysed) -> None:
    steps = [{"id": "hub", "operation": "extrapolate_to_hub_height", "parameters": {"hub_height": 120}}]
    entry = _ordered(analysed, steps)["steps"]["hub"]
    assert entry["status"] == "invalid"
    assert any("hub_height" in error for error in entry["errors"])


@pytest.mark.parametrize(
    ("operation", "why"),
    [("undo_last_change", "not offered on the canvas"), ("brighthub_login", "credentials")],
)
def test_an_operation_that_cannot_be_a_step_is_refused(analysed, operation: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        _ordered(analysed, [{"id": "x", "operation": operation, "parameters": {}}])


def test_named_pipelines_save_list_delete_and_undo(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path)
    state = manager.create_session()
    steps = [{"id": "w", "operation": "compute_weibull_params", "parameters": {"sensor_name": "Spd_100m"},
              "position": {"x": 10, "y": 20}}]
    saved = _call(state, "save_pipeline", name="chosen", steps=steps)
    assert saved["replaced"] is False and saved["steps"] == steps
    assert [entry["name"] for entry in _call(state, "list_pipelines")["pipelines"]] == ["chosen"]

    reopened = SessionManager(base_dir=tmp_path).get_session(state.session_id)
    assert reopened.pipelines == state.pipelines

    _call(state, "delete_pipeline", name="chosen")
    assert state.pipelines == {}
    _call(state, "undo_last_change")
    assert list(state.pipelines) == ["chosen"]
    _call(state, "undo_last_change")
    assert state.pipelines == {}
    _call(state, "redo_last_change")
    assert state.pipelines["chosen"]["steps"] == steps


def test_a_pipeline_that_cannot_be_ordered_is_not_saved(tmp_path: Path) -> None:
    state = SessionManager(base_dir=tmp_path).create_session()
    steps = [
        {"id": "a", "operation": "build_shear_table", "parameters": {}},
        {"id": "b", "operation": "build_aggr_momm_shear_table", "parameters": {"height_sensors": PAIR}},
    ]
    with pytest.raises(ValueError, match="One step produces each result"):
        _call(state, "save_pipeline", name="bad", steps=steps)
    assert state.pipelines == {}
