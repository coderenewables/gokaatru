"""A project holds several campaigns sharing one reanalysis node cache (P2-8, 0014.11-12).

Each campaign is a session that reopens by its own id after a restart; a node one campaign
downloaded is a cache hit for another; the project shows each campaign's own coordinate and
timezone and says when the timezones differ.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.state.manager import SessionManager
from server.state.projects import ProjectRegistry
from server.tools.config import _persist_runconfig
from server.tools.era5 import _era5_cache_path, _load_cached_era5
from tests.http_operations import operation


@pytest.fixture
def client(tmp_path: Path):
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    with TestClient(app) as test_client:
        yield test_client, manager
    app.dependency_overrides.clear()


def _project_with_two_campaigns(test_client) -> tuple[str, str, str]:
    project = test_client.post("/api/projects", json={"name": "Hollow Ridge", "site_name": "Ridge"}).json()
    mast = test_client.post(f"/api/projects/{project['id']}/campaigns", json={"name": "Mast M1", "kind": "mast"})
    lidar = test_client.post(f"/api/projects/{project['id']}/campaigns", json={"name": "Lidar L1", "kind": "lidar"})
    assert mast.status_code == lidar.status_code == 200, (mast.text, lidar.text)
    return project["id"], mast.json()["session_id"], lidar.json()["session_id"]


def test_a_project_is_created_listed_renamed_and_holds_its_campaigns(client) -> None:
    test_client, manager = client
    project_id, mast, lidar = _project_with_two_campaigns(test_client)

    listed = test_client.get("/api/projects").json()["projects"]
    assert [project["id"] for project in listed] == [project_id]
    assert [(c["name"], c["kind"]) for c in listed[0]["campaigns"]] == [("Mast M1", "mast"), ("Lidar L1", "lidar")]

    renamed = test_client.patch(f"/api/projects/{project_id}", json={"name": "Hollow Ridge II"}).json()
    assert renamed["name"] == "Hollow Ridge II" and renamed["site_name"] == "Ridge"
    campaigns = test_client.patch(f"/api/projects/{project_id}/campaigns/{lidar}", json={"name": "Lidar L2"}).json()
    assert [c["name"] for c in campaigns["campaigns"]] == ["Mast M1", "Lidar L2"]

    # Each campaign is a session the session routes serve by its id.
    state = manager.get_session(mast)
    assert state.project["id"] == project_id
    summary = operation(test_client, mast, "get_analysis_summary")
    assert summary.status_code == 200, summary.text


def test_a_node_one_campaign_cached_is_a_hit_for_the_other(client) -> None:
    test_client, manager = client
    project_id, mast, lidar = _project_with_two_campaigns(test_client)
    first, second = manager.get_session(mast), manager.get_session(lidar)
    index = pd.date_range("2000-01-01", periods=24 * 400, freq="h", tz="UTC")
    node = pd.DataFrame({"u100": np.ones(len(index)), "v100": np.zeros(len(index))}, index=index)

    node.to_parquet(_era5_cache_path(first, 55.25, 7.75))
    cached, hit = _load_cached_era5(_era5_cache_path(second, 55.25, 7.75), "2000-02-01", "2000-12-31")
    assert hit and cached is not None
    assert cached.index[0] == pd.Timestamp("2000-02-01", tz="UTC") and len(cached) == 8017
    shared = ProjectRegistry(manager).cache_dir(project_id)
    assert _era5_cache_path(second, 55.25, 7.75).parent == (shared / "earthdatahub").resolve()

    alone = manager.create_session()
    assert _era5_cache_path(alone, 55.25, 7.75).parent == alone.workspace_dir / "earthdatahub_cache"


def test_campaigns_reopen_by_their_own_id_after_a_restart(client, tmp_path: Path) -> None:
    test_client, _ = client
    project_id, mast, lidar = _project_with_two_campaigns(test_client)

    restarted = SessionManager(base_dir=tmp_path / "sessions")
    registry = ProjectRegistry(restarted)
    assert [c["session_id"] for c in registry.get(project_id)["campaigns"]] == [mast, lidar]
    for session_id in (mast, lidar):
        assert restarted.get_session(session_id).project["id"] == project_id


def test_each_campaign_shows_its_own_site_and_differing_timezones_are_flagged(client) -> None:
    test_client, manager = client
    project_id, mast, lidar = _project_with_two_campaigns(test_client)
    for session_id, (latitude, zone) in ((mast, (55.25, "UTC+01:00")), (lidar, (55.27, "UTC+01:00"))):
        state = manager.get_session(session_id)
        state.runconfig = {"location": {"latitude": latitude, "longitude": 7.8}, "site": {"timezone": zone}}
        _persist_runconfig(state)
    detail = test_client.get(f"/api/projects/{project_id}").json()
    assert [(c["latitude"], c["timezone"]) for c in detail["campaigns"]] == [(55.25, "UTC+01:00"), (55.27, "UTC+01:00")]
    assert detail["timezones_differ"] is False

    state = manager.get_session(lidar)
    state.runconfig["site"]["timezone"] = "UTC+00:00"
    _persist_runconfig(state)
    assert test_client.get(f"/api/projects/{project_id}").json()["timezones_differ"] is True


def test_a_campaigns_site_comes_from_its_data_model_with_no_config_file_written(client, tmp_path: Path) -> None:
    """The generated build_data_model route writes no runconfig.json; the project still shows
    the campaign's coordinate and timezone, from the open session and, after a restart, from
    its saved project."""
    test_client, manager = client
    project_id, mast, _ = _project_with_two_campaigns(test_client)
    state = manager.get_session(mast)
    index = pd.date_range("2023-01-01", periods=50, freq="10min")
    state.timeseries_df = pd.DataFrame({"Spd_80m": np.full(50, 7.0)}, index=index)
    state.raw_timeseries_df = state.timeseries_df.copy()
    spec = {
        "location": {"name": "M1", "latitude_ddeg": 55.25, "longitude_ddeg": 7.75, "offset_from_utc_hrs": 1},
        "points": [{"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 80.0}],
    }
    built = test_client.post(f"/api/sessions/{mast}/operations/build_data_model", json={"spec": spec},
                             headers={"X-GoKaatru-Session": mast})
    assert built.status_code == 200, built.text
    written = json.loads((tmp_path / "sessions" / mast / "runconfig.json").read_text())
    assert "location" not in written, "the route under test writes no configuration file"
    shown = test_client.get(f"/api/projects/{project_id}").json()["campaigns"][0]
    assert (shown["latitude"], shown["timezone"]) == (55.25, "UTC+01:00")

    restarted = ProjectRegistry(SessionManager(base_dir=tmp_path / "sessions"))
    after = restarted.get(project_id)["campaigns"][0]
    assert (after["latitude"], after["longitude"], after["timezone"]) == (55.25, 7.75, "UTC+01:00")


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "message"),
    [
        ("post", "/api/projects", {"name": "  "}, 400, "needs a name"),
        ("post", "/api/projects", {"name": "x", "colour": "red"}, 422, ""),
        ("get", "/api/projects/..%2F..%2Fsessions", None, 404, ""),
        ("get", "/api/projects/0123456789abcdef0123456789abcdef", None, 404, "Unknown project"),
    ],
)
def test_refusals(client, method: str, path: str, body: dict | None, status: int, message: str) -> None:
    test_client, _ = client
    response = getattr(test_client, method)(path, **({"json": body} if body is not None else {}))
    assert response.status_code == status, response.text
    assert message in response.text


def test_the_data_folder_can_be_moved_for_a_test_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOKAATRU_DATA_DIR", str(tmp_path / "e2e"))
    manager = SessionManager()
    assert manager.base_dir == tmp_path / "e2e" / "sessions"
    assert ProjectRegistry(manager).base_dir == tmp_path / "e2e" / "projects"
    monkeypatch.delenv("GOKAATRU_DATA_DIR")
    assert SessionManager(base_dir=tmp_path / "s").base_dir == tmp_path / "s"


def test_a_project_id_cannot_reach_outside_the_projects_folder(tmp_path: Path) -> None:
    from server.state.projects import ProjectError

    registry = ProjectRegistry(SessionManager(base_dir=tmp_path / "sessions"))
    for project_id in ("../sessions", "..\\sessions", "/etc", "ABCDEF0123456789abcdef0123456789"):
        with pytest.raises(ProjectError, match="Unknown project"):
            registry.get(project_id)


def test_a_campaign_needs_a_known_kind_and_a_new_name(client) -> None:
    test_client, _ = client
    project_id, _, _ = _project_with_two_campaigns(test_client)
    base = f"/api/projects/{project_id}/campaigns"
    sodar = test_client.post(base, json={"name": "S1", "kind": "sodar"})
    assert sodar.status_code == 400 and "mast, lidar, floating_lidar" in sodar.json()["detail"]
    again = test_client.post(base, json={"name": "Mast M1", "kind": "mast"})
    assert again.status_code == 400 and "already has a campaign named 'Mast M1'" in again.json()["detail"]
    missing = test_client.patch(f"{base}/{'f' * 32}", json={"name": "X"})
    assert missing.status_code == 404
