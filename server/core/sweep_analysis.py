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
