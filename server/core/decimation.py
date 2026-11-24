"""decimation — a time window of channels reduced to what a screen can show (decisions/0005).

The window is cut into equal-width buckets in time, and each channel reports its minimum,
maximum and number of valid records in every bucket. A chart that draws the band between
the two shows exactly the data's envelope: no peak falls between two sampled points, as it
does when a series is thinned by taking every n-th record. A window holding no more records
than buckets is returned record by record. Zooming in is a request for a narrower window,
which the same number of buckets then resolves more finely, down to the records themselves.

The window is half-open, like a selection's time range: a record at its end is outside it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_NS_PER_MS = 1_000_000


@dataclass(frozen=True)
class Window:
    """Per-bucket minimum, maximum and valid-record count for each channel.

    ``time_ms`` is each bucket's start (each record's time when not decimated), in UTC
    milliseconds. A bucket holding no valid record of a channel has NaN for both bounds and
    a count of 0.
    """

    channels: tuple[str, ...]
    time_ms: np.ndarray
    minimum: np.ndarray
    maximum: np.ndarray
    count: np.ndarray
    start_ms: int
    end_ms: int
    bucket_ms: int | None
    records: int
    decimated: bool


def reduce_window(
    index: pd.DatetimeIndex,
    values: np.ndarray,
    channels: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
    buckets: int,
) -> Window:
    """Reduce the records of ``values`` (one column per channel) in [start, end) to buckets.

    ``index`` must be UTC and increasing; ``start`` and ``end`` UTC.
    """
    if buckets < 1:
        raise ValueError(f"buckets must be at least 1, got {buckets}")
    if not end > start:
        raise ValueError(f"The window must end after it starts, got {start.isoformat()} to {end.isoformat()}")
    if not index.is_monotonic_increasing:
        raise ValueError("The records are not in time order, so a window cannot be cut from them")
    stamps = index.as_unit("ns").asi8
    start_ns = start.as_unit("ns").value
    end_ns = end.as_unit("ns").value
    lo, hi = np.searchsorted(stamps, [start_ns, end_ns], side="left")
    times = stamps[lo:hi]
    block = np.asarray(values[lo:hi], dtype=float)
    records = int(hi - lo)
    common = {"channels": channels, "start_ms": start_ns // _NS_PER_MS, "end_ms": end_ns // _NS_PER_MS}

    if records <= buckets:
        return Window(
            time_ms=times // _NS_PER_MS,
            minimum=block.copy(),
            maximum=block.copy(),
            count=(~np.isnan(block)).astype(np.int64),
            bucket_ms=None,
            records=records,
            decimated=False,
            **common,
        )

    # A whole number of milliseconds, so every bucket starts on a millisecond the client can
    # represent; rounding the width up keeps the count of buckets at or below the request.
    width_ns = -(-(end_ns - start_ns) // (buckets * _NS_PER_MS)) * _NS_PER_MS
    spanned = int(-(-(end_ns - start_ns) // width_ns))
    edges = start_ns + width_ns * np.arange(spanned, dtype=np.int64)
    first = np.searchsorted(times, edges, side="left")
    held = np.diff(np.append(first, records))
    occupied = held > 0
    # reduceat over the occupied buckets only: their first positions are strictly increasing
    # and each segment runs to the next occupied bucket's first record, which is exactly the
    # bucket's own records because the empty ones between hold none.
    positions = first[occupied]
    minimum = np.full((spanned, len(channels)), np.nan)
    maximum = np.full((spanned, len(channels)), np.nan)
    count = np.zeros((spanned, len(channels)), dtype=np.int64)
    if positions.size:
        valid = ~np.isnan(block)
        minimum[occupied] = np.fmin.reduceat(block, positions, axis=0)
        maximum[occupied] = np.fmax.reduceat(block, positions, axis=0)
        count[occupied] = np.add.reduceat(valid.astype(np.int64), positions, axis=0)
    return Window(
        time_ms=edges // _NS_PER_MS,
        minimum=minimum,
        maximum=maximum,
        count=count,
        bucket_ms=int(width_ns // _NS_PER_MS),
        records=records,
        decimated=True,
        **common,
    )
