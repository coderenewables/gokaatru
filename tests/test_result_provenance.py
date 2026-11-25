"""Results carry how they were made, a reopened project recomputes nothing, and results
from another engine read as stale (P1-12, decisions/0010)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

import server.state.session as session_module
from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager
from tests.test_operation_log import _populate


def _analysed_session(tmp_path: Path):
    manager = SessionManager(base_dir=tmp_path)
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        state = manager.get_session(session_id)
        _populate(state)
        headers = {"X-GoKaatru-Session": session_id}
        pair = json.dumps({"80": "Spd_80m", "100": "Spd_100m"})
        for name, body in [
            ("calculate_shear_timeseries", {"height_sensors": pair}),
            ("build_shear_table", {"aggregation": "momm"}),
            ("extrapolate_to_hub_height", {"hub_height_m": 120.0}),
        ]:
            response = client.post(f"/api/sessions/{session_id}/operations/{name}", headers=headers, json=body)
            assert response.status_code == 200, (name, response.text)
    app.dependency_overrides.clear()
    return session_id, state


def test_a_result_records_the_call_that_made_it(tmp_path: Path) -> None:
    _, state = _analysed_session(tmp_path)

    table = state.derived_provenance["shear_table"]
    assert table["operation"] == "build_shear_table"
    assert table["parameters"] == {"aggregation": "momm"}
    assert table["code_version"] == session_module.ENGINE_VERSION
    logged = state.operation_log[table["seq"] - 1]
    assert (logged["seq"], logged["operation"]) == (table["seq"], "build_shear_table")


def test_a_reopened_project_has_every_result_and_recomputes_nothing(tmp_path: Path) -> None:
    session_id, state = _analysed_session(tmp_path)

    reopened = SessionManager(base_dir=tmp_path).get_session(session_id)

    assert reopened.operation_log == state.operation_log
    assert reopened.derived_versions == state.derived_versions
    assert reopened.derived_provenance == state.derived_provenance
    pd.testing.assert_frame_equal(reopened.shear_table, state.shear_table)
    pd.testing.assert_frame_equal(reopened.timeseries_df, state.timeseries_df, check_freq=False)
    assert reopened.staleness_report() == state.staleness_report()
    assert reopened.stale_artifacts() == []


def test_results_from_another_engine_read_as_stale_after_reopening(tmp_path: Path, monkeypatch) -> None:
    session_id, state = _analysed_session(tmp_path)
    monkeypatch.setattr(session_module, "ENGINE_VERSION", "2099.1")

    reopened = SessionManager(base_dir=tmp_path).get_session(session_id)
    report = reopened.staleness_report()

    built = set(state.derived_provenance)
    assert built and set(report["stale_artifacts"]) == built
    assert all("engine 2099.1" in reason for reason in report["stale_reasons"].values())
    pd.testing.assert_frame_equal(reopened.shear_table, state.shear_table)


def test_an_artifact_stamped_outside_an_operation_has_no_provenance() -> None:
    state = session_module.SessionState()
    state.stamp_derived("shear_table")
    assert state.derived_versions == {"shear_table": 0}
    assert state.derived_provenance == {}
    assert state.staleness_report() == {"data_version": 0, "stale_artifacts": []}
