"""series — a window of measured channels for a chart, reduced on the server (decisions/0005).

``get_series_window`` returns per-bucket minimum, maximum and valid count as JSON, for MCP
clients and the generated route. ``GET /sessions/{id}/series`` serves the same window as an
Arrow stream for the interface (``server/api/routes/series.py``). Both call
``_series_window``, so the two cannot disagree.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from server.core.decimation import Window, reduce_window
from server.core.selection import SelectionError, utc_timestamp
from server.core.validators import to_utc_index
from server.operations import operation
from server.state.session import SessionState, session

#: Buckets when the caller names none: about the width of a chart in pixels.
DEFAULT_SERIES_BUCKETS = 2000
#: The most buckets one request may ask for; past this the payload is the record itself.
MAX_SERIES_BUCKETS = 20000


def _instant(value: str, what: str) -> pd.Timestamp:
    try:
        return utc_timestamp(value, what)
    except SelectionError as exc:
        raise ValueError(str(exc)) from exc


def _series_window(
    state: SessionState,
    channels: str,
    start: str = "",
    end: str = "",
    buckets: int = DEFAULT_SERIES_BUCKETS,
    keep: np.ndarray | None = None,
) -> Window:
    """The named channels over [start, end), reduced to at most ``buckets`` buckets.

    An empty ``start`` or ``end`` means the first record, or just past the last. ``keep``,
    one flag per working record, blanks every record it does not flag, as a selection does:
    the Arrow route passes a selection's mask here rather than blanking every channel of the
    session to read a few of them.
    """
    if state.timeseries_df is None:
        raise ValueError("Load a timeseries first")
    if not 1 <= buckets <= MAX_SERIES_BUCKETS:
        raise ValueError(f"buckets must be between 1 and {MAX_SERIES_BUCKETS}, got {buckets}")
    names = tuple(name.strip() for name in channels.split(",") if name.strip())
    if not names:
        raise ValueError("Name at least one channel")
    frame = to_utc_index(state.timeseries_df)
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("The records have no timestamp index")
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise ValueError(f"No channel named {', '.join(missing)}")
    if len(set(names)) != len(names):
        raise ValueError("A channel is named twice")
    numeric = [name for name in names if not pd.api.types.is_numeric_dtype(frame[name])]
    if numeric:
        raise ValueError(f"Channel {', '.join(numeric)} is not numeric")
    if frame.empty:
        raise ValueError("The timeseries holds no records")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("The records are not in time order, so a window cannot be cut from them")
    if keep is not None and len(keep) != len(frame):
        raise ValueError(f"keep flags {len(keep)} records, the working data holds {len(frame)}")
    window_start = _instant(start, "start") if start else frame.index[0]
    window_end = _instant(end, "end") if end else frame.index[-1] + pd.Timedelta(1, "ms")
    # Cut the window before copying, so a zoomed request reads only its own records.
    lo, hi = frame.index.searchsorted([window_start, max(window_start, window_end)], side="left")
    rows = frame.iloc[lo:hi]
    values = rows[list(names)].to_numpy(dtype=float)
    if keep is not None:
        values = np.where(keep[lo:hi, None], values, np.nan)
    return reduce_window(rows.index, values, names, window_start, window_end, buckets)


def _number_or_none(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


def window_payload(window: Window) -> dict:
    """The window as JSON: one list per channel and bound, missing as null."""
    return {
        "start_ms": int(window.start_ms),
        "end_ms": int(window.end_ms),
        "records": window.records,
        "decimated": window.decimated,
        "bucket_ms": window.bucket_ms,
        "time_ms": [int(value) for value in window.time_ms],
        "channels": {
            name: {
                "min": [_number_or_none(v) for v in window.minimum[:, column]],
                "max": [_number_or_none(v) for v in window.maximum[:, column]],
                "count": [int(v) for v in np.asarray(window.count[:, column])],
            }
            for column, name in enumerate(window.channels)
        },
    }


@operation(effect="read", stage="visualization", disclosure=("decimated", "bucket_ms"), selectable=True)
def get_series_window(
    channels: str,
    start: str = "",
    end: str = "",
    buckets: int = DEFAULT_SERIES_BUCKETS,
) -> dict:
    """Per-bucket minimum, maximum and valid count of measured channels over a half-open window.

    ``channels`` is comma-separated; ``start`` and ``end`` are timestamps with a UTC offset,
    empty for the whole record. When the window holds more records than ``buckets`` it is cut
    into equal-width buckets of ``bucket_ms`` and ``decimated`` is true; otherwise every record
    is its own bucket. Zoom by asking again for a narrower window.
    """
    return window_payload(_series_window(session, channels, start, end, buckets))
