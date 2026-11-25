"""Results of the flag operations (P2-4)."""
from __future__ import annotations

from server.schemas.results._base import Result


class FlagInterval(Result):
    """Consecutive working records of one channel flagged by one rule application."""

    first: str
    last: str
    #: The record after the interval, where its band ends; ``None`` past the last record.
    next: str | None
    records: int
    rule_sequence: int
    rule_type: str
    reason: str
    actor: str
    flagged_at: str


class ChannelFlags(Result):
    #: Every flagged record of the channel in the window, counted even past the interval limit.
    flagged_records: int
    intervals: list[FlagInterval]


class GetFlagIntervalsResult(Result):
    records: int
    channels: dict[str, ChannelFlags]
    interval_count: int
    truncated: bool
    interval_limit: int
    unplaced_flags: int
