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

from server.schemas.common import Coordinate
from server.state.session import session
from server.tools.air_density import compute_air_density
from server.tools.era5 import (
    ERA5_ZARR_URL,
    _align_tz,
    _cache_covers_period,
    _era5_dataset_url,
    _era5_storage_options,
    compute_era5_wind_speed,
    earthdatahub_clear_credential,
    earthdatahub_set_credential,
    earthdatahub_status,
    extract_era5_data,
    find_era5_nodes,
)
from server.tools.ltc import (
    MIN_CONCURRENT_HOURS,
    run_ltc_linear_least_squares,
    run_ltc_speedsort,
    run_ltc_total_least_squares,
    run_ltc_variance_ratio,
)
from server.tools.ltc_ml import run_ltc_xgboost

# LTC now rejects anything under six months of concurrent records (D9.1), so the
# synthetic fixtures below must clear that floor to exercise the algorithms at all.
_LTC_N = MIN_CONCURRENT_HOURS


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
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda *_args: fake_dataset)
    result = find_era5_nodes(52.4, 4.8)
    assert len(result["nodes"]) == 4
    assert all(node["distance_km"] > 0 for node in result["nodes"])
    assert math.isclose(result["grid_resolution_deg"], 0.25, rel_tol=1e-9)
    assert session.runconfig["location"]["latitude"] == 52.4
    assert session.runconfig["location"]["longitude"] == 4.8


def test_find_era5_nodes_closes_dataset_when_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Close the remote dataset even when coordinate-boundary calculation raises."""
    fake_dataset = xr.Dataset(coords={"latitude": [52.0, 52.25], "longitude": [4.5, 4.75]})
    closed: list[xr.Dataset] = []
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda *_args: fake_dataset)
    monkeypatch.setattr("server.tools.era5._close_dataset", lambda dataset: closed.append(dataset))
    monkeypatch.setattr("server.tools.era5._bounding_pair", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        find_era5_nodes(52.1, 4.6)

    assert closed == [fake_dataset]


def test_era5_storage_options_has_no_custom_auth_headers() -> None:
    """EarthDataHub's documented auth is URL-embedded or `.netrc`, not a custom header (2026-09).

    The credential now lives on the session (`earthdatahub_set_credential`), not in an
    environment variable, so there is nothing left for a header-based path to read.
    `trust_env` is the only option: it lets aiohttp pick up a `.netrc` entry on its own.
    """
    assert _era5_storage_options() == {"client_kwargs": {"trust_env": True}}


def test_era5_dataset_url_uses_the_session_credential() -> None:
    """EarthDataHub PAT moved from env/.netrc to the session (mirrors BrightHub's login).

    `_era5_dataset_url` embeds whatever PAT is stored on `session.earthdatahub_pat` — set via
    `earthdatahub_set_credential`, the session-scoped equivalent of `brighthub_login` — and
    falls back to the bare (unauthenticated) URL when none is configured.
    """
    assert earthdatahub_status()["configured"] is False
    assert _era5_dataset_url(session) == ERA5_ZARR_URL

    earthdatahub_set_credential("test-pat")
    assert earthdatahub_status()["configured"] is True
    assert _era5_dataset_url(session) == "https://edh:test-pat@data.earthdatahub.destine.eu/era5/reanalysis-era5-single-levels-v0.zarr"

    earthdatahub_clear_credential()
    assert earthdatahub_status()["configured"] is False
    assert _era5_dataset_url(session) == ERA5_ZARR_URL


def test_earthdatahub_set_credential_rejects_blank_input() -> None:
    """An empty/whitespace-only PAT must be refused rather than silently "configuring" nothing."""
    with pytest.raises(ValueError, match="must not be empty"):
        earthdatahub_set_credential("   ")


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
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda *_args: fake_dataset)
    monkeypatch.setattr("server.tools.era5._era5_cache_path", lambda latitude, longitude: tmp_path / "node.parquet")
    result = extract_era5_data(52.5, 4.75, "2024-01-01", "2024-01-01T02:00:00")
    assert result["rows"] == 3
    frame = session.era5_data["52.5_4.75"]
    assert isinstance(frame.index, pd.DatetimeIndex)
    assert frame.index.name == "time"


def test_extract_era5_data_retries_transient_payload_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify transient ERA5 payload truncation errors are retried before succeeding."""
    attempts = {"count": 0}
    index = pd.date_range("2024-01-01", periods=2, freq="h")
    frame = pd.DataFrame(
        {
            "u100": [1.0, 1.5],
            "v100": [2.0, 2.5],
            "sp": [101325.0, 101325.0],
            "t2m": [288.15, 288.15],
            "d2m": [280.15, 280.15],
        },
        index=index,
    )
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda *_args: object())
    monkeypatch.setattr(
        "server.tools.era5._era5_cache_path", lambda latitude, longitude: tmp_path / "retry-node.parquet"
    )
    monkeypatch.setattr("server.tools.era5.time.sleep", lambda _: None)

    def fake_read(dataset: object, latitude: float, longitude: float, start_date: str, end_date: str) -> pd.DataFrame:
        del dataset, latitude, longitude, start_date, end_date
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")
        return frame

    monkeypatch.setattr("server.tools.era5._read_remote_era5_frame", fake_read)

    result = extract_era5_data(52.5, 4.75, "2024-01-01", "2024-01-01T01:00:00")

    assert attempts["count"] == 2
    assert result["rows"] == 2
    assert session.era5_data["52.5_4.75"].equals(frame)


def test_extract_era5_data_does_not_move_the_site_coordinate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Extracting one grid node's data must never overwrite the session's site coordinate.

    Regression: `_extract_era5_data` used to call `_store_coordinate` with whatever lat/lon
    it was given. The direct-ERA5 flow calls it once per bounding node (four calls), so the
    site silently became whichever node was extracted last, and `_interpolate_era5_to_site`
    (which reads `state.get_coordinate()` as the interpolation target) then degenerated to
    exactly that node's raw value instead of a genuine spatial blend - with no error raised.
    """
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
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda *_args: fake_dataset)
    monkeypatch.setattr(
        "server.tools.era5._era5_cache_path", lambda latitude, longitude: tmp_path / "node.parquet"
    )
    session.set_coordinate(Coordinate(latitude=10.0, longitude=20.0, elevation_m=5.0))

    extract_era5_data(52.5, 4.75, "2024-01-01", "2024-01-01T02:00:00")

    coordinate = session.get_coordinate()
    assert coordinate is not None
    assert coordinate.latitude == 10.0
    assert coordinate.longitude == 20.0


def test_cache_covers_period_handles_tz_aware_cached_index() -> None:
    """A tz-aware cached index must compare against tz-naive request bounds without raising.

    Regression: every ERA5 node is cached tz-aware (UTC), so `_cache_covers_period` raised
    `TypeError: Cannot compare tz-naive and tz-aware timestamps` on any second request for
    the same node/date range - i.e. every cache hit after the first crashed instead of
    serving the cache.
    """
    index = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    frame = pd.DataFrame({"u100": np.ones(48)}, index=index)

    assert _cache_covers_period(frame, "2024-01-01", "2024-01-01T02:00:00") is True
    assert _cache_covers_period(frame, "2023-12-01", "2024-01-01T02:00:00") is False

    aligned = _align_tz(pd.Timestamp("2024-01-01"), frame.index)
    assert aligned.tz is not None


def test_find_era5_nodes_reports_a_missing_credential_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing/invalid EarthDataHub credential must surface as a clear ValueError.

    Regression: a missing or bad PAT makes EarthDataHub respond 401, which previously
    propagated as a raw ``aiohttp.ClientResponseError`` all the way up through FastAPI as an
    opaque 500 - "Find ERA5 nodes (direct)" just failed with no indication of why, which is
    indistinguishable from an unrelated server fault and was the actual cause behind a live
    report of "ERA5 not enabled in the sweep" (the credential wasn't set at acquisition time).
    """

    class _FakeUnauthorized(Exception):
        status = 401

    def _raise_unauthorized(*_args: object, **_kwargs: object) -> None:
        raise _FakeUnauthorized("401, message='Unauthorized'")

    monkeypatch.setattr("server.tools.era5._open_era5_dataset", _raise_unauthorized)

    with pytest.raises(ValueError, match="rejected the request"):
        find_era5_nodes(52.4, 4.8)


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
    reference = np.linspace(3.0, 15.0, _LTC_N)
    measured = 1.1 * reference + 0.5 + np.random.normal(0.0, 0.15, reference.size)
    _set_ltc_frames(measured, reference)
    result = run_ltc_linear_least_squares("Spd_100m", "Spd_100m_hub")
    metrics = result["metrics"]
    assert math.isclose(float(metrics["slope"]), 1.1, abs_tol=0.08)
    assert math.isclose(float(metrics["intercept"]), 0.5, abs_tol=0.3)


def test_ltc_same_column_names_supported() -> None:
    """Verify LTC works when measured and reference series use the same column name."""
    index = pd.date_range("2024-01-01", periods=_LTC_N, freq="h")
    reference = np.linspace(4.0, 12.0, _LTC_N)
    measured = 0.92 * reference + 0.4
    session.timeseries_df = pd.DataFrame({"Spd_100m": measured}, index=index)
    session.era5_interpolated_df = pd.DataFrame({"Spd_100m": reference}, index=index)
    result = run_ltc_linear_least_squares("Spd_100m", "Spd_100m")
    assert result["metrics"]["concurrent_points"] == _LTC_N
    assert result["metrics"]["r_squared"] > 0.99


def test_ltc_speedsort_threshold() -> None:
    """Verify the SpeedSort threshold equals min(4.0, 0.5 × mean reference speed)."""
    reference = np.full(_LTC_N, 7.0)
    measured = reference * 1.05
    _set_ltc_frames(measured, reference)
    result = run_ltc_speedsort("Spd_100m", "Spd_100m_hub")
    assert math.isclose(float(result["metrics"]["threshold"]), 3.5, rel_tol=1e-9)


def test_ltc_variance_ratio_identity() -> None:
    """Verify variance-ratio LTC returns the reference record unchanged when measured equals reference."""
    reference = np.linspace(2.0, 12.0, _LTC_N)
    _set_ltc_frames(reference.copy(), reference.copy())
    result = run_ltc_variance_ratio("Spd_100m", "Spd_100m_hub")
    corrected = session.ltc_results["variance_ratio"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)
    assert np.allclose(corrected, reference)
    assert math.isclose(float(result["metrics"]["variance_ratio"]), 1.0, rel_tol=1e-9)


@pytest.mark.skipif(importlib.util.find_spec("xgboost") is None, reason="xgboost not installed")
def test_ltc_xgboost_runs() -> None:
    """Verify XGBoost LTC produces corrected output and the expected metrics keys on synthetic data."""
    np.random.seed(11)
    reference = 7.0 + 2.0 * np.sin(np.linspace(0.0, 8.0 * np.pi, _LTC_N)) + np.random.normal(0.0, 0.2, _LTC_N)
    measured = 0.9 * reference + 0.7 + 0.3 * np.sin(np.linspace(0.0, 4.0 * np.pi, _LTC_N))
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
    reference = np.linspace(4.0, 14.0, _LTC_N)
    measured = 1.05 * reference + 0.25
    _set_ltc_frames(measured, reference)
    first = run_ltc_total_least_squares("Spd_100m", "Spd_100m_hub")
    first_corrected = session.ltc_results["total_least_squares"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)
    second = run_ltc_total_least_squares("Spd_100m", "Spd_100m_hub")
    second_corrected = session.ltc_results["total_least_squares"]["df"]["corrected_wind_speed"].to_numpy(dtype=float)
    assert np.allclose(first_corrected, second_corrected)
    assert math.isclose(float(first["metrics"]["slope"]), float(second["metrics"]["slope"]), rel_tol=1e-12)
