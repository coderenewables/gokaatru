"""Selections resolve to exactly the records an independent count gives (P1-15, decisions/0011)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.core.selection import SelectionError, resolve
from server.operations import REGISTRY
from server.state.project import ProjectStore
from server.state.session import SessionState, bind_session
from tests.oracles import selection_mask_oracle


def _frame(rows: int = 2000, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-03-01", periods=rows, freq="10min", tz="UTC")
    direction = rng.uniform(0, 360, rows)
    direction[:12] = [0.0, 360.0, 359.999, 0.001, 30.0, 330.0, 90.0, 180.0, 270.0, 45.0, 15.0, 345.0]
    speed = rng.weibull(2.0, rows) * 8.0
    speed[::37] = np.nan
    direction[13::41] = np.nan
    return pd.DataFrame({"Spd_100m": speed, "Dir_100m": direction}, index=index)


def _random_leaf(rng: np.random.Generator, frame: pd.DataFrame) -> dict:
    kind = rng.choice(["time_range", "sector", "band", "records"])
    if kind == "time_range":
        first, second = sorted(rng.choice(len(frame), 2, replace=False))
        start = frame.index[first].isoformat()
        end = frame.index[second].isoformat()
        return {"kind": "time_range", **({"start": start} if rng.random() < 0.8 else {}), "end": end}
    if kind == "sector":
        opening, closing = (float(x) for x in rng.choice([0, 15, 30, 90, 180, 270, 330, 345, 360], 2, replace=False))
        if opening % 360 == closing % 360:
            closing = 45.0
        return {"kind": "sector", "channel": "Dir_100m", "from_deg": opening, "to_deg": closing}
    if kind == "band":
        low, high = sorted(rng.uniform(0, 20, 2))
        upper = {"max": float(high)} if rng.random() < 0.7 else {}
        return {"kind": "band", "channel": "Spd_100m", "min": float(low), **upper}
    picks = rng.choice(len(frame), 25, replace=False)
    return {"kind": "records", "timestamps": [frame.index[i].isoformat() for i in sorted(picks)]}


def _random_definition(rng: np.random.Generator, frame: pd.DataFrame, depth: int = 0) -> dict:
    if depth >= 2 or rng.random() < 0.4:
        return _random_leaf(rng, frame)
    kind = rng.choice(["union", "intersection"])
    return {"kind": kind, "of": [_random_definition(rng, frame, depth + 1) for _ in range(rng.integers(2, 4))]}


def _oracle(definition: dict, frame: pd.DataFrame) -> np.ndarray:
    channels = {column: [float(v) for v in frame[column]] for column in frame.columns}
    return np.array(selection_mask_oracle(definition, list(frame.index), channels))


def test_two_hundred_random_selections_agree_with_the_oracle() -> None:
    frame = _frame()
    rng = np.random.default_rng(7)
    for _ in range(200):
        definition = _random_definition(rng, frame)
        assert np.array_equal(resolve(definition, frame), _oracle(definition, frame)), definition


@pytest.mark.parametrize(
    ("from_deg", "to_deg", "expected"),
    [
        (345.0, 15.0, {0.0, 360.0, 359.999, 0.001, 345.0}),
        (0.0, 30.0, {0.0, 360.0, 0.001, 15.0}),
        (330.0, 360.0, {330.0, 359.999, 345.0}),
    ],
)
def test_sectors_wrap_through_north_with_half_open_edges(from_deg: float, to_deg: float, expected: set) -> None:
    frame = _frame()
    mask = resolve({"kind": "sector", "channel": "Dir_100m", "from_deg": from_deg, "to_deg": to_deg}, frame)
    assert set(frame["Dir_100m"].iloc[:12][mask[:12]]) == expected


def test_adjacent_selections_share_no_record() -> None:
    frame = _frame()
    low = resolve({"kind": "band", "channel": "Spd_100m", "max": 6.0}, frame)
    high = resolve({"kind": "band", "channel": "Spd_100m", "min": 6.0}, frame)
    assert not (low & high).any()
    assert (low | high).sum() == frame["Spd_100m"].notna().sum()


@pytest.mark.parametrize(
    ("definition", "message"),
    [
        ({"kind": "blob"}, "kind must be one of"),
        ({"kind": "band", "channel": "Nope", "min": 1}, "not in the loaded data"),
        ({"kind": "band", "channel": "Spd_100m"}, "needs a min, a max or both"),
        ({"kind": "band", "channel": "Spd_100m", "min": 5, "max": 5}, "must be below its max"),
        ({"kind": "sector", "channel": "Dir_100m", "from_deg": 10, "to_deg": 370}, "within 0-360"),
        ({"kind": "sector", "channel": "Dir_100m", "from_deg": 0, "to_deg": 360}, "edges coincide"),
        ({"kind": "time_range", "start": "2023-03-01 00:00"}, "no UTC offset"),
        ({"kind": "time_range", "start": "2023-03-02T00:00Z", "end": "2023-03-01T00:00Z"}, "must be before"),
        ({"kind": "union", "of": []}, "non-empty list"),
        ({"kind": "records", "timestamps": ["1999-01-01T00:00Z"]}, "not in the loaded data"),
    ],
)
def test_a_definition_that_describes_nothing_is_refused(definition: dict, message: str) -> None:
    with pytest.raises(SelectionError, match=message):
        resolve(definition, _frame())


def _pairs(rows: int = 3000, seed: int = 11) -> pd.DataFrame:
    """Two speeds on a 0.25 m/s grid, so many records sit exactly on a polygon's edge or vertex."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-03-01", periods=rows, freq="10min", tz="UTC")
    low = np.round(rng.weibull(2.0, rows) * 7.0 * 4) / 4
    high = np.round((low * 1.1 + rng.normal(0, 1.0, rows)) * 4) / 4
    low[::29] = np.nan
    high[5::31] = np.nan
    return pd.DataFrame({"Spd_80m": low, "Spd_100m": high, "Dir_100m": rng.uniform(0, 360, rows)}, index=index)


def _random_polygon(rng: np.random.Generator) -> dict:
    corners = rng.integers(3, 13)
    # Vertices on a 0.5 grid, in random order: concave and self-crossing lassos included.
    vertices = [[float(rng.integers(0, 41) / 2), float(rng.integers(0, 41) / 2)] for _ in range(corners)]
    xs, ys = np.array(vertices).T
    if np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1)) == 0.0:
        vertices = [[0.0, 0.0], [10.0, 0.0], [5.0, 10.0]]
    return {"kind": "polygon", "x_channel": "Spd_80m", "y_channel": "Spd_100m", "vertices": vertices}


def test_three_hundred_random_polygons_agree_with_the_oracle() -> None:
    frame = _pairs()
    rng = np.random.default_rng(23)
    for _ in range(300):
        definition = _random_polygon(rng)
        if rng.random() < 0.3:
            definition = {
                "kind": rng.choice(["union", "intersection"]),
                "of": [definition, {"kind": "sector", "channel": "Dir_100m", "from_deg": 300.0, "to_deg": 60.0}],
            }
        assert np.array_equal(resolve(definition, frame), _oracle(definition, frame)), definition


def test_a_rectangle_holds_exactly_what_its_two_half_open_bands_hold() -> None:
    frame = _pairs()
    rectangle = {
        "kind": "polygon",
        "x_channel": "Spd_80m",
        "y_channel": "Spd_100m",
        "vertices": [[4.0, 5.0], [9.5, 5.0], [9.5, 11.0], [4.0, 11.0]],
    }
    bands = {
        "kind": "intersection",
        "of": [
            {"kind": "band", "channel": "Spd_80m", "min": 4.0, "max": 9.5},
            {"kind": "band", "channel": "Spd_100m", "min": 5.0, "max": 11.0},
        ],
    }
    on_edges = frame["Spd_80m"].isin([4.0, 9.5]) | frame["Spd_100m"].isin([5.0, 11.0])
    assert on_edges.sum() > 50
    assert np.array_equal(resolve(rectangle, frame), resolve(bands, frame))


def test_polygons_sharing_an_edge_share_no_record() -> None:
    frame = _pairs()
    left = {"kind": "polygon", "x_channel": "Spd_80m", "y_channel": "Spd_100m",
            "vertices": [[0.0, 0.0], [6.0, 2.0], [7.0, 14.0], [0.0, 14.0]]}
    right = {"kind": "polygon", "x_channel": "Spd_80m", "y_channel": "Spd_100m",
             "vertices": [[6.0, 2.0], [20.0, 0.0], [20.0, 14.0], [7.0, 14.0]]}
    whole = {"kind": "polygon", "x_channel": "Spd_80m", "y_channel": "Spd_100m",
             "vertices": [[0.0, 0.0], [6.0, 2.0], [20.0, 0.0], [20.0, 14.0], [0.0, 14.0]]}
    first, second = resolve(left, frame), resolve(right, frame)
    assert not (first & second).any()
    assert np.array_equal(first | second, resolve(whole, frame))


@pytest.mark.parametrize(
    ("vertices", "x_channel", "message"),
    [
        ([[0, 0], [1, 1]], "Spd_80m", "at least three vertices"),
        ([[0, 0], [1, 1], [2, 2]], "Spd_80m", "no area"),
        ([[0, 0], [1, 0], [1]], "Spd_80m", r"pair \[x, y\]"),
        ([[0, 0], [1, 0], [1, "a"]], "Spd_80m", "must be a number"),
        ([[0, 0], [1, 0], [1, 1]], "Spd_100m", "two different channels"),
        ([[0, 0], [1, 0], [1, 1]], "Nope", "not in the loaded data"),
        ([[float(i % 2), float(i)] for i in range(1001)], "Spd_80m", "at most 1000 vertices"),
    ],
)
def test_a_polygon_that_describes_nothing_is_refused(vertices: list, x_channel: str, message: str) -> None:
    definition = {"kind": "polygon", "x_channel": x_channel, "y_channel": "Spd_100m", "vertices": vertices}
    with pytest.raises(SelectionError, match=message):
        resolve(definition, _pairs())


def test_a_definition_is_described_in_words() -> None:
    from server.core.selection import describe

    definition = {
        "kind": "union",
        "of": [
            {"kind": "sector", "channel": "Dir_100m", "from_deg": 300.0, "to_deg": 60.0},
            {
                "kind": "intersection",
                "of": [
                    {"kind": "time_range", "start": "2023-02-01T00:00Z", "end": "2023-03-01T00:00Z"},
                    {"kind": "band", "channel": "Spd_100m", "min": 4.0, "max": 12.5},
                    {"kind": "band", "channel": "Spd_80m", "max": 20},
                ],
            },
            {"kind": "polygon", "x_channel": "Spd_80m", "y_channel": "Spd_100m", "vertices": [[0, 0], [1, 0], [1, 1]]},
            {"kind": "records", "timestamps": ["2023-03-01T00:00Z", "2023-03-01T00:10Z"]},
            {"kind": "time_range", "start": "2023-04-01T00:00Z"},
            {"kind": "band", "channel": "Spd_80m", "min": 3},
        ],
    }
    assert describe(definition) == (
        "Dir_100m from 300° to before 60° or (from 2023-02-01T00:00Z to before 2023-03-01T00:00Z and "
        "Spd_100m from 4 to below 12.5 and Spd_80m below 20) or Spd_80m against Spd_100m inside a "
        "3-vertex polygon or 2 listed records or from 2023-04-01T00:00Z on or Spd_80m at least 3"
    )


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    state.timeseries_df = _frame()
    return state


def _call(state: SessionState, operation_name: str, **arguments):
    with bind_session(state):
        return REGISTRY.get(operation_name).fn(**arguments)


def test_define_list_resolve_and_delete(tmp_path: Path) -> None:
    state = _state()
    state.workspace_dir = tmp_path
    westerly = {"kind": "sector", "channel": "Dir_100m", "from_deg": 225.0, "to_deg": 315.0}
    defined = _call(state, "define_selection", name="westerly", definition=westerly)
    expected = int(resolve(westerly, state.timeseries_df).sum())

    assert defined["records"] == expected and defined["replaced"] is False
    assert _call(state, "list_selections")["selections"][0]["records"] == expected
    resolved = _call(state, "resolve_selection", name="westerly")
    assert resolved["records"] == expected and resolved["of_records"] == len(state.timeseries_df)

    restored = SessionState()
    ProjectStore(tmp_path).load(restored)
    assert restored.selections["westerly"]["definition"] == westerly

    _call(state, "delete_selection", name="westerly")
    assert _call(state, "list_selections")["selections"] == []
    with pytest.raises(ValueError, match="No selection named"):
        _call(state, "resolve_selection", name="westerly")


def test_a_bad_definition_is_refused_before_it_is_stored() -> None:
    state = _state()
    with pytest.raises(ValueError, match="not in the loaded data"):
        _call(state, "define_selection", name="x", definition={"kind": "band", "channel": "Nope", "min": 1})
    assert state.selections == {}
