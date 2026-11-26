"""A session's state survives on disk and comes back identical (P1-9, decisions/0010)."""
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.state.manager import SessionManager
from server.state.project import (
    CATALOGUE_NAME,
    EXCLUDED_FIELDS,
    ProjectIntegrityError,
    ProjectStore,
    persisted_fields,
)
from server.state.session import SessionState
from server.tools.era5 import _store_coordinate


def _rich_state(workspace: Path) -> SessionState:
    rng = np.random.default_rng(3)
    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    index = pd.date_range("2023-01-01", periods=2000, freq="10min", tz="UTC")
    frame = pd.DataFrame({"Spd_100m": rng.weibull(2.0, 2000) * 8, "Dir_100m": rng.uniform(0, 360, 2000)}, index=index)
    frame.iloc[5:9, 0] = np.nan
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {100.0: {"speed_col": "Spd_100m", "dir_col": "Dir_100m", "sd_col": None}}
    state.sensor_inventory = {"Spd_100m": {"height_m": 100.0, "sensor_type": "wind_speed", "date_from": None}}
    state.cleaning_log = [{"rule_type": "range_check", "sensor": "Spd_100m", "records_affected": 4, "params": {}}]
    state.shear_table = pd.DataFrame(rng.uniform(0.05, 0.3, (12, 24)), index=range(1, 13), columns=range(24))
    state.shear_table.columns.name = "hour"
    state.timezone = timezone(timedelta(hours=5, minutes=30))
    _store_coordinate(state, 55.5, 7.75)
    state.measurement_type = "mast"
    state.hub_height_m = 120.0
    long_index = pd.date_range("2015-01-01", periods=500, freq="h", tz="UTC")
    state.era5_data = {"55.25_7.75": pd.DataFrame({"Spd_100m": rng.uniform(2, 15, 500)}, index=long_index)}
    state.reanalysis_interpolated = {"era5": state.era5_data["55.25_7.75"].copy()}
    state.ltc_results = {
        "variance_ratio": {
            "df": pd.DataFrame({"Timestamp": long_index, "corrected_wind_speed": rng.uniform(2, 15, 500)}),
            "metrics": {"slope": 1.08, "r_squared": float("nan"), "concurrent_points": 450},
            "file": "",
            "persisted": False,
        }
    }
    state.data_version = 4
    state.derived_versions = {"shear_table": 3, "ltc:variance_ratio": 4}
    state.scenarios = [{"name": "base", "hub_height_m": 120.0}]
    state.runconfig = {"hub_height_m": 120.0, "site": {"timezone": "UTC+05:30"}}
    return state


def _assert_same(expected: SessionState, actual: SessionState) -> None:
    for name in persisted_fields(expected):
        left, right = getattr(expected, name), getattr(actual, name)
        _compare(left, right, name)


def _compare(left, right, path: str) -> None:
    if isinstance(left, pd.DataFrame):
        pd.testing.assert_frame_equal(left, right, check_freq=False, obj=path)
    elif isinstance(left, dict):
        assert isinstance(right, dict) and left.keys() == right.keys(), path
        for key in left:
            _compare(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        assert isinstance(right, list) and len(left) == len(right), path
        for index, (a, b) in enumerate(zip(left, right)):
            _compare(a, b, f"{path}[{index}]")
    elif isinstance(left, float) and np.isnan(left):
        assert isinstance(right, float) and np.isnan(right), path
    else:
        assert left == right, f"{path}: {left!r} != {right!r}"


def test_a_saved_session_loads_back_identical(tmp_path: Path) -> None:
    original = _rich_state(tmp_path)
    ProjectStore(tmp_path).save(original)

    restored = SessionState()
    assert ProjectStore(tmp_path).load(restored) is True
    _assert_same(original, restored)
    assert restored.sensor_mapping == {100.0: {"speed_col": "Spd_100m", "dir_col": "Dir_100m", "sd_col": None}}
    assert list(restored.shear_table.columns) == list(range(24))
    assert restored.shear_table.columns.name == "hour"


def test_an_unchanged_frame_is_not_written_again(tmp_path: Path) -> None:
    state = _rich_state(tmp_path)
    store = ProjectStore(tmp_path)
    first = store.save(state)
    second = store.save(state)

    assert first["frames_written"] > 0
    assert second["frames_written"] == 0
    assert second["frames_reused"] == first["frames_written"] + first["frames_reused"]

    state.timeseries_df.iloc[0, 0] = 99.0
    assert store.save(state)["frames_written"] == 1


def test_a_field_the_session_no_longer_has_is_not_restored(tmp_path: Path) -> None:
    """Projects saved before P3-17d hold the retired Canvas's run state; it is left on disk."""
    state = _rich_state(tmp_path)
    state.workflow_runs = [{"run_id": "old"}]
    ProjectStore(tmp_path).save(state)

    restored = SessionState()
    assert ProjectStore(tmp_path).load(restored) is True
    assert not hasattr(restored, "workflow_runs")
    del state.workflow_runs
    _assert_same(state, restored)


def test_credentials_are_never_written(tmp_path: Path) -> None:
    state = _rich_state(tmp_path)
    state.brighthub_token = "BRIGHTHUB-SECRET-7a1f"
    state.earthdatahub_pat = "EDH-SECRET-93c2"
    ProjectStore(tmp_path).save(state)

    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert b"BRIGHTHUB-SECRET-7a1f" not in content, path
            assert b"EDH-SECRET-93c2" not in content, path
    restored = SessionState()
    ProjectStore(tmp_path).load(restored)
    assert restored.brighthub_token is None and restored.earthdatahub_pat is None


def test_every_exclusion_names_a_real_field_and_says_why() -> None:
    fields = set(vars(SessionState()))
    assert set(EXCLUDED_FIELDS) <= fields
    assert all(reason.strip() for reason in EXCLUDED_FIELDS.values())
    assert {"brighthub_token", "earthdatahub_pat"} <= set(EXCLUDED_FIELDS)


def test_a_changed_or_missing_raw_input_refuses_the_project(tmp_path: Path) -> None:
    state = _rich_state(tmp_path)
    (tmp_path / "uploads").mkdir()
    raw = tmp_path / "uploads" / "mast.csv"
    raw.write_text("Timestamp,Spd_100m\n2023-01-01 00:00,7.1\n", encoding="utf-8")
    store = ProjectStore(tmp_path)
    assert store.save(state)["raw_files_recorded"] == 1

    raw.write_text("Timestamp,Spd_100m\n2023-01-01 00:00,9.9\n", encoding="utf-8")
    with pytest.raises(ProjectIntegrityError, match="changed since they were recorded: mast.csv"):
        store.load(SessionState())

    store.record_raw("mast.csv")
    assert store.load(SessionState()) is True

    raw.unlink()
    with pytest.raises(ProjectIntegrityError, match="missing: mast.csv"):
        store.load(SessionState())


def test_a_restarted_manager_reopens_the_project(tmp_path: Path) -> None:
    first = SessionManager(base_dir=tmp_path)
    state = first.create_session()
    populated = _rich_state(state.workspace_dir)
    populated.session_id = state.session_id
    ProjectStore(state.workspace_dir).save(populated)

    restarted = SessionManager(base_dir=tmp_path)
    reopened = restarted.get_session(state.session_id)

    _assert_same(populated, reopened)
    assert (state.workspace_dir / CATALOGUE_NAME).exists()


def test_the_session_proxy_saves_the_bound_session(tmp_path: Path) -> None:
    from server.state.session import bind_session, session

    state = _rich_state(tmp_path)
    with bind_session(state):
        ProjectStore(tmp_path).save(session)
    restored = SessionState()
    ProjectStore(tmp_path).load(restored)
    _assert_same(state, restored)


def test_a_fully_analysed_campaign_round_trips(tmp_path: Path) -> None:
    """Launakalana through cleaning, shear, extrapolation and every correction, saved and
    reopened: every field the session holds comes back identical."""
    from server.state.session import get_active_session
    from tests import published_numbers as harness

    campaign = harness.CAMPAIGNS["launakalana"]
    missing = campaign.missing_files()
    if missing:
        pytest.skip(f"campaign files not present: {missing[0]}")
    recorder = harness.Recorder()
    harness._load(campaign, recorder)
    harness._load_reanalysis(campaign, recorder)
    harness._clean(campaign, recorder)
    harness._shear(campaign, recorder)
    hub = harness._extrapolate(campaign, recorder)
    harness._long_term(campaign, recorder, hub)
    analysed = get_active_session()

    ProjectStore(tmp_path).save(analysed)
    restored = SessionState()
    ProjectStore(tmp_path).load(restored)

    _assert_same(analysed, restored)
    assert set(restored.ltc_results) >= {"linear_least_squares", "speedsort", "variance_ratio"}


def test_the_api_refuses_a_project_whose_raw_input_changed(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from server.api.deps import get_session_manager
    from server.api.main import create_app

    first = SessionManager(base_dir=tmp_path)
    state = first.create_session()
    (state.workspace_dir / "uploads" / "mast.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    ProjectStore(state.workspace_dir).save(_rich_state(state.workspace_dir))
    (state.workspace_dir / "uploads" / "mast.csv").write_text("a,b\n1,3\n", encoding="utf-8")

    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: SessionManager(base_dir=tmp_path)
    with TestClient(app) as client:
        response = client.get(
            f"/api/sessions/{state.session_id}/config", headers={"X-GoKaatru-Session": state.session_id}
        )
    assert response.status_code == 409
    assert "mast.csv" in response.json()["detail"]


def test_concurrent_saves_of_one_project_leave_it_loadable(tmp_path: Path) -> None:
    """The interface sends several changing requests at once. Two saves wrote the same frame
    through one temporary name and the rename failed on Windows (found by the Playwright run);
    unserialised, one save's clean-up could also delete a frame another had just recorded."""
    from concurrent.futures import ThreadPoolExecutor

    states = []
    for index in range(8):
        state = _rich_state(tmp_path)
        state.timeseries_df.iloc[0, 0] = float(index)
        states.append(state)
    store = ProjectStore(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store.save, states * 3))

    restored = SessionState()
    assert store.load(restored) is True
    assert restored.timeseries_df.iloc[0, 0] in {float(index) for index in range(8)}
    assert not list((tmp_path / "working").glob("*.tmp"))


def test_the_catalogue_records_frames_by_content_hash(tmp_path: Path) -> None:
    state = _rich_state(tmp_path)
    ProjectStore(tmp_path).save(state)
    import sqlite3

    with sqlite3.connect(tmp_path / CATALOGUE_NAME) as connection:
        rows = dict(connection.execute("SELECT path, sha256 FROM frames").fetchall())
        schema = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    # The fixture's working and raw frames hold the same data, so they are stored once.
    assert rows["timeseries_df"] == rows["raw_timeseries_df"]
    assert json.loads(schema) == 1
    files = {path.stem for path in (tmp_path / "working").glob("*.parquet")}
    assert files == set(rows.values())
