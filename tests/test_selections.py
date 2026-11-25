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
