"""Results of the selection operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, OpenResult, Result


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
