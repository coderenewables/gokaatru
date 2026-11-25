"""Results of the selection operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, OpenResult, Result, SelectionUsed


class SelectionDefinition(OpenResult):
    """A selection as it was defined (``server/core/selection.py``): a leaf, or a union or
    intersection of selections. Keys the resolver does not read are kept as sent."""

    kind: str
    channel: str | None = None
    from_deg: Number = None
    to_deg: Number = None
    min: Number = None
    max: Number = None
    start: str | None = None
    end: str | None = None
    timestamps: list[str] | None = None
    x_channel: str | None = None
    y_channel: str | None = None
    vertices: list[list[Number]] | None = None
    of: list[SelectionDefinition] | None = None


class SelectionSummary(Result):
    name: str
    definition: SelectionDefinition
    records: int
    of_records: int
    #: Contiguous runs of selected records, as [first, last] timestamps.
    ranges: list[list[str]]
    ranges_truncated: bool
    range_limit: int


class DefineSelectionResult(SelectionSummary):
    status: str
    replaced: bool


class DeleteSelectionResult(Result):
    status: str
    deleted: str


class StoredSelection(Result):
    name: str
    definition: SelectionDefinition
    actor: str | None
    #: Absent when no timeseries is loaded.
    records: int | None = None
    #: Present instead of ``records`` when the selection no longer resolves on the data.
    unresolvable: str | None = None


class ListSelectionsResult(Result):
    selections: list[StoredSelection]


class ResolveSelectionResult(SelectionSummary):
    pass


class ChannelSummary(Result):
    valid: int
    #: Null when the channel has no valid record (on the selection).
    mean: Number
    min: Number
    max: Number


class SummariseChannelsResult(Result):
    #: Working records; with a selection, those outside it count but are blank.
    records: int
    channels: dict[str, ChannelSummary]
    selection: SelectionUsed | None = None
