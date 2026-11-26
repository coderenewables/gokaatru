"""Series windows reduced on the server, as JSON and as Arrow (P1-17, decisions/0005).

Each bucket's minimum, maximum and valid count must equal an independent per-record
bucketing in ``tests/oracles.py`` exactly, over random windows, bucket counts and gaps; the
envelope of the buckets is then the envelope of the records. The Arrow route and the
``get_series_window`` operation must return the same window.
"""
from __future__ import annotations

import io
import json
import math
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
from server.tools.series import MAX_SERIES_BUCKETS, _series_window
from tests.oracles import bucket_min_max_oracle

CHANNELS = ("Spd_100m", "Spd_80m", "Dir_100m")


def _frame(rows: int = 6000, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2024-01-01", periods=rows, freq="10min", tz="UTC")
    index = index.delete(np.arange(2000, 2400))  # a gap of 400 records
    frame = pd.DataFrame(
        {
            "Spd_100m": rng.weibull(2.0, len(index)) * 8.0,
            "Spd_80m": rng.weibull(2.0, len(index)) * 7.0,
            "Dir_100m": rng.uniform(0, 360, len(index)),
            "Label": ["a"] * len(index),
        },
        index=index,
    )
    frame.loc[frame.index[::17], "Spd_100m"] = np.nan
    frame.loc[frame.index[3000:3500], "Spd_80m"] = np.nan
    return frame


def _state(frame: pd.DataFrame) -> SessionState:
    state = SessionState()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    return state


def _same(actual: list, expected: list) -> bool:
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        if isinstance(e, float) and math.isnan(e):
            if not (a is None or (isinstance(a, float) and math.isnan(a))):
                return False
        elif a != e:
            return False
    return True


def _check(payload: dict, expected: dict) -> None:
    assert payload["decimated"] is expected["decimated"]
    if expected["decimated"]:
        assert payload["bucket_ms"] == expected["bucket_ms"]
    assert payload["time_ms"] == expected["time_ms"]
    for column, name in enumerate(CHANNELS):
        for bound in ("min", "max"):
            assert _same(payload["channels"][name][bound], [row[column] for row in expected[bound]]), (name, bound)
        assert payload["channels"][name]["count"] == [row[column] for row in expected["count"]], name


def _oracle(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, buckets: int) -> dict:
    stamps = [int(value) for value in frame.index.as_unit("ns").asi8]
    values = [[float(v) for v in row] for row in frame[list(CHANNELS)].to_numpy(dtype=float)]
    return bucket_min_max_oracle(stamps, values, start.as_unit("ns").value, end.as_unit("ns").value, buckets)


def _window(state: SessionState, **arguments) -> dict:
    with bind_session(state):
        return REGISTRY.get("get_series_window").fn(channels=",".join(CHANNELS), **arguments)


def test_buckets_equal_the_oracle_over_random_windows() -> None:
    frame = _frame()
    state = _state(frame)
    rng = np.random.default_rng(3)
    first, last = frame.index[0], frame.index[-1]
    span = (last - first).total_seconds()
    decimated = 0
    for _ in range(60):
        a, b = sorted(rng.uniform(-0.05, 1.05, 2))
        start = (first + pd.Timedelta(seconds=a * span)).floor("s")
        end = (first + pd.Timedelta(seconds=b * span)).ceil("s")
        if end <= start:
            continue
        if rng.random() < 0.2:  # on a record, to exercise the half-open bounds
            start = frame.index[rng.integers(len(frame))]
            end = start + pd.Timedelta(hours=int(rng.integers(1, 400)))
        buckets = int(rng.choice([1, 2, 7, 50, 333, 1000, 7000]))
        payload = _window(state, start=start.isoformat(), end=end.isoformat(), buckets=buckets)
        expected = _oracle(frame, start, end, buckets)
        _check(payload, expected)
        decimated += expected["decimated"]
    assert decimated >= 20


def test_the_whole_record_by_default_and_the_envelope_is_preserved() -> None:
    frame = _frame()
    payload = _window(_state(frame), buckets=97)
    expected = _oracle(frame, frame.index[0], frame.index[-1] + pd.Timedelta(1, "ms"), 97)
    _check(payload, expected)
    assert payload["records"] == len(frame)
    assert len(payload["time_ms"]) <= 97
    for name in CHANNELS:
        lows = [v for v in payload["channels"][name]["min"] if v is not None]
        highs = [v for v in payload["channels"][name]["max"] if v is not None]
        assert min(lows) == float(np.nanmin(frame[name]))
        assert max(highs) == float(np.nanmax(frame[name]))
        assert sum(payload["channels"][name]["count"]) == int(frame[name].notna().sum())
    # Empty buckets across the gap: no record, so no bound and a count of 0.
    gap = [i for i, counts in enumerate(payload["channels"]["Dir_100m"]["count"]) if counts == 0]
    assert gap and all(payload["channels"]["Dir_100m"]["min"][i] is None for i in gap)


def test_zooming_in_resolves_more_finely_down_to_the_records() -> None:
    frame = _frame()
    state = _state(frame)
    whole = _window(state, buckets=200)
    start = frame.index[1000]
    week = _window(state, start=start.isoformat(), end=(start + pd.Timedelta(days=7)).isoformat(), buckets=200)
    day = _window(state, start=start.isoformat(), end=(start + pd.Timedelta(days=1)).isoformat(), buckets=200)
    assert whole["decimated"] and week["decimated"]
    assert week["bucket_ms"] < whole["bucket_ms"]
    assert not day["decimated"] and day["bucket_ms"] is None
    assert day["records"] == 144 and len(day["time_ms"]) == 144
    assert day["channels"]["Spd_80m"]["min"] == day["channels"]["Spd_80m"]["max"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"channels": "Nope"}, "No channel named Nope"),
        ({"channels": "Label"}, "Label is not numeric"),
        ({"channels": "Spd_100m,Spd_100m"}, "named twice"),
        ({"channels": " , "}, "at least one channel"),
        ({"channels": "Spd_100m", "start": "2024-01-02T00:00:00"}, "no UTC offset"),
        ({"channels": "Spd_100m", "start": "2024-01-03T00:00:00Z", "end": "2024-01-02T00:00:00Z"}, "must end after"),
        ({"channels": "Spd_100m", "buckets": 0}, "between 1 and"),
        ({"channels": "Spd_100m", "buckets": MAX_SERIES_BUCKETS + 1}, "between 1 and"),
    ],
)
def test_refusals(arguments: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _series_window(_state(_frame()), **arguments)


def test_no_timeseries_is_refused() -> None:
    with pytest.raises(ValueError, match="Load a timeseries first"):
        _series_window(SessionState(), "Spd_100m")


def _table(response) -> pa.Table:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == ARROW_STREAM
    return pa.ipc.open_stream(io.BytesIO(response.content)).read_all()


def _as_payload(table: pa.Table) -> dict:
    meta = json.loads(table.schema.metadata[b"gokaatru"])
    return {
        **{key: meta[key] for key in ("start_ms", "end_ms", "records", "decimated", "bucket_ms")},
        "time_ms": table.column("time").cast(pa.int64()).to_pylist(),
        "channels": {
            name: {bound: table.column(f"{name}.{bound}").to_pylist() for bound in ("min", "max", "count")}
            for name in meta["channels"]
        },
    }, meta


def test_the_arrow_route_serves_the_operation_s_window(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path / "sessions")
    app = create_app()
    app.dependency_overrides[get_session_manager] = lambda: manager
    try:
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            state = manager.get_session(session_id)
            frame = _frame()
            state.timeseries_df = frame
            state.raw_timeseries_df = frame.copy()
            headers = {"X-GoKaatru-Session": session_id}
            url = f"/api/sessions/{session_id}/series"
            query = {"channels": ",".join(CHANNELS), "buckets": 150}

            arrow, meta = _as_payload(_table(client.get(url, headers=headers, params=query)))
            assert meta["selection"] is None
            assert arrow == _window(state, buckets=150)

            definition = {"kind": "band", "channel": "Spd_100m", "min": 6.0}
            with bind_session(state):
                REGISTRY.get("define_selection").fn(name="windy", definition=definition)
            def fetch(**params):
                return _as_payload(_table(client.get(url, headers=headers, params={**query, **params})))

            selected, meta = fetch(selection="windy")
            expected = _window(state, buckets=150, selection="windy")
            assert meta["selection"] == expected.pop("selection")
            assert selected == expected
            assert sum(selected["channels"]["Spd_100m"]["count"]) == meta["selection"]["records"]

            # A zoomed window cuts the selection's mask with the records, past the gap.
            zoom = {"start": frame.index[2500].isoformat(), "end": frame.index[4100].isoformat(), "buckets": 300}
            zoomed, _ = fetch(**zoom, selection="windy")
            expected = _window(state, **zoom, selection="windy")
            del expected["selection"]
            assert zoomed["decimated"] and zoomed == expected

            assert client.get(url, headers=headers, params={**query, "selection": "nowhere"}).status_code == 400
            assert client.get(url, headers=headers, params={"channels": "Nope"}).status_code == 400

            # The same window POSTed, with the selection inline: equal, and neither logged
            # as a change nor saved.
            logged = len(state.operation_log)
            inline = {**query, **zoom, "selection": json.dumps(definition)}
            posted, posted_meta = _as_payload(_table(client.post(url, headers=headers, json=inline)))
            assert posted == zoomed
            assert posted_meta["selection"]["inline"] is True and posted_meta["selection"]["name"] is None
            assert len(state.operation_log) == logged
            refused = client.post(url, headers=headers, json={**query, "selection": "{"})
            assert refused.status_code == 400 and "JSON object" in refused.json()["detail"]
            assert client.post(url, headers=headers, json={**query, "extra": 1}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_the_payload_is_bounded_by_buckets_not_records() -> None:
    rows = 6 * 24 * 365
    rng = np.random.default_rng(1)
    index = pd.date_range("2023-01-01", periods=rows, freq="10min", tz="UTC")
    frame = pd.DataFrame({f"C{i}": rng.normal(8, 2, rows) for i in range(8)}, index=index)
    window = _series_window(_state(frame), ",".join(frame.columns), buckets=2000)
    assert window.records == rows
    assert len(window.time_ms) <= 2000
    assert window.minimum.shape == (len(window.time_ms), 8)
