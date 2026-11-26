"""Results of the cleaning operations (P1-19)."""
from __future__ import annotations

from typing import Any

from server.schemas.results._base import CleaningDetail, CleaningLogEntry, Result, Staleness


class PrecedingRule(Result):
    sequence: int
    rule_type: str
    sensor: str


class OrderDependence(Result):
    sequence: int
    order_is_material: bool
    note: str
    applied_before_on_this_sensor: list[PrecedingRule]
    #: Present when an earlier rule on the same sensor changed what this one saw.
    warning: str | None = None


class ApplyCleaningRuleResult(CleaningDetail):
    status: str
    rule: str
    sensor: str
    records_affected: int
    order_dependence: OrderDependence


class ColumnChange(Result):
    set_missing: int
    restored: int
    changed: int
    #: Contiguous runs of changed records, as [first, last] timestamps.
    ranges: list[list[str]]
    ranges_truncated: bool


class FrameChange(Result):
    """What a dry run would change, as a diff of the working frame (``_change_summary``)."""

    rows_before: int
    rows_after: int
    rows_inserted: int
    rows_removed: int
    columns_dropped: list[str]
    columns_added: list[str]
    #: Only the columns whose values would change, by name.
    columns: dict[str, ColumnChange]
    range_limit: int


class ApplyCleaningRulePreview(ApplyCleaningRuleResult):
    applied: bool
    changes: FrameChange


class FlagsByRule(Result):
    rule_sequence: int
    rule_type: str
    reason: str
    sensor: str
    records: int


class FlagSummary(Result):
    flagged_records: int
    by_rule: list[FlagsByRule]


class GetCleaningLogResult(Result):
    entries: list[CleaningLogEntry]
    order_is_material: bool
    order_note: str
    flags: FlagSummary


class CleaningRule(Result):
    name: str
    description: str
    #: The rule's own parameters and their defaults.
    default_params: dict[str, Any]


class ListCleaningRulesResult(Result):
    rules: list[CleaningRule]
    #: The reason codes ``exclude_selection`` accepts (``MANUAL_FLAG_REASONS``).
    manual_flag_reasons: list[str]
    order_is_material: bool
    order_note: str
    outlier_detection: str
    outlier_note: str


class UndoCleaningRuleResult(Staleness):
    status: str
    remaining_rules: int
    #: Derived columns the replay from raw data removed; the warning names them.
    dropped_columns: list[str]


class UndoCleaningRulePreview(UndoCleaningRuleResult):
    applied: bool
    changes: FrameChange
