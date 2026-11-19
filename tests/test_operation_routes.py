"""Generated HTTP routes, one per operation (P1-5, decisions/0009).

Each read operation is run twice on identical synthetic sessions: through FastMCP's own
``tool.run``, serialized as the MCP result crosses the wire, and through its generated
HTTP route. The results must be equal, refusals included; both send NaN as null. A read
operation must also leave the session as it found it, which is what its ``effect`` declares.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.main import mcp
from server.operations import REGISTRY
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session
from server.tools.era5 import _store_coordinate

READ_OPERATIONS = sorted(
    declared.name for declared in REGISTRY if declared.effect == "read" and not declared.network
)
# Reads whose answer depends on the surface by design, so they cannot match across them.
SURFACE_DEPENDENT = {
    "get_operation_log": "it reports the calls made so far, and each surface logs its own, with its own actor",
}

# Values for required parameters, by parameter name. Anything not here keeps its default.
ARGUMENT_VALUES: dict[str, object] = {
    "sensor_name": "Spd_100m",
    "speed_sensor": "Spd_100m",
    "speed_col": "Spd_100m",
    "sensor_a": "Spd_100m",
    "sensor_b": "Spd_80m",
    "direction_sensor": "Dir_100m",
    "sd_sensor": "Spd_100m_sd",
    "sensor_names": "Spd_100m,Spd_80m",
    "sweep_id": "no-such-sweep",
    "name": "no-such-selection",
    "pressure_pa": 101325.0,
    "temperature_k": 288.15,
    "dewpoint_k": 280.0,
    "pressure_col": "Prs_2m",
    "temperature_col": "Tmp_2m",
    "dewpoint_col": "Dew_2m",
    "total_pct": 10.0,
    "measurement_pct": 2.0,
    "vertical_pct": 3.0,
    "mcp_pct": 4.0,
    "future_pct": 5.0,
}


def _populate(state: SessionState) -> None:
    """A mast with three speed heights, one vane, a speed SD and met channels."""
    rng = np.random.default_rng(5)
    index = pd.date_range("2023-01-01", periods=120 * 144, freq="10min", tz="UTC")
    top = rng.weibull(2.0, len(index)) * 8.0
    frame = pd.DataFrame(
        {
            "Spd_100m": top,
            "Spd_80m": top * (80 / 100) ** 0.14,
            "Spd_60m": top * (60 / 100) ** 0.14,
            "Dir_100m": rng.uniform(0, 360, len(index)),
            "Spd_100m_sd": top * 0.1,
            "Prs_2m": rng.normal(101000, 300, len(index)),
            "Tmp_2m": rng.normal(285, 3, len(index)),
            "Dew_2m": rng.normal(280, 2, len(index)),
        },
        index=index,
    )
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        100.0: {"speed_col": "Spd_100m", "dir_col": "Dir_100m", "sd_col": "Spd_100m_sd"},
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None},
        60.0: {"speed_col": "Spd_60m", "dir_col": None, "sd_col": None},
    }
    state.sensor_inventory = {
        "Spd_100m": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Spd_80m": {"height_m": 80.0, "sensor_type": "wind_speed"},
        "Spd_60m": {"height_m": 60.0, "sensor_type": "wind_speed"},
        "Dir_100m": {"height_m": 100.0, "sensor_type": "wind_direction"},
        "Tmp_2m": {"height_m": 2.0, "sensor_type": "temperature"},
        "Prs_2m": {"height_m": 2.0, "sensor_type": "pressure"},
    }
    state.set_measurement_type("mast")
    state.set_hub_height_m(120.0)
    _store_coordinate(state, 55.0, 8.0)


def _arguments(name: str) -> dict[str, object]:
    function = REGISTRY.get(name).fn
    return {
        parameter.name: ARGUMENT_VALUES[parameter.name]
        for parameter in inspect.signature(function).parameters.values()
        if parameter.default is inspect.Parameter.empty
    }


def _fingerprint(state: SessionState) -> dict[str, object]:
    """Everything a read must leave alone: config, versions, data and derived results."""
    frame = state.timeseries_df
    return {
        "runconfig": copy.deepcopy(state.runconfig),
        "data_version": state.data_version,
        "derived_versions": copy.deepcopy(state.derived_versions),
        "columns": list(frame.columns),
        "values": hashlib.sha256(np.ascontiguousarray(frame.to_numpy(dtype=float)).tobytes()).hexdigest(),
        "cleaning_log": copy.deepcopy(state.cleaning_log),
        "ltc_results": sorted(state.ltc_results),
        "shear_table": state.shear_table is not None,
        "roughness_table": state.roughness_table is not None,
        "scenarios": len(state.scenarios),
    }


@pytest.fixture
def client(tmp_path: Path):
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _new_session(client: TestClient, manager: SessionManager) -> tuple[str, SessionState]:
    session_id = client.post("/api/sessions").json()["session_id"]
    state = manager.get_session(session_id)
    _populate(state)
    return session_id, state


def _mcp_result(name: str, state: SessionState, arguments: dict[str, object]) -> tuple[bool, object]:
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    with bind_session(state):
        try:
            direct = REGISTRY.get(name).fn(**arguments)
        except (ValueError, RuntimeError) as exc:
            return False, str(exc)
        del direct
    with bind_session(state):
        result = asyncio.run(tools[name].run(arguments))
    # As it crosses the wire: the MCP result model writes NaN and infinity as null.
    wire = CallToolResult(content=[], structuredContent=result.structured_content).model_dump_json()
    return True, json.loads(wire)["structuredContent"]


@pytest.mark.parametrize("name", READ_OPERATIONS)
def test_a_read_operation_returns_the_same_over_http_as_over_mcp(client, name: str) -> None:
    if name in SURFACE_DEPENDENT:
        pytest.skip(SURFACE_DEPENDENT[name])
    test_client, manager = client
    arguments = _arguments(name)
    _, mcp_state = _new_session(test_client, manager)
    succeeded, expected = _mcp_result(name, mcp_state, arguments)

    session_id, _ = _new_session(test_client, manager)
    response = test_client.post(
        f"/api/sessions/{session_id}/operations/{name}",
        headers={"X-GoKaatru-Session": session_id},
        json=arguments,
    )

    if succeeded:
        assert response.status_code == 200, response.text
        assert response.json() == expected
    else:
        assert response.status_code in (400, 502), response.text
        assert response.json()["detail"] == expected


@pytest.mark.parametrize("name", READ_OPERATIONS)
def test_a_read_operation_leaves_the_session_unchanged(client, name: str) -> None:
    test_client, manager = client
    _, state = _new_session(test_client, manager)
    before = _fingerprint(state)
    with bind_session(state):
        try:
            REGISTRY.get(name).fn(**_arguments(name))
        except (ValueError, RuntimeError):
            pass
    assert _fingerprint(state) == before


def test_an_operation_route_refuses_unknown_and_missing_parameters(client) -> None:
    test_client, manager = client
    session_id, _ = _new_session(test_client, manager)
    headers = {"X-GoKaatru-Session": session_id}
    url = f"/api/sessions/{session_id}/operations/compute_weibull_params"

    assert test_client.post(url, headers=headers, json={"sensor_name": "Spd_100m", "extra": 1}).status_code == 422
    assert test_client.post(url, headers=headers, json={}).status_code == 422
    assert test_client.post(url, headers=headers).status_code == 422
    assert test_client.post(url, headers=headers, json={"sensor_name": "Spd_100m"}).status_code == 200


def test_the_operation_list_describes_every_declaration(client) -> None:
    test_client, _ = client
    listed = {item["name"]: item for item in test_client.get("/api/operations").json()}
    assert set(listed) == REGISTRY.names()
    declared = REGISTRY.get("build_shear_table")
    assert listed["build_shear_table"]["effect"] == "change"
    assert listed["build_shear_table"]["stage"] == "shear"
    assert listed["build_shear_table"]["parameters"] == declared.parameters
