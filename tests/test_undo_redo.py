"""Undo restores the identical series or configuration; redo reapplies it (P1-13)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.operations import REGISTRY
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session
from tests.test_dry_run import _populate

FLAG_CONTENT = ["timestamp", "sensor", "rule_sequence", "rule_type", "reason"]


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    _populate(state)
    state.runconfig = {"hub_height_m": 120.0}
    state.hub_height_m = 120.0
    return state


def _call(state: SessionState, name: str, **arguments):
    with bind_session(state):
        return REGISTRY.get(name).fn(**arguments)


def _same(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    return (
        left.index.equals(right.index)
        and list(left.columns) == list(right.columns)
        and bool(np.array_equal(left.to_numpy(dtype=float), right.to_numpy(dtype=float), equal_nan=True))
    )


def _flags(state: SessionState) -> pd.DataFrame:
    return state.cleaning_flags[FLAG_CONTENT].reset_index(drop=True)


def test_undo_and_redo_of_a_cleaning_rule_are_exact() -> None:
    state = _state()
    _call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_100m", params="{}")
    after_first, first_flags = state.timeseries_df.copy(), _flags(state)
    _call(state, "apply_cleaning_rule", rule_type="stuck_sensor", sensor="Spd_100m", params="{}")
    after_second, second_flags = state.timeseries_df.copy(), _flags(state)

    undone = _call(state, "undo_last_change")
    assert undone["undone"]["operation"] == "apply_cleaning_rule"
    assert _same(state.timeseries_df, after_first)
    pd.testing.assert_frame_equal(_flags(state), first_flags)

    redone = _call(state, "redo_last_change")
    assert redone["redone"]["parameters"]["rule_type"] == "stuck_sensor"
    assert _same(state.timeseries_df, after_second)
    pd.testing.assert_frame_equal(_flags(state), second_flags)


def test_undo_and_redo_of_a_configuration_change_are_exact() -> None:
    state = _state()
    before = copy.deepcopy(state.runconfig)
    _call(state, "update_run_config", key="hub_height_m", value="110")
    after = copy.deepcopy(state.runconfig)
    assert state.hub_height_m == 110.0

    _call(state, "undo_last_change")
    assert state.runconfig == before
    assert state.hub_height_m == 120.0

    _call(state, "redo_last_change")
    assert state.runconfig == after
    assert state.hub_height_m == 110.0


def test_a_later_unrelated_configuration_write_survives_the_undo() -> None:
    state = _state()
    _call(state, "update_run_config", key="hub_height_m", value="110")
    state.runconfig["reference_source"] = "merra2"

    _call(state, "undo_last_change")

    assert state.hub_height_m == 120.0
    assert state.runconfig["reference_source"] == "merra2"


def test_undo_refuses_when_a_later_change_moved_what_it_would_restore() -> None:
    state = _state()
    _call(state, "update_run_config", key="hub_height_m", value="110")
    state.runconfig["hub_height_m"] = 95.0
    with pytest.raises(ValueError, match="a later change has moved hub_height_m"):
        _call(state, "undo_last_change")


def test_undo_refuses_a_rule_that_is_no_longer_the_last() -> None:
    state = _state()
    _call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_100m", params="{}")
    _call(state, "undo_cleaning_rule", entry_index=0)
    with pytest.raises(ValueError, match="no longer the last cleaning rule"):
        _call(state, "undo_last_change")


def test_nothing_to_undo_or_redo_is_refused() -> None:
    state = _state()
    with pytest.raises(ValueError, match="Nothing to undo"):
        _call(state, "undo_last_change")
    with pytest.raises(ValueError, match="Nothing to redo"):
        _call(state, "redo_last_change")


def test_a_fresh_change_after_an_undo_clears_the_redo() -> None:
    state = _state()
    _call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_100m", params="{}")
    _call(state, "undo_last_change")
    _call(state, "apply_cleaning_rule", rule_type="stuck_sensor", sensor="Spd_100m", params="{}")
    with pytest.raises(ValueError, match="Nothing to redo"):
        _call(state, "redo_last_change")


def test_undo_walks_back_through_both_kinds_in_order() -> None:
    state = _state()
    original = state.timeseries_df.copy()
    _call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_100m", params="{}")
    _call(state, "update_run_config", key="hub_height_m", value="110")

    assert _call(state, "undo_last_change")["undone"]["operation"] == "update_run_config"
    assert _call(state, "undo_last_change")["undone"]["operation"] == "apply_cleaning_rule"
    assert _same(state.timeseries_df, original)
    log = _call(state, "get_operation_log", limit=10)
    assert log["can_undo"] is False and log["can_redo"] is True
    assert len(log["undo_stack"]) == 2


def test_undo_and_redo_over_http_and_across_a_restart(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path)
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        state = manager.get_session(session_id)
        _populate(state)
        headers = {"X-GoKaatru-Session": session_id}
        base = f"/api/sessions/{session_id}/operations"
        body = {"rule_type": "range_check", "sensor": "Spd_100m", "params": json.dumps({})}
        assert client.post(f"{base}/apply_cleaning_rule", headers=headers, json=body).status_code == 200
        assert client.post(f"{base}/undo_last_change", headers=headers).status_code == 200
    app.dependency_overrides.clear()

    reopened = SessionManager(base_dir=tmp_path).get_session(session_id)
    assert reopened.undo_stack == state.undo_stack != []
    with bind_session(reopened):
        REGISTRY.get("redo_last_change").fn()
    assert reopened.cleaning_log[-1]["rule_type"] == "range_check"
