"""test_api_sessions — Smoke tests for the FastAPI scaffold and session routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create an isolated FastAPI test client backed by a temporary session workspace."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_api_health(client: TestClient) -> None:
    """Verify the FastAPI scaffold exposes the expected health payload."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gokaatru-web-api"}


def test_root_redirects_to_health(client: TestClient) -> None:
    """Verify the root URL redirects to the API health endpoint."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/api/health"


def test_session_lifecycle_routes(client: TestClient) -> None:
    """Verify session creation, summary, reset, and deletion work through the web API scaffold."""
    create_response = client.post("/api/sessions")
    assert create_response.status_code == 200
    created = create_response.json()
    session_id = created["session_id"]
    workspace_dir = Path(created["workspace_dir"])
    assert workspace_dir.exists()

    headers = {"X-GoKaatru-Session": session_id}
    summary_response = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["session_id"] == session_id
    assert summary["timeseries_loaded"] is False
    assert summary["ltc_algorithms"] == []

    reset_response = client.post(f"/api/sessions/{session_id}/reset", headers=headers)
    assert reset_response.status_code == 200
    reset_body = reset_response.json()
    assert reset_body["session_id"] == session_id
    assert Path(reset_body["workspace_dir"]).exists()

    delete_response = client.delete(f"/api/sessions/{session_id}", headers=headers)
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "ok", "session_id": session_id}
    assert not workspace_dir.exists()


def test_session_routes_require_header(client: TestClient) -> None:
    """Verify session-scoped routes reject requests without the required session header."""
    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing required header 'X-GoKaatru-Session'"
