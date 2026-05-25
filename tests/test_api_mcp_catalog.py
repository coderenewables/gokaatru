"""test_api_mcp_catalog - MCP catalog route tests.

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
    """Create an isolated FastAPI test client for MCP catalog endpoint tests."""
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_mcp_catalog_exposes_registered_tools(client: TestClient) -> None:
    """Return the MCP tool catalog for same-origin frontend discovery."""
    response = client.get("/api/mcp/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["serverName"] == "GoKaatru"
    assert isinstance(payload["tools"], list)
    assert any(tool["name"] == "get_run_config" for tool in payload["tools"])