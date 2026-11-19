"""selection — a set of records described by what the analyst drew (decisions/0011).

A selection is a small tree. Its leaves are a time range, a direction sector, a value band
on a named channel, or an explicit set of records; ``union`` and ``intersection`` combine
them. The browser sends the bounds; the server resolves them to records here, so every view
and every statistic uses exactly the same ones, rather than each chart library's own count.

Bounds are half-open: a record at a range's end, a band's maximum or a sector's closing
edge is outside it, so two adjacent selections never share a record. A missing value is
never selected. A sector whose opening edge is past its closing edge wraps through north.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

LEAF_KINDS: tuple[str, ...] = ("time_range", "sector", "band", "records")
COMBINING_KINDS: tuple[str, ...] = ("union", "intersection")
KINDS: tuple[str, ...] = LEAF_KINDS + COMBINING_KINDS


class SelectionError(ValueError):
    """A selection definition that cannot be resolved as written."""


def _timestamp(value: Any, what: str) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise SelectionError(f"{what} {value!r} is not a timestamp") from exc
    if stamp.tzinfo is None:
        raise SelectionError(
            f"{what} {value!r} has no UTC offset; the records are in UTC, so give one (for example 'Z')"
        )
    return stamp.tz_convert("UTC")


def _number(value: Any, what: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SelectionError(f"{what} must be a number, got {value!r}")
    if not np.isfinite(value):
        raise SelectionError(f"{what} must be finite, got {value!r}")
    return float(value)


def validate(definition: Any, columns: Iterable[str]) -> None:
    """Refuse a definition that names no kind, a channel the data lacks, or bounds that
    describe nothing."""
    available = set(columns)
    if not isinstance(definition, dict):
        raise SelectionError(f"A selection must be an object with a 'kind', got {type(definition).__name__}")
    kind = definition.get("kind")
    if kind not in KINDS:
        raise SelectionError(f"Selection kind must be one of {', '.join(KINDS)}, got {kind!r}")
    if kind in COMBINING_KINDS:
        parts = definition.get("of")
        if not isinstance(parts, list) or not parts:
            raise SelectionError(f"A '{kind}' needs a non-empty list 'of' selections")
        for part in parts:
            validate(part, available)
        return
    if kind in ("sector", "band"):
        channel = definition.get("channel")
        if channel not in available:
            raise SelectionError(f"Channel {channel!r} is not in the loaded data")
    if kind == "time_range":
        start, end = definition.get("start"), definition.get("end")
        if start is None and end is None:
            raise SelectionError("A time range needs a start, an end or both")
        if start is not None and end is not None and _timestamp(start, "start") >= _timestamp(end, "end"):
            raise SelectionError(f"A time range's start {start!r} must be before its end {end!r}")
        for bound, what in ((start, "start"), (end, "end")):
            if bound is not None:
                _timestamp(bound, what)
    elif kind == "sector":
        opening = _number(definition.get("from_deg"), "from_deg")
        closing = _number(definition.get("to_deg"), "to_deg")
        if opening is None or closing is None:
            raise SelectionError("A sector needs both from_deg and to_deg")
        for value, what in ((opening, "from_deg"), (closing, "to_deg")):
            if not 0.0 <= value <= 360.0:
                raise SelectionError(f"{what} must be within 0-360 degrees, got {value}")
        if opening % 360.0 == closing % 360.0:
            raise SelectionError("A sector whose edges coincide is ambiguous: either nothing or the whole circle")
    elif kind == "band":
        low = _number(definition.get("min"), "min")
        high = _number(definition.get("max"), "max")
        if low is None and high is None:
            raise SelectionError("A band needs a min, a max or both")
        if low is not None and high is not None and low >= high:
            raise SelectionError(f"A band's min {low} must be below its max {high}")
    elif kind == "records":
        stamps = definition.get("timestamps")
        if not isinstance(stamps, list) or not stamps:
            raise SelectionError("A record set needs a non-empty list of timestamps")
        for value in stamps:
            _timestamp(value, "timestamp")


def resolve(definition: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    """The records of ``frame`` the selection holds, as a boolean mask over its index."""
    validate(definition, frame.columns)
    return _resolve(definition, frame)


def _resolve(definition: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    kind = definition["kind"]
    if kind == "union":
        return np.logical_or.reduce([_resolve(part, frame) for part in definition["of"]])
    if kind == "intersection":
        return np.logical_and.reduce([_resolve(part, frame) for part in definition["of"]])
    index = pd.DatetimeIndex(frame.index)
    if kind == "time_range":
        stamps = index.tz_convert("UTC") if index.tz is not None else index.tz_localize("UTC")
        mask = np.ones(len(frame), dtype=bool)
        if definition.get("start") is not None:
            mask &= stamps >= _timestamp(definition["start"], "start")
        if definition.get("end") is not None:
            mask &= stamps < _timestamp(definition["end"], "end")
        return mask
    if kind == "records":
        stamps = index.tz_convert("UTC") if index.tz is not None else index.tz_localize("UTC")
        wanted = pd.DatetimeIndex([_timestamp(value, "timestamp") for value in definition["timestamps"]])
        missing = wanted.difference(stamps)
        if len(missing):
            raise SelectionError(
                f"{len(missing)} of the selection's records are not in the loaded data, first {missing[0].isoformat()}"
            )
        return np.asarray(stamps.isin(wanted))
    values = pd.to_numeric(frame[definition["channel"]], errors="coerce").to_numpy(dtype=float)
    present = np.isfinite(values)
    if kind == "band":
        mask = present.copy()
        if definition.get("min") is not None:
            mask &= values >= float(definition["min"])
        if definition.get("max") is not None:
            mask &= values < float(definition["max"])
        return mask
    direction = np.mod(values, 360.0)
    opening, closing = float(definition["from_deg"]) % 360.0, float(definition["to_deg"]) % 360.0
    if closing == 0.0 and float(definition["to_deg"]) == 360.0:
        closing = 360.0
    inside = (direction >= opening) & (direction < closing) if opening < closing else (direction >= opening) | (
        direction < closing
    )
    return present & inside
