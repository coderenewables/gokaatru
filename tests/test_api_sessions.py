"""test_api_sessions — Smoke tests for the FastAPI scaffold and session routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.schemas.common import Coordinate
from server.state.manager import SessionManager
from server.tools.era5 import Era5UpstreamError


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


def test_config_step_requires_saved_hub_height(client: TestClient) -> None:
    """Verify workflow config step becomes complete only after hub height is saved with metadata."""
    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    without_hub = client.put(
        f"/api/sessions/{session_id}/config",
        headers=headers,
        json={
            "updates": [
                {"key": "project_name", "value": "North Ridge"},
                {"key": "location.latitude", "value": 52.4},
                {"key": "location.longitude", "value": 4.8},
            ]
        },
    )
    assert without_hub.status_code == 200

    summary_without_hub = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert summary_without_hub.status_code == 200
    assert "config" not in summary_without_hub.json()["completed_steps"]

    with_hub = client.put(
        f"/api/sessions/{session_id}/config",
        headers=headers,
        json={"updates": [{"key": "hub_height_m", "value": 150}]},
    )
    assert with_hub.status_code == 200

    summary_with_hub = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert summary_with_hub.status_code == 200
    assert "config" in summary_with_hub.json()["completed_steps"]


def test_era5_extract_upstream_failure_returns_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify transient EarthDataHub failures are surfaced as 502 instead of uncaught 500 responses."""
    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    def fail_extract(*args: object, **kwargs: object) -> dict:
        del args, kwargs
        raise Era5UpstreamError(
            "ERA5 download failed while reading the remote EarthDataHub payload. Please retry the request."
        )

    monkeypatch.setattr("server.api.routes.analysis._extract_era5_data", fail_extract)

    response = client.post(
        f"/api/sessions/{session_id}/era5/extract",
        headers=headers,
        json={
            "latitude": 52.4,
            "longitude": 4.8,
            "start_date": "2024-01-01",
            "end_date": "2024-01-02",
        },
    )

    assert response.status_code == 502
    assert "ERA5 download failed" in response.json()["detail"]


def test_era5_interpolate_reads_source_from_the_request_body(tmp_path: Path) -> None:
    """Verify `POST /era5/interpolate` reads `source` from the JSON body, not a query string.

    Regression: `source` used to be a bare `str = "era5"` function parameter with no
    `Body()` annotation, so FastAPI bound it as a *query* parameter. Every real caller
    (including this project's own frontend) sends it in the JSON body instead, which FastAPI
    silently discarded, always falling back to the `"era5"` default - the "Interpolate
    MERRA-2 to site" call added to fix the "MERRA-2 stays unavailable" report therefore never
    actually interpolated MERRA-2 at all; it silently re-interpolated ERA5 a second time. Only
    caught by exercising the real HTTP route through a request body, which nothing did before
    (existing tests call `_interpolate_era5_to_site` directly, bypassing FastAPI's parameter
    binding entirely).
    """
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            create_response = client.post("/api/sessions")
            session_id = create_response.json()["session_id"]
            headers = {"X-GoKaatru-Session": session_id}

            state = manager.get_session(session_id)
            state.set_coordinate(Coordinate(latitude=10.0, longitude=20.0, elevation_m=0.0))
            index = pd.date_range("2020-01-01", periods=5, freq="h", tz="UTC")
            nodes = [(10.0, 20.0), (10.0, 20.5), (10.5, 20.0), (10.5, 20.5)]
            state.merra_nodes = [
                {"latitude": lat, "longitude": lon, "distance_km": 1.0, "bearing": "N"} for lat, lon in nodes
            ]
            for lat, lon in nodes:
                state.merra_data[f"{lat}_{lon}"] = pd.DataFrame(
                    {"Spd_50m": [5.0] * 5, "Dir_50m": [180.0] * 5}, index=index
                )

            response = client.post(
                f"/api/sessions/{session_id}/era5/interpolate",
                headers=headers,
                json={"source": "merra2"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["reference_source"] == "merra2"
    assert body["speed_column"] == "Spd_50m"
    assert body["reference_height_m"] == 50.0


def test_earthdatahub_credential_lifecycle(client: TestClient) -> None:
    """The EarthDataHub PAT is set/cleared per session via the HTTP route, not an env file.

    Mirrors BrightHub's login/logout/status shape (`/brighthub/login`, `/brighthub/logout`,
    `/brighthub/status`), just without an OAuth round trip — EarthDataHub's PAT is a static
    credential, stored as entered.
    """
    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    status_before = client.get(f"/api/sessions/{session_id}/era5/credential/status", headers=headers)
    assert status_before.status_code == 200
    assert status_before.json() == {"configured": False}

    set_response = client.post(
        f"/api/sessions/{session_id}/era5/credential", headers=headers, json={"pat": "test-pat"}
    )
    assert set_response.status_code == 200
    assert set_response.json() == {"status": "ok", "configured": True}

    status_after_set = client.get(f"/api/sessions/{session_id}/era5/credential/status", headers=headers)
    assert status_after_set.json() == {"configured": True}

    clear_response = client.delete(f"/api/sessions/{session_id}/era5/credential", headers=headers)
    assert clear_response.status_code == 200
    assert clear_response.json() == {"status": "ok", "configured": False}

    status_after_clear = client.get(f"/api/sessions/{session_id}/era5/credential/status", headers=headers)
    assert status_after_clear.json() == {"configured": False}


def test_earthdatahub_credential_rejects_blank_pat(client: TestClient) -> None:
    """A blank PAT is a 400, not a silently-accepted empty credential."""
    create_response = client.post("/api/sessions")
    session_id = create_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    response = client.post(f"/api/sessions/{session_id}/era5/credential", headers=headers, json={"pat": "  "})
    assert response.status_code == 400


def test_earthdatahub_credential_is_session_scoped(client: TestClient) -> None:
    """One session's PAT must not leak into a different session (session-scoped, not global)."""
    session_a = client.post("/api/sessions").json()["session_id"]
    session_b = client.post("/api/sessions").json()["session_id"]

    client.post(
        f"/api/sessions/{session_a}/era5/credential",
        headers={"X-GoKaatru-Session": session_a},
        json={"pat": "only-for-a"},
    )

    status_b = client.get(
        f"/api/sessions/{session_b}/era5/credential/status", headers={"X-GoKaatru-Session": session_b}
    )
    assert status_b.json() == {"configured": False}
