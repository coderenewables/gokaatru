from __future__ import annotations

import json

import pandas as pd
import pytest

from server.state.session import SessionState, session
from server.tools.brighthub import (
    _prepare_brighthub_reanalysis,
    brighthub_download_reanalysis,
    brighthub_find_reanalysis_nodes,
    brighthub_get_data_model,
    brighthub_import_location,
)
from server.tools.era5 import interpolate_era5_to_site
from server.tools.extrapolation import _extrapolate_reanalysis_to_hub


def _payload(latitude: float, longitude: float, dataset: str = "ERA5") -> dict:
    """Build a BrightHub node payload in the column shape that dataset is actually served in.

    ERA5 carries 100 m winds and MERRA-2 carries 50 m; `download_reanalysis_data`
    requests different variables for each. This helper used to return ERA5 columns for
    both, which is not a payload BrightHub can produce (design doc S6.3).
    """
    height = 100 if dataset == "ERA5" else 50
    speed_key, dir_key = f"Spd_{height}m_mps", f"Dir_{height}m_deg"
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timeseries_data": {
            "data": [
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    speed_key: 8.0,
                    dir_key: 180.0,
                    "Tmp_2m_degC": 10.0,
                    "Prs_0m_hPa": 1010.0,
                },
                {
                    "timestamp": "2024-01-01T01:00:00Z",
                    speed_key: 9.0,
                    dir_key: 190.0,
                    "Tmp_2m_degC": 11.0,
                    "Prs_0m_hPa": 1011.0,
                },
            ]
        },
    }


def test_prepare_brighthub_reanalysis_stores_era5_merra_and_interpolates(monkeypatch, tmp_path) -> None:
    state = SessionState()
    state.workspace_dir = tmp_path
    state.brighthub_token = "token"
    era5_nodes = [
        {"latitude_ddeg": 52.0, "longitude_ddeg": 4.0},
        {"latitude_ddeg": 52.0, "longitude_ddeg": 5.0},
        {"latitude_ddeg": 53.0, "longitude_ddeg": 4.0},
        {"latitude_ddeg": 53.0, "longitude_ddeg": 5.0},
    ]
    merra_nodes = [
        {"latitude_ddeg": 52.5, "longitude_ddeg": 4.5},
        {"latitude_ddeg": 52.5, "longitude_ddeg": 4.75},
        {"latitude_ddeg": 52.75, "longitude_ddeg": 4.5},
        {"latitude_ddeg": 52.75, "longitude_ddeg": 4.75},
    ]

    monkeypatch.setattr(
        "server.tools.brighthub.fetch_reanalysis_nodes",
        lambda *_args: {"era5_nodes": era5_nodes, "merra2_nodes": merra_nodes},
    )
    monkeypatch.setattr(
        "server.tools.brighthub.download_reanalysis_data",
        lambda _token, nodes, dataset: [
            _payload(node["latitude_ddeg"], node["longitude_ddeg"], dataset)
            for node in nodes
        ],
    )

    result = _prepare_brighthub_reanalysis(state, 52.5, 4.5)

    assert result["source"] == "brighthub"
    assert result["era5_nodes"] == 4
    assert result["merra2_nodes"] == 4
    assert len(state.era5_data) == 4
    assert len(state.merra_data) == 4
    assert isinstance(state.era5_interpolated_df, pd.DataFrame)

    # Each downloaded BrightHub reanalysis node is persisted to the session workspace.
    cache_dir = tmp_path / "brighthub_cache"
    assert cache_dir.is_dir()
    assert len(list(cache_dir.glob("ERA5_*.parquet"))) == 4
    assert len(list(cache_dir.glob("MERRA-2_*.parquet"))) == 4


def test_brighthub_download_reanalysis_persists_brighthub_frames(monkeypatch, tmp_path) -> None:
    """brighthub_download_reanalysis writes one parquet per node into the session workspace."""
    session.workspace_dir = tmp_path
    session.brighthub_token = "token"
    nodes = [
        {"latitude_ddeg": 52.0, "longitude_ddeg": 4.0},
        {"latitude_ddeg": 52.0, "longitude_ddeg": 5.0},
    ]

    monkeypatch.setattr(
        "server.tools.brighthub.download_reanalysis_data",
        lambda _token, req_nodes, dataset: [
            _payload(node["latitude_ddeg"], node["longitude_ddeg"], dataset) for node in req_nodes
        ],
    )

    result = brighthub_download_reanalysis("ERA5", json.dumps(nodes), source="brighthub")

    assert result["source"] == "brighthub"
    assert result["count"] == 2
    cache_dir = tmp_path / "brighthub_cache"
    assert len(list(cache_dir.glob("ERA5_*.parquet"))) == 2
    assert len(session.era5_data) == 2


def test_nodes_found_then_downloaded_one_at_a_time_interpolate_through_the_operations(monkeypatch, tmp_path) -> None:
    """The workbench's acquisition: find the nodes, take each one alone, interpolate each source.

    brighthub_find_reanalysis_nodes was a read, and neither it nor the download recorded the
    node lists interpolation reads, so through the operations a BrightHub download could not be
    interpolated; only the hand-written route stored them (P3-17a).
    """
    session.workspace_dir = tmp_path
    session.brighthub_token = "token"
    session.era5_nodes = None
    session.merra_nodes = None
    session.era5_data = {}
    session.merra_data = {}
    # Farthest first, so the recorded order is the finder's own.
    era5 = [(53.0, 5.0), (52.0, 5.0), (53.0, 4.0), (52.0, 4.0)]
    merra = [(52.75, 4.75), (52.5, 4.75), (52.75, 4.5), (52.5, 4.5)]
    monkeypatch.setattr(
        "server.tools.brighthub.fetch_reanalysis_nodes",
        lambda *_args: {
            "era5_nodes": [{"latitude_ddeg": lat, "longitude_ddeg": lon} for lat, lon in era5],
            "merra2_nodes": [{"latitude_ddeg": lat, "longitude_ddeg": lon} for lat, lon in merra],
        },
    )
    monkeypatch.setattr(
        "server.tools.brighthub.download_reanalysis_data",
        lambda _token, nodes, dataset: [
            _payload(node["latitude_ddeg"], node["longitude_ddeg"], dataset) for node in nodes
        ],
    )

    found = brighthub_find_reanalysis_nodes(52.1, 4.1)
    distances = [node["distance_km"] for node in found["era5_nodes"]]
    assert distances == sorted(distances)
    assert (found["era5_nodes"][0]["latitude_ddeg"], found["era5_nodes"][0]["longitude_ddeg"]) == (52.0, 4.0)
    assert found["era5_count"] == found["merra2_count"] == 4
    assert (session.get_coordinate().latitude, session.get_coordinate().longitude) == (52.1, 4.1)

    for dataset, key in (("ERA5", "era5_nodes"), ("MERRA-2", "merra2_nodes")):
        for node in found[key]:
            brighthub_download_reanalysis(dataset, json.dumps([node]))
    for source in ("era5", "merra2"):
        assert interpolate_era5_to_site(source)["status"] == "ok"
    assert len(session.reanalysis_interpolated["merra2"]) == 2


@pytest.mark.parametrize("uuid", ["../escape", "a/b", "..", "with space", ""])
def test_a_location_id_that_could_leave_the_uploads_folder_is_refused(monkeypatch, tmp_path, uuid) -> None:
    """The id names files in the campaign's uploads folder; the hand-written route checked it and
    the operations did not (P3-17a)."""
    session.workspace_dir = tmp_path
    session.brighthub_token = "token"
    fetched: list[str] = []
    monkeypatch.setattr("server.tools.brighthub.get_data_model", lambda _token, uuid: fetched.append(uuid) or {})
    with pytest.raises(ValueError, match="Invalid BrightHub location id"):
        brighthub_import_location(uuid)
    with pytest.raises(ValueError, match="Invalid BrightHub location id"):
        brighthub_get_data_model(uuid)
    assert fetched == []
    assert not any(tmp_path.rglob("*"))


def test_brighthub_import_rolls_back_when_datamodel_parsing_fails(monkeypatch, tmp_path) -> None:
    """Do not replace session data or saved imports when a BrightHub import cannot be fully parsed."""
    session.workspace_dir = tmp_path
    session.brighthub_token = "token"
    session.timeseries_df = pd.DataFrame({"existing": [1.0]})
    session.raw_timeseries_df = session.timeseries_df.copy(deep=True)
    session.runconfig = {"project_name": "Existing"}
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir()
    datamodel_path = uploads_dir / "datamodel_site.json"
    timeseries_path = uploads_dir / "ts_site.csv"
    datamodel_path.write_text("previous datamodel", encoding="utf-8")
    timeseries_path.write_text("previous timeseries", encoding="utf-8")

    monkeypatch.setattr("server.tools.brighthub.get_data_model", lambda *_args: {"measurement_point": []})
    monkeypatch.setattr(
        "server.tools.brighthub.fetch_timeseries_csv",
        lambda *_args, **_kwargs: "Timestamp,Spd_100m\n2024-01-01T00:00:00,8\n2024-01-01T01:00:00,9\n",
    )

    def fail_datamodel_parse(*_args):
        raise ValueError("invalid datamodel")

    monkeypatch.setattr("server.tools.data_io._parse_datamodel", fail_datamodel_parse)

    with pytest.raises(ValueError, match="invalid datamodel"):
        brighthub_import_location("site")

    pd.testing.assert_frame_equal(session.timeseries_df, pd.DataFrame({"existing": [1.0]}))
    assert session.runconfig == {"project_name": "Existing"}
    assert datamodel_path.read_text(encoding="utf-8") == "previous datamodel"
    assert timeseries_path.read_text(encoding="utf-8") == "previous timeseries"
    assert not list(uploads_dir.glob("tmp*"))


def test_prepare_brighthub_reanalysis_reuses_matching_site_cache(monkeypatch) -> None:
    """Avoid repeat ERA5/MERRA provider calls until the requested station location changes."""
    state = SessionState()
    state.brighthub_token = "token"
    era5_nodes = [
        {"latitude_ddeg": 52.0, "longitude_ddeg": 4.0},
        {"latitude_ddeg": 52.0, "longitude_ddeg": 5.0},
        {"latitude_ddeg": 53.0, "longitude_ddeg": 4.0},
        {"latitude_ddeg": 53.0, "longitude_ddeg": 5.0},
    ]
    merra_nodes = [
        {"latitude_ddeg": 52.5, "longitude_ddeg": 4.5},
        {"latitude_ddeg": 52.5, "longitude_ddeg": 4.75},
        {"latitude_ddeg": 52.75, "longitude_ddeg": 4.5},
        {"latitude_ddeg": 52.75, "longitude_ddeg": 4.75},
    ]
    calls = {"find": 0, "download": 0}

    def find_nodes(*_args):
        calls["find"] += 1
        return {"era5_nodes": era5_nodes, "merra2_nodes": merra_nodes}

    def download(_token, nodes, _dataset):
        calls["download"] += 1
        return [_payload(node["latitude_ddeg"], node["longitude_ddeg"], _dataset) for node in nodes]

    monkeypatch.setattr("server.tools.brighthub.fetch_reanalysis_nodes", find_nodes)
    monkeypatch.setattr("server.tools.brighthub.download_reanalysis_data", download)

    first = _prepare_brighthub_reanalysis(state, 52.5, 4.5)
    second = _prepare_brighthub_reanalysis(state, 52.5, 4.5)

    assert first["cached"] is False
    assert second["cached"] is True
    assert calls == {"find": 1, "download": 2}

    state.reanalysis_cache_identity = {"source": "earthdatahub", "latitude": 52.5, "longitude": 4.5}
    changed_source = _prepare_brighthub_reanalysis(state, 52.5, 4.5)
    assert changed_source["cached"] is False
    assert calls == {"find": 2, "download": 4}

    moved_site = _prepare_brighthub_reanalysis(state, 52.55, 4.5)
    assert moved_site["cached"] is False
    assert calls == {"find": 3, "download": 6}


def test_reanalysis_hub_extrapolation_creates_ltc_reference_column() -> None:
    state = SessionState()
    index = pd.date_range("2024-01-01", periods=2, freq="h")
    state.era5_interpolated_df = pd.DataFrame({"Spd_100m": [8.0, 9.0]}, index=index)
    state.shear_table = pd.DataFrame(0.2, index=range(1, 13), columns=range(24))

    result = _extrapolate_reanalysis_to_hub(state, 150.0)

    assert result["column_name"] == "Spd_150m_hub"
    assert "Spd_150m_hub" in state.era5_interpolated_df.columns
