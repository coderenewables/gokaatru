"""The sensors route the workbench's charts read their channels from.

Moved from ``test_api_workflow_execution.py`` when the Canvas executor and its routes were
retired (P3-17d); the route stays.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager


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


def test_sensors_on_an_empty_session_is_an_empty_inventory(execution_client: tuple[TestClient, SessionManager]) -> None:
    """The interface asks for the inventory before any upload; that answered 400 (P1-18)."""
    client, _manager = execution_client
    session_id, headers = _create_session(client)
    response = client.get(f"/api/sessions/{session_id}/sensors", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"sensors": []}
