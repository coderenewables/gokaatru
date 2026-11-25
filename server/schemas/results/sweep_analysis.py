"""Results of the sweep read operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class SweepEntry(Result):
    """One stored sweep. A manifest written before a field existed reads it as null."""

    sweep_id: str
    started_at: str | None
    finished_at: str | None
    #: ``planned``, ``run``, ``completed``, ``failed``, ``admissible``, ``inadmissible``,
    #: ``duplicates_skipped``; whichever the manifest recorded.
    counts: dict[str, int]
    fixed_prefix_hash: str | None
    in_progress: bool


class ListSweepsResult(Result):
    sweeps: list[SweepEntry]


class DuplicateLevel(Result):
    """A level whose leaves were skipped because they resolved to another level's sensors."""

    same_as: list[str]
    scenarios: int


class AxisSummary(Result):
    levels_designed: list[str]
    levels_admissible: list[str]
    #: By the level that was skipped.
    duplicate_levels: dict[str, DuplicateLevel]
    collapsed_to_one_level: bool


class GetSweepSummaryResult(Result):
    sweep_id: str
    fixed_prefix_hash: str | None
    #: Null on a manifest written before the engine version was stamped.
    engine_version: str | None
    scenarios_total: int
    scenarios_admissible: int
    duplicates_skipped: int
    #: By axis.
    axes: dict[str, AxisSummary]
    #: Scenarios failing each admissibility gate, by gate.
    gate_failures: dict[str, int]
    note: str
    duplicate_note: str
    not_swept: list[str]
    not_swept_statement: str
    not_swept_recorded_in_manifest: bool


class LevelMean(Result):
    level: str
    mean: Number
    count: int


class AxisContribution(Result):
    axis: str
    levels: int
    share: Number
    swing: Number
    level_means: list[LevelMean]
    duplicate_levels: dict[str, DuplicateLevel]


class Spread(Result):
    """The metric's spread over the scenarios; only ``count`` when there are none."""

    count: int
    min: Number = None
    max: Number = None
    mean: Number = None
    std: Number = None
    range: Number = None


class AxisSpread(Result):
    levels: int
    #: Null below ``MIN_LEVELS_FOR_EMPIRICAL`` levels.
    spread_pct: Number


class SubstitutedComponent(Result):
    component: str
    treatment: str
    axes: list[str]
    axes_used: list[str]
    axes_under_resolved: list[str]
    axes_not_varied: list[str]
    parametric_mean_pct: Number
    empirical_pct: Number
    applied_pct: Number
    #: ``empirical``, ``parametric``, ``added`` or ``not_resolved``.
    basis: str


class Distribution(Result):
    min: Number
    median: Number
    max: Number
    mean: Number


class SubstitutionTotals(Result):
    scenarios: int
    scenarios_missing_components: int
    raised: int
    #: Null when no scenario carries every component.
    parametric: Distribution | None
    substituted: Distribution | None
    combination: str


class UncertaintySubstitution(Result):
    """Unavailable, with the reason, with fewer than two usable scenarios."""

    available: bool
    reason: str | None = None
    metric: str | None = None
    statistic: str | None = None
    min_levels: int | None = None
    grand_mean: Number = None
    axes: dict[str, AxisSpread] | None = None
    components: list[SubstitutedComponent] | None = None
    parametric_only: list[str] | None = None
    totals: SubstitutionTotals | None = None
    note: str | None = None


class AnalyzeSweepSpreadResult(Result):
    sweep_id: str
    metric: str
    scenarios_analysed: int
    contributions: list[AxisContribution]
    single_level_axes: list[str]
    basis: str
    basis_note: str
    single_level_note: str
    duplicate_note: str
    spread: Spread
    uncertainty_substitution: UncertaintySubstitution
    #: What no sweep varies (decisions/0013.6), as the manifest states it; a manifest written
    #: before the field gets the same statement, with ``not_swept_recorded_in_manifest`` false.
    not_swept: list[str]
    not_swept_statement: str
    not_swept_recorded_in_manifest: bool
