"""test_phase10 — Verification tests for GoKaatru Phase 10 scenarios and dashboard summaries.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager
from server.state.session import SessionState, session
from server.tools.visualization import _plot_scenario_comparison


@pytest.fixture
def api_client(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client backed by a temporary session manager."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _seed_scenario_ready_state(state: SessionState) -> None:
    """Populate one session with the minimum LTC and uncertainty data needed to save scenarios."""
    state.set_hub_height_m(150)
    state.runconfig["shear_aggregation"] = "momm"
    state.sensor_mapping = {
        100.0: {"speed_col": "Spd_100m", "dir_col": None, "sd_col": None, "temp_col": None, "pressure_col": None},
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None, "temp_col": None, "pressure_col": None},
    }
    state.ltc_results["linear_least_squares"] = {
        "df": pd.DataFrame(
            {
                "Timestamp": pd.date_range("2020-01-31", periods=3, freq="ME"),
                "ERA5_original": [8.0, 8.3, 8.4],
                "corrected_wind_speed": [8.4, 8.6, 8.8],
            }
        ),
        "metrics": {"r_squared": 0.93},
        "file": "results/lls.csv",
    }
    state.ensemble_df = pd.DataFrame(
        {
            "Timestamp": pd.date_range("2020-01-31", periods=3, freq="ME"),
            "Ensemble_Speed": [8.45, 8.55, 8.7],
        }
    )
    state.latest_uncertainty = {
        "total_uncertainty_pct": 8.2,
        "components": {
            "measurement": 2.1,
            "vertical_extrapolation": 1.8,
            "mcp": 4.2,
            "future_variability": 5.1,
        },
        "p_factors": {"p50": 1.0, "p75": 0.9447, "p90": 0.8949, "p99": 0.8093},
        "inputs": {
            "measurement_height_m": 100.0,
            "hub_height_m": 150.0,
            "shear_method": "simple_power_law",
            "mcp_r_squared": 0.9,
            "concurrent_months": 12.0,
            "iav_pct": 6.0,
            "algorithm": "linear_least_squares",
            "is_interpolation": False,
        },
    }


def test_save_scenario_captures_state(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify saving a scenario snapshots the current config and result outputs."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    _seed_scenario_ready_state(state)

    response = client.post(f"/api/sessions/{session_id}/scenarios", headers=headers, json={"name": "Base case"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "Base case"
    assert state.scenarios[0]["config"]["ltc_algorithm"] == "linear_least_squares"
    assert state.scenarios[0]["results"]["total_uncertainty_pct"] == 8.2


def test_list_scenarios_returns_all(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify listing scenarios returns every saved scenario in order."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    _seed_scenario_ready_state(state)

    for name in ["Base", "Tall hub", "Low shear"]:
        response = client.post(f"/api/sessions/{session_id}/scenarios", headers=headers, json={"name": name})
        assert response.status_code == 200

    response = client.get(f"/api/sessions/{session_id}/scenarios", headers=headers)

    assert response.status_code == 200
    assert [scenario["name"] for scenario in response.json()["scenarios"]] == ["Base", "Tall hub", "Low shear"]


def test_delete_scenario_removes_entry(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify deleting one scenario removes it from the saved list."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    _seed_scenario_ready_state(state)
    client.post(f"/api/sessions/{session_id}/scenarios", headers=headers, json={"name": "Scenario A"})
    client.post(f"/api/sessions/{session_id}/scenarios", headers=headers, json={"name": "Scenario B"})

    delete_response = client.delete(f"/api/sessions/{session_id}/scenarios/0", headers=headers)
    list_response = client.get(f"/api/sessions/{session_id}/scenarios", headers=headers)

    assert delete_response.status_code == 200
    assert [scenario["name"] for scenario in list_response.json()["scenarios"]] == ["Scenario B"]


def test_scenario_comparison_plot() -> None:
    """Verify the scenario comparison plot renders grouped bars and the uncertainty overlay."""
    session.scenarios = [
        {
            "name": "Base",
            "created_at": "2026-04-09T00:00:00+00:00",
            "config": {},
            "results": {"long_term_mean_speed": 8.5, "p75": 0.95, "p90": 0.9, "total_uncertainty_pct": 8.0},
        },
        {
            "name": "Alternate",
            "created_at": "2026-04-09T00:01:00+00:00",
            "config": {},
            "results": {"long_term_mean_speed": 8.8, "p75": 0.94, "p90": 0.89, "total_uncertainty_pct": 8.6},
        },
    ]

    result = _plot_scenario_comparison(session)
    parsed = json.loads(result["plotly_json"])
    trace_types = [trace["type"] for trace in parsed["data"]]

    assert trace_types.count("bar") == 3
    assert trace_types.count("scatter") == 1


def test_scenario_without_uncertainty_fails(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify scenario creation is rejected until uncertainty has been calculated."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    _seed_scenario_ready_state(state)
    state.latest_uncertainty = None

    response = client.post(f"/api/sessions/{session_id}/scenarios", headers=headers, json={"name": "Missing uncertainty"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Run uncertainty before saving a scenario"


def test_summary_includes_scenario_count(api_client: tuple[TestClient, SessionManager]) -> None:
    """Verify the summary endpoint includes the number of saved scenarios."""
    client, manager = api_client
    session_id = client.post("/api/sessions").json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}
    state = manager.get_session(session_id)
    _seed_scenario_ready_state(state)
    client.post(f"/api/sessions/{session_id}/scenarios", headers=headers, json={"name": "Scenario summary"})

    response = client.get(f"/api/sessions/{session_id}/summary", headers=headers)

    assert response.status_code == 200
    assert response.json()["scenario_count"] == 1