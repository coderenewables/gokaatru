from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from server.state.session import SessionState, session
from server.tools.brighthub import (
    _prepare_brighthub_reanalysis,
    brighthub_download_reanalysis,
    brighthub_import_location,
)
from server.tools.extrapolation import _extrapolate_reanalysis_to_hub


def _payload(latitude: float, longitude: float) -> dict:
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timeseries_data": {
            "data": [
                {"timestamp": "2024-01-01T00:00:00Z", "Spd_100m_mps": 8.0, "Dir_100m_deg": 180.0, "Tmp_2m_degC": 10.0, "Prs_0m_hPa": 1010.0},
                {"timestamp": "2024-01-01T01:00:00Z", "Spd_100m_mps": 9.0, "Dir_100m_deg": 190.0, "Tmp_2m_degC": 11.0, "Prs_0m_hPa": 1011.0},
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
    merra_nodes = [{"latitude_ddeg": 52.5, "longitude_ddeg": 4.5}]

    monkeypatch.setattr(
        "server.tools.brighthub.fetch_reanalysis_nodes",
        lambda *_args: {"era5_nodes": era5_nodes, "merra2_nodes": merra_nodes},
    )
    monkeypatch.setattr(
        "server.tools.brighthub.download_reanalysis_data",
        lambda _token, nodes, dataset: [
            _payload(node["latitude_ddeg"], node["longitude_ddeg"])
            for node in nodes
        ],
    )

    result = _prepare_brighthub_reanalysis(state, 52.5, 4.5)

    assert result["source"] == "brighthub"
    assert result["era5_nodes"] == 4
    assert result["merra2_nodes"] == 1
    assert len(state.era5_data) == 4
    assert len(state.merra_data) == 1
    assert isinstance(state.era5_interpolated_df, pd.DataFrame)

    # Each downloaded BrightHub reanalysis node is persisted to the session workspace.
    cache_dir = tmp_path / "brighthub_cache"
    assert cache_dir.is_dir()
    assert len(list(cache_dir.glob("ERA5_*.parquet"))) == 4
    assert len(list(cache_dir.glob("MERRA-2_*.parquet"))) == 1


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
            _payload(node["latitude_ddeg"], node["longitude_ddeg"]) for node in req_nodes
        ],
    )

    result = brighthub_download_reanalysis("ERA5", json.dumps(nodes), source="brighthub")

    assert result["source"] == "brighthub"
    assert result["count"] == 2
    cache_dir = tmp_path / "brighthub_cache"
    assert len(list(cache_dir.glob("ERA5_*.parquet"))) == 2
    assert len(session.era5_data) == 2


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
    merra_nodes = [{"latitude_ddeg": 52.5, "longitude_ddeg": 4.5}]
    calls = {"find": 0, "download": 0}

    def find_nodes(*_args):
        calls["find"] += 1
        return {"era5_nodes": era5_nodes, "merra2_nodes": merra_nodes}

    def download(_token, nodes, _dataset):
        calls["download"] += 1
        return [_payload(node["latitude_ddeg"], node["longitude_ddeg"]) for node in nodes]

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