"""test_phase3 — Verification tests for GoKaatru Phase 3 features.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from server.state.session import session
from server.tools.air_density import compute_air_density
from server.tools.era5 import (
    _era5_dataset_url,
    _era5_storage_options,
    compute_era5_wind_speed,
    extract_era5_data,
    find_era5_nodes,
)
from server.tools.ltc import (
    run_ltc_linear_least_squares,
    run_ltc_speedsort,
    run_ltc_total_least_squares,
    run_ltc_variance_ratio,
)
from server.tools.ltc_ml import run_ltc_xgboost


def _set_ltc_frames(measured: np.ndarray, reference: np.ndarray) -> pd.DatetimeIndex:
    """Populate measured and reference session dataframes for LTC tests."""
    index = pd.date_range("2023-01-01", periods=len(measured), freq="h")
    session.timeseries_df = pd.DataFrame(
        {"Spd_100m": measured, "Dir_100m": np.linspace(0.0, 359.0, len(measured))},
        index=index,
    )
    session.era5_interpolated_df = pd.DataFrame(
        {
            "Spd_100m_hub": reference,
            "Dir_100m": np.linspace(5.0, 364.0, len(reference)) % 360.0,
            "t2m": np.full(len(reference), 288.15),
            "sp": np.full(len(reference), 101325.0),
            "d2m": np.full(len(reference), 275.0),
        },
        index=index,
    )
    return index


def test_find_era5_nodes_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify surrounding ERA5 nodes are discovered from a mocked 0.25° latitude-longitude grid."""
    fake_dataset = xr.Dataset(coords={"latitude": [52.0, 52.25, 52.5], "longitude": [4.5, 4.75, 5.0]})
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda: fake_dataset)
    result = find_era5_nodes(52.4, 4.8)
    assert len(result["nodes"]) == 4
    assert all(node["distance_km"] > 0 for node in result["nodes"])
    assert math.isclose(result["grid_resolution_deg"], 0.25, rel_tol=1e-9)
    assert session.runconfig["location"]["latitude"] == 52.4
    assert session.runconfig["location"]["longitude"] == 4.8


def test_era5_storage_options_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify EarthDataHub bearer-token auth is translated into HTTP storage headers."""
    monkeypatch.delenv("EARTHDATAHUB_AUTH_HEADER", raising=False)
    monkeypatch.delenv("EARTHDATAHUB_AUTH_VALUE", raising=False)
    monkeypatch.delenv("EARTHDATAHUB_API_KEY", raising=False)
    monkeypatch.delenv("EARTHDATAHUB_API_KEY_HEADER", raising=False)
    monkeypatch.setenv("EARTHDATAHUB_BEARER_TOKEN", "secret-token")
    options = _era5_storage_options()
    assert options["headers"] == {"Authorization": "Bearer secret-token"}


def test_era5_dataset_url_from_netrc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify EarthDataHub PATs stored in netrc are translated into the documented edh:PAT URL format."""
    netrc_path = tmp_path / ".netrc"
    netrc_path.write_text("machine data.earthdatahub.destine.eu\npassword test-pat\n", encoding="utf-8")
    monkeypatch.delenv("EARTHDATAHUB_PAT", raising=False)
    monkeypatch.delenv("EDH_PAT", raising=False)
    monkeypatch.delenv("DESTINE_PAT", raising=False)
    monkeypatch.setenv("NETRC", str(netrc_path))
    dataset_url = _era5_dataset_url()
    assert dataset_url.startswith("https://edh:test-pat@data.earthdatahub.destine.eu/")


def test_extract_era5_data_supports_valid_time(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify live-style ERA5 datasets using valid_time are converted into a standard datetime index."""
    index = pd.date_range("2024-01-01", periods=3, freq="h")
    fake_dataset = xr.Dataset(
        data_vars={
            "u100": (("valid_time", "latitude", "longitude"), np.ones((3, 1, 1), dtype=float)),
            "v100": (("valid_time", "latitude", "longitude"), np.full((3, 1, 1), 2.0, dtype=float)),
            "sp": (("valid_time", "latitude", "longitude"), np.full((3, 1, 1), 101325.0, dtype=float)),
            "t2m": (("valid_time", "latitude", "longitude"), np.full((3, 1, 1), 288.15, dtype=float)),
            "d2m": (("valid_time", "latitude", "longitude"), np.full((3, 1, 1), 280.15, dtype=float)),
        },
        coords={"valid_time": index, "latitude": [52.5], "longitude": [4.75]},
    )
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda: fake_dataset)
    monkeypatch.setattr("server.tools.era5._era5_cache_path", lambda latitude, longitude: tmp_path / "node.parquet")
    result = extract_era5_data(52.5, 4.75, "2024-01-01", "2024-01-01T02:00:00")
    assert result["rows"] == 3
    frame = session.era5_data["52.5_4.75"]
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.name == "time"


def test_compute_wind_speed() -> None:
    """Verify ERA5 u and v components convert to the expected speed and meteorological direction."""
    index = pd.date_range("2024-01-01", periods=5, freq="h")
    session.era5_data["52.25_4.75"] = pd.DataFrame({"u100": np.full(5, 5.0), "v100": np.full(5, 5.0)}, index=index)
    result = compute_era5_wind_speed(52.25, 4.75)
    frame = session.era5_data["52.25_4.75"]
    assert math.isclose(result["mean_speed"], math.sqrt(50.0), rel_tol=1e-6)
    assert math.isclose(float(frame["Dir_100m"].iloc[0]), 225.0, rel_tol=1e-6)


def test_ltc_linear_known_relationship() -> None:
    """Verify robust linear LTC recovers a known measured-reference relationship within tolerance."""
    np.random.seed(3)
    reference = np.linspace(3.0, 15.0, 240)
    measured = 1.1 * reference + 0.5 + np.random.normal(0.0, 0.15, reference.size)
    _set_ltc_frames(measured, reference)
    result = run_ltc_linear_least_squares("Spd_100m", "Spd_100m_hub")
    metrics = result["metrics"]
    assert math.isclose(float(metrics["slope"]), 1.1, abs_tol=0.08)
    assert math.isclose(float(metrics["intercept"]), 0.5, abs_tol=0.3)


def test_ltc_same_column_names_supported() -> None:
    """Verify LTC works when measured and reference series use the same column name."""
    index = pd.date_range("2024-01-01", periods=120, freq="h")
    reference = np.linspace(4.0, 12.0, 120)
    measured = 0.92 * reference + 0.4
    session.timeseries_df = pd.DataFrame({"Spd_100m": measured}, index=index)
    session.era5_interpolated_df = pd.DataFrame({"Spd_100m": reference}, index=index)
    result = run_ltc_linear_least_squares("Spd_100m", "Spd_100m")
    assert result["metrics"]["concurrent_points"] == 120
    assert result["metrics"]["r_squared"] > 0.99


def test_ltc_speedsort_threshold() -> None:
    """Verify the SpeedSort threshold equals min(4.0, 0.5 × mean reference speed)."""
    reference = np.full(120, 7.0)
    measured = reference * 1.05
    _set_ltc_frames(measured, reference)
    result = run_ltc_speedsort("Spd_100m", "Spd_100m_hub")
    assert math.isclose(float(result["metrics"]["threshold"]), 3.5, rel_tol=1e-9)


def test_ltc_variance_ratio_identity() -> None:
    """Verify variance-ratio LTC returns the reference record unchanged when measured equals reference."""
    reference = np.linspace(2.0, 12.0, 140)
    _set_ltc_frames(reference.copy(), reference.copy())
    result = run_ltc_variance_ratio("Spd_100m", "Spd_100m_hub")
    corrected = session.ltc_results["variance_ratio"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)
    assert np.allclose(corrected, reference)
    assert math.isclose(float(result["metrics"]["variance_ratio"]), 1.0, rel_tol=1e-9)


@pytest.mark.skipif(importlib.util.find_spec("xgboost") is None, reason="xgboost not installed")
def test_ltc_xgboost_runs() -> None:
    """Verify XGBoost LTC produces corrected output and the expected metrics keys on synthetic data."""
    np.random.seed(11)
    reference = 7.0 + 2.0 * np.sin(np.linspace(0.0, 8.0 * np.pi, 240)) + np.random.normal(0.0, 0.2, 240)
    measured = 0.9 * reference + 0.7 + 0.3 * np.sin(np.linspace(0.0, 4.0 * np.pi, 240))
    _set_ltc_frames(measured, reference)
    result = run_ltc_xgboost("Spd_100m", "Spd_100m_hub", "Dir_100m", "Dir_100m")
    metrics = result["metrics"]
    stored = session.ltc_results["xgboost"]["df"]
    assert result["status"] == "ok"
    assert "corrected_wind_speed" in stored.columns
    assert {"r_squared", "rmse", "mae", "mbe", "best_iteration", "feature_importance"}.issubset(metrics.keys())


def test_air_density_standard_atmosphere() -> None:
    """Verify the air-density MCP tool reproduces standard atmosphere density within tolerance."""
    result = compute_air_density(101325.0, 288.15, 275.0)
    assert math.isclose(float(result["air_density_kg_m3"]), 1.225, abs_tol=0.01)


def test_ltc_determinism() -> None:
    """Verify deterministic LTC algorithms produce identical corrected output on repeated runs."""
    reference = np.linspace(4.0, 14.0, 160)
    measured = 1.05 * reference + 0.25
    _set_ltc_frames(measured, reference)
    first = run_ltc_total_least_squares("Spd_100m", "Spd_100m_hub")
    first_corrected = session.ltc_results["total_least_squares"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)
    second = run_ltc_total_least_squares("Spd_100m", "Spd_100m_hub")
    second_corrected = session.ltc_results["total_least_squares"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)
    assert np.allclose(first_corrected, second_corrected)
    assert math.isclose(float(first["metrics"]["slope"]), float(second["metrics"]["slope"]), rel_tol=1e-12)
