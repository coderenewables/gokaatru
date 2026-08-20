"""Per-source long-term reference handling — design doc §6.

MERRA-2 used to be downloaded, cached, extrapolated and then used for nothing. Four
separate defects kept it out of the pipeline: only one node was fetched, the prepare
flow never interpolated it, the column contract assumed a 100 m field it does not
have, and there was a single interpolated-series slot both sources wrote to.

These tests pin the corrected behaviour, so a regression on any one of the four shows
up as a named failure rather than as MERRA-2 quietly going unused again.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401  — establishes tool-module import order
from server.core.brighthub import select_grid_nodes
from server.core.reanalysis import get_reference_source, reference_source_names
from server.schemas.common import Coordinate
from server.state.session import SessionState
from server.tools.era5 import _interpolate_era5_to_site
from server.tools.extrapolation import _extrapolate_all_reanalysis_nodes


# ---------------------------------------------------------------------------
# §6.3 — the descriptor table
# ---------------------------------------------------------------------------


def test_reference_descriptors_carry_the_height_each_source_is_served_at():
    """ERA5 is a 100 m product and MERRA-2 a 50 m one; neither height is a default."""
    era5 = get_reference_source("era5")
    merra2 = get_reference_source("merra2")

    assert (era5.native_height_m, era5.speed_col, era5.dir_col) == (100.0, "Spd_100m", "Dir_100m")
    assert (merra2.native_height_m, merra2.speed_col, merra2.dir_col) == (50.0, "Spd_50m", "Dir_50m")
    assert set(reference_source_names()) == {"era5", "merra2"}


def test_unknown_reference_source_is_rejected_by_name():
    with pytest.raises(ValueError, match="source must be one of"):
        get_reference_source("cfsr")


# ---------------------------------------------------------------------------
# §6.1 — node selection brackets the site rather than merely being nearest
# ---------------------------------------------------------------------------


def _grid(lats, lons, site_lat, site_lon):
    nodes = []
    for lat in lats:
        for lon in lons:
            nodes.append(
                {
                    "latitude_ddeg": lat,
                    "longitude_ddeg": lon,
                    "distance_km": float(np.hypot(lat - site_lat, lon - site_lon) * 111.0),
                }
            )
    return nodes


def test_node_selection_brackets_a_site_inside_a_grid_cell():
    """The four returned nodes must straddle the site, not sit on one side of it.

    Sorting purely by distance can return four nodes all to one side when the site is
    near a cell corner, which silently turns bilinear interpolation into extrapolation.
    """
    site_lat, site_lon = 52.05, 5.05
    nodes = _grid([51.75, 52.0, 52.25, 52.5], [4.75, 5.0, 5.25, 5.5], site_lat, site_lon)

    selected = select_grid_nodes(nodes, site_lat, site_lon, 4)

    assert len(selected) == 4
    lats = [n["latitude_ddeg"] for n in selected]
    lons = [n["longitude_ddeg"] for n in selected]
    # The site is genuinely inside the hull of the selection in both axes.
    assert min(lats) <= site_lat <= max(lats)
    assert min(lons) <= site_lon <= max(lons)
    # And it is exactly the containing cell.
    assert set(lats) == {52.0, 52.25}
    assert set(lons) == {5.0, 5.25}


def test_node_selection_degrades_to_nearest_when_the_site_is_outside_the_grid():
    """At a data boundary there is nothing to bracket with; nearest-N is the honest fallback."""
    site_lat, site_lon = 53.0, 6.0
    nodes = _grid([51.75, 52.0, 52.25], [4.75, 5.0, 5.25], site_lat, site_lon)

    selected = select_grid_nodes(nodes, site_lat, site_lon, 4)

    assert len(selected) == 4
    distances = [n["distance_km"] for n in selected]
    assert distances == sorted(distances)
    assert distances == sorted(n["distance_km"] for n in nodes)[:4]


def test_node_selection_is_distance_sorted_even_when_it_returns_everything():
    """Fewer nodes than requested must not change the ordering contract."""
    site_lat, site_lon = 52.0, 5.0
    nodes = [
        {"latitude_ddeg": 52.5, "longitude_ddeg": 5.0, "distance_km": 55.0},
        {"latitude_ddeg": 52.1, "longitude_ddeg": 5.0, "distance_km": 11.0},
    ]
    selected = select_grid_nodes(nodes, site_lat, site_lon, 4)
    assert [n["distance_km"] for n in selected] == [11.0, 55.0]


# ---------------------------------------------------------------------------
# §6.4 — both interpolated series coexist
# ---------------------------------------------------------------------------


def _source_state() -> SessionState:
    index = pd.date_range("2015-01-01", periods=400, freq="h", tz="UTC")
    rng = np.random.default_rng(11)
    corners = [(52.0, 4.5), (52.0, 4.75), (52.25, 4.5), (52.25, 4.75)]

    def frame(speed_col: str, dir_col: str, offset: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                speed_col: 7.0 + offset + rng.normal(0, 1.0, len(index)),
                dir_col: np.full(len(index), 220.0),
            },
            index=index,
        )

    state = SessionState()
    state.reset()
    state.set_coordinate(Coordinate(latitude=52.13, longitude=4.62))
    nodes = [{"latitude": lat, "longitude": lon} for lat, lon in corners]
    state.era5_nodes = list(nodes)
    state.merra_nodes = list(nodes)
    state.era5_data = {
        f"{lat}_{lon}": frame("Spd_100m", "Dir_100m", i) for i, (lat, lon) in enumerate(corners)
    }
    state.merra_data = {
        f"{lat}_{lon}": frame("Spd_50m", "Dir_50m", i) for i, (lat, lon) in enumerate(corners)
    }
    return state


def test_both_sources_interpolate_to_site_and_coexist():
    """Interpolating MERRA-2 must not destroy the ERA5 site series, and vice versa.

    There used to be one `era5_interpolated_df` slot that both wrote to, so selecting a
    reference source erased the other and an axis over source was impossible.
    """
    state = _source_state()

    era5_result = _interpolate_era5_to_site(state, source="era5")
    merra_result = _interpolate_era5_to_site(state, source="merra2")

    assert era5_result["reference_height_m"] == 100.0
    assert merra_result["reference_height_m"] == 50.0
    assert set(state.reanalysis_interpolated) == {"era5", "merra2"}
    assert "Spd_100m" in state.reanalysis_interpolated["era5"].columns
    assert "Spd_50m" in state.reanalysis_interpolated["merra2"].columns


def test_active_source_switches_what_legacy_readers_see():
    """`era5_interpolated_df` is a view on the active source, so old readers follow it."""
    state = _source_state()
    _interpolate_era5_to_site(state, source="era5")
    _interpolate_era5_to_site(state, source="merra2")

    # Interpolating merra2 last leaves it active.
    assert state.active_reference_source == "merra2"
    assert "Spd_50m" in state.era5_interpolated_df.columns

    state.set_active_reference_source("era5")
    assert "Spd_100m" in state.era5_interpolated_df.columns
    assert state.runconfig["reference_source"] == "era5"


def test_clearing_the_active_series_leaves_the_other_source_intact():
    state = _source_state()
    _interpolate_era5_to_site(state, source="era5")
    _interpolate_era5_to_site(state, source="merra2")

    state.set_active_reference_source("merra2")
    state.era5_interpolated_df = None

    assert state.has_reference_series("era5") is True
    assert state.has_reference_series("merra2") is False


# ---------------------------------------------------------------------------
# §6.3 — hub extrapolation uses each source's own reference height
# ---------------------------------------------------------------------------


def test_hub_extrapolation_uses_each_sources_native_reference_height():
    """MERRA-2 nodes were skipped wholesale for want of a `Spd_100m` they cannot have.

    One reference column derived from a fixed 100 m default was applied to every
    source, so every MERRA-2 series fell through to `skipped_nodes` — the mechanical
    reason MERRA-2 was acquired and then used for nothing.
    """
    state = _source_state()
    _interpolate_era5_to_site(state, source="era5")
    _interpolate_era5_to_site(state, source="merra2")
    state.shear_table = pd.DataFrame(
        np.full((12, 24), 0.2), index=range(1, 13), columns=range(24)
    )

    result = _extrapolate_all_reanalysis_nodes(state, 120.0)

    assert result["status"] == "ok"
    assert result["skipped_nodes"] == []
    assert result["reference_columns"] == {"era5": "Spd_100m", "merra2": "Spd_50m"}
    assert sorted(result["interpolated_sources"]) == ["era5", "merra2"]
    # Every node of both sources got a hub column.
    assert len([k for k in result["extrapolated_nodes"] if k.startswith("merra:")]) == 4
    for frame in state.merra_data.values():
        assert "Spd_120m_hub" in frame.columns
    for frame in state.reanalysis_interpolated.values():
        assert "Spd_120m_hub" in frame.columns


def test_merra_hub_speed_exceeds_era5_for_the_same_shear_because_its_lever_is_longer():
    """A 50 m reference carried to 120 m is a longer lever than a 100 m one.

    This is the physical consequence of getting the reference height right, and the
    reason a fixed 100 m default was not a cosmetic bug: applied to MERRA-2 it would
    have under-extrapolated by the ratio (120/50)^a / (120/100)^a.
    """
    state = _source_state()
    _interpolate_era5_to_site(state, source="era5")
    _interpolate_era5_to_site(state, source="merra2")
    alpha = 0.2
    state.shear_table = pd.DataFrame(
        np.full((12, 24), alpha), index=range(1, 13), columns=range(24)
    )

    _extrapolate_all_reanalysis_nodes(state, 120.0)

    era5_frame = state.reanalysis_interpolated["era5"]
    merra_frame = state.reanalysis_interpolated["merra2"]
    era5_ratio = (era5_frame["Spd_120m_hub"] / era5_frame["Spd_100m"]).mean()
    merra_ratio = (merra_frame["Spd_120m_hub"] / merra_frame["Spd_50m"]).mean()

    assert era5_ratio == pytest.approx((120.0 / 100.0) ** alpha, rel=1e-9)
    assert merra_ratio == pytest.approx((120.0 / 50.0) ** alpha, rel=1e-9)
    assert merra_ratio > era5_ratio
