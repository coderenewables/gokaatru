"""Results of the hub-height extrapolation operations (P1-19)."""
from __future__ import annotations

from server.schemas.results._base import Number, Result


class ExtrapolateReanalysisToHubResult(Result):
    status: str
    column_name: str
    reference_source: str
    reference_height_m: Number


class MethodCounts(Result):
    direct: int
    interpolated: int
    extrapolated: int
    #: Records whose reference speed sat below the shear gate; they are extrapolated too.
    below_shear_gate: int | None = None


class MethodModels(Result):
    direct: str
    interpolated: str
    extrapolated: str


class ReanalysisExtrapolation(Result):
    """The reanalysis leg: ``ok``, ``no_op``, ``skipped`` (with the reason) or ``failed``."""

    status: str
    wrote_hub_column: bool
    reason: str | None = None
    hub_column: str | None = None
    shear_model: str | None = None
    reference_columns: dict[str, str] | None = None
    extrapolated_nodes: list[str] | None = None
    skipped_nodes: list[str] | None = None
    interpolated_extrapolated: bool | None = None
    interpolated_sources: list[str] | None = None
    warning: str | None = None


class ReferenceHeights(Result):
    min: Number
    max: Number
    most_common: Number
    #: Records extrapolated from each reference height.
    record_counts: dict[str, int]


class ExtrapolationRatios(Result):
    min: Number
    max: Number
    mean: Number


class ExtrapolateToHubHeightResult(Result):
    """When a sensor sits at hub height its series is used directly and only the first six
    fields are sent, with ``reference_height_m`` the hub height and a ratio of 1."""

    status: str
    column_name: str
    method_counts: MethodCounts
    extrapolated_records: int
    #: A distribution when records were extrapolated, the hub height when measured there,
    #: null when nothing was extrapolated.
    reference_height_m: ReferenceHeights | Number
    extrapolation_ratio: ExtrapolationRatios | Number
    warning: str | None
    method_models: MethodModels | None = None
    method_note: str | None = None
    method_is_mixed: bool | None = None
    stability_treatment: str | None = None
    stability_note: str | None = None
    alpha_reclamped_records: int | None = None
    alpha_clamp_band: list[Number] | None = None
    extrapolation_speed_gate_mps: Number = None
    records_below_extrapolation_gate: int | None = None
    reanalysis: ReanalysisExtrapolation | None = None
    extrapolation_ratio_warn_threshold: Number = None
    records_above_warn_threshold: int | None = None
    data_version: int | None = None
    stale_artifacts: list[str] | None = None
    stale_reasons: dict[str, str | None] | None = None
    extrapolation_gate_warning: str | None = None
    alpha_clamp_warning: str | None = None
    method_warning: str | None = None
    reanalysis_warning: str | None = None
