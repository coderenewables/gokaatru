"""sweep_analysis — decompose a sweep's spread across its axes (design doc §7.9).

This lived only in the browser (`frontend/src/lib/sweepAnalysis.ts`), which meant the
question the Analysis Engine exists to answer — *which methodological choice actually
moved the number* — was computable only inside the Interrogate page. Nothing server-side
could answer it, so the Copilot had no tool to reach for and, asked about a spread,
answered from the live session state it could see instead of saying it could not see the
sweep at all.

It now lives here, and the TypeScript copy is deleted rather than mirrored: two
implementations of the same statistic drift, and a drift in *this* statistic is invisible
because both answers look plausible.

The decomposition is one-way between-group variance per axis, normalised so the shares
sum to 1. It is **first-order**: it attributes nothing to interactions, so the shares
describe main effects and will not account for the whole spread where axes interact.
Reported rather than hidden, because §8.1 sizes the uncertainty substitution from these
shares and a reader has to know what they do and do not cover.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

#: The five scenario axes, in design-doc order (A1, A2, B, C, D).
AXIS_COLUMNS: tuple[str, ...] = (
    "shear_fit_policy",
    "reference_policy",
    "shear_model",
    "reference_source",
    "ltc_algorithm",
)

#: A level that never varied cannot explain variance — its group mean *is* the grand
#: mean, so its between-group sum of squares is exactly zero. That reads identically to
#: "this choice was tested and did not matter", which is a different and much stronger
#: claim, so the level count travels with every share.
SINGLE_LEVEL_NOTE = (
    "An axis with one level has no share by construction: it was not varied in this "
    "sweep, which is not the same as having been varied and found not to matter."
)


#: The axes a duplicate can differ on: two leaves are duplicates when their sensor
#: policies resolve to the same columns, so only the policy names can disagree.
POLICY_AXES: tuple[str, ...] = ("shear_fit_policy", "reference_policy")

DUPLICATE_LEVEL_NOTE = (
    "A level listed under duplicate_levels resolved to the same sensors as the level it "
    "names, so its scenarios were not run again and carry that level's results. It was "
    "varied and gave identical numbers; it was not left out."
)


def duplicate_levels(
    rows: Sequence[dict[str, Any]], duplicates: Iterable[dict[str, Any]]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Map each policy level a sweep skipped as a duplicate to the level whose rows it shares.

    Without this, a level whose every leaf was a duplicate has no rows, so it reads as a
    level that was never designed, and an axis can read as single-level ("not varied")
    when it was varied and found identical. A duplicate whose ``same_as`` row is not in
    ``rows`` (filtered out, or inadmissible) is not counted: its results are not in view.
    """
    by_hash = {str(row.get("config_hash")): row for row in rows}
    found: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in duplicates:
        kept = by_hash.get(str(entry.get("same_as")))
        if kept is None:
            continue
        for axis in POLICY_AXES:
            skipped_level, kept_level = entry.get(axis), kept.get(axis)
            if skipped_level is None or kept_level is None or skipped_level == kept_level:
                continue
            record = found.setdefault(axis, {}).setdefault(
                str(skipped_level), {"same_as": set(), "scenarios": 0}
            )
            record["same_as"].add(str(kept_level))
            record["scenarios"] += 1
    return {
        axis: {
            level: {"same_as": sorted(record["same_as"]), "scenarios": record["scenarios"]}
            for level, record in sorted(levels.items())
        }
        for axis, levels in found.items()
    }


def _metric_value(row: dict[str, Any], metric: str) -> float | None:
    """Return a row's metric as a finite float, or None when it cannot enter a statistic."""
    value = row.get(metric)
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def admissible_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only scenarios the gates admitted; an excluded one stays in the table but
    never enters a statistic."""
    return [row for row in rows if row.get("admissible")]


def decompose_variance(
    rows: Sequence[dict[str, Any]], metric: str
) -> list[dict[str, Any]]:
    """Attribute the variance of *metric* to each axis, most-explanatory first.

    Returns one entry per axis — including axes that explain nothing, because an absent
    row and a zero share are different findings.
    """
    usable = [row for row in rows if _metric_value(row, metric) is not None]
    if len(usable) < 2:
        return []

    values = [_metric_value(row, metric) for row in usable]
    grand_mean = sum(values) / len(values)  # type: ignore[arg-type]

    raw: list[dict[str, Any]] = []
    for axis in AXIS_COLUMNS:
        groups: dict[str, list[float]] = {}
        for row in usable:
            level = str(row.get(axis) if row.get(axis) is not None else "—")
            groups.setdefault(level, []).append(_metric_value(row, metric))  # type: ignore[arg-type]

        level_means = sorted(
            (
                {
                    "level": level,
                    "mean": sum(group) / len(group),
                    "count": len(group),
                }
                for level, group in groups.items()
            ),
            key=lambda entry: entry["mean"],
            reverse=True,
        )
        between = sum(
            entry["count"] * (entry["mean"] - grand_mean) ** 2 for entry in level_means
        )
        swing = (
            0.0 if len(level_means) < 2 else level_means[0]["mean"] - level_means[-1]["mean"]
        )
        raw.append(
            {
                "axis": axis,
                "levels": len(groups),
                "share": 0.0,
                "swing": swing,
                "level_means": level_means,
                "_between": between,
            }
        )

    total = sum(entry["_between"] for entry in raw)
    for entry in raw:
        entry["share"] = 0.0 if total == 0 else entry.pop("_between") / total
        entry.pop("_between", None)
    return sorted(raw, key=lambda entry: entry["share"], reverse=True)


#: The sweep's empirical uncertainty is read off the answer itself, the long-term mean
#: speed. The browser copy used the swing of ``total_uncertainty_pct``, which is a spread
#: of the uncertainty figure rather than of the answer (F9).
SUBSTITUTION_METRIC = "long_term_mean_speed_mps"

#: Below this many levels an axis's spread is a range across one or two points, not a
#: dispersion estimate, so it can neither displace a parametric term nor add one.
MIN_LEVELS_FOR_EMPIRICAL = 3

#: (component, parametric column, axes that measure it, treatment). "substitute" takes
#: max(parametric, empirical) per scenario; "add" has no parametric counterpart (two
#: independent references disagreeing is carried nowhere else in the model).
SUBSTITUTION_RULES: tuple[tuple[str, str | None, tuple[str, ...], str], ...] = (
    ("mcp", "u_mcp_pct", ("ltc_algorithm",), "substitute"),
    (
        "vertical_extrapolation",
        "u_vertical_pct",
        ("shear_fit_policy", "reference_policy", "shear_model"),
        "substitute",
    ),
    ("long_term_reference", None, ("reference_source",), "add"),
)

#: Parametric terms the sweep has no axis for; they enter every total unchanged.
PARAMETRIC_ONLY: tuple[tuple[str, str], ...] = (
    ("measurement", "u_measurement_pct"),
    ("future_variability", "u_future_pct"),
)

SUBSTITUTION_NOTE = (
    "Each axis's empirical spread is the sample standard deviation of the long-term mean "
    "speed across its level means, as a percentage of the sweep's mean speed. A component "
    "measured by several axes combines their spreads in quadrature. An axis needs at least "
    f"{MIN_LEVELS_FOR_EMPIRICAL} levels. Per scenario, max(parametric, empirical) replaces "
    "the MCP and vertical terms, the reference-source spread is added, and everything is "
    "combined in quadrature as the scenario's own total is. max() never reports less than "
    "the parametric model alone and is biased upward by design, and a narrow sweep gives a "
    "smaller empirical term, so read the totals beside the axis coverage."
)


def _axis_spread(rows: Sequence[dict[str, Any]], axis: str, grand_mean: float) -> dict[str, Any]:
    """Return an axis's level count and its level-mean spread, or None when under-resolved."""
    groups: dict[str, list[float]] = {}
    for row in rows:
        level = str(row.get(axis) if row.get(axis) is not None else "—")
        groups.setdefault(level, []).append(_metric_value(row, SUBSTITUTION_METRIC))  # type: ignore[arg-type]
    means = [sum(group) / len(group) for group in groups.values()]
    spread = None
    if len(means) >= MIN_LEVELS_FOR_EMPIRICAL and grand_mean > 0.0:
        centre = sum(means) / len(means)
        variance = sum((mean - centre) ** 2 for mean in means) / (len(means) - 1)
        spread = math.sqrt(variance) / grand_mean * 100.0
    return {"levels": len(means), "spread_pct": spread}


def _distribution(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "min": ordered[0],
        "median": median,
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def uncertainty_substitution(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fold the sweep's empirical spread into each scenario's uncertainty (design doc §8.1).

    The empirical terms are sweep-level constants computed from the rows given, so the
    caller's own row selection decides them; each scenario's total then combines them with
    its own parametric terms.
    """
    usable = [row for row in rows if _metric_value(row, SUBSTITUTION_METRIC) is not None]
    if len(usable) < 2:
        return {
            "available": False,
            "reason": f"At least two scenarios with {SUBSTITUTION_METRIC} are needed.",
            "metric": SUBSTITUTION_METRIC,
        }
    grand_mean = sum(_metric_value(row, SUBSTITUTION_METRIC) for row in usable) / len(usable)  # type: ignore[misc]
    axes = {axis: _axis_spread(usable, axis, grand_mean) for axis in AXIS_COLUMNS}

    components: list[dict[str, Any]] = []
    empirical_by_component: dict[str, float | None] = {}
    for name, column, axis_set, treatment in SUBSTITUTION_RULES:
        used = [axis for axis in axis_set if axes[axis]["spread_pct"] is not None]
        thin = [axis for axis in axis_set if axes[axis]["spread_pct"] is None and axes[axis]["levels"] >= 2]
        not_varied = [axis for axis in axis_set if axes[axis]["levels"] < 2]
        empirical = math.sqrt(sum(axes[axis]["spread_pct"] ** 2 for axis in used)) if used else None
        empirical_by_component[name] = empirical
        parametric_values = [
            value for value in (_metric_value(row, column) for row in usable) if value is not None
        ] if column else []
        parametric_mean = sum(parametric_values) / len(parametric_values) if parametric_values else None
        if treatment == "add":
            applied, basis = (empirical, "added") if empirical is not None else (None, "not_resolved")
        elif empirical is not None and (parametric_mean is None or empirical > parametric_mean):
            applied, basis = empirical, "empirical"
        else:
            applied, basis = parametric_mean, "parametric"
        components.append(
            {
                "component": name,
                "treatment": treatment,
                "axes": list(axis_set),
                "axes_used": used,
                "axes_under_resolved": thin,
                "axes_not_varied": not_varied,
                "parametric_mean_pct": parametric_mean,
                "empirical_pct": empirical,
                "applied_pct": applied,
                "basis": basis,
            }
        )

    parametric_totals: list[float] = []
    substituted_totals: list[float] = []
    missing = 0
    raised = 0
    for row in usable:
        own = {column: _metric_value(row, column) for column in (
            "u_measurement_pct", "u_vertical_pct", "u_mcp_pct", "u_future_pct"
        )}
        if any(value is None for value in own.values()):
            missing += 1
            continue
        base_terms = [own["u_measurement_pct"], own["u_vertical_pct"], own["u_mcp_pct"], own["u_future_pct"]]
        terms = [own["u_measurement_pct"], own["u_future_pct"]]
        for name, column, _axes, treatment in SUBSTITUTION_RULES:
            empirical = empirical_by_component[name]
            if treatment == "add":
                if empirical is not None:
                    terms.append(empirical)
            else:
                terms.append(own[column] if empirical is None else max(own[column], empirical))  # type: ignore[index, type-var]
        parametric_total = math.sqrt(sum(term**2 for term in base_terms))  # type: ignore[operator]
        substituted_total = math.sqrt(sum(term**2 for term in terms))  # type: ignore[operator]
        parametric_totals.append(parametric_total)
        substituted_totals.append(substituted_total)
        if substituted_total > parametric_total:
            raised += 1

    return {
        "available": True,
        "metric": SUBSTITUTION_METRIC,
        "statistic": "sample_std_of_level_means_pct_of_grand_mean",
        "min_levels": MIN_LEVELS_FOR_EMPIRICAL,
        "grand_mean": grand_mean,
        "axes": axes,
        "components": components,
        "parametric_only": [name for name, _column in PARAMETRIC_ONLY],
        "totals": {
            "scenarios": len(parametric_totals),
            "scenarios_missing_components": missing,
            "raised": raised,
            "parametric": _distribution(parametric_totals),
            "substituted": _distribution(substituted_totals),
            "combination": "quadrature",
        },
        "note": SUBSTITUTION_NOTE,
    }


def spread_summary(rows: Sequence[dict[str, Any]], metric: str) -> dict[str, Any]:
    """Summarise the metric's spread over the rows given, for a caller that cannot see
    the table itself — the Copilot's whole view of a sweep."""
    values = sorted(
        value for value in (_metric_value(row, metric) for row in rows) if value is not None
    )
    if not values:
        return {"count": 0}
    mean = sum(values) / len(values)
    variance = (
        0.0 if len(values) < 2
        else sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    )
    return {
        "count": len(values),
        "min": values[0],
        "max": values[-1],
        "mean": mean,
        "std": math.sqrt(variance),
        "range": values[-1] - values[0],
    }
