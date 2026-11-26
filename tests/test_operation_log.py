"""Every operation call is logged, every change is saved, and the log survives a restart
(P1-10, decisions/0010)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import server.api.routes.chat as chat_route
import server.tools.brighthub as brighthub_tools
from server.api.deps import get_session_manager
from server.api.main import create_app
from server.operations import REDACTED, REGISTRY
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session


def _populate(state: SessionState) -> None:
    rng = np.random.default_rng(11)
    index = pd.date_range("2023-01-01", periods=60 * 144, freq="10min", tz="UTC")
    top = rng.weibull(2.0, len(index)) * 8.0
    top[100:110] = 75.0
    frame = pd.DataFrame(
        {"Spd_100m": top, "Spd_80m": top * 0.8 ** 0.14, "Dir_100m": rng.uniform(0, 360, len(index))}, index=index
    )
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        100.0: {"speed_col": "Spd_100m", "dir_col": "Dir_100m", "sd_col": None},
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None},
    }
    state.sensor_inventory = {
        "Spd_100m": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Spd_80m": {"height_m": 80.0, "sensor_type": "wind_speed"},
    }
    state.set_hub_height_m(120.0)


def _bare_state() -> SessionState:
    state = SessionState()
    state.reset()
    _populate(state)
    return state


def _call(state: SessionState, name: str, **arguments):
    with bind_session(state):
        return REGISTRY.get(name).fn(**arguments)


def test_a_call_records_who_what_and_the_data_versions() -> None:
    state = _bare_state()
    _call(state, "compute_weibull_params", sensor_name="Spd_100m")
    _call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_100m", params="{}")

    read, change = state.operation_log
    assert read["seq"] == 1 and change["seq"] == 2
    assert read["operation"] == "compute_weibull_params" and read["effect"] == "read"
    assert read["actor"] == "direct"
    assert read["parameters"] == {"sensor_name": "Spd_100m", "method": "wasp_m1_m3"}
    assert read["data_version_before"] == read["data_version_after"]
    assert change["effect"] == "change" and change["status"] == "ok"
    assert change["data_version_after"] == change["data_version_before"] + 1
    assert change["code_version"]


def test_a_failed_call_is_logged_and_still_raises() -> None:
    state = _bare_state()
    with pytest.raises(ValueError):
        _call(state, "compute_weibull_params", sensor_name="Nope")
    entry = state.operation_log[-1]
    assert entry["status"] == "error"
    assert "Nope" in entry["error"]


def test_credentials_are_redacted_in_the_log_and_never_reach_disk(tmp_path: Path, monkeypatch) -> None:
    state = _bare_state()
    state.workspace_dir = tmp_path

    _call(state, "earthdatahub_set_credential", pat="EDH-SECRET-41d9")

    def refuse(client_id: str, client_secret: str) -> str:
        raise RuntimeError(f"rejected {client_id}:{client_secret}")

    monkeypatch.setattr(brighthub_tools, "authenticate", refuse)
    with pytest.raises(RuntimeError):
        _call(state, "brighthub_login", client_id="BH-ID-77", client_secret="BH-SECRET-2c8")

    stored, failed = state.operation_log[-2:]
    assert stored["parameters"] == {"pat": REDACTED}
    assert failed["parameters"] == {"client_id": REDACTED, "client_secret": REDACTED}
    assert "BH-SECRET-2c8" not in failed["error"] and "BH-ID-77" not in failed["error"]
    for path in tmp_path.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            for secret in (b"EDH-SECRET-41d9", b"BH-SECRET-2c8", b"BH-ID-77"):
                assert secret not in content, (path, secret)


@pytest.fixture
def api(tmp_path: Path):
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as client:
        yield client, manager, tmp_path / "sessions"
    app.dependency_overrides.clear()


def _session(client: TestClient, manager: SessionManager) -> tuple[str, dict[str, str], SessionState]:
    session_id = client.post("/api/sessions").json()["session_id"]
    state = manager.get_session(session_id)
    _populate(state)
    return session_id, {"X-GoKaatru-Session": session_id}, state


def test_a_pipeline_run_over_http_is_logged_in_order_and_survives_a_restart(api) -> None:
    client, manager, base_dir = api
    session_id, headers, state = _session(client, manager)
    steps = [
        ("apply_cleaning_rule", {"rule_type": "range_check", "sensor": "Spd_100m", "params": "{}"}),
        ("calculate_shear_timeseries", {"height_sensors": json.dumps({"80": "Spd_80m", "100": "Spd_100m"})}),
        ("build_shear_table", {}),
        ("extrapolate_to_hub_height", {"hub_height_m": 120.0}),
        ("compute_weibull_params", {"sensor_name": "Spd_120m_hub"}),
    ]
    for name, body in steps:
        response = client.post(f"/api/sessions/{session_id}/operations/{name}", headers=headers, json=body)
        assert response.status_code == 200, (name, response.text)

    logged = [(entry["operation"], entry["actor"]) for entry in state.operation_log]
    assert logged == [(name, "user") for name, _ in steps]

    reopened = SessionManager(base_dir=base_dir).get_session(session_id)
    # Saved after the last change; the read after it is in memory only until the next save.
    assert [entry["operation"] for entry in reopened.operation_log] == [name for name, _ in steps[:4]]
    pd.testing.assert_frame_equal(reopened.timeseries_df, state.timeseries_df, check_freq=False)
    pd.testing.assert_frame_equal(reopened.shear_table, state.shear_table)


def test_the_assistant_is_recorded_as_the_actor(api, monkeypatch) -> None:
    client, manager, _ = api
    session_id, headers, state = _session(client, manager)
    replies = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {"id": "1", "type": "function", "function": {"name": "list_sensors", "arguments": "{}"}}
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {"choices": [{"message": {"role": "assistant", "content": "Two sensors."}, "finish_reason": "stop"}]},
        ]
    )
    monkeypatch.setattr(chat_route, "_call_llm", lambda *args, **kwargs: next(replies))

    response = client.post(
        f"/api/sessions/{session_id}/chat",
        headers=headers,
        json={
            "api_key": "test-key",
            "provider": "openai",
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "?"}],
        },
    )

    assert response.status_code == 200, response.text
    assert state.operation_log[-1]["operation"] == "list_sensors"
    assert state.operation_log[-1]["actor"] == "assistant:openai/gpt-4o"


def test_a_change_through_a_hand_written_route_is_logged_and_saved(api) -> None:
    client, manager, base_dir = api
    session_id, headers, state = _session(client, manager)

    response = client.put(
        f"/api/sessions/{session_id}/config",
        headers=headers,
        json={"updates": [{"key": "hub_height_m", "value": 110}]},
    )

    assert response.status_code == 200, response.text
    entry = state.operation_log[-1]
    assert entry["operation"] == "http PUT /api/sessions/{session_id}/config"
    assert entry["actor"] == "user" and entry["parameters"] == {}
    reopened = SessionManager(base_dir=base_dir).get_session(session_id)
    assert reopened.operation_log[-1]["operation"] == entry["operation"]
    assert reopened.hub_height_m == 110
