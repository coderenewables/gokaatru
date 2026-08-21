"""scenario_result — one flat, hashable record per scenario.

Every frontend view in the design is a query over one table (design doc §7.8), so the
shape of that table is the interface between the engine and everything downstream:
the distribution panel, the parallel-coordinates plot, the scenario table, the variance
decomposition, and the CSV export are all projections of these records.

Flat on purpose. Nested payloads are convenient to produce and miserable to filter,
sort and group, which is the entire job on the other side.

**Two hashes travel with every record.**

``fixed_prefix_hash``
    Cleaning log, reanalysis identity, sensor inventory, hub height — everything decided
    once before the sweep opened (design doc §2). Two scenarios with different values here
    are not comparable, and the engine refuses to put them in one spread rather than
    quietly mixing them.

``config_hash``
    The scenario's own axis values, taken over the *resolved* configuration rather than
    the policy names. That is what makes the §4 deduplication possible: two policies that
    resolve to the same sensors on this mast produce the same hash and the same
    computation, whatever they are called.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from server.core.admissibility import AdmissibilityReport, GateThresholds

#: Columns that identify a scenario's position in the space (design doc §3).
AXIS_COLUMNS: tuple[str, ...] = (
    "shear_fit_policy",
    "reference_policy",
    "shear_model",
    "reference_source",
    "ltc_algorithm",
)

#: The two pinned headline metrics (design doc §11), then the secondary ones.
METRIC_COLUMNS: tuple[str, ...] = (
    "long_term_mean_speed_mps",
    "indicative_gross_aep_mwh",
    "capacity_factor",
    "energy_sensitivity_factor",
    "total_uncertainty_pct",
    "u_measurement_pct",
    "u_vertical_pct",
    "u_mcp_pct",
    "u_future_pct",
    "ltc_r_squared",
    "concurrent_months",
    "mean_shear_alpha",
    "extrapolation_ratio_max",
)


def _stable_hash(payload: Any) -> str:
    """Return a short content hash over a JSON-serialisable payload.

    ``sort_keys`` makes the hash independent of dict ordering, so the same configuration
    hashes identically however it was assembled.
    """
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def fixed_prefix_hash(state: Any) -> str:
    """Hash everything decided once, before the sweep opened (design doc §2)."""
    return _stable_hash(
        {
            "cleaning_log": state.cleaning_log,
            "reanalysis_identity": state.reanalysis_cache_identity,
            "reanalysis_sources": sorted(state.reanalysis_interpolated),
            "sensor_inventory": sorted(state.sensor_inventory or {}),
            "hub_height_m": state.get_hub_height_m(),
            "measurement_type": state.get_measurement_type(),
            "power_curve": state.get_power_curve_name(),
        }
    )


def config_hash(scenario_record: dict[str, Any], prefix_hash: str) -> str:
    """Hash a scenario's resolved configuration, including the prefix it was built on."""
    selection = scenario_record.get("sensor_selection", {})
    return _stable_hash(
        {
            "prefix": prefix_hash,
            "spec": scenario_record.get("spec", {}),
            # Resolved columns, not policy names — see the module docstring.
            "shear_fit_columns": selection.get("shear_fit", {}).get("resolved_columns"),
            "reference_columns": selection.get("extrapolation_reference", {}).get(
                "resolved_columns"
            ),
        }
    )


@dataclass
class ScenarioResult:
    """One row of the sweep's result table."""

    config_hash: str
    fixed_prefix_hash: str
    axes: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float | None] = field(default_factory=dict)
    admissible: bool = True
    gate_status: dict[str, str] = field(default_factory=dict)
    #: The number each gate was reached on, so the UI can show *why* a scenario failed
    #: rather than only that it did. None where a gate had nothing to measure.
    gate_values: dict[str, float | None] = field(default_factory=dict)
    #: One line per gate explaining its verdict, carried into the scenario runconfig.
    gate_details: dict[str, str] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    marks: list[str] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None

    def as_row(self) -> dict[str, Any]:
        """Return the flat row: one dict, no nesting, ready for a table or a CSV."""
        row: dict[str, Any] = {
            "config_hash": self.config_hash,
            "fixed_prefix_hash": self.fixed_prefix_hash,
            "status": self.status,
            "admissible": self.admissible,
        }
        for column in AXIS_COLUMNS:
            row[column] = self.axes.get(column)
        for column in METRIC_COLUMNS:
            row[column] = self.metrics.get(column)
        for name, status in sorted(self.gate_status.items()):
            row[f"gate_{name}"] = status
            # The measured value travels beside the verdict. A status alone tells a
            # reader a scenario was excluded; the value tells them by how much, which is
            # what they need to judge whether the threshold or the campaign is at fault.
            row[f"gate_{name}_value"] = self.gate_values.get(name)
        row["failed_gates"] = ",".join(self.failures)
        row["warned_gates"] = ",".join(self.warnings)
        row["marked_gates"] = ",".join(self.marks)
        row["error"] = self.error
        return row


def _finite(value: Any) -> float | None:
    """Return a float when the value is a finite number, else None."""
    if isinstance(value, (int, float)) and np.isfinite(value):
        return float(value)
    return None


def _collect_metrics(state: Any, scenario_record: dict[str, Any]) -> dict[str, float | None]:
    """Read the headline and secondary metrics off a completed scenario's own artefacts."""
    metrics: dict[str, float | None] = {column: None for column in METRIC_COLUMNS}

    series, _source = state.long_term_speed_series()
    if series is not None and not series.empty:
        metrics["long_term_mean_speed_mps"] = float(series.mean())

    uncertainty = state.latest_uncertainty or {}
    metrics["total_uncertainty_pct"] = _finite(uncertainty.get("total_uncertainty_pct"))
    components = uncertainty.get("components") or {}
    metrics["u_measurement_pct"] = _finite(components.get("measurement"))
    metrics["u_vertical_pct"] = _finite(components.get("vertical_extrapolation"))
    metrics["u_mcp_pct"] = _finite(components.get("mcp"))
    metrics["u_future_pct"] = _finite(components.get("future_variability"))

    # AEP, capacity factor and S all come from the energy block, which the uncertainty
    # stage computed against the sweep's single power curve (design doc §7.12).
    energy = uncertainty.get("energy_sensitivity") or {}
    if energy.get("available"):
        metrics["indicative_gross_aep_mwh"] = _finite(energy.get("indicative_gross_aep_mwh"))
        metrics["energy_sensitivity_factor"] = _finite(energy.get("factor"))
        curve = energy.get("power_curve") or {}
        metrics["capacity_factor"] = _finite(curve.get("indicative_capacity_factor"))

    stages = scenario_record.get("stages", {})
    ltc = stages.get("run_ltc", {})
    metrics["ltc_r_squared"] = _finite(ltc.get("r_squared"))
    points = ltc.get("concurrent_points")
    if isinstance(points, (int, float)) and points > 0:
        metrics["concurrent_months"] = float(points) / 730.0

    if state.shear_table is not None:
        mean_alpha = float(np.nanmean(state.shear_table.to_numpy(dtype=float)))
        metrics["mean_shear_alpha"] = _finite(mean_alpha)

    ratio = stages.get("extrapolate", {}).get("extrapolation_ratio")
    if isinstance(ratio, dict):
        metrics["extrapolation_ratio_max"] = _finite(ratio.get("max"))

    return metrics


def build_result(
    state: Any,
    scenario_record: dict[str, Any],
    report: AdmissibilityReport,
) -> ScenarioResult:
    """Assemble one completed scenario into a table row."""
    prefix = fixed_prefix_hash(state)
    spec = scenario_record.get("spec", {})
    selection = spec.get("sensor_selection", {})
    return ScenarioResult(
        config_hash=config_hash(scenario_record, prefix),
        fixed_prefix_hash=prefix,
        axes={
            "shear_fit_policy": selection.get("shear_fit"),
            "reference_policy": selection.get("extrapolation_reference"),
            "shear_model": spec.get("shear_model"),
            "reference_source": spec.get("reference_source"),
            "ltc_algorithm": spec.get("ltc_algorithm"),
        },
        metrics=_collect_metrics(state, scenario_record),
        admissible=report.admissible,
        gate_status={gate.name: gate.status for gate in report.gates},
        gate_values={gate.name: gate.value for gate in report.gates},
        gate_details={gate.name: gate.detail for gate in report.gates},
        failures=report.failures,
        warnings=report.warnings,
        marks=report.marks,
    )


def failed_result(spec_record: dict[str, Any], prefix: str, stage: str, message: str) -> ScenarioResult:
    """Record a scenario that could not run at all.

    Failures are rows, not omissions. A sweep that silently drops what it could not
    compute reports a spread over a set nobody can enumerate.
    """
    selection = spec_record.get("sensor_selection", {})
    return ScenarioResult(
        config_hash=_stable_hash({"prefix": prefix, "spec": spec_record}),
        fixed_prefix_hash=prefix,
        axes={
            "shear_fit_policy": selection.get("shear_fit"),
            "reference_policy": selection.get("extrapolation_reference"),
            "shear_model": spec_record.get("shear_model"),
            "reference_source": spec_record.get("reference_source"),
            "ltc_algorithm": spec_record.get("ltc_algorithm"),
        },
        metrics={column: None for column in METRIC_COLUMNS},
        admissible=False,
        status="failed",
        failures=[f"stage:{stage}"],
        error=message,
    )


def scenario_runconfig(
    state: Any,
    scenario_record: dict[str, Any],
    result: ScenarioResult,
    thresholds: GateThresholds,
) -> dict[str, Any]:
    """Build the complete, materialised runconfig for one scenario (design doc §7.13).

    Materialised rather than a diff: policies appear as names *and* as the sensors they
    resolved to, so the file stays interpretable if the resolver's behaviour later changes.
    Carries the fixed-prefix identity and the admissibility thresholds in force, so a
    result's pass/fail can be re-derived rather than trusted.
    """
    config = dict(state.to_runconfig())
    config["scenario"] = {
        "config_hash": result.config_hash,
        "fixed_prefix_hash": result.fixed_prefix_hash,
        **scenario_record.get("spec", {}),
        "sensor_selection_resolved": scenario_record.get("sensor_selection", {}),
        "stages": scenario_record.get("stages", {}),
    }
    config["admissibility"] = {
        "thresholds": thresholds.as_runconfig(),
        "result": {
            "admissible": result.admissible,
            "failures": result.failures,
            "warnings": result.warnings,
            "marks": result.marks,
            # Full records rather than bare statuses: the runconfig is what an analyst
            # takes away, and "failed" without the number it failed on is not auditable.
            "gates": [
                {
                    "name": name,
                    "status": status,
                    "value": result.gate_values.get(name),
                    "detail": result.gate_details.get(name, ""),
                }
                for name, status in sorted(result.gate_status.items())
            ],
        },
    }
    return config
