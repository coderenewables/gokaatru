"""test_api_workflow_execution - Phase 3 workflow execution API tests.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.core.executor import WorkflowExecutor, _loads_lenient, _tool_registry
from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager
from server.tools.shear import calculate_shear_timeseries


@pytest.fixture
def execution_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client with temporary session storage for execution tests."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _create_session(client: TestClient) -> tuple[str, dict[str, str]]:
    """Create one browser session and return session id plus required header payload."""
    create_response = client.post("/api/sessions")
    assert create_response.status_code == 200
    session_id = create_response.json()["session_id"]
    return session_id, {"X-GoKaatru-Session": session_id}


def _palette_tool_template_ids() -> set[str]:
    """Parse node template tool ids from the workflow palette registry file."""
    content = Path("frontend/src/lib/nodeRegistry.ts").read_text(encoding="utf-8")
    blocks = re.findall(r"toolFunctions:\s*\[(.*?)\]", content, flags=re.DOTALL)
    ids: set[str] = set()
    for block in blocks:
        ids.update(re.findall(r'"([a-z0-9_]+)"', block))
    return ids


def test_executor_dispatch_registry_covers_palette_tools() -> None:
    """Ensure every palette tool template id resolves to a backend callable."""
    template_ids = _palette_tool_template_ids()
    registry = _tool_registry()
    missing = sorted(template_id for template_id in template_ids if template_id not in registry)
    assert missing == []


def test_loads_lenient_repairs_windows_paths_with_unicode_prefix() -> None:
    """Repair raw Windows paths where a directory name begins with the JSON unicode escape prefix."""
    payload = r'{"file_path":"D:\gokaatru\data\uploads\HKW-B-FLS-Boxkite_timeseries_data.csv","alias":"HKW-B-FLS-Boxkite"}'

    result = _loads_lenient(payload)

    assert result == {
        "file_path": r"D:\gokaatru\data\uploads\HKW-B-FLS-Boxkite_timeseries_data.csv",
        "alias": "HKW-B-FLS-Boxkite",
    }


def test_build_kwargs_coerces_list_for_postponed_str_annotations(
    execution_client: tuple[TestClient, SessionManager],
) -> None:
    """Coerce list params into JSON string kwargs when tool annotations are postponed strings."""
    client, manager = execution_client
    session_id, _headers = _create_session(client)
    state = manager.get_session(session_id)
    executor = WorkflowExecutor(state, [], [])

    kwargs = executor._build_kwargs(
        calculate_shear_timeseries,
        {"height_sensors": ["Spd_180m", "Spd_140m"]},
    )

    assert kwargs == {"height_sensors": '["Spd_180m", "Spd_140m"]'}


def test_sensors_endpoint_falls_back_to_timeseries_inference_without_datamodel(
    execution_client: tuple[TestClient, SessionManager],
) -> None:
    """Return inferred sensors from timeseries columns when datamodel mapping has not been loaded."""
    client, manager = execution_client
    session_id, headers = _create_session(client)
    state = manager.get_session(session_id)

    index = pd.date_range("2024-01-01", periods=4, freq="10min")
    state.timeseries_df = pd.DataFrame(
        {
            "Spd_180m": [8.0, 8.2, 8.1, 7.9],
            "Dir_180m": [0.0, 45.0, 90.0, 135.0],
        },
        index=index,
    )
    state.sensor_mapping = {}

    response = client.get(f"/api/sessions/{session_id}/sensors", headers=headers)
    assert response.status_code == 200
    sensors = response.json()["sensors"]
    names = {item["name"] for item in sensors}
    assert "Spd_180m" in names
    assert "Dir_180m" in names


def test_workflow_execute_and_status(execution_client: tuple[TestClient, SessionManager]) -> None:
    """Execute an in-memory workflow graph and verify status snapshot fields."""
    client, _manager = execution_client
    session_id, headers = _create_session(client)

    payload = {
        "mode": "auto",
        "nodes": [
            {"id": "dataset-1", "kind": "dataset", "label": "Dataset", "config": {}},
            {
                "id": "op-1",
                "kind": "operation",
                "label": "Placeholder",
                    "template_id": "windkit_create_sector_coords",
                "config": {"params_json": "{}"},
            },
        ],
        "edges": [{"source": "dataset-1", "target": "op-1"}],
    }

    execute_response = client.post(f"/api/sessions/{session_id}/workflow/execute", headers=headers, json=payload)
    assert execute_response.status_code == 200
    execute_payload = execute_response.json()
    assert execute_payload["status"] == "ok"
    assert execute_payload["node_statuses"]["dataset-1"] == "done"
    assert execute_payload["node_statuses"]["op-1"] == "done"
    assert len(execute_payload["events"]) >= 4

    status_response = client.get(f"/api/sessions/{session_id}/workflow/status", headers=headers)
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["run_id"] == execute_payload["run_id"]
    assert status_payload["is_running"] is False
    assert status_payload["cancelled"] is False
    assert status_payload["node_statuses"]["op-1"] == "done"


def test_workflow_step_respects_input_status(execution_client: tuple[TestClient, SessionManager]) -> None:
    """Run manual step mode and ensure the next pending node completes."""
    client, _manager = execution_client
    session_id, headers = _create_session(client)

    payload = {
        "mode": "manual",
        "nodes": [
            {
                "id": "op-1",
                "kind": "operation",
                "label": "First",
                "template_id": "windkit_create_sector_coords",
                "config": {"params_json": "{}"},
                "status": "done",
            },
            {
                "id": "op-2",
                "kind": "operation",
                "label": "Second",
                "template_id": "windkit_create_sector_coords",
                "config": {"params_json": "{}"},
                "status": "pending",
            },
        ],
        "edges": [{"source": "op-1", "target": "op-2"}],
    }

    step_response = client.post(f"/api/sessions/{session_id}/workflow/execute/step", headers=headers, json=payload)
    assert step_response.status_code == 200
    step_payload = step_response.json()
    assert step_payload["status"] == "ok"
    assert step_payload["node_statuses"]["op-1"] == "done"
    assert step_payload["node_statuses"]["op-2"] == "done"


def test_workflow_stream_endpoint_emits_events(execution_client: tuple[TestClient, SessionManager]) -> None:
    """Stream workflow execution and verify SSE event frames are returned."""
    client, _manager = execution_client
    session_id, headers = _create_session(client)

    payload = {
        "mode": "auto",
        "nodes": [
            {
                "id": "op-1",
                "kind": "operation",
                "label": "Only Node",
                "template_id": "windkit_create_sector_coords",
                "config": {"params_json": "{}"},
            }
        ],
        "edges": [],
    }

    with client.stream("POST", f"/api/sessions/{session_id}/workflow/execute/stream", headers=headers, json=payload) as response:
        assert response.status_code == 200
        lines = [line for line in response.iter_lines() if line]

    assert any("run_started" in line for line in lines)
    assert any("run_finished" in line for line in lines)


def test_workflow_capabilities_endpoint_returns_signature_hints(
    execution_client: tuple[TestClient, SessionManager],
) -> None:
    """Return template dispatch signature hints for frontend node parameter assistance."""
    client, _manager = execution_client
    session_id, headers = _create_session(client)

    response = client.get(f"/api/sessions/{session_id}/workflow/capabilities", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, list)
    assert len(capabilities) > 0

    by_template = {item["template_id"]: item for item in capabilities}
    assert "parse_timeseries" in by_template
    assert "windkit_create_sector_coords" in by_template

    parse_timeseries = by_template["parse_timeseries"]
    assert parse_timeseries["required_params"] == ["file_path"]
    assert parse_timeseries["optional_params"] == []

    sector_coords = by_template["windkit_create_sector_coords"]
    assert sector_coords["required_params"] == []
    assert "bins" in sector_coords["optional_params"]
    assert "start" in sector_coords["optional_params"]


def test_workflow_branch_fork_clones_session_state(
    execution_client: tuple[TestClient, SessionManager],
) -> None:
    """Fork workflow branch session and verify cloned state with isolated session identity."""
    client, manager = execution_client
    parent_session_id, parent_headers = _create_session(client)

    config_response = client.put(
        f"/api/sessions/{parent_session_id}/config",
        headers=parent_headers,
        json={
            "updates": [
                {"key": "project_name", "value": "Forked Ridge"},
                {"key": "location.latitude", "value": 52.4},
                {"key": "location.longitude", "value": 4.9},
                {"key": "hub_height_m", "value": 150},
            ]
        },
    )
    assert config_response.status_code == 200

    fork_response = client.post(
        f"/api/sessions/{parent_session_id}/workflow/branches/fork",
        headers=parent_headers,
        json={"name": "branch-a", "from_node_id": "op-3"},
    )
    assert fork_response.status_code == 200
    fork_payload = fork_response.json()
    assert fork_payload["status"] == "ok"
    assert fork_payload["parent_session_id"] == parent_session_id
    assert fork_payload["from_node_id"] == "op-3"
    assert fork_payload["branch_name"] == "branch-a"

    branch_session_id = fork_payload["branch_session_id"]
    assert branch_session_id != parent_session_id

    branch_headers = {"X-GoKaatru-Session": branch_session_id}
    branch_summary_response = client.get(f"/api/sessions/{branch_session_id}", headers=branch_headers)
    assert branch_summary_response.status_code == 200
    branch_summary = branch_summary_response.json()
    assert branch_summary["project_name"] == "Forked Ridge"
    assert branch_summary["hub_height_m"] == 150

    parent_state = manager.get_session(parent_session_id)
    branch_state = manager.get_session(branch_session_id)
    assert parent_state is not branch_state
    assert parent_state.runconfig == branch_state.runconfig


def test_workflow_compare_returns_metrics_diffs_and_plots(
    execution_client: tuple[TestClient, SessionManager],
) -> None:
    """Compare parent and branch sessions and verify dashboard payload sections are populated."""
    client, manager = execution_client
    parent_session_id, parent_headers = _create_session(client)

    fork_response = client.post(
        f"/api/sessions/{parent_session_id}/workflow/branches/fork",
        headers=parent_headers,
        json={"name": "compare-branch"},
    )
    assert fork_response.status_code == 200
    branch_session_id = fork_response.json()["branch_session_id"]

    parent_state = manager.get_session(parent_session_id)
    branch_state = manager.get_session(branch_session_id)

    parent_state.runconfig = {"hub_height_m": 150, "ltc_source": "speedsort", "location": {"latitude": 52.4}}
    branch_state.runconfig = {"hub_height_m": 120, "ltc_source": "variance_ratio", "location": {"latitude": 52.4}}

    parent_state.timeseries_df = pd.DataFrame({"Spd_100m": [8.2, 8.5, 8.8, 9.0], "Dir_100m": [0, 45, 180, 270]})
    branch_state.timeseries_df = pd.DataFrame({"Spd_100m": [7.1, 7.3, 7.4, 7.8], "Dir_100m": [20, 60, 200, 300]})

    parent_state.latest_uncertainty = {
        "total_uncertainty_pct": 8.7,
        "components": {
            "measurement": 2.0,
            "vertical_extrapolation": 3.4,
            "mcp": 2.1,
            "future_variability": 1.2,
        },
        "p_factors": {"p50": 1.0, "p75": 0.94, "p90": 0.88, "p99": 0.81},
    }
    branch_state.latest_uncertainty = {
        "total_uncertainty_pct": 9.2,
        "components": {
            "measurement": 2.0,
            "vertical_extrapolation": 3.9,
            "mcp": 2.5,
            "future_variability": 1.3,
        },
        "p_factors": {"p50": 1.0, "p75": 0.93, "p90": 0.87, "p99": 0.8},
    }

    compare_response = client.post(
        f"/api/sessions/{parent_session_id}/workflow/compare",
        headers=parent_headers,
        json={"branch_session_ids": [branch_session_id]},
    )
    assert compare_response.status_code == 200
    payload = compare_response.json()

    assert payload["status"] == "ok"
    assert payload["session_ids"] == [parent_session_id, branch_session_id]
    assert len(payload["metrics"]) >= 6
    assert f"{parent_session_id}<->{branch_session_id}" in payload["config_diff"]

    diff_entries = payload["config_diff"][f"{parent_session_id}<->{branch_session_id}"]
    assert any(entry["key"] == "hub_height_m" for entry in diff_entries)

    assert payload["plots"]["weibull"] is not None
    assert payload["plots"]["ltc_scatter"] is not None
    assert payload["plots"]["uncertainty_tornado"] is not None
    assert len(payload["plots"]["windrose"]) == 2


def test_workflow_snapshot_save_list_and_load(
    execution_client: tuple[TestClient, SessionManager],
) -> None:
    """Persist a workflow snapshot to disk and round-trip it through list/load routes."""
    client, manager = execution_client
    session_id, headers = _create_session(client)

    snapshot_payload = {
        "version": 1,
        "activeBranchId": "main",
        "branches": [
            {
                "id": "main",
                "name": "main",
                "color": "#0b7a6f",
                "sessionId": None,
                "forkPoint": None,
            }
        ],
        "branchStates": {
            "main": {
                "nodes": [],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 0.8},
            }
        },
        "datasets": [],
    }

    save_response = client.put(
        f"/api/sessions/{session_id}/workflow/snapshots/phase6-main",
        headers=headers,
        json={"snapshot": snapshot_payload},
    )
    assert save_response.status_code == 200
    assert save_response.json()["name"] == "phase6-main"

    list_response = client.get(f"/api/sessions/{session_id}/workflow/snapshots", headers=headers)
    assert list_response.status_code == 200
    listed = list_response.json()["snapshots"]
    assert len(listed) == 1
    assert listed[0]["name"] == "phase6-main"

    load_response = client.get(f"/api/sessions/{session_id}/workflow/snapshots/phase6-main", headers=headers)
    assert load_response.status_code == 200
    assert load_response.json()["name"] == "phase6-main"
    assert load_response.json()["snapshot"] == snapshot_payload

    state = manager.get_session(session_id)
    assert state.workspace_dir is not None
    assert (state.workspace_dir / "workflows" / "phase6-main.json").exists()
