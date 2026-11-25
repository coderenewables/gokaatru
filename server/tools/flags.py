"""flags — the cleaning flags of a window as intervals, for drawing them as bands.

A flag marks one record of one channel as set missing by one cleaning rule
(``state.cleaning_flags``, decisions/0010). Drawn record by record, five years of scattered
flags are hundreds of thousands of marks, so this returns them run-length encoded: per
channel, each run of consecutive working records flagged by the same rule application, with
the rule, the reason, who applied it and when. Expanding every interval gives the flag table
back exactly (``tests/test_flag_intervals.py``).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.core.selection import SelectionError, utc_timestamp
from server.core.validators import to_utc_index
from server.operations import operation
from server.schemas.results import flags as result_models
from server.state.session import SessionState, session

#: At most this many intervals per response. Past it ``truncated`` is true and the per-channel
#: counts stay complete; the interface asks again for a narrower window.
MAX_FLAG_INTERVALS = 20000


def _instant(value: str, what: str) -> pd.Timestamp:
    try:
        return utc_timestamp(value, what)
    except SelectionError as exc:
        raise ValueError(str(exc)) from exc


def _iso(stamp: pd.Timestamp) -> str:
    return pd.Timestamp(stamp).isoformat()


def _flag_intervals(state: SessionState, channels: str, start: str = "", end: str = "") -> dict:
    if state.timeseries_df is None:
        raise ValueError("Load a timeseries first")
    names = [name.strip() for name in channels.split(",") if name.strip()]
    if not names:
        raise ValueError("Name at least one channel")
    frame = to_utc_index(state.timeseries_df)
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise ValueError(f"No channel named {', '.join(missing)}")
    if len(set(names)) != len(names):
        raise ValueError("A channel is named twice")
    index = pd.DatetimeIndex(frame.index)
    if not index.is_monotonic_increasing:
        raise ValueError("The records are not in time order, so a window cannot be cut from them")
    lo, hi = 0, len(index)
    if start:
        lo = int(index.searchsorted(_instant(start, "start"), side="left"))
    if end:
        hi = int(index.searchsorted(_instant(end, "end"), side="left"))
    hi = max(lo, hi)

    flags = state.cleaning_flags
    stamps = pd.DatetimeIndex(flags["timestamp"])
    stamps = stamps.tz_convert("UTC") if stamps.tz is not None else stamps.tz_localize("UTC")
    positions = index.get_indexer(stamps) if len(flags) else np.array([], dtype=np.int64)
    sensors = flags["sensor"].to_numpy()
    sequences = flags["rule_sequence"].to_numpy()
    described = {column: flags[column].astype(str).to_numpy() for column in ("rule_type", "reason", "actor",
                                                                             "flagged_at")}
    by_channel: dict[str, dict[str, object]] = {}
    total = 0
    truncated = False
    for name in names:
        on_channel = np.flatnonzero((sensors == name) & (positions >= lo) & (positions < hi))
        order = on_channel[np.argsort(positions[on_channel], kind="stable")]
        where = positions[order]
        breaks = np.flatnonzero((np.diff(where) != 1) | (np.diff(sequences[order]) != 0)) + 1
        starts = np.concatenate(([0], breaks)) if len(order) else np.array([], dtype=np.int64)
        ends = np.concatenate((breaks, [len(order)])) - 1 if len(order) else np.array([], dtype=np.int64)
        intervals: list[dict[str, object]] = []
        for run_start, run_end in zip(starts, ends):
            if total >= MAX_FLAG_INTERVALS:
                truncated = True
                break
            row = order[run_start]
            first, last = int(where[run_start]), int(where[run_end])
            intervals.append({
                "first": _iso(index[first]),
                "last": _iso(index[last]),
                # Where the band ends: the record after the run, or none past the last record.
                "next": _iso(index[last + 1]) if last + 1 < len(index) else None,
                "records": int(run_end - run_start + 1),
                "rule_sequence": int(sequences[row]),
                **{column: str(values[row]) for column, values in described.items()},
            })
            total += 1
        by_channel[name] = {"flagged_records": int(len(order)), "intervals": intervals}
    return {
        "records": int(hi - lo),
        "channels": by_channel,
        "interval_count": total,
        "truncated": truncated,
        "interval_limit": MAX_FLAG_INTERVALS,
        # A flag on a timestamp the working records no longer hold; always 0 unless the flag
        # table and the working data have come apart, which this would show rather than hide.
        "unplaced_flags": int((positions < 0).sum()) if len(flags) else 0,
    }


@operation(
    effect="read", stage="cleaning", canvas=False, disclosure=("truncated",),
    result=result_models.GetFlagIntervalsResult,
    reads=("measured_data",),
)
def get_flag_intervals(channels: str, start: str = "", end: str = "") -> dict:
    """Cleaning flags of measured channels over a half-open window, as intervals of consecutive
    records flagged by one rule, with the rule, reason, actor and time of each.

    ``channels`` is comma-separated; ``start`` and ``end`` are timestamps with a UTC offset,
    empty for the whole record. ``next`` is the record after an interval, where its band ends.
    """
    return _flag_intervals(session, channels, start, end)
