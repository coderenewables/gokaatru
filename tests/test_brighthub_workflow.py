from __future__ import annotations

import pandas as pd

from server.state.session import SessionState
from server.tools.brighthub import _prepare_brighthub_reanalysis
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


def test_prepare_brighthub_reanalysis_stores_era5_merra_and_interpolates(monkeypatch) -> None:
    state = SessionState()
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