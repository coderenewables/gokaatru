"""Results of the sensor removal operation (P2-6)."""
from __future__ import annotations

from server.schemas.results._base import Result
from server.schemas.results.cleaning import FrameChange


class RemoveSensorsResult(Result):
    status: str
    removed: list[str]
    #: Named sensors that were not in the inventory, or were named twice.
    not_found: list[str]
    remaining_count: int
    #: The columns taken out of ``timeseries_df`` and ``raw_timeseries_df``.
    columns_dropped: dict[str, list[str]]


class RemoveSensorsPreview(RemoveSensorsResult):
    applied: bool
    changes: FrameChange


class RestoredSensors(Result):
    """Undoing a sensor removal: the sensors put back."""

    restored: list[str]
