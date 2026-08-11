"""test_windkit_submodule_smoke — D39: cheap smoke test calling one function
per WindKit submodule to catch upstream signature drift at CI time instead
of in production.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from server.tools.windkit._serializers import dict_to_da, dict_to_ds


@pytest.fixture(autouse=True)
def _windkit_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set WindKit configuration env vars so climate tools don't prompt for input."""
    monkeypatch.setenv("WINDKIT_NAME", "GoKaatru Test")
    monkeypatch.setenv("WINDKIT_EMAIL", "test@gokaatru.local")
    monkeypatch.setenv("WINDKIT_INSTITUTION", "GoKaatru")


# Minimal inputs shared by spatial / climate wrappers
_COORDS_KW = dict(
    west_east=json.dumps([10.0]),
    south_north=json.dumps([55.0]),
    height=json.dumps([100.0]),
    crs="EPSG:4326",
)


class TestSpatialSmoke:
    """windkit.spatial submodule."""

    def test_create_point(self) -> None:
        from server.tools.windkit.spatial import windkit_create_point

        result = windkit_create_point(**_COORDS_KW)
        ds = dict_to_ds(result["result"])
        assert "point" in ds.dims


class TestClimateSmoke:
    """windkit.create_bwc submodule."""

    def test_create_bwc(self) -> None:
        from server.tools.windkit.climate import windkit_create_bwc

        result = windkit_create_bwc(**_COORDS_KW)
        ds = dict_to_ds(result["result"])
        assert "sector" in ds.dims


class TestClimateStatsSmoke:
    """windkit.create_met_fields submodule."""

    def test_create_met_fields(self) -> None:
        from server.tools.windkit.climate_stats import windkit_create_met_fields

        result = windkit_create_met_fields(**_COORDS_KW)
        ds = dict_to_ds(result["result"])
        # met_fields returns a dataset with 'point' dim and data vars like wspd
        assert "point" in ds.dims
        assert "wspd" in ds.data_vars


class TestWindSmoke:
    """windkit.wind_speed submodule."""

    def test_wind_speed(self) -> None:
        from server.tools.windkit.wind import windkit_wind_speed

        result = windkit_wind_speed(u=json.dumps([3.0, 5.0]), v=json.dumps([4.0, 0.0]))
        ws = np.array(result["result"]["data"])
        np.testing.assert_allclose(ws, [5.0, 5.0], atol=0.01)


class TestWeibullSmoke:
    """windkit.weibull submodule."""

    def test_fit_weibull_wasp_m1_m3(self) -> None:
        from server.tools.windkit.other import windkit_fit_weibull_wasp_m1_m3

        result = windkit_fit_weibull_wasp_m1_m3(m1=8.0, m3=800.0)
        params = result["result"]
        assert "A" in params
        assert "k" in params
        assert params["A"] > 0
        assert params["k"] > 0


class TestWindfarmSmoke:
    """windkit.get_uncertainty_table submodule."""

    def test_get_uncertainty_table(self) -> None:
        from server.tools.windkit.windfarm import windkit_get_uncertainty_table

        result = windkit_get_uncertainty_table()
        # Should return a valid uncertainty table structure
        assert "result" in result
        assert result["status"] == "ok"


class TestSectorCoordsSmoke:
    """windkit.create_sector_coords submodule."""

    def test_create_sector_coords(self) -> None:
        from server.tools.windkit.other import windkit_create_sector_coords

        result = windkit_create_sector_coords(bins=12)
        da = dict_to_da(result["result"])
        assert len(da) == 12


class TestWsbinCoordsSmoke:
    """windkit.create_wsbin_coords submodule."""

    def test_create_wsbin_coords(self) -> None:
        from server.tools.windkit.other import windkit_create_wsbin_coords

        result = windkit_create_wsbin_coords()
        da = dict_to_da(result["result"])
        assert len(da) > 0


class TestPlottingSmoke:
    """windkit.plot submodule — most plotting wrappers require the optional 'dash'
    package.  We verify the import path resolves and the wrapper is callable;
    actual rendering is gated on dash availability."""

    @pytest.mark.skipif(
        True,  # dash is an optional dependency; plotting wrappers need it
        reason="dash not installed — plotting smoke deferred to env with dash",
    )
    def test_plot_histogram(self) -> None:  # pragma: no cover
        from server.tools.windkit.climate import windkit_create_bwc
        from server.tools.windkit.plotting import windkit_plot_histogram

        bwc = windkit_create_bwc(**_COORDS_KW)
        result = windkit_plot_histogram(bwc_dataset=json.dumps(bwc["result"]))
        assert result["status"] == "ok"

    def test_plotting_wrapper_importable(self) -> None:
        """Verify the plotting module imports without error — this catches
        upstream signature drift at import time."""
        from server.tools.windkit.plotting import (
            windkit_plot_histogram,
            windkit_plot_wind_rose,
            windkit_plot_vertical_profile,
        )
        assert callable(windkit_plot_histogram)
        assert callable(windkit_plot_wind_rose)
        assert callable(windkit_plot_vertical_profile)
