"""Results of the series window operation (P1-19)."""
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
