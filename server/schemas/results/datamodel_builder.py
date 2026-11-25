"""Results of the data model builder operations (P1-19)."""
from __future__ import annotations

from typing import Any

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


class DataModelInUse(Result):
    #: The document's file name in the workspace uploads.
    file: str
    #: Whether the builder wrote it; only then can the workbench edit it (decisions/0014.8).
    built: bool
    #: The spec a data model built here was built from; null for one delivered with the campaign.
    spec: dict[str, Any] | None


class DraftDataModelResult(Result):
    columns: list[DraftedColumn]
    detected_heights_m: list[Number]
    columns_needing_a_height: list[str]
    basis: str
    note: str
    #: The data model the mapping comes from now; null before any is loaded.
    in_use: DataModelInUse | None = None


class BuildDataModelResult(ParseDatamodelResult):
    file_path: str
    file_name: str
    points_declared: int
    warnings: list[str]
