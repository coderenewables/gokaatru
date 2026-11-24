"""Results of the data model builder operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result
from server.schemas.results.data_io import ParseDatamodelResult


class DraftedColumn(Result):
    name: str
    #: ``measurement``, ``statistic`` or ``ignored``.
    role: str
    measurement_type_id: str | None
    height_m: Number
    statistic_type_id: str | None
    parent: str | None
    reason: str | None


class DraftDataModelResult(Result):
    columns: list[DraftedColumn]
    detected_heights_m: list[Number]
    columns_needing_a_height: list[str]
    basis: str
    note: str


class BuildDataModelResult(ParseDatamodelResult):
    file_path: str
    file_name: str
    points_declared: int
    warnings: list[str]
