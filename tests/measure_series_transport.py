"""Payload and server time of a series window at campaign scale (P1-17).

Five years of 10-minute records on 60 channels (262,800 records, 15.8 million values), the
whole record and a zoomed week, as Arrow and as JSON, with and without a selection:

    python -m tests.measure_series_transport

Server time is the window, the selection and the encoding, not the network; the median of
``REPEATS`` runs.
"""
from __future__ import annotations

import json
import statistics
import time

import numpy as np
import pandas as pd

YEARS = 5
CHANNELS = 60
REPEATS = 5


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    index = pd.date_range("2019-01-01", periods=YEARS * 365 * 144, freq="10min", tz="UTC")
    frame = pd.DataFrame(
        {f"Spd_{i:02d}": rng.weibull(2.0, len(index)) * 8.0 for i in range(CHANNELS - 1)},
        index=index,
    )
    frame["Dir_00"] = rng.uniform(0, 360, len(index))
    return frame


def _median_ms(run) -> tuple[float, object]:
    times, result = [], None
    for _ in range(REPEATS):
        began = time.perf_counter()
        result = run()
        times.append((time.perf_counter() - began) * 1000.0)
    return statistics.median(times), result


def main() -> int:
    from server.api.routes.series import series_arrow
    from server.operations import selection_view
    from server.state.session import SessionState, bind_session
    from server.tools.selections import _define_selection
    from server.tools.series import _series_window, window_payload

    frame = _frame()
    state = SessionState()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    with bind_session(state):
        _define_selection(state, "sector", {"kind": "sector", "channel": "Dir_00", "from_deg": 300.0, "to_deg": 60.0})
    channels = ",".join(frame.columns)
    week = (frame.index[100_000].isoformat(), (frame.index[100_000] + pd.Timedelta(days=7)).isoformat())
    full_bytes = frame.memory_usage(index=True, deep=False).sum()

    print(f"{len(frame):,} records x {CHANNELS} channels; the frame holds {full_bytes / 1e6:.1f} MB")
    print(f"{'request':<38}{'rows':>7}{'Arrow KB':>10}{'Arrow ms':>10}{'JSON KB':>10}{'JSON ms':>9}")
    cases = [
        ("whole record, 2000 buckets", "", "", 2000, ""),
        ("whole record, 2000 buckets, selection", "", "", 2000, "sector"),
        ("one week (1008 records)", week[0], week[1], 2000, ""),
    ]
    for label, start, end, buckets, selection in cases:
        def arrow() -> bytes:
            return series_arrow(state, channels, start, end, buckets, selection)

        def as_json() -> str:
            # The operation's path: a selection blanks a copy of the session first.
            source = selection_view(state, selection)[0] if selection else state
            return json.dumps(window_payload(_series_window(source, channels, start, end, buckets)))

        arrow_ms, arrow_payload = _median_ms(arrow)
        json_ms, json_payload = _median_ms(as_json)
        rows = len(_series_window(state, channels, start, end, buckets).time_ms)
        print(
            f"{label:<38}{rows:>7}{len(arrow_payload) / 1e3:>10.1f}{arrow_ms:>10.1f}"
            f"{len(json_payload) / 1e3:>10.1f}{json_ms:>9.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
