"""A scatter's points: every record of a window where both channels are valid (P2-5).

The scatter draws every point and colours those the shared selection holds, so the pairs
come with the selection marked, not applied. The JSON operation and the Arrow route read the
same ``_scatter_pairs``.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient

from server.api.deps import get_session_manager
from server.api.main import create_app
from server.api.routes.series import ARROW_STREAM
from server.operations import REGISTRY
from server.state.manager import SessionManager
from server.state.session import SessionState, bind_session
from server.tools.series import _scatter_pairs, pairs_payload
from tests.oracles import selection_mask_oracle

LASSO = {
    "kind": "polygon",
    "x_channel": "Spd_80m",
    "y_channel": "Spd_100m",
    "vertices": [[3.0, 2.0], [12.0, 6.0], [14.0, 16.0], [5.0, 11.0]],
}


def _frame(rows: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(8)
    index = pd.date_range("2023-04-01", periods=rows, freq="10min", tz="UTC")
    low = rng.weibull(2.0, rows) * 7.0
    high = low * 1.12 + rng.normal(0, 0.8, rows)
    low[::17] = np.nan
    high[3::23] = np.nan
    return pd.DataFrame({"Spd_80m": low, "Spd_100m": high, "Dir_100m": rng.uniform(0, 360, rows)}, index=index)


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    state.timeseries_df = _frame()
    state.raw_timeseries_df = state.timeseries_df.copy()
    return state


def _oracle(frame: pd.DataFrame, definition: dict) -> np.ndarray:
    channels = {column: [float(v) for v in frame[column]] for column in frame.columns}
    return np.array(selection_mask_oracle(definition, list(frame.index), channels))


def test_the_pairs_are_every_valid_record_and_the_highlight_is_the_oracle_mask() -> None:
    state = _state()
    frame = state.timeseries_df
    start, end = frame.index[400], frame.index[4600]
    pairs = _scatter_pairs(state, "Spd_80m", "Spd_100m", start.isoformat(), end.isoformat(), json.dumps(LASSO))

    window = frame.iloc[400:4600]
    valid = window["Spd_80m"].notna() & window["Spd_100m"].notna()
    expected = window[valid]
    assert pairs.window_records == 4200 and len(pairs.time_ms) == len(expected) < 4200
    assert np.array_equal(pairs.time_ms, expected.index.as_unit("ms").asi8)
    assert np.array_equal(pairs.x, expected["Spd_80m"].to_numpy()) and np.array_equal(pairs.y, expected["Spd_100m"])
    held = _oracle(frame, LASSO)[400:4600][valid.to_numpy()]
    assert 0 < held.sum() < len(held)
    assert np.array_equal(pairs.highlighted, held)
    assert pairs.highlight["inline"] is True and pairs.highlight["records"] == int(held.sum())
    assert pairs.highlight["of_records"] == len(expected)


def test_without_a_highlight_nothing_is_marked() -> None:
    pairs = _scatter_pairs(_state(), "Spd_80m", "Spd_100m")
    assert pairs.highlighted is None and pairs.highlight is None
    assert len(pairs.time_ms) == int((_frame()["Spd_80m"].notna() & _frame()["Spd_100m"].notna()).sum())


@pytest.mark.parametrize(
    ("x", "y", "message"),
    [
        ("Spd_80m", "Spd_80m", "two different channels"),
        ("Spd_80m", "Nope", "No channel named Nope"),
        ("", "Spd_80m", "two different channels|at least one channel|No channel named"),
    ],
)
def test_refusals(x: str, y: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _scatter_pairs(_state(), x, y)


def test_the_json_form_is_refused_past_its_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import server.tools.series as series

    state = _state()
    monkeypatch.setattr(series, "MAX_JSON_PAIRS", 100)
    with bind_session(state), pytest.raises(ValueError, match="more than the 100 the JSON form lists"):
        REGISTRY.get("get_scatter_pairs").fn(x_channel="Spd_80m", y_channel="Spd_100m")
    frame = state.timeseries_df
    with bind_session(state):
        narrow = REGISTRY.get("get_scatter_pairs").fn(
            x_channel="Spd_80m", y_channel="Spd_100m", start=frame.index[0].isoformat(),
            end=frame.index[90].isoformat(),
        )
    assert narrow["records"] <= 90 and narrow["highlighted"] is None


def _table(response) -> pa.Table:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == ARROW_STREAM
    return pa.ipc.open_stream(io.BytesIO(response.content)).read_all()


def test_the_arrow_route_serves_the_operations_pairs(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            state = manager.get_session(session_id)
            state.timeseries_df = _frame()
            state.raw_timeseries_df = state.timeseries_df.copy()
            headers = {"X-GoKaatru-Session": session_id}
            url = f"/api/sessions/{session_id}/pairs"
            query = {"x_channel": "Spd_80m", "y_channel": "Spd_100m", "highlight": json.dumps(LASSO)}
            with bind_session(state):
                expected = REGISTRY.get("get_scatter_pairs").fn(**query)
            logged = len(state.operation_log)

            for table in (_table(client.get(url, headers=headers, params=query)),
                          _table(client.post(url, headers=headers, json=query))):
                meta = json.loads(table.schema.metadata[b"gokaatru"])
                assert table.column("time").cast(pa.int64()).to_pylist() == expected["time_ms"]
                assert table.column("x").to_pylist() == expected["x"]
                assert table.column("y").to_pylist() == expected["y"]
                assert table.column("highlighted").to_pylist() == expected["highlighted"]
                assert meta["highlight"] == expected["highlight"] and meta["records"] == expected["records"]
            assert len(state.operation_log) == logged, "the routes read; neither is logged"

            plain = _table(client.get(url, headers=headers, params={"x_channel": "Spd_80m", "y_channel": "Spd_100m"}))
            assert "highlighted" not in plain.column_names
            refused = client.get(url, headers=headers, params={"x_channel": "Spd_80m", "y_channel": "x"})
            assert refused.status_code == 400
            assert client.post(url, headers=headers, json={**query, "extra": 1}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_the_payload_lists_what_the_pairs_hold() -> None:
    pairs = _scatter_pairs(_state(), "Spd_80m", "Spd_100m")
    payload = pairs_payload(pairs)
    assert payload["records"] == len(payload["x"]) == len(payload["y"]) == len(payload["time_ms"])
