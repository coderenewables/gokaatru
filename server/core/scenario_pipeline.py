"""scenario_pipeline — one scenario as composable stages, from shear to uncertainty.

``_run_scenario_pipeline`` starts at the LTC, so axes A (sensor selection) and B (shear
model) — which live *upstream* of it — could not be varied at all (design doc §7.3).
This module runs the whole chain::

    resolve sensors (A1, A2)
        -> shear / roughness table (B)
        -> measured series to hub height
        -> reanalysis to hub height (C)
        -> long-term correction (D)
        -> uncertainty, from this scenario's own results (§7.5)

Each stage is a plain function taking the bound scenario state and returning a record of
what it did. They are separate rather than one procedure so the DAG runner can memoise
them individually: every LTC choice downstream of a given ``(A1, B)`` pair shares that
pair's shear table, and recomputing it per leaf is the single largest waste available
(design doc §5).

**Stages never own isolation.** They mutate whatever state is bound, exactly as the
interactive tools do. Running them safely is ``scenario_context``'s job, and keeping the
two concerns apart is what lets the same code serve an interactive analysis and a sweep.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from server.core.sensor_selection import SensorSelection, resolve_policy
from server.core.uncertainty_inputs import derive_uncertainty_inputs, uncertainty_call_args

#: Axis B levels that map onto the existing shear tooling.
POWER_LAW_AGGREGATIONS = ("mean", "median", "momm")
SHEAR_MODELS: tuple[str, ...] = (
    "power_law_mean",
    "power_law_median",
    "power_law_momm",
    "power_law_constant",
    "log_law_mean",
    "log_law_median",
    "log_law_momm",
)

#: Axis B levels the design calls for that the extrapolation path cannot yet consume.
#: `_extrapolate_to_hub_height` reads a single 12x24 `state.shear_table`, so a directional
#: table or a per-record series has nowhere to go. Declared here so a sweep that requests
#: one fails with this explanation rather than silently falling back to a table.
UNIMPLEMENTED_SHEAR_MODELS: dict[str, str] = {
    "power_law_sector_12": "sector shear tables are built but extrapolation reads only the 12x24 table",
    "power_law_sector_16": "sector shear tables are built but extrapolation reads only the 12x24 table",
    "power_law_per_record": "extrapolation looks alpha up by month-hour, not per record",
}


@dataclass(frozen=True)
class ScenarioSpec:
    """One point in the scenario space (design doc §3)."""

    shear_fit_policy: str
    reference_policy: str
    shear_model: str
    reference_source: str
    ltc_algorithm: str
    hub_height_m: float | None = None
    analyst_shear_alpha: float | None = None

    def as_runconfig(self) -> dict[str, Any]:
        """Return the axis values as they are written into a scenario runconfig (§7.13)."""
        record: dict[str, Any] = {
            "sensor_selection": {
                "shear_fit": self.shear_fit_policy,
                "extrapolation_reference": self.reference_policy,
            },
            "shear_model": self.shear_model,
            "reference_source": self.reference_source,
            "ltc_algorithm": self.ltc_algorithm,
        }
        if self.hub_height_m is not None:
            record["hub_height_m"] = float(self.hub_height_m)
        if self.analyst_shear_alpha is not None:
            record["analyst_shear_alpha"] = float(self.analyst_shear_alpha)
        return record


@dataclass
class StageResult:
    """What one stage did, for the scenario record and for debugging a failure."""

    stage: str
    ok: bool
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class ScenarioError(RuntimeError):
    """A scenario could not be run as specified. Carries the stage that refused."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


def _height_sensors_json(selection: SensorSelection) -> str:
    """Format a resolved selection as the height->column JSON the shear tools take."""
    return json.dumps(
        {str(int(height)): column for height, column in zip(selection.heights_m, selection.columns)}
    )


def resolve_sensors(state: Any, spec: ScenarioSpec) -> tuple[SensorSelection, SensorSelection]:
    """Resolve axis A1 and A2, refusing the scenario if either policy does not apply here."""
    hub = spec.hub_height_m
    fit = resolve_policy(state, spec.shear_fit_policy, hub)
    reference = resolve_policy(state, spec.reference_policy, hub)
    if not fit.available:
        raise ScenarioError("resolve_sensors", f"shear-fit policy unusable: {fit.reason}")
    if not reference.available:
        raise ScenarioError("resolve_sensors", f"reference policy unusable: {reference.reason}")
    if not fit.can_fit_shear and spec.analyst_shear_alpha is None:
        raise ScenarioError(
            "resolve_sensors",
            f"policy '{spec.shear_fit_policy}' resolves to "
            f"{len(fit.heights_m)} height(s); a shear exponent cannot be fitted from fewer "
            "than two, so the scenario must supply one (design doc §3.A.1)",
        )
    return fit, reference


def _constant_shear_table(alpha: float) -> pd.DataFrame:
    """Return a 12x24 lookup filled with one exponent, for the constant-alpha levels."""
    return pd.DataFrame(np.full((12, 24), float(alpha)), index=range(1, 13), columns=range(24))


def build_shear(state: Any, spec: ScenarioSpec, fit: SensorSelection) -> StageResult:
    """Build the scenario's vertical-profile table (axis B).

    An analyst-supplied exponent short-circuits the fit entirely and writes a constant
    table, which is the honest representation of "we assumed this" — the extrapolation
    then reads it exactly as it reads a fitted one, and the *provenance* rather than the
    mechanism is what marks the difference (design doc §3.A.1).
    """
    from server.tools.shear import (
        _build_roughness_table,
        _build_shear_table,
        _calculate_roughness_timeseries,
        _calculate_shear_timeseries,
    )

    if spec.shear_model in UNIMPLEMENTED_SHEAR_MODELS:
        raise ScenarioError(
            "build_shear",
            f"shear model '{spec.shear_model}' is not yet supported: "
            f"{UNIMPLEMENTED_SHEAR_MODELS[spec.shear_model]}",
        )
    if spec.shear_model not in SHEAR_MODELS:
        raise ScenarioError(
            "build_shear",
            f"shear model must be one of {', '.join(SHEAR_MODELS)}, got '{spec.shear_model}'",
        )

    height_sensors = _height_sensors_json(fit)

    if spec.analyst_shear_alpha is not None:
        state.shear_table = _constant_shear_table(spec.analyst_shear_alpha)
        state.stamp_derived("shear_table")
        return StageResult(
            "build_shear",
            True,
            {
                "method": "power_law",
                "shear_source": "analyst_supplied",
                "alpha": float(spec.analyst_shear_alpha),
                "fit_heights_m": list(fit.heights_m),
            },
        )

    if spec.shear_model.startswith("log_law"):
        _calculate_roughness_timeseries(state, height_sensors)
        table = _build_roughness_table(state, spec.shear_model.removeprefix("log_law_"))
        return StageResult(
            "build_shear",
            True,
            {
                "method": "log_law",
                "shear_source": "fitted",
                "aggregation": table["aggregation"],
                "fit_heights_m": list(fit.heights_m),
            },
        )

    _calculate_shear_timeseries(state, height_sensors)
    if spec.shear_model == "power_law_constant":
        # One site-wide exponent: the mean of the scenario's own series, not a default.
        series = state.shear_timeseries_df["shear_coefficient"].dropna()
        if series.empty:
            raise ScenarioError("build_shear", "shear series is empty, so no site-wide alpha exists")
        alpha = float(series.mean())
        state.shear_table = _constant_shear_table(alpha)
        state.stamp_derived("shear_table")
        return StageResult(
            "build_shear",
            True,
            {
                "method": "power_law",
                "shear_source": "fitted",
                "aggregation": "site_constant",
                "alpha": alpha,
                "fit_heights_m": list(fit.heights_m),
            },
        )

    table = _build_shear_table(state, spec.shear_model.removeprefix("power_law_"))
    return StageResult(
        "build_shear",
        True,
        {
            "method": "power_law",
            "shear_source": "fitted",
            "aggregation": table["aggregation"],
            "fit_heights_m": list(fit.heights_m),
            "table_coverage": table.get("table_coverage"),
            "shear_clamping": table.get("shear_clamping"),
        },
    )


def extrapolate(state: Any, spec: ScenarioSpec, reference: SensorSelection) -> StageResult:
    """Carry the measured series and both reanalyses to hub height (axes A2, C)."""
    from server.tools.extrapolation import (
        _extrapolate_all_reanalysis_nodes,
        _extrapolate_to_hub_height,
    )

    hub = spec.hub_height_m if spec.hub_height_m is not None else state.get_hub_height_m()
    if hub is None:
        raise ScenarioError("extrapolate", "hub height is not set")
    shear_model = "log_law" if spec.shear_model.startswith("log_law") else "power_law"
    measured = _extrapolate_to_hub_height(
        state, float(hub), shear_model, reference_columns=list(reference.columns)
    )
    # Same profile for the reference as for the measurement: correlating a
    # power-law-extrapolated reanalysis with a log-law-extrapolated site series would
    # be an internally inconsistent pair.
    reanalysis = _extrapolate_all_reanalysis_nodes(state, float(hub), shear_model=shear_model)
    return StageResult(
        "extrapolate",
        True,
        {
            "hub_column": measured["column_name"],
            "reference_heights_m": list(reference.heights_m),
            "method_counts": measured.get("method_counts"),
            "extrapolation_ratio": measured.get("extrapolation_ratio"),
            "extrapolation_warning": measured.get("warning"),
            "reanalysis_status": reanalysis.get("status"),
            "reanalysis_skipped": reanalysis.get("skipped_nodes"),
        },
    )


def run_ltc(state: Any, spec: ScenarioSpec) -> StageResult:
    """Run the scenario's long-term correction against its chosen reference (axes C, D)."""
    from server.api.routes.analysis import LTC_ALGORITHMS, _resolve_ltc_columns

    state.set_active_reference_source(spec.reference_source)
    algorithm = spec.ltc_algorithm
    runner = LTC_ALGORITHMS.get(algorithm)
    if runner is None:
        raise ScenarioError(
            "run_ltc", f"unknown LTC algorithm '{algorithm}'; expected one of {sorted(LTC_ALGORITHMS)}"
        )
    short_col, long_col, short_dir_col, long_dir_col = _resolve_ltc_columns(state)
    if algorithm == "xgboost":
        result = runner(state, short_col, long_col, short_dir_col, long_dir_col)
    else:
        result = runner(state, short_col, long_col)
    metrics = result.get("metrics", {})
    return StageResult(
        "run_ltc",
        True,
        {
            "algorithm": algorithm,
            "reference_source": spec.reference_source,
            "short_column": short_col,
            "long_column": long_col,
            "r_squared": metrics.get("r_squared"),
            "concurrent_points": metrics.get("concurrent_points"),
        },
    )


def run_uncertainty(state: Any, spec: ScenarioSpec, reference: SensorSelection) -> StageResult:
    """Compute uncertainty from this scenario's own fit, series and geometry (§7.5)."""
    from server.tools.uncertainty import _calculate_uncertainty

    shear_source = "analyst_supplied" if spec.analyst_shear_alpha is not None else "fitted"
    inputs = derive_uncertainty_inputs(
        state,
        spec.ltc_algorithm,
        hub_height_m=spec.hub_height_m,
        reference_heights=list(reference.heights_m),
        shear_source=shear_source,
    )
    result = _calculate_uncertainty(state, **uncertainty_call_args(inputs))
    return StageResult(
        "run_uncertainty",
        True,
        {
            "total_uncertainty_pct": result.get("total_uncertainty_pct"),
            "components": result.get("components"),
            "provenance": inputs["provenance"],
        },
    )


def run_scenario(state: Any, spec: ScenarioSpec) -> dict[str, Any]:
    """Run every stage in order against the bound state, returning the stage records.

    Raises :class:`ScenarioError` naming the stage that refused. A sweep catches it and
    records the scenario as failed with its reason, rather than dropping it silently.
    """
    fit, reference = resolve_sensors(state, spec)
    stages = [
        build_shear(state, spec, fit),
        extrapolate(state, spec, reference),
        run_ltc(state, spec),
        run_uncertainty(state, spec, reference),
    ]
    return {
        "spec": spec.as_runconfig(),
        "sensor_selection": {
            "shear_fit": fit.to_runconfig(),
            "extrapolation_reference": reference.to_runconfig(),
        },
        "stages": {stage.stage: stage.detail for stage in stages},
    }
