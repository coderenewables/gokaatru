"""Results of the series window and scatter pairs operations (P1-19, P2-5)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, SelectionUsed


class ChannelBuckets(Result):
    min: list[Number]
    max: list[Number]
    count: list[int]


class GetSeriesWindowResult(Result):
    start_ms: int
    end_ms: int
    records: int
    decimated: bool
    #: Null when the window is returned record by record.
    bucket_ms: int | None
    time_ms: list[int]
    channels: dict[str, ChannelBuckets]
    selection: SelectionUsed | None = None


class GetScatterPairsResult(Result):
    x_channel: str
    y_channel: str
    start_ms: int
    end_ms: int
    #: Working records in the window; ``records`` of them have both channels valid.
    window_records: int
    records: int
    time_ms: list[int]
    x: list[float]
    y: list[float]
    #: Per pair, whether the highlight selection holds it; null without one.
    highlighted: list[bool] | None
    #: The highlight selection, counted over the pairs (``of_records``).
    highlight: SelectionUsed | None
