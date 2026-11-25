"""Results of the clipping analysis (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result, Staleness


class CandidateWindow(Result):
    start_year: int
    n_years: int
    mean_speed: Number
    iav: Number
    lta_ratio: Number
    deviation: Number
    historic_uncertainty: Number
    climate_uncertainty: Number
    combined_uncertainty: Number


class WindowChoice(Result):
    start_year: int
    n_years: int
    combined_uncertainty: Number


class ExponentSensitivity(Result):
    exponent_used: Number
    #: The window each plausible exponent would select, by exponent.
    selection_by_exponent: dict[str, WindowChoice]
    selection_is_exponent_sensitive: bool
    note: str
    selected_window_matches_chosen_exponent: WindowChoice


class IncompleteYear(Result):
    year: int
    completeness: Number
    records: int
    expected_records: int


class RunClippingAnalysisResult(Staleness):
    optimal_start_year: int
    min_uncertainty: Number
    min_uncertainty_pct: Number
    iav: Number
    iav_pct: Number
    selected_iav: Number
    selected_iav_pct: Number
    selected_years: list[int]
    selected_n_years: int
    selected_mean_speed: Number
    analysis_data: list[CandidateWindow]
    years_used: list[int]
    years_dropped_by_objective: list[int]
    years_excluded: list[int]
    excluded_reason: str
    excluded_detail: list[IncompleteYear]
    min_year_completeness: Number
    reference_window_years: int
    shortest_candidate_years: int
    min_window_years: int
    min_window_years_applied: bool
    unconstrained_optimal_start_year: int
    unconstrained_n_years: int
    unconstrained_min_uncertainty: Number
    structural_bias_note: str
    climate_deviation_exponent: Number
    exponent_sensitivity: ExponentSensitivity
    #: Present when the window floor changed the selection.
    window_floor_warning: str | None = None
    #: Present when the selection depends on the climate deviation exponent.
    exponent_warning: str | None = None
