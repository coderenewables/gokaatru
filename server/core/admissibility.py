"""admissibility — decide whether a scenario's result may enter the reported spread.

This is what separates an analysis engine from a random-number generator (design doc
§7.7). A sweep that averages every combination it can construct reports the spread of
its own parameter grid, not of the site: combinations extrapolating three times past the
top sensor, or fitting a correction on four months of overlap, are arithmetic rather than
analysis, and including them widens the interval with noise that looks like uncertainty.

Gates are **two-tier**. ``warn`` keeps the scenario in the reported statistics and marks
it; ``fail`` excludes it. Both are reported either way, because a reader needs to see
what was excluded and why — a filtered set with no record of the filtering is not
auditable.

Two statuses are neither pass nor fail:

``not_applicable``
    The gate has nothing to measure here — a log-law scenario has no shear exponent, an
    unsectored one has no per-sector counts. Distinguished from ``pass`` so an absent
    check is never mistaken for a satisfied one.
``marked``
    The condition is not a defect but must stay visible, such as a shear exponent the
    analyst supplied rather than fitted.

Thresholds travel with the scenario rather than living as code defaults, so a result's
pass/fail can be re-derived later instead of trusted (design doc §7.7).

**There is deliberately no LTC R^2 gate.** There was one, and the first live-reanalysis
run showed it does not screen what it appears to (design doc §13.6). R^2 is the quantity
least squares *minimises by construction*, so ranking MCP estimators by it is circular:
measured on a real campaign, linear least squares scored 0.441 against total least squares
0.341 and variance ratio 0.330, and any threshold cutting between them removes the
non-least-squares methods regardless of whether they are wrong. Variance ratio deliberately
does not maximise R^2 — it matches the mean and standard deviation, which is precisely the
variance attenuation least squares suffers from and which `_variance_attenuation` exists to
report. Gating on R^2 therefore eliminates the methodological diversity axis D exists to
measure, and at any threshold that admits anything it collapses the sweep onto one corner
of the space.

`ltc_r_squared` remains a **reported metric** on every scenario row, and still feeds the
parametric `u_mcp` term through `derive_mcp_r_squared`. It is informative; it is just not
a basis for exclusion.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

PASS = "pass"
WARN = "warn"
FAIL = "fail"
NOT_APPLICABLE = "not_applicable"
MARKED = "marked"

#: Hours in an average month, for turning a concurrent-record count into months.
HOURS_PER_MONTH = 730.0


@dataclass(frozen=True)
class GateThresholds:
    """The numeric limits a sweep is judged against. Recorded per scenario (§7.13)."""

    extrapolation_ratio_warn: float = 1.5
    extrapolation_ratio_fail: float = 2.0

    concurrent_months_warn: float = 12.0
    concurrent_months_fail: float = 9.0

    sector_records_warn: int = 200
    sector_records_fail: int = 100

    # A *mean* alpha below zero is not physical for resource assessment; the upper bound
    # admits dense forest and urban terrain plus stability-skewed sites (design doc §7.7.1).
    mean_alpha_warn_low: float = 0.05
    mean_alpha_warn_high: float = 0.40
    mean_alpha_fail_low: float = 0.00
    mean_alpha_fail_high: float = 0.50

    # Individual month-hour cells legitimately sit higher than the site mean, so the
    # per-cell band is wider and the gate is on the *fraction* outside it.
    cell_alpha_low: float = 0.00
    cell_alpha_high: float = 0.60
    cell_outside_fraction_warn: float = 0.10
    cell_outside_fraction_fail: float = 0.25

    # A cell counts as observed only once it holds enough records to mean anything;
    # `_table_fill_report` counts a cell observed on one (design doc §7.7.2).
    min_records_per_cell: int = 30
    cell_coverage_warn: float = 0.90
    cell_coverage_fail: float = 0.75

    # Share of a roughness series that may sit on a clip bound. A clipped z0 carries no
    # information about the surface at all, and on a real 4-height mast 35% of records
    # land on a bound — so a log-law scenario can rest almost entirely on bounds while
    # passing every other gate, since the alpha gates do not apply to it.
    roughness_clip_warn: float = 0.05
    roughness_clip_fail: float = 0.25

    def as_runconfig(self) -> dict[str, Any]:
        """Return the thresholds as they are written into a scenario runconfig."""
        return asdict(self)


DEFAULT_THRESHOLDS = GateThresholds()


@dataclass(frozen=True)
class GateResult:
    """One gate's verdict, with the number it was reached on."""

    name: str
    status: str
    value: float | None = None
    detail: str = ""

    def as_record(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "value": self.value, "detail": self.detail}


@dataclass
class AdmissibilityReport:
    """Every gate's verdict for one scenario, and the admissibility that follows."""

    gates: list[GateResult] = field(default_factory=list)

    @property
    def admissible(self) -> bool:
        """Whether this scenario's result may enter the reported statistics."""
        return not any(gate.status == FAIL for gate in self.gates)

    @property
    def failures(self) -> list[str]:
        return [gate.name for gate in self.gates if gate.status == FAIL]

    @property
    def warnings(self) -> list[str]:
        return [gate.name for gate in self.gates if gate.status == WARN]

    @property
    def marks(self) -> list[str]:
        return [gate.name for gate in self.gates if gate.status == MARKED]

    def as_record(self) -> dict[str, Any]:
        return {
            "admissible": self.admissible,
            "failures": self.failures,
            "warnings": self.warnings,
            "marks": self.marks,
            "gates": [gate.as_record() for gate in self.gates],
        }


def _banded(value: float, warn_low: float, warn_high: float, fail_low: float, fail_high: float) -> str:
    """Classify a value against a warn band nested inside a fail band."""
    if value < fail_low or value > fail_high:
        return FAIL
    if value < warn_low or value > warn_high:
        return WARN
    return PASS


def _descending(value: float, warn_above: float, fail_above: float) -> str:
    """Classify a value where larger is worse."""
    if value > fail_above:
        return FAIL
    if value > warn_above:
        return WARN
    return PASS


def _ascending(value: float, warn_below: float, fail_below: float) -> str:
    """Classify a value where smaller is worse."""
    if value < fail_below:
        return FAIL
    if value < warn_below:
        return WARN
    return PASS


def observed_cell_fraction(
    shear_series: pd.DataFrame | None, min_records: int
) -> tuple[float | None, dict[str, Any]]:
    """Return the share of the 288 month-hour cells holding enough records to mean anything.

    `_table_fill_report` counts a cell observed on a single record, so a three-record cell
    is nominally observed and statistically meaningless (design doc §7.7.2). This applies a
    population floor instead.
    """
    if shear_series is None or "shear_coefficient" not in shear_series.columns:
        return None, {}
    valid = shear_series["shear_coefficient"].dropna()
    if valid.empty:
        return 0.0, {"cells_observed": 0, "cells_total": 288, "min_records_per_cell": min_records}
    counts = valid.groupby([valid.index.month, valid.index.hour]).size()
    observed = int((counts >= min_records).sum())
    return observed / 288.0, {
        "cells_observed": observed,
        "cells_total": 288,
        "min_records_per_cell": min_records,
        "median_records_per_cell": int(counts.median()) if len(counts) else 0,
    }


def _extrapolation_gate(stages: dict[str, Any], thresholds: GateThresholds) -> GateResult:
    detail = stages.get("extrapolate", {})
    ratio = detail.get("extrapolation_ratio")
    if not isinstance(ratio, dict) or ratio.get("max") is None:
        counts = detail.get("method_counts") or {}
        if counts.get("extrapolated", 0) == 0:
            return GateResult(
                "extrapolation_ratio",
                NOT_APPLICABLE,
                None,
                "hub height is bracketed by measurements, so nothing was extrapolated",
            )
        return GateResult("extrapolation_ratio", NOT_APPLICABLE, None, "no ratio was reported")
    worst = float(ratio["max"])
    status = _descending(worst, thresholds.extrapolation_ratio_warn, thresholds.extrapolation_ratio_fail)
    return GateResult(
        "extrapolation_ratio",
        status,
        worst,
        f"hub height is up to {worst:.2f}x the reference height used",
    )


def _concurrent_gate(state: Any, algorithm: str, thresholds: GateThresholds) -> GateResult:
    metrics = (state.ltc_results.get(algorithm) or {}).get("metrics") or {}
    points = metrics.get("concurrent_points")
    if not isinstance(points, (int, float)) or points <= 0:
        return GateResult("concurrent_period", NOT_APPLICABLE, None, "no concurrent_points recorded")
    months = float(points) / HOURS_PER_MONTH
    status = _ascending(months, thresholds.concurrent_months_warn, thresholds.concurrent_months_fail)
    return GateResult(
        "concurrent_period", status, months, f"{months:.1f} months of concurrent record"
    )


def _mean_alpha_gate(state: Any, stages: dict[str, Any], thresholds: GateThresholds) -> GateResult:
    if stages.get("build_shear", {}).get("method") == "log_law":
        return GateResult("mean_shear_alpha", NOT_APPLICABLE, None, "log-law scenario has no exponent")
    if state.shear_table is None:
        return GateResult("mean_shear_alpha", NOT_APPLICABLE, None, "no shear table was built")
    mean_alpha = float(np.nanmean(state.shear_table.to_numpy(dtype=float)))
    status = _banded(
        mean_alpha,
        thresholds.mean_alpha_warn_low,
        thresholds.mean_alpha_warn_high,
        thresholds.mean_alpha_fail_low,
        thresholds.mean_alpha_fail_high,
    )
    return GateResult("mean_shear_alpha", status, mean_alpha, f"table mean alpha {mean_alpha:.4f}")


def _alpha_dispersion_gate(state: Any, stages: dict[str, Any], thresholds: GateThresholds) -> GateResult:
    if stages.get("build_shear", {}).get("method") == "log_law" or state.shear_table is None:
        return GateResult("alpha_cell_dispersion", NOT_APPLICABLE, None, "no shear table to inspect")
    values = state.shear_table.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return GateResult("alpha_cell_dispersion", NOT_APPLICABLE, None, "shear table holds no finite cell")
    outside = np.count_nonzero(
        (finite < thresholds.cell_alpha_low) | (finite > thresholds.cell_alpha_high)
    )
    fraction = float(outside) / float(finite.size)
    status = _descending(
        fraction, thresholds.cell_outside_fraction_warn, thresholds.cell_outside_fraction_fail
    )
    return GateResult(
        "alpha_cell_dispersion",
        status,
        fraction,
        f"{fraction:.1%} of cells outside "
        f"[{thresholds.cell_alpha_low:g}, {thresholds.cell_alpha_high:g}]",
    )


def _cell_coverage_gate(state: Any, stages: dict[str, Any], thresholds: GateThresholds) -> GateResult:
    if stages.get("build_shear", {}).get("shear_source") == "analyst_supplied":
        return GateResult(
            "shear_table_coverage",
            NOT_APPLICABLE,
            None,
            "a supplied exponent has no month-hour table to populate",
        )
    fraction, detail = observed_cell_fraction(
        getattr(state, "shear_timeseries_df", None), thresholds.min_records_per_cell
    )
    if fraction is None:
        return GateResult("shear_table_coverage", NOT_APPLICABLE, None, "no shear series to count")
    status = _ascending(fraction, thresholds.cell_coverage_warn, thresholds.cell_coverage_fail)
    observed = detail.get("cells_observed", 0)
    return GateResult(
        "shear_table_coverage",
        status,
        fraction,
        f"{observed}/288 cells hold at least "
        f"{thresholds.min_records_per_cell} records ({fraction:.0%})",
    )


def _sector_records_gate(stages: dict[str, Any], thresholds: GateThresholds) -> GateResult:
    counts = stages.get("build_shear", {}).get("sector_record_counts")
    if not counts:
        return GateResult(
            "sector_records",
            NOT_APPLICABLE,
            None,
            "scenario does not use a directional shear table",
        )
    worst = float(min(counts.values()))
    status = _ascending(worst, float(thresholds.sector_records_warn), float(thresholds.sector_records_fail))
    return GateResult("sector_records", status, worst, f"thinnest sector holds {int(worst)} records")


def _roughness_clip_gate(state: Any, stages: dict[str, Any], thresholds: GateThresholds) -> GateResult:
    """Judge how much of a log-law scenario's roughness series is a bound, not a fit.

    The power-law gates (`mean_shear_alpha`, `alpha_cell_dispersion`) are
    `not_applicable` for a log-law scenario, so without this one a log-law result passes
    with strictly fewer checks than its power-law sibling.
    """
    if stages.get("build_shear", {}).get("method") != "log_law":
        return GateResult(
            "roughness_clipping", NOT_APPLICABLE, None, "scenario does not use the log law"
        )
    stats = getattr(state, "roughness_clip_stats", None)
    if not isinstance(stats, dict) or not stats.get("records_used"):
        return GateResult("roughness_clipping", NOT_APPLICABLE, None, "no roughness series was built")
    fraction = float(stats.get("clipped_fraction", 0.0))
    status = _descending(fraction, thresholds.roughness_clip_warn, thresholds.roughness_clip_fail)
    return GateResult(
        "roughness_clipping",
        status,
        fraction,
        f"{fraction:.1%} of roughness records sit on a clip bound "
        f"({stats.get('records_clipped', 0):,} of {stats.get('records_used', 0):,})",
    )


def _shear_provenance_gate(stages: dict[str, Any]) -> GateResult:
    source = stages.get("build_shear", {}).get("shear_source")
    if source == "analyst_supplied":
        alpha = stages["build_shear"].get("alpha")
        return GateResult(
            "shear_provenance",
            MARKED,
            float(alpha) if isinstance(alpha, (int, float)) else None,
            "shear exponent was supplied by the analyst, not fitted from measurements",
        )
    return GateResult("shear_provenance", PASS, None, "shear exponent fitted from measurements")


def evaluate_gates(
    state: Any,
    scenario_record: dict[str, Any],
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> AdmissibilityReport:
    """Judge one completed scenario against every gate.

    ``scenario_record`` is what :func:`server.core.scenario_pipeline.run_scenario` returned;
    ``state`` is the scenario's own bound state, still holding its artefacts.
    """
    stages = scenario_record.get("stages", {})
    algorithm = str(scenario_record.get("spec", {}).get("ltc_algorithm", ""))
    return AdmissibilityReport(
        gates=[
            _extrapolation_gate(stages, thresholds),
            _concurrent_gate(state, algorithm, thresholds),
            _mean_alpha_gate(state, stages, thresholds),
            _alpha_dispersion_gate(state, stages, thresholds),
            _cell_coverage_gate(state, stages, thresholds),
            _roughness_clip_gate(state, stages, thresholds),
            _sector_records_gate(stages, thresholds),
            _shear_provenance_gate(stages),
        ]
    )
