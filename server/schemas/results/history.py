"""Results of the history operations: undo, redo and the operation log (P1-19)."""
from __future__ import annotations

from typing import Any

from server.schemas.results._base import Result, RunConfig, Staleness
from server.schemas.results.cleaning import ApplyCleaningRuleResult, UndoCleaningRuleResult
from server.schemas.results.datamodel_builder import BuildDataModelResult
from server.schemas.results.sensors import RemoveSensorsResult, RestoredSensors


class LoggedCall(Result):
    seq: int
    operation: str
    #: The call's own parameters, credentials recorded as "[redacted]".
    parameters: dict[str, Any]


class RestoredPaths(Result):
    """Undoing a configuration change: the run-configuration paths put back."""

    restored_paths: list[str]


class RestoredDataModel(RestoredPaths):
    """Undoing a data model build: the earlier mapping, inventory, timezone and document back,
    and the run-configuration paths the build had set."""

    data_model: str


class UndoLastChangeResult(Staleness):
    status: str
    undone: LoggedCall
    #: A cleaning rule's undo is a replay from raw data; a configuration change's names the
    #: paths restored; a sensor removal's names the sensors put back.
    detail: UndoCleaningRuleResult | RestoredDataModel | RestoredPaths | RestoredSensors
    can_undo: bool
    can_redo: bool


class RedoLastChangeResult(Staleness):
    status: str
    redone: LoggedCall
    #: What the change returned when it was made again.
    detail: ApplyCleaningRuleResult | RemoveSensorsResult | BuildDataModelResult | RunConfig
    can_undo: bool
    can_redo: bool


class OperationLogEntry(Result):
    seq: int
    at: str
    #: ``user``, ``assistant:<provider>/<model>``, ``canvas``, ``mcp`` or ``direct``.
    actor: str
    operation: str
    effect: str
    parameters: dict[str, Any]
    code_version: str
    data_version_before: int
    data_version_after: int
    status: str
    error: str | None
    #: What undoing this call needs, set by the operations that can be undone.
    undo: dict[str, Any] | None = None


class GetOperationLogResult(Result):
    total: int
    entries: list[OperationLogEntry]
    #: Log sequence numbers of undone changes that can be redone, newest last.
    undo_stack: list[int]
    can_undo: bool
    can_redo: bool
