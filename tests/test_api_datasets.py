"""test_api_datasets - Dataset pool API tests for Phase 2.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_dataset_pool_manager, get_session_manager
from server.api.main import create_app
from server.state.dataset_pool import DatasetPoolManager
from server.state.manager import SessionManager


@pytest.fixture
def dataset_client(tmp_path: Path) -> tuple[TestClient, SessionManager, DatasetPoolManager]:
    """Create an isolated FastAPI client with temporary session and dataset roots."""
    session_manager = SessionManager(base_dir=tmp_path / "sessions")
    dataset_manager = DatasetPoolManager(base_dir=tmp_path / "datasets")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: session_manager
    app.dependency_overrides[get_dataset_pool_manager] = lambda: dataset_manager
    with TestClient(app) as test_client:
        yield test_client, session_manager, dataset_manager
    app.dependency_overrides.clear()


def _upload_bytes(path: Path) -> bytes:
    """Read one checked-in fixture file as upload bytes."""
    return path.read_bytes()


def test_dataset_pool_crud_and_load(
    uploaded_timeseries_path: Path,
    uploaded_datamodel_path: Path,
    dataset_client: tuple[TestClient, SessionManager, DatasetPoolManager],
) -> None:
    """Verify shared dataset upload/list/get/load/delete API behavior."""
    client, _session_manager, _dataset_manager = dataset_client

    create_dataset_response = client.post(
        "/api/datasets",
        data={"name": "Boxkite Shared"},
        files={
            "timeseries": (
                uploaded_timeseries_path.name,
                _upload_bytes(uploaded_timeseries_path),
                "text/csv",
            ),
            "datamodel": (
                uploaded_datamodel_path.name,
                _upload_bytes(uploaded_datamodel_path),
                "application/json",
            ),
        },
    )
    assert create_dataset_response.status_code == 200
    created_dataset = create_dataset_response.json()
    dataset_id = created_dataset["id"]
    assert created_dataset["name"] in {"Boxkite Shared", "HKW-B-FLS-Boxkite"}
    assert created_dataset["sensor_count"] >= 1
    assert created_dataset["date_range"]["start"] == "2019-02-10T09:00:00"
    assert created_dataset["date_range"]["end"] == "2021-02-11T23:50:00"

    list_response = client.get("/api/datasets")
    assert list_response.status_code == 200
    listed = list_response.json()["datasets"]
    assert len(listed) == 1
    assert listed[0]["id"] == dataset_id

    get_response = client.get(f"/api/datasets/{dataset_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == dataset_id

    preview_response = client.get(f"/api/datasets/{dataset_id}/preview?limit=5")
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["dataset_id"] == dataset_id
    assert preview_payload["preview_rows"] == 5
    assert preview_payload["total_rows"] == 73532
    assert "timestamp" in preview_payload["columns"]
    assert len(preview_payload["rows"]) == 5

    create_session_response = client.post("/api/sessions")
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["session_id"]
    headers = {"X-GoKaatru-Session": session_id}

    load_response = client.post(f"/api/sessions/{session_id}/datasets/{dataset_id}/load", headers=headers)
    assert load_response.status_code == 200
    load_payload = load_response.json()
    assert load_payload["status"] == "ok"
    assert load_payload["timeseries"]["rows"] == 73532
    assert 100.0 in load_payload["datamodel"]["heights"]

    summary_response = client.get(f"/api/sessions/{session_id}", headers=headers)
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["timeseries_loaded"] is True
    assert summary_payload["datamodel_loaded"] is True

    delete_response = client.delete(f"/api/datasets/{dataset_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "ok", "dataset_id": dataset_id}

    list_after_delete = client.get("/api/datasets")
    assert list_after_delete.status_code == 200
    assert list_after_delete.json()["datasets"] == []
