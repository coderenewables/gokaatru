"""Dry runs show exactly what a change would do, and change nothing (P1-6, decisions/0011).

Each cleaning rule is previewed on a session, the session is checked untouched, the rule is
then applied for real, and the change it made must equal the change the preview reported.
The same for undoing a rule.
"""
from __future__ import annotations

import copy
import hashlib
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
from server.tools.cleaning import (
    _apply_cleaning_rule,
    _change_summary,
    _preview_cleaning_rule,
    _preview_undo_cleaning_rule,
    _undo_cleaning_rule,
)

RULES = [
    ("range_check", "Spd_100m", "{}", "", ""),
    ("stuck_sensor", "Spd_100m", "{}", "", ""),
    ("tower_shadow", "Spd_100m", "{}", "", ""),
    ("icing_filter", "Spd_100m", "{}", "", ""),
    ("custom_period_exclude", "Spd_100m", "{}", "2023-02-01", "2023-02-03"),
    ("expression_filter", "Spd_100m", json.dumps({"expression": "Spd_100m > 15"}), "", ""),
    ("timestamp_gap_fill", "Spd_100m", "{}", "", ""),
]


def _populate(state: SessionState) -> None:
    """Sixty days of 10-minute data with out-of-range values, a stuck run, cold calm spells
    and three missing timestamps."""
    rng = np.random.default_rng(17)
    index = pd.date_range("2023-01-01", periods=60 * 144, freq="10min", tz="UTC")
    speed = rng.weibull(2.0, len(index)) * 8.0
    speed[100:110] = 75.0
    speed[200:220] = 6.25
    sd = speed * 0.1
    temperature = rng.normal(8.0, 4.0, len(index))
    temperature[3000:3040] = -3.0
    sd[3000:3040] = 0.0
    speed[3000:3040] = 4.0
    direction = rng.uniform(0, 360, len(index))
    direction[3000:3040] = 123.0
    frame = pd.DataFrame(
        {"Spd_100m": speed, "Spd_100m_sd": sd, "Dir_100m": direction, "Tmp_100m": temperature},
        index=index,
    ).drop(index[[500, 501, 900]])
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        100.0: {"speed_col": "Spd_100m", "dir_col": "Dir_100m", "sd_col": "Spd_100m_sd", "temp_col": "Tmp_100m"},
    }
    state.sensor_inventory = {
        "Spd_100m": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Dir_100m": {"height_m": 100.0, "sensor_type": "wind_direction"},
        "Tmp_100m": {"height_m": 100.0, "sensor_type": "temperature"},
    }


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    _populate(state)
    return state


def _fingerprint(state: SessionState) -> dict[str, object]:
    frame = state.timeseries_df
    return {
        "index": hashlib.sha256(frame.index.as_unit("ns").asi8.tobytes()).hexdigest(),
        "values": hashlib.sha256(np.ascontiguousarray(frame.to_numpy(dtype=float)).tobytes()).hexdigest(),
        "columns": list(frame.columns),
        "cleaning_log": copy.deepcopy(state.cleaning_log),
        "data_version": state.data_version,
        "derived_versions": copy.deepcopy(state.derived_versions),
        "runconfig": copy.deepcopy(state.runconfig),
    }


@pytest.mark.parametrize(("rule", "sensor", "params", "start", "end"), RULES, ids=[rule[0] for rule in RULES])
def test_the_preview_of_a_rule_is_the_change_applying_it_makes(rule, sensor, params, start, end) -> None:
    state = _state()
    before_fingerprint = _fingerprint(state)
    before = state.timeseries_df.copy()

    preview = _preview_cleaning_rule(state, rule, sensor, params, start, end)

    assert _fingerprint(state) == before_fingerprint
    applied = _apply_cleaning_rule(state, rule, sensor, params, start, end)
    assert preview["status"] == "preview" and preview["applied"] is False
    assert preview["records_affected"] == applied["records_affected"]
    assert preview["changes"] == _change_summary(before, state.timeseries_df)
    assert preview["records_affected"] > 0, "the fixture plants something for every rule to find"


def test_the_preview_of_an_undo_is_the_change_undoing_makes() -> None:
    state = _state()
    _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
    _apply_cleaning_rule(state, "stuck_sensor", "Spd_100m", "{}")
    before_fingerprint = _fingerprint(state)
    before = state.timeseries_df.copy()

    # Undo the stuck-sensor entry: the replayed range check still removes the 75 m/s run,
    # so what comes back is the 20-record stuck run and the 40-record icing spell, whose
    # speed is held constant too.
    preview = _preview_undo_cleaning_rule(state, 1)

    assert _fingerprint(state) == before_fingerprint
    _undo_cleaning_rule(state, 1)
    changes = _change_summary(before, state.timeseries_df)
    assert preview["changes"] == changes
    assert changes["columns"]["Spd_100m"]["restored"] == 60


def test_a_summary_counts_runs_and_caps_the_listed_ranges() -> None:
    index = pd.date_range("2023-01-01", periods=400, freq="10min", tz="UTC")
    before = pd.DataFrame({"x": np.arange(400.0)}, index=index)
    after = before.copy()
    after.iloc[::4, 0] = np.nan

    summary = _change_summary(before, after)

    column = summary["columns"]["x"]
    assert column["set_missing"] == 100
    assert len(column["ranges"]) == summary["range_limit"] < 100
    assert column["ranges_truncated"] is True
    assert column["ranges"][0] == [index[0].isoformat(), index[0].isoformat()]


def test_the_registry_carries_the_dry_runs_with_their_operations_signatures() -> None:
    declared = {op.name for op in REGISTRY if op.dry_run is not None}
    assert declared == {"apply_cleaning_rule", "undo_cleaning_rule", "remove_sensors"}
    state = _state()
    with bind_session(state):
        preview = REGISTRY.get("apply_cleaning_rule").dry_run(rule_type="range_check", sensor="Spd_100m", params="{}")
    assert preview["records_affected"] == 10
    assert state.cleaning_log == []


@pytest.fixture
def client(tmp_path: Path):
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def test_the_preview_route_previews_and_only_exists_where_a_dry_run_does(client) -> None:
    test_client, manager = client
    session_id = test_client.post("/api/sessions").json()["session_id"]
    state = manager.get_session(session_id)
    _populate(state)
    headers = {"X-GoKaatru-Session": session_id}
    base = f"/api/sessions/{session_id}/operations"
    body = {"rule_type": "range_check", "sensor": "Spd_100m", "params": "{}"}

    preview = test_client.post(f"{base}/apply_cleaning_rule/preview", headers=headers, json=body)

    assert preview.status_code == 200, preview.text
    assert preview.json()["records_affected"] == 10
    assert state.cleaning_log == []
    assert test_client.post(f"{base}/build_shear_table/preview", headers=headers, json={}).status_code == 404
