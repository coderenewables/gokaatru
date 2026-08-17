"""Reanalysis acquisition, spatial interpolation and hub referencing — Step 7.

Step 8 audited the LTC estimators assuming their reference series was trustworthy.
This step checks that assumption: how the four grid nodes are chosen, how they are
combined into a site series, and whether the vector algebra along the way is right.

Verified by 20 assertions. Magnitudes measured, not estimated.

Headline: the u/v algebra is correct — speed is reconstructed per timestamp before any
averaging, the direction convention is meteorological in all four quadrants, and the
scalar-speed / vector-direction split is implemented exactly as documented. The findings
are about the *grid*: an antimeridian cell that assembles wrongly, an IDW fallback that
measures distance in degrees, and a second reanalysis dataset that is downloaded and
then never used.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.spatial import bearing_compass, haversine_km, idw_interpolate, interpolate_spatial
from server.state.session import SessionState
from server.tools.era5 import _bounding_pair, _compute_era5_wind_speed, _interpolate_era5_to_site
from server.schemas.common import Coordinate

ERA5_GRID_DEG = 0.25


def _era5_state(node_speeds: dict[tuple[float, float], float], site: tuple[float, float]) -> SessionState:
    """Return a session with four ERA5 nodes carrying constant speeds and a north-ish direction."""
    index = pd.date_range("2021-01-01", periods=240, freq="h", tz="UTC")
    state = SessionState()
    state.reset()
    state.set_coordinate(Coordinate(latitude=site[0], longitude=site[1], elevation_m=0.0))
    state.era5_nodes = [
        {"latitude": lat, "longitude": lon} for (lat, lon) in node_speeds
    ]
    for (lat, lon), speed in node_speeds.items():
        state.era5_data[f"{float(lat)}_{float(lon)}"] = pd.DataFrame(
            {
                "Spd_100m": np.full(len(index), speed),
                "Dir_100m": np.full(len(index), 270.0),
                "sp": np.full(len(index), 101325.0),
                "t2m": np.full(len(index), 288.15),
                "d2m": np.full(len(index), 283.15),
            },
            index=index,
        )
    return state


# ---------------------------------------------------------------------------
# Verified correct — the vector algebra
# ---------------------------------------------------------------------------


def test_speed_is_reconstructed_per_timestamp_before_any_averaging():
    """VERIFIED: sqrt(u^2+v^2) is applied record by record, not to averaged components.

    Averaging u and v first and taking the magnitude afterwards under-predicts the mean
    speed whenever direction varies — badly so on a reversing regime. This constructs
    exactly that case: components that average to zero but carry a constant 10 m/s.
    """
    index = pd.date_range("2021-01-01", periods=1000, freq="h", tz="UTC")
    sign = np.where(np.arange(len(index)) % 2 == 0, 1.0, -1.0)
    state = SessionState()
    state.reset()
    state.era5_data["10.0_20.0"] = pd.DataFrame(
        {"u100": 10.0 * sign, "v100": np.zeros(len(index))}, index=index
    )

    result = _compute_era5_wind_speed(state, 10.0, 20.0)
    frame = state.era5_data["10.0_20.0"]

    assert result["mean_speed"] == pytest.approx(10.0)
    assert np.allclose(frame["Spd_100m"].to_numpy(), 10.0)
    # The component means are zero, so the vector-first order would have given 0 m/s.
    assert abs(float(frame["u100"].mean())) < 1e-12
    assert float(np.hypot(frame["u100"].mean(), frame["v100"].mean())) == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("u", "v", "expected_direction"),
    [
        (1.0, 0.0, 270.0),   # blowing east  -> comes from the west
        (-1.0, 0.0, 90.0),   # blowing west  -> comes from the east
        (0.0, 1.0, 180.0),   # blowing north -> comes from the south
        (0.0, -1.0, 0.0),    # blowing south -> comes from the north
        (1.0, 1.0, 225.0),   # blowing north-east -> from the south-west
    ],
)
def test_direction_uses_the_meteorological_convention_in_every_quadrant(
    u: float, v: float, expected_direction: float
) -> None:
    """VERIFIED: (270 - atan2(v,u)) gives the direction the wind comes FROM."""
    index = pd.date_range("2021-01-01", periods=10, freq="h", tz="UTC")
    state = SessionState()
    state.reset()
    state.era5_data["10.0_20.0"] = pd.DataFrame(
        {"u100": np.full(len(index), u), "v100": np.full(len(index), v)}, index=index
    )
    _compute_era5_wind_speed(state, 10.0, 20.0)
    direction = float(state.era5_data["10.0_20.0"]["Dir_100m"].iloc[0])
    assert direction == pytest.approx(expected_direction, abs=1e-9)


def test_interpolation_is_scalar_for_speed_and_vector_for_direction():
    """VERIFIED: the documented split is what the code does, and it matters.

    With node directions diverging across the cell, vector-interpolating the speed would
    let opposing components cancel and under-predict. Four nodes each at 10 m/s but
    pointing to the four cardinal directions must still give 10 m/s at the site.
    """
    index = pd.date_range("2021-01-01", periods=48, freq="h", tz="UTC")
    nodes = {(10.0, 20.0): 0.0, (10.0, 20.25): 90.0, (10.25, 20.0): 180.0, (10.25, 20.25): 270.0}
    state = SessionState()
    state.reset()
    state.set_coordinate(Coordinate(latitude=10.125, longitude=20.125, elevation_m=0.0))
    state.era5_nodes = [{"latitude": lat, "longitude": lon} for (lat, lon) in nodes]
    for (lat, lon), direction in nodes.items():
        state.era5_data[f"{lat}_{lon}"] = pd.DataFrame(
            {"Spd_100m": np.full(len(index), 10.0), "Dir_100m": np.full(len(index), direction)},
            index=index,
        )

    result = _interpolate_era5_to_site(state)
    interpolated = state.era5_interpolated_df

    assert result["speed_interpolation"] == "scalar"
    # Scalar interpolation preserves the magnitude despite total directional cancellation.
    assert float(interpolated["Spd_100m"].mean()) == pytest.approx(10.0, rel=1e-9)
    # The vector-interpolated direction is genuinely degenerate here, which is correct:
    # four opposing directions have no meaningful resultant.
    assert "Dir_100m" in interpolated.columns


def test_bounding_pair_brackets_an_interior_target():
    """VERIFIED: node selection returns the two grid values either side of the site."""
    grid = np.arange(10.0, 11.01, ERA5_GRID_DEG)
    lower, upper = _bounding_pair(grid, 10.31)
    assert lower == pytest.approx(10.25)
    assert upper == pytest.approx(10.50)
    assert lower < 10.31 < upper


def test_node_frames_are_joined_on_an_exact_index_intersection():
    """VERIFIED: interpolation uses the shared timestamps only — no nearest/asof merge."""
    long_index = pd.date_range("2021-01-01", periods=200, freq="h", tz="UTC")
    short_index = long_index[50:150]
    state = _era5_state(
        {(10.0, 20.0): 8.0, (10.0, 20.25): 8.0, (10.25, 20.0): 8.0, (10.25, 20.25): 8.0},
        site=(10.125, 20.125),
    )
    # Shorten one node's coverage; the result must shrink to the intersection.
    key = "10.25_20.25"
    state.era5_data[key] = state.era5_data[key].loc[short_index]

    _interpolate_era5_to_site(state)
    assert len(state.era5_interpolated_df) == len(short_index)
    assert state.era5_interpolated_df.index.equals(short_index)


def test_bearing_compass_is_correct_at_the_octant_boundaries():
    """VERIFIED: the 8-point bearing helper bins on the right boundaries."""
    assert bearing_compass(0.0, 0.0, 1.0, 0.0) == "N"
    assert bearing_compass(0.0, 0.0, 0.0, 1.0) == "E"
    assert bearing_compass(0.0, 0.0, -1.0, 0.0) == "S"
    assert bearing_compass(0.0, 0.0, 0.0, -1.0) == "W"
    assert bearing_compass(0.0, 0.0, 1.0, 1.0) == "NE"


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_merra2_is_downloaded_but_never_reaches_the_long_term_correction():
    """FINDING F-58 (M): MERRA-2 is acquired, cached, extrapolated — and used for nothing.

    ``_interpolate_era5_to_site`` reads ``state.era5_data`` only, and ``_require_ltc_inputs``
    reads ``state.era5_interpolated_df`` only, so nothing in ``state.merra_data`` can ever
    become an LTC reference. Its only consumers are the hub-height extrapolation
    side-effect (which writes a column nothing reads) and a map marker.

    A second independent long-term source is the standard way to test whether an LTC
    result depends on the reference chosen. The README advertises "BrightHub ERA5 and
    MERRA-2" and the default plan downloads both, so the cost is paid and the benefit is
    not collected.
    """
    import inspect

    from server.tools import era5 as era5_module
    from server.tools import ltc as ltc_module

    interpolation_source = inspect.getsource(era5_module._interpolate_era5_to_site)
    assert "era5_data" in interpolation_source
    assert "merra_data" not in interpolation_source

    ltc_source = inspect.getsource(ltc_module._require_ltc_inputs)
    assert "era5_interpolated_df" in ltc_source
    assert "merra" not in ltc_source.lower()

    # And a session holding only MERRA data cannot interpolate at all.
    state = SessionState()
    state.reset()
    state.set_coordinate(Coordinate(latitude=10.1, longitude=20.1, elevation_m=0.0))
    state.merra_data = {"10.0_20.0": pd.DataFrame({"Spd_100m": [8.0]})}
    with pytest.raises(ValueError, match="ERA5 nodes are not available"):
        _interpolate_era5_to_site(state)


def test_antimeridian_cell_falls_back_to_idw_instead_of_bilinear():
    """FINDING F-59 (L after the F-60 fix): a cell across 180 deg still skips bilinear.

    Node longitudes are stored signed, so a cell spanning the antimeridian holds ``180.0``
    and ``-179.75``. ``interpolate_spatial`` sees a 359.75-degree span, the ``inside_cell``
    test fails, and bilinear is skipped.

    Before the F-60 haversine fix this was severe: IDW measured the far-side node as
    359.9 degrees away, weighted it to nothing, and returned **12.00 m/s against a truth
    of 8.40 (+42.9%)** on a cell with an east-west gradient. Great-circle distance sees
    the wrap correctly, so the same case now returns **8.80 (+4.78%)** — the ordinary
    IDW-versus-bilinear difference rather than a cell-assembly failure.

    What remains: the cell is still assembled as though it were 359.75 degrees wide, so
    the exact bilinear path is unavailable and nothing in the response says why. The fix
    is to unwrap longitudes onto a common branch before assembling the cell.
    """
    nodes = [(-10.0, 180.0), (-10.0, -179.75), (-9.75, 180.0), (-9.75, -179.75)]
    values = np.array([[8.0], [12.0], [8.0], [12.0]])

    site_lon = 180.0 + ERA5_GRID_DEG * 0.1 - 360.0
    out, method = interpolate_spatial(nodes, values, (-9.875, site_lon))

    assert method == "idw"  # bilinear still skipped
    error = float(out[0]) / 8.4 - 1.0
    assert 0.0 < error < 0.10  # was +42.9%, now under 5%

    # Mid-cell the two sides balance, so IDW happens to be exact there.
    mid, _ = interpolate_spatial(nodes, values, (-9.875, -179.875))
    assert float(mid[0]) == pytest.approx(10.0, abs=0.01)

    # Control: the same geometry away from the antimeridian is exact and uses bilinear.
    nodes_ok = [(-10.0, 20.0), (-10.0, 20.25), (-9.75, 20.0), (-9.75, 20.25)]
    out_ok, method_ok = interpolate_spatial(nodes_ok, values, (-9.875, 20.0 + ERA5_GRID_DEG * 0.1))
    assert method_ok == "linear"
    assert float(out_ok[0]) == pytest.approx(8.4, rel=1e-9)


def test_idw_weights_by_great_circle_distance():
    """F-60 (M) — FIXED. Regression test: IDW must weight by kilometres, not degrees.

    The bug: ``_euclidean_distances`` took a norm over raw (lat, lon) degrees, treating a
    degree of longitude as a degree of latitude. Meridians converge, so nodes lying east
    or west were overweighted:

        45 deg N : 1 deg lat = 111.2 km, 1 deg lon = 78.6 km  (**1.41x**)
        60 deg N : 111.2 km vs 55.6 km                        (**2.00x**)
        70 deg N : 111.2 km vs 38.0 km                        (**2.92x**)

    Measured at 60 deg N with two nodes equidistant in degrees: the old code split them
    **50/50**; weighting by true ground distance gives the nearer eastern node **80%**.
    ``haversine_km`` was already in the module, unused.
    """
    for latitude, expected in ((45.0, 1.41), (60.0, 2.00), (70.0, 2.92)):
        anisotropy = haversine_km(latitude, 0.0, latitude + 1.0, 0.0) / haversine_km(
            latitude, 0.0, latitude, 1.0
        )
        assert anisotropy == pytest.approx(expected, abs=0.02)

    north = (61.0, 0.0)
    east = (60.0, 1.0)
    target = (60.0, 0.0)
    result = float(idw_interpolate([north, east], np.array([0.0, 100.0]), target)[()])

    # Matches a hand-computed inverse-square weighting over haversine distance.
    distances = np.array([haversine_km(*target, *north), haversine_km(*target, *east)])
    weights = (1.0 / distances**2) / np.sum(1.0 / distances**2)
    assert result == pytest.approx(float(weights @ np.array([0.0, 100.0])), rel=1e-9)
    assert result == pytest.approx(80.0, abs=0.5)  # was 50.0 before the fix

    # At the equator a degree of longitude *is* a degree of latitude, so the even split
    # there is correct and must be preserved.
    equator = float(idw_interpolate([(1.0, 0.0), (0.0, 1.0)], np.array([0.0, 100.0]), (0.0, 0.0))[()])
    assert equator == pytest.approx(50.0, abs=1e-6)


def test_idw_returns_the_node_value_when_the_target_coincides_with_it():
    """A target sitting on a node must take its value outright, not divide by zero."""
    points = [(10.0, 20.0), (10.25, 20.0), (10.0, 20.25)]
    values = np.array([[5.0], [50.0], [500.0]])
    assert float(idw_interpolate(points, values, (10.0, 20.0))[0]) == pytest.approx(5.0)


def test_brighthub_columns_are_converted_to_native_reanalysis_units():
    """F-61 (M) — FIXED. Regression test: `t2m` and `sp` must mean one thing everywhere.

    The bug: EarthDataHub delivers native ERA5 units — `t2m` in Kelvin, `sp` in Pascals.
    BrightHub delivers `Tmp_2m_degC` and `Prs_0m_hPa`, which the column map renamed to the
    *same* `t2m` / `sp` names **without converting**, so identically-named columns carried
    Celsius and hectopascals on one path and Kelvin and Pascals on the other. That is the
    F-04 nineteenfold density error arriving by a second route.

    The fix converts at the parse boundary, before the rename, so the names carry their
    implied units. Step 6's unit detection is now a backstop rather than the only defence.
    """
    from server.tools.brighthub import _BRIGHTHUB_ERA5_COLUMNS, _reanalysis_frame
    from server.tools.era5 import ERA5_BASE_VARIABLES

    assert _BRIGHTHUB_ERA5_COLUMNS["Tmp_2m_degC"] == "t2m"
    assert _BRIGHTHUB_ERA5_COLUMNS["Prs_0m_hPa"] == "sp"
    assert "t2m" in ERA5_BASE_VARIABLES and "sp" in ERA5_BASE_VARIABLES

    payload = {
        "timeseries_data": {
            "data": [
                {"timestamp": "2021-01-01T00:00:00Z", "Spd_100m_mps": 8.0,
                 "Dir_100m_deg": 270.0, "Tmp_2m_degC": 15.0, "Prs_0m_hPa": 1013.25},
                {"timestamp": "2021-01-01T01:00:00Z", "Spd_100m_mps": 9.0,
                 "Dir_100m_deg": 275.0, "Tmp_2m_degC": -5.0, "Prs_0m_hPa": 990.0},
            ]
        }
    }
    frame = _reanalysis_frame(payload, _BRIGHTHUB_ERA5_COLUMNS)

    assert frame["t2m"].tolist() == pytest.approx([288.15, 268.15])  # K, not degC
    assert frame["sp"].tolist() == pytest.approx([101325.0, 99000.0])  # Pa, not hPa
    # Wind speed and direction are already in native units and must be untouched.
    assert frame["Spd_100m"].tolist() == pytest.approx([8.0, 9.0])
    assert frame["Dir_100m"].tolist() == pytest.approx([270.0, 275.0])


def test_converted_brighthub_units_are_accepted_by_the_density_tool():
    """The end-to-end point of F-61: BrightHub-sourced columns now read as ERA5 units."""
    from server.state.session import bind_session
    from server.tools.air_density import compute_air_density_timeseries
    from server.tools.brighthub import _BRIGHTHUB_ERA5_COLUMNS, _reanalysis_frame

    rows = [
        {
            "timestamp": f"2021-01-01T{hour:02d}:00:00Z",
            "Spd_100m_mps": 8.0,
            "Dir_100m_deg": 270.0,
            "Tmp_2m_degC": 15.0,
            "Prs_0m_hPa": 1013.25,
        }
        for hour in range(24)
    ]
    frame = _reanalysis_frame({"timeseries_data": {"data": rows}}, _BRIGHTHUB_ERA5_COLUMNS)
    frame["d2m"] = 283.15

    state = SessionState()
    state.reset()
    state.era5_interpolated_df = frame
    with bind_session(state):
        result = compute_air_density_timeseries("sp", "t2m", "d2m", "era5")

    assert result["units_detected"] == {"temperature": "K", "dewpoint": "K", "pressure": "Pa"}
    assert 1.20 < result["mean_density"] < 1.24


def test_a_variable_missing_from_one_node_is_dropped_without_warning():
    """FINDING F-63 (L): an incomplete variable disappears from the interpolated frame.

    ``_interpolate_era5_to_site`` only interpolates a variable when *every* node has it.
    One node missing `d2m` silently removes dew point from the site series, which is what
    the density calculation needs. It is visible in the returned `variables` list, but
    nothing warns, and the failure surfaces later as a missing-column error elsewhere.
    """
    state = _era5_state(
        {(10.0, 20.0): 8.0, (10.0, 20.25): 8.0, (10.25, 20.0): 8.0, (10.25, 20.25): 8.0},
        site=(10.125, 20.125),
    )
    state.era5_data["10.25_20.25"] = state.era5_data["10.25_20.25"].drop(columns=["d2m"])

    result = _interpolate_era5_to_site(state)

    assert "d2m" not in result["variables"]
    assert "d2m" not in state.era5_interpolated_df.columns
    assert "sp" in result["variables"]  # the complete ones survive
    assert "warning" not in result
    assert "skipped_variables" not in result


def test_interpolation_method_label_collapses_a_per_variable_mixture():
    """FINDING F-62 (L): one `method` label describes what may be several methods.

    `methods_used` is a set across variables and the u/v pair; the response reduces it to
    `"idw"` if *any* member used IDW, else `"linear"`. A run where speed interpolated
    bilinearly but direction fell back is reported wholly as IDW. Likewise
    `speed_interpolation: "scalar"` is a hardcoded literal rather than something the
    interpolation path reports, so it cannot detect a future change of approach.
    """
    import inspect

    from server.tools import era5 as era5_module

    source = inspect.getsource(era5_module._interpolate_era5_to_site)
    assert 'method_name = "idw" if "idw" in methods_used else "linear"' in source
    assert '"speed_interpolation": "scalar"' in source

    state = _era5_state(
        {(10.0, 20.0): 8.0, (10.0, 20.25): 8.0, (10.25, 20.0): 8.0, (10.25, 20.25): 8.0},
        site=(10.125, 20.125),
    )
    result = _interpolate_era5_to_site(state)
    assert result["method"] in {"linear", "idw"}
    assert "methods_by_variable" not in result
