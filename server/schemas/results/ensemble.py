"""Results of the ensemble operation (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, Staleness


class OverlapMetrics(Result):
    rmse: Number
    r2: Number
    bias: Number


class ComponentSpread(Result):
    available: bool
    #: Present when the spread could not be measured.
    reason: str | None = None
    records_with_all_components: int | None = None
    components: list[str] | None = None
    mean_std_mps: Number = None
    median_std_mps: Number = None
    p95_std_mps: Number = None
    mean_range_mps: Number = None
    max_range_mps: Number = None
    long_term_mean_spread_mps: Number = None
    component_long_term_means: dict[str, Number] | None = None
    note: str | None = None
    mean_std_pct_of_blend: Number = None


class ComponentCoverage(Result):
    total_records: int
    fully_covered_records: int
    partially_covered_records: int
    partially_covered_fraction: Number
    uncovered_records: int
    component_records: dict[str, int]


class RunEnsembleResult(Staleness):
    status: str
    #: By algorithm, for the components that were blended.
    weights: dict[str, Number]
    weight_basis: dict[str, str]
    weight_rmse: dict[str, Number]
    weight_basis_note: str
    weight_basis_is_mixed: bool
    metrics: OverlapMetrics
    component_spread: ComponentSpread
    component_coverage: ComponentCoverage
    result_file: str
    persisted: bool
    #: Present when the weights mix out-of-sample and in-sample error.
    weight_basis_warning: str | None = None
