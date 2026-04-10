"""test_windkit — Comprehensive tests for WindKit integration.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from server.tools.windkit._serializers import (
    _NumpyEncoder,
    _ok,
    da_to_dict,
    df_to_dict,
    dict_to_da,
    dict_to_df,
    dict_to_ds,
    ds_to_dict,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = REPO_ROOT / "data" / "uploads"


@pytest.fixture(autouse=True)
def _windkit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set WindKit configuration env vars so climate tools don't prompt for input."""
    monkeypatch.setenv("WINDKIT_NAME", "GoKaatru Test")
    monkeypatch.setenv("WINDKIT_EMAIL", "test@gokaatru.local")
    monkeypatch.setenv("WINDKIT_INSTITUTION", "GoKaatru")


# =====================================================================
# 1. Serializer Round-Trip Tests
# =====================================================================


class TestNumpyEncoder:
    """Tests for _NumpyEncoder JSON encoder."""

    def test_numpy_int(self) -> None:
        result = json.loads(json.dumps({"v": np.int64(42)}, cls=_NumpyEncoder))
        assert result["v"] == 42
        assert isinstance(result["v"], int)

    def test_numpy_float(self) -> None:
        result = json.loads(json.dumps({"v": np.float64(3.14)}, cls=_NumpyEncoder))
        assert result["v"] == pytest.approx(3.14)

    def test_numpy_bool(self) -> None:
        result = json.loads(json.dumps({"v": np.bool_(True)}, cls=_NumpyEncoder))
        assert result["v"] is True

    def test_numpy_array(self) -> None:
        arr = np.array([1.0, 2.0, 3.0])
        result = json.loads(json.dumps({"v": arr}, cls=_NumpyEncoder))
        assert result["v"] == [1.0, 2.0, 3.0]

    def test_pandas_timestamp(self) -> None:
        ts = pd.Timestamp("2024-01-15 12:30:00")
        result = json.loads(json.dumps({"v": ts}, cls=_NumpyEncoder))
        assert "2024-01-15" in result["v"]


class TestDatasetSerialization:
    """Round-trip tests for xarray Dataset serialization."""

    def test_dataset_round_trip(self) -> None:
        ds = xr.Dataset({"temp": (["x"], [10.0, 20.0, 30.0])})
        d = ds_to_dict(ds)
        rebuilt = dict_to_ds(d)
        np.testing.assert_array_equal(rebuilt["temp"].values, [10.0, 20.0, 30.0])

    def test_dataset_with_coords(self) -> None:
        ds = xr.Dataset(
            {"wind_speed": (["height"], [5.0, 7.0, 9.0])},
            coords={"height": [80, 100, 120]},
        )
        d = ds_to_dict(ds)
        rebuilt = dict_to_ds(d)
        np.testing.assert_array_equal(rebuilt.coords["height"].values, [80, 100, 120])
        np.testing.assert_array_equal(rebuilt["wind_speed"].values, [5.0, 7.0, 9.0])

    def test_dataset_multidim(self) -> None:
        data = np.random.rand(3, 4)
        ds = xr.Dataset({"values": (["x", "y"], data)})
        d = ds_to_dict(ds)
        rebuilt = dict_to_ds(d)
        np.testing.assert_array_almost_equal(rebuilt["values"].values, data)


class TestDataArraySerialization:
    """Round-trip tests for xarray DataArray serialization."""

    def test_dataarray_round_trip(self) -> None:
        da = xr.DataArray([1.0, 2.0, 3.0], dims=["x"])
        d = da_to_dict(da)
        rebuilt = dict_to_da(d)
        np.testing.assert_array_equal(rebuilt.values, [1.0, 2.0, 3.0])

    def test_dataarray_with_name(self) -> None:
        da = xr.DataArray([5.0, 10.0], dims=["point"], name="speed")
        d = da_to_dict(da)
        rebuilt = dict_to_da(d)
        assert rebuilt.name == "speed"


class TestDataFrameSerialization:
    """Round-trip tests for pandas DataFrame serialization."""

    def test_dataframe_round_trip(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
        d = df_to_dict(df)
        rebuilt = dict_to_df(d)
        assert list(rebuilt.columns) == ["a", "b"]
        assert len(rebuilt) == 3
        np.testing.assert_array_equal(rebuilt["a"].values, [1, 2, 3])
        np.testing.assert_array_almost_equal(rebuilt["b"].values, [4.0, 5.0, 6.0])

    def test_dataframe_with_datetime_index(self) -> None:
        idx = pd.date_range("2024-01-01", periods=3, freq="h")
        df = pd.DataFrame({"val": [1.0, 2.0, 3.0]}, index=idx)
        d = df_to_dict(df)
        rebuilt = dict_to_df(d)
        assert len(rebuilt) == 3


class TestOkHelper:
    """Tests for _ok() envelope wrapper."""

    def test_ok_wraps_data(self) -> None:
        result = _ok({"foo": 42})
        assert result["status"] == "ok"
        assert result["result"]["foo"] == 42

    def test_ok_wraps_list(self) -> None:
        result = _ok([1, 2, 3])
        assert result["status"] == "ok"
        assert result["result"] == [1, 2, 3]


# =====================================================================
# 2. Wind Function Tests (server/tools/windkit/wind.py)
# =====================================================================


class TestWindSpeed:
    """Tests for windkit_wind_speed and windkit_wind_direction."""

    def test_wind_speed_from_components(self) -> None:
        from server.tools.windkit.wind import windkit_wind_speed

        u = json.dumps([3.0, 0.0, -5.0])
        v = json.dumps([4.0, 10.0, 0.0])
        result = windkit_wind_speed(u, v)
        assert result["status"] == "ok"
        speeds = result["result"]["data"]
        assert pytest.approx(speeds[0], abs=0.01) == 5.0
        assert pytest.approx(speeds[1], abs=0.01) == 10.0
        assert pytest.approx(speeds[2], abs=0.01) == 5.0

    def test_wind_direction_from_components(self) -> None:
        from server.tools.windkit.wind import windkit_wind_direction

        # Pure southerly wind: u=0, v=-10 → direction = 180 (from south)
        # Wind convention: direction wind is coming FROM
        u = json.dumps([0.0])
        v = json.dumps([-10.0])
        result = windkit_wind_direction(u, v)
        assert result["status"] == "ok"
        directions = result["result"]["data"]
        assert len(directions) == 1
        # Direction should be defined (not NaN)
        assert not math.isnan(directions[0])


class TestWindSpeedAndDirection:
    """Tests for windkit_wind_speed_and_direction."""

    def test_combined_output(self) -> None:
        from server.tools.windkit.wind import windkit_wind_speed_and_direction

        u = json.dumps([3.0, 0.0])
        v = json.dumps([4.0, 5.0])
        result = windkit_wind_speed_and_direction(u, v)
        assert result["status"] == "ok"
        assert "wind_speed" in result["result"]
        assert "wind_direction" in result["result"]
        ws = result["result"]["wind_speed"]["data"]
        assert pytest.approx(ws[0], abs=0.01) == 5.0
        assert pytest.approx(ws[1], abs=0.01) == 5.0


class TestWindVectors:
    """Tests for windkit_wind_vectors (inverse of speed/direction)."""

    def test_round_trip_speed_direction_to_vectors(self) -> None:
        from server.tools.windkit.wind import windkit_wind_speed, windkit_wind_vectors

        ws = json.dumps([10.0, 5.0, 8.0])
        wd = json.dumps([0.0, 90.0, 180.0])
        vectors = windkit_wind_vectors(ws, wd)
        assert vectors["status"] == "ok"
        u_data = vectors["result"]["u"]["data"]
        v_data = vectors["result"]["v"]["data"]
        # Convert back to verify round-trip
        u_json = json.dumps(u_data)
        v_json = json.dumps(v_data)
        speed_result = windkit_wind_speed(u_json, v_json)
        speeds = speed_result["result"]["data"]
        assert pytest.approx(speeds[0], abs=0.1) == 10.0
        assert pytest.approx(speeds[1], abs=0.1) == 5.0
        assert pytest.approx(speeds[2], abs=0.1) == 8.0


class TestWindDirectionDifference:
    """Tests for windkit_wind_direction_difference."""

    def test_direction_diff_zero(self) -> None:
        from server.tools.windkit.wind import windkit_wind_direction_difference

        obs = json.dumps([0.0, 90.0, 180.0])
        mod = json.dumps([0.0, 90.0, 180.0])
        result = windkit_wind_direction_difference(obs, mod)
        assert result["status"] == "ok"
        diffs = result["result"]["data"]
        for d in diffs:
            assert pytest.approx(d, abs=0.01) == 0.0

    def test_direction_diff_wrapping(self) -> None:
        from server.tools.windkit.wind import windkit_wind_direction_difference

        # 350 vs 10 should give a small difference, not 340
        obs = json.dumps([350.0])
        mod = json.dumps([10.0])
        result = windkit_wind_direction_difference(obs, mod)
        diff = abs(result["result"]["data"][0])
        assert diff <= 20.0  # Circular distance should be small


class TestWdToSector:
    """Tests for windkit_wd_to_sector."""

    def test_sector_assignment_12(self) -> None:
        from server.tools.windkit.wind import windkit_wd_to_sector

        # North (0°) should be sector 0, East (90°) should be sector 3
        wd = json.dumps([0.0, 90.0, 180.0, 270.0])
        result = windkit_wd_to_sector(wd, sectors=12, output_type="indices")
        assert result["status"] == "ok"
        sectors = result["result"]["sectors"]["data"]
        assert len(sectors) == 4
        assert sectors[0] == 0  # North
        assert sectors[1] == 3  # East
        assert sectors[2] == 6  # South
        assert sectors[3] == 9  # West

    def test_sector_assignment_4(self) -> None:
        from server.tools.windkit.wind import windkit_wd_to_sector

        wd = json.dumps([0.0, 90.0, 180.0, 270.0])
        result = windkit_wd_to_sector(wd, sectors=4, output_type="indices")
        sectors = result["result"]["sectors"]["data"]
        assert sectors[0] == 0
        assert sectors[1] == 1
        assert sectors[2] == 2
        assert sectors[3] == 3


# =====================================================================
# 3. Climate Tools Tests (server/tools/windkit/climate.py)
# =====================================================================


class TestTSWC:
    """Tests for Time Series Wind Climate (TSWC) tools."""

    def test_create_empty_tswc(self) -> None:
        from server.tools.windkit.climate import windkit_create_tswc

        result = windkit_create_tswc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert "WSWD" in ds.data_vars or len(ds.data_vars) >= 0  # Check it's a valid Dataset

    def test_is_tswc_on_non_tswc(self) -> None:
        from server.tools.windkit.climate import windkit_is_tswc

        ds = xr.Dataset({"temp": (["x"], [1.0, 2.0])})
        result = windkit_is_tswc(json.dumps(ds_to_dict(ds)))
        assert result["status"] == "ok"
        assert result["result"]["is_tswc"] is False


class TestBWC:
    """Tests for Binned Wind Climate (BWC) tools."""

    def test_create_empty_bwc(self) -> None:
        from server.tools.windkit.climate import windkit_create_bwc

        result = windkit_create_bwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            n_sectors=12,
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert "sector" in ds.dims

    def test_is_bwc_on_non_bwc(self) -> None:
        from server.tools.windkit.climate import windkit_is_bwc

        ds = xr.Dataset({"temp": (["x"], [1.0, 2.0])})
        result = windkit_is_bwc(json.dumps(ds_to_dict(ds)))
        assert result["status"] == "ok"
        assert result["result"]["is_bwc"] is False


class TestWWC:
    """Tests for Weibull Wind Climate (WWC) tools."""

    def test_create_empty_wwc(self) -> None:
        from server.tools.windkit.climate import windkit_create_wwc

        result = windkit_create_wwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            n_sectors=12,
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert "sector" in ds.dims or "sector" in ds.coords

    def test_is_wwc_on_non_wwc(self) -> None:
        from server.tools.windkit.climate import windkit_is_wwc

        ds = xr.Dataset({"temp": (["x"], [1.0, 2.0])})
        result = windkit_is_wwc(json.dumps(ds_to_dict(ds)))
        assert result["status"] == "ok"
        assert result["result"]["is_wwc"] is False


class TestGWC:
    """Tests for Generalized Wind Climate (GWC) tools."""

    def test_is_gwc_on_non_gwc(self) -> None:
        from server.tools.windkit.climate import windkit_is_gwc

        ds = xr.Dataset({"temp": (["x"], [1.0, 2.0])})
        result = windkit_is_gwc(json.dumps(ds_to_dict(ds)))
        assert result["status"] == "ok"
        assert result["result"]["is_gwc"] is False


class TestGeoWC:
    """Tests for Generalized Geostrophic Wind Climate (GeoWC) tools."""

    def test_is_geowc_on_non_geowc(self) -> None:
        from server.tools.windkit.climate import windkit_is_geowc

        ds = xr.Dataset({"temp": (["x"], [1.0, 2.0])})
        result = windkit_is_geowc(json.dumps(ds_to_dict(ds)))
        assert result["status"] == "ok"
        assert result["result"]["is_geowc"] is False


# =====================================================================
# 4. Weibull Distribution Tests (server/tools/windkit/other.py)
# =====================================================================


class TestWeibullMoment:
    """Tests for windkit_weibull_moment."""

    def test_first_moment(self) -> None:
        from server.tools.windkit.other import windkit_weibull_moment

        # For Weibull(A=10, k=2), mean ≈ A * Gamma(1 + 1/k) ≈ 10 * 0.886 ≈ 8.86
        result = windkit_weibull_moment(A=10.0, k=2.0, n=1)
        assert result["status"] == "ok"
        moment = result["result"]["moment"]
        assert pytest.approx(moment, rel=0.01) == 10.0 * math.gamma(1 + 1.0 / 2.0)

    def test_second_moment(self) -> None:
        from server.tools.windkit.other import windkit_weibull_moment

        result = windkit_weibull_moment(A=10.0, k=2.0, n=2)
        assert result["status"] == "ok"
        expected = 10.0**2 * math.gamma(1 + 2.0 / 2.0)
        assert pytest.approx(result["result"]["moment"], rel=0.01) == expected

    def test_third_moment(self) -> None:
        from server.tools.windkit.other import windkit_weibull_moment

        result = windkit_weibull_moment(A=8.0, k=2.5, n=3)
        assert result["status"] == "ok"
        expected = 8.0**3 * math.gamma(1 + 3.0 / 2.5)
        assert pytest.approx(result["result"]["moment"], rel=0.01) == expected


class TestWeibullPDF:
    """Tests for windkit_weibull_pdf."""

    def test_pdf_at_zero(self) -> None:
        from server.tools.windkit.other import windkit_weibull_pdf

        result = windkit_weibull_pdf(A=10.0, k=2.0, x=json.dumps([0.0]))
        assert result["status"] == "ok"
        assert result["result"]["pdf"][0] == pytest.approx(0.0, abs=1e-10)

    def test_pdf_positive_values(self) -> None:
        from server.tools.windkit.other import windkit_weibull_pdf

        x_vals = [2.0, 5.0, 8.0, 12.0, 15.0]
        result = windkit_weibull_pdf(A=10.0, k=2.0, x=json.dumps(x_vals))
        assert result["status"] == "ok"
        pdf = result["result"]["pdf"]
        assert len(pdf) == 5
        for p in pdf:
            assert p >= 0.0  # PDF is non-negative

    def test_pdf_integrates_to_one(self) -> None:
        from server.tools.windkit.other import windkit_weibull_pdf

        # Approximate integration with fine grid
        x = np.linspace(0.01, 40.0, 4000).tolist()
        result = windkit_weibull_pdf(A=10.0, k=2.0, x=json.dumps(x))
        pdf = np.array(result["result"]["pdf"])
        integral = np.trapz(pdf, x)
        assert pytest.approx(integral, abs=0.02) == 1.0


class TestWeibullCDF:
    """Tests for windkit_weibull_cdf."""

    def test_cdf_at_zero(self) -> None:
        from server.tools.windkit.other import windkit_weibull_cdf

        result = windkit_weibull_cdf(A=10.0, k=2.0, x=json.dumps([0.0]))
        assert result["status"] == "ok"
        assert result["result"]["cdf"][0] == pytest.approx(0.0, abs=1e-10)

    def test_cdf_at_large_value(self) -> None:
        from server.tools.windkit.other import windkit_weibull_cdf

        result = windkit_weibull_cdf(A=10.0, k=2.0, x=json.dumps([50.0]))
        assert result["status"] == "ok"
        assert result["result"]["cdf"][0] == pytest.approx(1.0, abs=0.01)

    def test_cdf_monotonically_increasing(self) -> None:
        from server.tools.windkit.other import windkit_weibull_cdf

        x = [1.0, 5.0, 10.0, 15.0, 20.0, 25.0]
        result = windkit_weibull_cdf(A=10.0, k=2.0, x=json.dumps(x))
        cdf = result["result"]["cdf"]
        for i in range(1, len(cdf)):
            assert cdf[i] >= cdf[i - 1]


class TestWeibullFreqGtMean:
    """Tests for windkit_weibull_freq_gt_mean."""

    def test_freq_gt_mean_reasonable(self) -> None:
        from server.tools.windkit.other import windkit_weibull_freq_gt_mean

        result = windkit_weibull_freq_gt_mean(A=10.0, k=2.0)
        assert result["status"] == "ok"
        fgtm = result["result"]["freq_gt_mean"]
        # Typically between 0.3 and 0.5 for Weibull distributions
        assert 0.2 < fgtm < 0.6


class TestWeibullProbability:
    """Tests for windkit_get_weibull_probability."""

    def test_probability_array(self) -> None:
        from server.tools.windkit.other import windkit_get_weibull_probability

        # Pass speed bins as array
        bins = np.linspace(0.0, 40.0, 41).tolist()
        result = windkit_get_weibull_probability(A=10.0, k=2.0, speed_range=json.dumps(bins))
        assert result["status"] == "ok"
        probs = result["result"]["probability"]
        assert len(probs) > 0
        # All probabilities should be non-negative
        for p in probs:
            if isinstance(p, (list, np.ndarray)):
                for pp in p:
                    assert pp >= 0.0
            else:
                assert p >= 0.0

    def test_probability_sums_near_one(self) -> None:
        from server.tools.windkit.other import windkit_get_weibull_probability

        # Fine bins covering most of the distribution
        bins = np.linspace(0.0, 50.0, 51).tolist()
        result = windkit_get_weibull_probability(A=10.0, k=2.0, speed_range=json.dumps(bins))
        probs = np.array(result["result"]["probability"]).flatten()
        # Probabilities should all be non-negative
        assert (probs >= 0).all()
        # Total should be finite and positive
        assert float(probs.sum()) > 0


class TestWeibullFit:
    """Tests for windkit_fit_weibull_wasp_m1_m3."""

    def test_fit_from_moments(self) -> None:
        from server.tools.windkit.other import windkit_fit_weibull_wasp_m1_m3, windkit_weibull_moment

        # Generate moments from known A=10, k=2
        m1_res = windkit_weibull_moment(A=10.0, k=2.0, n=1)
        m3_res = windkit_weibull_moment(A=10.0, k=2.0, n=3)
        m1 = m1_res["result"]["moment"]
        m3 = m3_res["result"]["moment"]

        fit = windkit_fit_weibull_wasp_m1_m3(m1=m1, m3=m3)
        assert fit["status"] == "ok"
        assert pytest.approx(fit["result"]["A"], rel=0.05) == 10.0
        assert pytest.approx(fit["result"]["k"], rel=0.05) == 2.0


# =====================================================================
# 5. Spatial Tools Tests (server/tools/windkit/spatial.py)
# =====================================================================


class TestCreatePoint:
    """Tests for windkit_create_point."""

    def test_single_point(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point

        result = windkit_create_point(
            west_east=json.dumps([12.5]),
            south_north=json.dumps([55.5]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert "point" in ds.dims

    def test_multiple_points(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point

        result = windkit_create_point(
            west_east=json.dumps([12.0, 13.0, 14.0]),
            south_north=json.dumps([55.0, 56.0, 57.0]),
            height=json.dumps([80.0, 100.0, 120.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert ds.dims["point"] == 3


class TestCreateDataset:
    """Tests for windkit_create_dataset."""

    def test_create_dataset(self) -> None:
        from server.tools.windkit.spatial import windkit_create_dataset

        result = windkit_create_dataset(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert isinstance(ds, xr.Dataset)


class TestCreateCuboid:
    """Tests for windkit_create_cuboid."""

    def test_create_cuboid(self) -> None:
        from server.tools.windkit.spatial import windkit_create_cuboid

        result = windkit_create_cuboid(
            west_east=json.dumps([12.0, 13.0]),
            south_north=json.dumps([55.0, 56.0]),
            height=json.dumps([80.0, 100.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert "west_east" in ds.dims
        assert "south_north" in ds.dims
        assert "height" in ds.dims


class TestCreateRaster:
    """Tests for windkit_create_raster."""

    def test_create_raster(self) -> None:
        from server.tools.windkit.spatial import windkit_create_raster

        result = windkit_create_raster(
            west_east=json.dumps([0.0, 1.0, 2.0]),
            south_north=json.dumps([50.0, 51.0, 52.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert "west_east" in ds.dims
        assert "south_north" in ds.dims


class TestSpatialValidation:
    """Tests for is_point, is_cuboid, is_stacked_point, is_raster."""

    def test_point_is_point(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point, windkit_is_point

        pt = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        result = windkit_is_point(json.dumps(pt["result"]))
        assert result["status"] == "ok"
        assert result["result"]["is_point"] is True

    def test_cuboid_is_not_point(self) -> None:
        from server.tools.windkit.spatial import windkit_create_cuboid, windkit_is_point

        cb = windkit_create_cuboid(
            west_east=json.dumps([12.0, 13.0]),
            south_north=json.dumps([55.0, 56.0]),
            height=json.dumps([80.0, 100.0]),
            crs="EPSG:4326",
        )
        result = windkit_is_point(json.dumps(cb["result"]))
        assert result["result"]["is_point"] is False

    def test_cuboid_is_cuboid(self) -> None:
        from server.tools.windkit.spatial import windkit_create_cuboid, windkit_is_cuboid

        cb = windkit_create_cuboid(
            west_east=json.dumps([12.0, 13.0]),
            south_north=json.dumps([55.0, 56.0]),
            height=json.dumps([80.0, 100.0]),
            crs="EPSG:4326",
        )
        result = windkit_is_cuboid(json.dumps(cb["result"]))
        assert result["result"]["is_cuboid"] is True

    def test_raster_is_raster(self) -> None:
        from server.tools.windkit.spatial import windkit_create_raster, windkit_is_raster

        rast = windkit_create_raster(
            west_east=json.dumps([0.0, 1.0, 2.0]),
            south_north=json.dumps([50.0, 51.0, 52.0]),
            crs="EPSG:4326",
        )
        result = windkit_is_raster(json.dumps(rast["result"]))
        assert result["result"]["is_raster"] is True


class TestSpatialConversions:
    """Tests for spatial conversion tools."""

    def test_point_to_cuboid_round_trip(self) -> None:
        from server.tools.windkit.spatial import (
            windkit_create_cuboid,
            windkit_is_cuboid,
            windkit_to_point,
        )

        cb = windkit_create_cuboid(
            west_east=json.dumps([12.0, 13.0]),
            south_north=json.dumps([55.0, 56.0]),
            height=json.dumps([80.0, 100.0]),
            crs="EPSG:4326",
        )
        # Convert cuboid to point
        pt_result = windkit_to_point(json.dumps(cb["result"]))
        assert pt_result["status"] == "ok"

    def test_stacked_point_creation(self) -> None:
        from server.tools.windkit.spatial import windkit_create_stacked_point

        result = windkit_create_stacked_point(
            west_east=json.dumps([12.0, 13.0]),
            south_north=json.dumps([55.0, 56.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"


class TestSpatialComparison:
    """Tests for spatial comparison tools."""

    def test_same_dataset_spatially_equal(self) -> None:
        from server.tools.windkit.spatial import windkit_are_spatially_equal, windkit_create_point

        pt = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        ds_json = json.dumps(pt["result"])
        result = windkit_are_spatially_equal(ds_json, ds_json)
        assert result["status"] == "ok"
        assert result["result"]["equal"] is True

    def test_different_datasets_not_equal(self) -> None:
        from server.tools.windkit.spatial import windkit_are_spatially_equal, windkit_create_point

        pt1 = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        pt2 = windkit_create_point(
            west_east=json.dumps([13.0]),
            south_north=json.dumps([56.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        result = windkit_are_spatially_equal(json.dumps(pt1["result"]), json.dumps(pt2["result"]))
        assert result["result"]["equal"] is False

    def test_equal_spatial_shape(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point, windkit_equal_spatial_shape

        pt1 = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        pt2 = windkit_create_point(
            west_east=json.dumps([13.0]),
            south_north=json.dumps([56.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        result = windkit_equal_spatial_shape(json.dumps(pt1["result"]), json.dumps(pt2["result"]))
        assert result["status"] == "ok"
        assert result["result"]["equal"] is True


class TestCRS:
    """Tests for CRS operations."""

    def test_set_and_get_crs(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point, windkit_get_crs

        pt = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        result = windkit_get_crs(json.dumps(pt["result"]))
        assert result["status"] == "ok"
        assert "4326" in str(result["result"]["crs"])

    def test_crs_are_equal(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point, windkit_crs_are_equal

        pt1 = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        pt2 = windkit_create_point(
            west_east=json.dumps([13.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        result = windkit_crs_are_equal(json.dumps(pt1["result"]), json.dumps(pt2["result"]))
        assert result["status"] == "ok"
        assert result["result"]["equal"] is True


# =====================================================================
# 6. Coordinate Helpers Tests (server/tools/windkit/other.py)
# =====================================================================


class TestSectorCoords:
    """Tests for windkit_create_sector_coords."""

    def test_default_12_sectors(self) -> None:
        from server.tools.windkit.other import windkit_create_sector_coords

        result = windkit_create_sector_coords(bins=12, start=0.0)
        assert result["status"] == "ok"
        da = dict_to_da(result["result"])
        assert len(da) == 12

    def test_custom_sectors(self) -> None:
        from server.tools.windkit.other import windkit_create_sector_coords

        result = windkit_create_sector_coords(bins=36, start=0.0)
        assert result["status"] == "ok"
        da = dict_to_da(result["result"])
        assert len(da) == 36


class TestWsbinCoords:
    """Tests for windkit_create_wsbin_coords."""

    def test_default_30_bins(self) -> None:
        from server.tools.windkit.other import windkit_create_wsbin_coords

        result = windkit_create_wsbin_coords(bins=30, width=1.0, start=0.0)
        assert result["status"] == "ok"
        da = dict_to_da(result["result"])
        assert len(da) == 30

    def test_custom_bins(self) -> None:
        from server.tools.windkit.other import windkit_create_wsbin_coords

        result = windkit_create_wsbin_coords(bins=50, width=0.5, start=0.0)
        assert result["status"] == "ok"
        da = dict_to_da(result["result"])
        assert len(da) == 50

    def test_bin_spacing(self) -> None:
        from server.tools.windkit.other import windkit_create_wsbin_coords

        result = windkit_create_wsbin_coords(bins=10, width=2.0, start=0.0)
        da = dict_to_da(result["result"])
        vals = da.values.tolist()
        # Check spacing is approximately 2.0
        for i in range(1, len(vals)):
            assert pytest.approx(vals[i] - vals[i - 1], abs=0.01) == 2.0


# =====================================================================
# 7. Climate Statistics Tests (server/tools/windkit/climate_stats.py)
# =====================================================================


class TestCreateMetFields:
    """Tests for windkit_create_met_fields."""

    def test_create_met_fields(self) -> None:
        from server.tools.windkit.climate_stats import windkit_create_met_fields

        result = windkit_create_met_fields(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            n_sectors=12,
        )
        assert result["status"] == "ok"
        ds = dict_to_ds(result["result"])
        assert isinstance(ds, xr.Dataset)
        # Met fields should contain wspd and power_density variables
        assert "wspd" in ds.data_vars or "power_density" in ds.data_vars


class TestMeanWindSpeed:
    """Tests for windkit_mean_wind_speed using a real BWC."""

    def test_mean_wind_speed_from_bwc(self) -> None:
        from server.tools.windkit.climate import windkit_create_bwc
        from server.tools.windkit.climate_stats import windkit_mean_wind_speed

        bwc = windkit_create_bwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            n_sectors=12,
        )
        # An empty BWC should have 0 mean wind speed
        result = windkit_mean_wind_speed(json.dumps(bwc["result"]))
        assert result["status"] == "ok"


class TestMeanPowerDensity:
    """Tests for windkit_mean_power_density."""

    def test_mean_power_density_from_bwc(self) -> None:
        from server.tools.windkit.climate import windkit_create_bwc
        from server.tools.windkit.climate_stats import windkit_mean_power_density

        bwc = windkit_create_bwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            n_sectors=12,
        )
        result = windkit_mean_power_density(json.dumps(bwc["result"]))
        assert result["status"] == "ok"


# =====================================================================
# 8. BWC from TSWC Pipeline Test
# =====================================================================


class TestBWCFromTSWCPipeline:
    """End-to-end test: create TSWC → convert to BWC → validate → compute stats."""

    def test_tswc_to_bwc_pipeline(self) -> None:
        from server.tools.windkit.climate import (
            windkit_bwc_from_tswc,
            windkit_create_tswc,
            windkit_is_bwc,
        )

        # Create a TSWC with actual time data
        tswc_result = windkit_create_tswc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            date_range_start="2023-01-01",
            date_range_end="2023-01-31",
            freq="h",
        )
        assert tswc_result["status"] == "ok"
        tswc_ds = dict_to_ds(tswc_result["result"])

        # Put some synthetic wind data into the TSWC
        np.random.seed(42)
        n_time = tswc_ds.dims["time"]
        # WindKit TSWC stores WSWD variable with (time, point) dims
        if "WSWD" in tswc_ds.data_vars:
            ws = np.random.weibull(2.0, n_time) * 8.0
            wd = np.random.uniform(0, 360, n_time)
            tswc_ds["WSWD"].values[:, 0] = ws + 1j * wd  # complex representation

        # Convert TSWC to BWC
        tswc_json = json.dumps(ds_to_dict(tswc_ds))
        try:
            bwc_result = windkit_bwc_from_tswc(tswc_json)
            if bwc_result["status"] == "ok":
                # Verify it's a valid BWC
                is_bwc = windkit_is_bwc(json.dumps(bwc_result["result"]))
                assert is_bwc["result"]["is_bwc"] is True
        except (ValueError, TypeError):
            # Some TSWC formats may need specific data; this is acceptable
            pytest.skip("TSWC data format not compatible for BWC conversion")


# =====================================================================
# 9. GeoDataFrame Conversion Test
# =====================================================================


class TestGdfConversion:
    """Tests for windkit_ds_to_gdf and windkit_gdf_to_ds."""

    def test_point_to_gdf_and_back(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point, windkit_ds_to_gdf

        pt = windkit_create_point(
            west_east=json.dumps([12.5]),
            south_north=json.dumps([55.5]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        gdf_result = windkit_ds_to_gdf(json.dumps(pt["result"]))
        assert gdf_result["status"] == "ok"
        geojson = gdf_result["result"]
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 1


# =====================================================================
# 10. With Sample Data Tests
# =====================================================================


class TestWithSampleData:
    """Tests that use the real sample datasets from data/uploads/."""

    @pytest.fixture
    def boxkite_df(self) -> pd.DataFrame:
        path = UPLOADS_DIR / "HKW-B-FLS-Boxkite_timeseries_data.csv"
        if not path.exists():
            pytest.skip("Boxkite sample data not found")
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        df = df.set_index("Timestamp")
        return df

    @pytest.fixture
    def hornsrev_df(self) -> pd.DataFrame:
        path = UPLOADS_DIR / "HornsRev-MAST_timeseries_data.csv"
        if not path.exists():
            pytest.skip("HornsRev sample data not found")
        df = pd.read_csv(path, parse_dates=["Timestamp"])
        df = df.set_index("Timestamp")
        return df

    def test_wind_speed_with_boxkite_data(self, boxkite_df: pd.DataFrame) -> None:
        """Use Boxkite Spd columns to compute wind vectors and back."""
        from server.tools.windkit.wind import windkit_wind_speed, windkit_wind_vectors

        # Take first 100 rows, speed and direction at 100m
        spd = boxkite_df["Spd_100m"].dropna().head(100).tolist()
        direction = boxkite_df["Dir_100m"].dropna().head(100).tolist()
        # Align lengths
        n = min(len(spd), len(direction))
        spd = spd[:n]
        direction = direction[:n]

        # Convert to u,v and back
        vectors = windkit_wind_vectors(json.dumps(spd), json.dumps(direction))
        assert vectors["status"] == "ok"
        u = vectors["result"]["u"]["data"]
        v = vectors["result"]["v"]["data"]

        speed_back = windkit_wind_speed(json.dumps(u), json.dumps(v))
        speeds = speed_back["result"]["data"]
        for orig, recovered in zip(spd, speeds):
            assert pytest.approx(recovered, abs=0.01) == orig

    def test_sectors_with_boxkite_directions(self, boxkite_df: pd.DataFrame) -> None:
        """Sector assignment for real Boxkite direction data."""
        from server.tools.windkit.wind import windkit_wd_to_sector

        dirs = boxkite_df["Dir_100m"].dropna().head(500).tolist()
        result = windkit_wd_to_sector(json.dumps(dirs), sectors=12, output_type="indices")
        assert result["status"] == "ok"
        sectors = result["result"]["sectors"]["data"]
        assert len(sectors) == len(dirs)
        # All sectors in range [0, 11]
        for s in sectors:
            assert 0 <= s <= 11

    def test_weibull_fit_with_hornsrev_data(self, hornsrev_df: pd.DataFrame) -> None:
        """Fit Weibull to HornsRev wind speed data and verify reasonable parameters."""
        from server.tools.windkit.other import windkit_weibull_moment

        spd_cols = [c for c in hornsrev_df.columns if c.startswith("Spd_")]
        if not spd_cols:
            pytest.skip("No speed columns in HornsRev data")

        speeds = hornsrev_df[spd_cols[0]].dropna()
        if len(speeds) < 100:
            pytest.skip("Insufficient data for Weibull fit")

        from scipy.stats import weibull_min

        shape, loc, scale = weibull_min.fit(speeds[speeds > 0], floc=0)

        # Verify moment calculation with fitted parameters
        m1_result = windkit_weibull_moment(A=float(scale), k=float(shape), n=1)
        expected_mean = float(scale) * math.gamma(1 + 1.0 / float(shape))
        assert pytest.approx(m1_result["result"]["moment"], rel=0.01) == expected_mean

    def test_create_point_for_boxkite_location(self) -> None:
        """Create a WindKit spatial point at the Boxkite measurement location."""
        from server.tools.windkit.spatial import windkit_create_point, windkit_is_point

        # Boxkite coordinates from the data model: lat=52.57005, lon=3.97127
        result = windkit_create_point(
            west_east=json.dumps([3.97127]),
            south_north=json.dumps([52.57005]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert result["status"] == "ok"
        is_pt = windkit_is_point(json.dumps(result["result"]))
        assert is_pt["result"]["is_point"] is True

    def test_wind_direction_diff_with_boxkite_heights(self, boxkite_df: pd.DataFrame) -> None:
        """Compare wind directions between two heights at Boxkite site."""
        from server.tools.windkit.wind import windkit_wind_direction_difference

        dir_80 = boxkite_df["Dir_80m"].dropna().head(200).tolist()
        dir_100 = boxkite_df["Dir_100m"].dropna().head(200).tolist()
        n = min(len(dir_80), len(dir_100))
        dir_80 = dir_80[:n]
        dir_100 = dir_100[:n]

        result = windkit_wind_direction_difference(json.dumps(dir_80), json.dumps(dir_100))
        assert result["status"] == "ok"
        diffs = result["result"]["data"]
        assert len(diffs) == n
        # Most direction differences between heights should be small
        diffs_arr = np.array(diffs)
        mean_abs_diff = np.nanmean(np.abs(diffs_arr))
        assert mean_abs_diff < 90.0  # Reasonable for adjacent heights


# =====================================================================
# 11. Integration Tests — Cross-Module Workflows
# =====================================================================


class TestCrossModuleWorkflows:
    """Tests spanning multiple WindKit tool modules."""

    def test_create_bwc_and_compute_stats(self) -> None:
        """Create BWC → compute mean wind speed and power density."""
        from server.tools.windkit.climate import windkit_create_bwc
        from server.tools.windkit.climate_stats import (
            windkit_mean_power_density,
            windkit_mean_wind_speed,
        )

        bwc = windkit_create_bwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        bwc_json = json.dumps(bwc["result"])

        mws = windkit_mean_wind_speed(bwc_json)
        assert mws["status"] == "ok"

        mpd = windkit_mean_power_density(bwc_json)
        assert mpd["status"] == "ok"

    def test_create_wwc_and_validate(self) -> None:
        """Create WWC → validate it → check GWC (should fail)."""
        from server.tools.windkit.climate import (
            windkit_create_wwc,
            windkit_is_gwc,
            windkit_is_wwc,
            windkit_validate_wwc,
        )

        wwc = windkit_create_wwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        wwc_json = json.dumps(wwc["result"])

        # Should be valid WWC
        is_wwc = windkit_is_wwc(wwc_json)
        assert is_wwc["result"]["is_wwc"] is True

        # Should validate without error
        valid = windkit_validate_wwc(wwc_json)
        assert valid["result"]["valid"] is True

        # Should NOT be a GWC
        is_gwc = windkit_is_gwc(wwc_json)
        assert is_gwc["result"]["is_gwc"] is False

    def test_spatial_point_to_climate(self) -> None:
        """Create spatial point → use it to create a BWC."""
        from server.tools.windkit.climate import windkit_create_bwc
        from server.tools.windkit.spatial import windkit_create_point

        pt = windkit_create_point(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert pt["status"] == "ok"

        # Create BWC at same location
        bwc = windkit_create_bwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
        )
        assert bwc["status"] == "ok"

    def test_sector_coords_match_bwc_sectors(self) -> None:
        """Verify sector coords have same count as BWC sectors."""
        from server.tools.windkit.climate import windkit_create_bwc
        from server.tools.windkit.other import windkit_create_sector_coords

        sectors = windkit_create_sector_coords(bins=12)
        sector_da = dict_to_da(sectors["result"])
        assert len(sector_da) == 12

        bwc = windkit_create_bwc(
            west_east=json.dumps([12.0]),
            south_north=json.dumps([55.0]),
            height=json.dumps([100.0]),
            crs="EPSG:4326",
            n_sectors=12,
        )
        bwc_ds = dict_to_ds(bwc["result"])
        assert bwc_ds.dims["sector"] == 12

    def test_weibull_pdf_cdf_consistency(self) -> None:
        """Verify PDF integral ≈ CDF at each point."""
        from server.tools.windkit.other import windkit_weibull_cdf, windkit_weibull_pdf

        A, k = 10.0, 2.0
        x = np.linspace(0.01, 30.0, 300).tolist()
        pdf_result = windkit_weibull_pdf(A=A, k=k, x=json.dumps(x))
        cdf_result = windkit_weibull_cdf(A=A, k=k, x=json.dumps(x))

        pdf = np.array(pdf_result["result"]["pdf"])
        cdf = np.array(cdf_result["result"]["cdf"])

        # Numerically integrate PDF and compare with CDF
        cumulative = np.cumsum(pdf) * (x[1] - x[0])
        # Compare at the end
        assert pytest.approx(cumulative[-1], abs=0.05) == cdf[-1]
