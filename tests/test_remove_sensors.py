"""Removing sensors is an operation with a dry run and an undo (P2-6, decisions/0014.6).

Undo restores every field the removal touched: the inventory in its order, the height
mapping, the run configuration's exclusion list, and the columns of the working and raw
data, values and position, cleaning gaps included.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.operations import REGISTRY
from server.state.project import ProjectStore
from server.state.session import SessionState, bind_session
from tests.test_cleaning_flags import _same
from tests.test_dry_run import _fingerprint, _populate


def _state(workspace: Path) -> SessionState:
    state = SessionState()
    state.reset()
    _populate(state)
    state.workspace_dir = workspace
    state.sensor_inventory["Spd_100m_sd"] = {"height_m": 100.0, "sensor_type": "wind_speed_sd"}
    frame = state.timeseries_df
    frame.loc[frame.index[50:60], "Dir_100m"] = np.nan
    return state


def _call(state: SessionState, name: str, **arguments):
    with bind_session(state):
        return REGISTRY.get(name).fn(**arguments)


def _snapshot(state: SessionState) -> dict:
    return {
        "inventory": list(state.sensor_inventory.items()),
        "mapping": copy.deepcopy(state.sensor_mapping),
        "excluded": state.runconfig.get("excluded_sensors", "absent"),
        "working": state.timeseries_df.copy(),
        "raw": state.raw_timeseries_df.copy(),
    }


def _equal(left: dict, right: dict) -> bool:
    return (
        left["inventory"] == right["inventory"]
        and left["mapping"] == right["mapping"]
        and left["excluded"] == right["excluded"]
        and _same(left["working"], right["working"])
        and _same(left["raw"], right["raw"])
    )


def test_removal_takes_the_sensor_out_everywhere(tmp_path: Path) -> None:
    state = _state(tmp_path)
    version = state.data_version
    result = _call(state, "remove_sensors", sensor_names=["Dir_100m", "Nope", "Dir_100m"])

    assert result["removed"] == ["Dir_100m"] and result["not_found"] == ["Nope", "Dir_100m"]
    assert result["columns_dropped"] == {"timeseries_df": ["Dir_100m"], "raw_timeseries_df": ["Dir_100m"]}
    assert "Dir_100m" not in state.sensor_inventory
    assert state.sensor_mapping[100.0]["dir_col"] is None
    assert "Dir_100m" not in state.timeseries_df.columns and "Dir_100m" not in state.raw_timeseries_df.columns
    assert state.runconfig["excluded_sensors"] == ["Dir_100m"]
    assert json.loads((tmp_path / "runconfig.json").read_text())["excluded_sensors"] == ["Dir_100m"]
    assert state.data_version == version + 1, "the working data changed, so derived results read as stale"


def test_the_preview_is_the_change_removing_makes(tmp_path: Path) -> None:
    from server.tools.cleaning import _change_summary

    state = _state(tmp_path)
    fingerprint = _fingerprint(state)
    before = state.timeseries_df.copy()
    with bind_session(state):
        preview = REGISTRY.get("remove_sensors").dry_run(sensor_names=["Spd_100m"])

    assert _fingerprint(state) == fingerprint and state.removed_sensors == {}
    assert "Spd_100m" in state.sensor_inventory and not (tmp_path / "runconfig.json").exists()
    _call(state, "remove_sensors", sensor_names=["Spd_100m"])
    assert preview["changes"] == _change_summary(before, state.timeseries_df)
    assert preview["changes"]["columns_dropped"] == ["Spd_100m"]
    assert preview["removed"] == ["Spd_100m"] and preview["applied"] is False


def test_undo_restores_every_field_and_redo_removes_it_again(tmp_path: Path) -> None:
    state = _state(tmp_path)
    original = _snapshot(state)
    _call(state, "remove_sensors", sensor_names=["Spd_100m", "Dir_100m"])
    removed = _snapshot(state)
    # A speed sensor takes its standard deviation slot with it, and the height stays only
    # while the temperature sensor still holds it.
    assert removed["mapping"] == {100.0: {"speed_col": None, "dir_col": None, "sd_col": None, "temp_col": "Tmp_100m"}}

    undone = _call(state, "undo_last_change")
    assert undone["detail"] == {"restored": ["Spd_100m", "Dir_100m"]}
    assert _equal(_snapshot(state), original)
    assert list(state.timeseries_df.columns) == list(original["working"].columns)
    assert state.removed_sensors == {}
    assert "excluded_sensors" not in json.loads((tmp_path / "runconfig.json").read_text())

    _call(state, "redo_last_change")
    assert _equal(_snapshot(state), removed)
    _call(state, "undo_last_change")
    assert _equal(_snapshot(state), original)


def test_two_removals_undo_in_turn(tmp_path: Path) -> None:
    state = _state(tmp_path)
    original = _snapshot(state)
    _call(state, "remove_sensors", sensor_names=["Tmp_100m"])
    after_first = _snapshot(state)
    _call(state, "remove_sensors", sensor_names=["Dir_100m"])
    _call(state, "undo_last_change")
    assert _equal(_snapshot(state), after_first)
    _call(state, "undo_last_change")
    assert _equal(_snapshot(state), original)


def test_undo_refuses_when_a_later_change_moved_what_it_restores(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _call(state, "remove_sensors", sensor_names=["Dir_100m"])
    state.timeseries_df = state.timeseries_df.iloc[:-5]
    with pytest.raises(ValueError, match="moved the records of timeseries_df"):
        _call(state, "undo_last_change")

    state = _state(tmp_path)
    _call(state, "remove_sensors", sensor_names=["Dir_100m"])
    state.sensor_mapping[100.0]["dir_col"] = "Spd_100m_sd"
    with pytest.raises(ValueError, match="moved the sensor mapping"):
        _call(state, "undo_last_change")


def test_what_a_removal_kept_aside_survives_the_project_store(tmp_path: Path) -> None:
    state = _state(tmp_path)
    original = _snapshot(state)
    _call(state, "remove_sensors", sensor_names=["Dir_100m"])
    restored = SessionState()
    ProjectStore(tmp_path).load(restored)
    restored.workspace_dir = tmp_path
    kept = restored.removed_sensors[next(iter(restored.removed_sensors))]
    pd.testing.assert_frame_equal(kept["frames"]["timeseries_df"], original["working"][["Dir_100m"]])
    _call(restored, "undo_last_change")
    assert _equal(_snapshot(restored), original)


def test_refusals(tmp_path: Path) -> None:
    state = SessionState()
    state.reset()
    with pytest.raises(ValueError, match="Sensor inventory is not loaded"):
        _call(state, "remove_sensors", sensor_names=["Spd_100m"])
    state = _state(tmp_path)
    with pytest.raises(ValueError, match="at least one sensor"):
        _call(state, "remove_sensors", sensor_names=[])
    _call(state, "remove_sensors", sensor_names=["Nope"])
    with pytest.raises(ValueError, match="Nothing to undo"):
        _call(state, "undo_last_change")
