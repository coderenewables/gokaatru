"""A result is stale when anything it was built from changed (P3-3, decisions/0015.3).

Before, only the data version and the engine counted: rebuilding the shear table with
another method left the hub series, every long-term correction, the ensemble and the
uncertainty reported current, although each was built from the table that was replaced.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from server.operations import REGISTRY
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import run_pipeline

PAIR = json.dumps({"80": "Spd_80m", "100": "Spd_100m"})
AFTER_THE_SHEAR_TABLE = {
    "hub_height_series", "ltc:linear_least_squares", "ltc:total_least_squares", "ltc:variance_ratio",
    "ltc:speedsort", "ltc:xgboost", "ensemble", "clipping", "uncertainty",
}


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> tuple[SessionState, Path]:
    workspace = tmp_path_factory.mktemp("staleness") / "pipeline"
    state, _ = run_pipeline(workspace)
    return state, workspace


def _copy(analysed: tuple[SessionState, Path], tmp_path: Path) -> SessionState:
    import copy

    state = copy.deepcopy(analysed[0])
    shutil.copytree(analysed[1], tmp_path / "pipeline")
    state.workspace_dir = tmp_path / "pipeline"
    return state


def _call(state: SessionState, operation: str, /, **arguments):
    with bind_session(state):
        return REGISTRY.get(operation).fn(**arguments)


def test_the_analysed_pipeline_starts_current(analysed) -> None:
    assert analysed[0].stale_artifacts() == []


def test_a_rebuilt_shear_table_makes_everything_built_from_it_stale(analysed, tmp_path: Path) -> None:
    state = _copy(analysed, tmp_path)
    version = state.data_version
    _call(state, "build_aggr_momm_shear_table", height_sensors=PAIR)

    assert state.data_version == version
    assert set(state.stale_artifacts()) == AFTER_THE_SHEAR_TABLE
    reasons = state.staleness_report()["stale_reasons"]
    assert "shear_table" in reasons["hub_height_series"]
    assert "stale" in reasons["ensemble"]


def test_rebuilding_with_the_same_result_makes_nothing_stale(analysed, tmp_path: Path) -> None:
    state = _copy(analysed, tmp_path)
    _call(state, "build_shear_table")
    assert state.stale_artifacts() == []


def test_a_rerun_correction_makes_only_what_follows_it_stale(analysed, tmp_path: Path) -> None:
    state = _copy(analysed, tmp_path)
    # Against the reference carried to hub height instead of its native 100 m: another answer
    # from the same inputs.
    _call(state, "run_ltc_variance_ratio", short_col="Spd_120m_hub", long_col="Spd_120m_hub")

    stale = set(state.stale_artifacts())
    assert "ensemble" in stale and "uncertainty" in stale
    assert stale.isdisjoint({"shear_table", "hub_height_series", "ltc:linear_least_squares", "ltc:variance_ratio"})


def test_dependencies_survive_a_restart(analysed, tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path)
    state = manager.create_session()
    session_id = state.session_id
    source = _copy(analysed, tmp_path)
    for name, value in vars(source).items():
        if name not in {"session_id", "workspace_dir", "created_at", "project"}:
            setattr(state, name, value)
    _call(state, "build_aggr_momm_shear_table", height_sensors=PAIR)
    stale = state.stale_artifacts()

    reopened = SessionManager(base_dir=tmp_path).get_session(session_id)
    assert reopened.stale_artifacts() == stale
    assert reopened.derived_inputs == state.derived_inputs
    assert reopened.artifact_versions == state.artifact_versions
