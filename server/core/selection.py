"""selection — a set of records described by what the analyst drew (decisions/0011).

A selection is a small tree. Its leaves are a time range, a direction sector, a value band
on a named channel, a polygon over two channels (a lasso on a scatter), or an explicit set
of records; ``union`` and ``intersection`` combine them. The browser sends the bounds; the
server resolves them to records here, so every view and every statistic uses exactly the
same ones, rather than each chart library's own count.

Bounds are half-open: a record at a range's end, a band's maximum or a sector's closing
edge is outside it, so two adjacent selections never share a record. A polygon follows the
same rule through the even-odd crossing test: a point on a left or lower edge is inside, one
on a right or upper edge is outside, so an axis-aligned rectangle holds exactly what the two
half-open bands it spans hold, and a lasso that crosses itself holds what is enclosed an odd
number of times. A missing value is never selected. A sector whose opening edge is past its
closing edge wraps through north.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

LEAF_KINDS: tuple[str, ...] = ("time_range", "sector", "band", "polygon", "records")
COMBINING_KINDS: tuple[str, ...] = ("union", "intersection")
KINDS: tuple[str, ...] = LEAF_KINDS + COMBINING_KINDS

#: A lasso is simplified in the browser before it is sent; a polygon with more vertices than
#: this is refused rather than resolved slowly (each vertex is one pass over the records).
MAX_POLYGON_VERTICES = 1000


class SelectionError(ValueError):
    """A selection definition that cannot be resolved as written."""


def utc_timestamp(value: Any, what: str) -> pd.Timestamp:
    """A timestamp that names its UTC offset, in UTC; an offset-less one is refused."""
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
    if kind == "polygon":
        _validate_polygon(definition, available)
        return
    if kind == "time_range":
        start, end = definition.get("start"), definition.get("end")
        if start is None and end is None:
            raise SelectionError("A time range needs a start, an end or both")
        if start is not None and end is not None and utc_timestamp(start, "start") >= utc_timestamp(end, "end"):
            raise SelectionError(f"A time range's start {start!r} must be before its end {end!r}")
        for bound, what in ((start, "start"), (end, "end")):
            if bound is not None:
                utc_timestamp(bound, what)
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
            utc_timestamp(value, "timestamp")


def _validate_polygon(definition: dict[str, Any], available: set[str]) -> None:
    for axis in ("x_channel", "y_channel"):
        channel = definition.get(axis)
        if channel not in available:
            raise SelectionError(f"{axis} {channel!r} is not in the loaded data")
    if definition["x_channel"] == definition["y_channel"]:
        raise SelectionError("A polygon needs two different channels; one channel against itself is a band")
    vertices = definition.get("vertices")
    if not isinstance(vertices, list) or len(vertices) < 3:
        raise SelectionError("A polygon needs a list of at least three vertices, each [x, y]")
    if len(vertices) > MAX_POLYGON_VERTICES:
        raise SelectionError(
            f"A polygon may have at most {MAX_POLYGON_VERTICES} vertices, got {len(vertices)}; simplify the lasso"
        )
    for position, vertex in enumerate(vertices):
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 2:
            raise SelectionError(f"Vertex {position} must be a pair [x, y], got {vertex!r}")
        _number(vertex[0], f"vertex {position} x")
        _number(vertex[1], f"vertex {position} y")
    xs = np.array([float(vertex[0]) for vertex in vertices])
    ys = np.array([float(vertex[1]) for vertex in vertices])
    twice_area = np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1))
    if twice_area == 0.0:
        raise SelectionError("A polygon with no area holds nothing; its vertices lie on one line")


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
            mask &= stamps >= utc_timestamp(definition["start"], "start")
        if definition.get("end") is not None:
            mask &= stamps < utc_timestamp(definition["end"], "end")
        return mask
    if kind == "records":
        stamps = index.tz_convert("UTC") if index.tz is not None else index.tz_localize("UTC")
        wanted = pd.DatetimeIndex([utc_timestamp(value, "timestamp") for value in definition["timestamps"]])
        missing = wanted.difference(stamps)
        if len(missing):
            raise SelectionError(
                f"{len(missing)} of the selection's records are not in the loaded data, first {missing[0].isoformat()}"
            )
        return np.asarray(stamps.isin(wanted))
    if kind == "polygon":
        return _inside_polygon(definition, frame)
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


def _number_text(value: Any) -> str:
    return f"{float(value):g}"


def describe(definition: dict[str, Any]) -> str:
    """The definition in words, for a log a reader checks without parsing it."""
    kind = definition["kind"]
    if kind in COMBINING_KINDS:
        joiner = " or " if kind == "union" else " and "
        return joiner.join(
            f"({describe(part)})" if part["kind"] in COMBINING_KINDS else describe(part) for part in definition["of"]
        )
    if kind == "time_range":
        start, end = definition.get("start"), definition.get("end")
        if start is not None and end is not None:
            return f"from {start} to before {end}"
        return f"from {start} on" if start is not None else f"before {end}"
    if kind == "sector":
        return (
            f"{definition['channel']} from {_number_text(definition['from_deg'])}° "
            f"to before {_number_text(definition['to_deg'])}°"
        )
    if kind == "band":
        low, high = definition.get("min"), definition.get("max")
        if low is not None and high is not None:
            return f"{definition['channel']} from {_number_text(low)} to below {_number_text(high)}"
        return (
            f"{definition['channel']} at least {_number_text(low)}"
            if low is not None
            else f"{definition['channel']} below {_number_text(high)}"
        )
    if kind == "polygon":
        return (
            f"{definition['x_channel']} against {definition['y_channel']} inside a "
            f"{len(definition['vertices'])}-vertex polygon"
        )
    return f"{len(definition['timestamps'])} listed records"


def _inside_polygon(definition: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    x = pd.to_numeric(frame[definition["x_channel"]], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(frame[definition["y_channel"]], errors="coerce").to_numpy(dtype=float)
    vertices = [(float(vx), float(vy)) for vx, vy in definition["vertices"]]
    mask = np.zeros(len(frame), dtype=bool)
    ys = [vy for _, vy in vertices]
    # A record below the lowest vertex or at or above the highest straddles no edge, so it
    # is never tested. Only the y extent is used: the test on y is comparisons alone, while
    # a cut on x could disagree with the crossing arithmetic in the last bit.
    candidates = np.flatnonzero(np.isfinite(x) & np.isfinite(y) & (y >= min(ys)) & (y < max(ys)))
    if len(candidates) == 0:
        return mask
    px, py = x[candidates], y[candidates]
    inside = np.zeros(len(candidates), dtype=bool)
    previous = len(vertices) - 1
    for current in range(len(vertices)):
        xi, yi = vertices[current]
        xj, yj = vertices[previous]
        straddles = (yi > py) != (yj > py)
        if straddles.any():
            with np.errstate(divide="ignore", invalid="ignore"):
                crossing = (xj - xi) * (py - yi) / (yj - yi) + xi
            inside ^= straddles & (px < crossing)
        previous = current
    mask[candidates] = inside
    return mask
