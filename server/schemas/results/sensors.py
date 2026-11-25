"""Results of the sensor removal operation (P2-6)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result
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


class Instrument(Result):
    name: str
    height_m: Number
    sensor_type: str | None
    #: Whether the working data holds its column (a removed sensor's does not).
    in_data: bool
    #: The sensor_mapping slot it fills (``speed_col``, ``dir_col``, ...), or null.
    mapped_as: str | None
    #: Its statistic columns (standard deviation, minimum, maximum), by name.
    statistics: list[str]
    boom_orientation_deg: Number = None


class OtherChannel(Result):
    """A column of the data that belongs to no instrument, with how its header reads."""

    name: str
    #: ``measurement``, ``statistic`` or ``ignored`` (the data model builder's reading).
    role: str
    reason: str | None


class ListInstrumentsResult(Result):
    heights: list[Number]
    instruments: list[Instrument]
    other_channels: list[OtherChannel]


class RestoredSensors(Result):
    """Undoing a sensor removal: the sensors put back."""

    restored: list[str]
