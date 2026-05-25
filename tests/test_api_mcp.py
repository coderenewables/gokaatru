"""test_api_mcp — Session-aware MCP transport tests for the FastAPI scaffold.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager


def _parse_mcp_stream_payload(body: str) -> dict:
    """Extract the JSON-RPC payload from a streamable HTTP event-stream response."""
    data_lines = [line[len("data: ") :] for line in body.splitlines() if line.startswith("data: ")]
    assert data_lines, body
    return json.loads(data_lines[-1])


@pytest.fixture
def client_and_manager(tmp_path: Path) -> tuple[TestClient, SessionManager]:
    """Create an isolated API client with a temporary session manager for MCP transport tests."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _create_session(client: TestClient) -> str:
    """Create one browser session and return its identifier."""
    response = client.post("/api/sessions")
    assert response.status_code == 200
    return response.json()["session_id"]


def test_session_aware_mcp_tool_updates_only_target_session(client_and_manager: tuple[TestClient, SessionManager]) -> None:
    """Route MCP tool mutations through the session-specific FastAPI mount instead of the legacy singleton."""
    client, manager = client_and_manager
    first_session_id = _create_session(client)
    second_session_id = _create_session(client)

    response = client.post(
        f"/api/sessions/{first_session_id}/mcp",
        headers={"accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "update_run_config",
                "arguments": {"key": "project_name", "value": '"Alpha Ridge"'},
            },
        },
    )

    assert response.status_code == 200
    payload = _parse_mcp_stream_payload(response.text)
    assert payload["result"]["isError"] is False
    assert manager.get_session(first_session_id).runconfig["project_name"] == "Alpha Ridge"
    assert "project_name" not in manager.get_session(second_session_id).runconfig


def test_session_aware_mcp_rejects_mismatched_session_header(client_and_manager: tuple[TestClient, SessionManager]) -> None:
    """Reject MCP requests when an explicit session header disagrees with the mounted session path."""
    client, _manager = client_and_manager
    first_session_id = _create_session(client)
    second_session_id = _create_session(client)

    response = client.post(
        f"/api/sessions/{first_session_id}/mcp",
        headers={
            "accept": "application/json, text/event-stream",
            "X-GoKaatru-Session": second_session_id,
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Header 'X-GoKaatru-Session' must match path session_id"