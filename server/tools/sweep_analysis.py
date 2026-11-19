"""sweep_analysis — MCP surface for reading and explaining a scenario sweep.

Part of GoKaatru MCP Server.

The sweep engine was HTTP-only, so the Copilot had no tool that could see a sweep at all.
Asked "why is the LTC method the only contributor to the spread?", it answered from the
live session state it *could* read — where the sweep leaves no trace, because each one
runs in a forked context that never writes back — and produced a confident, entirely
fabricated explanation about the spread between anemometers. For a tool aimed at bankable
analysis that is the worst available failure mode: not a refusal, an invention.

These three tools close that gap. They are pure reads of the session's own persisted
sweep files, through the path-confined ``_sweep_dir``; they mutate nothing and reach no
network. Paired one-for-one with ``GET /sessions/{id}/sweep``,
``GET /sessions/{id}/sweep/{sweep_id}`` and ``POST /sessions/{id}/sweep/{sweep_id}/spread``.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from server.core.sweep_analysis import (
    AXIS_COLUMNS,
    DUPLICATE_LEVEL_NOTE,
    SINGLE_LEVEL_NOTE,
    admissible_rows,
    decompose_variance,
    duplicate_levels,
    spread_summary,
    uncertainty_substitution,
)
from server.main import mcp
from server.operations import operation
from server.state.session import SessionState, session

#: Rows are wide and a sweep can hold hundreds of them, so a summary is returned by
#: default rather than the table. A caller that wants the table has the HTTP route.
MAX_ROWS_RETURNED = 50


def _rows_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the scenario rows from a loaded sweep, whatever shape it was stored in."""
    results = payload.get("results")
    if isinstance(results, list):
        return [row for row in results if isinstance(row, dict)]
    if isinstance(results, dict):
        for key in ("rows", "results", "scenarios"):
            candidate = results.get(key)
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
    return []


def _list_sweeps(state: SessionState) -> dict:
    """List every persisted sweep in this session."""
    from server.core.sweep import list_sweeps

    return {"sweeps": list_sweeps(state)}


def _sweep_summary(state: SessionState, sweep_id: str) -> dict:
    """Summarise one sweep: what varied, what the gates rejected, and why."""
    from server.core.sweep import load_sweep

    payload = load_sweep(state, sweep_id)
    manifest = payload.get("manifest") or {}
    rows = _rows_of(payload)
    good = admissible_rows(rows)
    duplicates = manifest.get("duplicates_skipped") or []
    dup_all = duplicate_levels(rows, duplicates)
    dup_good = duplicate_levels(good, duplicates)

    axes: dict[str, Any] = {}
    for axis in AXIS_COLUMNS:
        designed = sorted(
            {str(row.get(axis)) for row in rows if row.get(axis) is not None}
            | set(dup_all.get(axis, {}))
        )
        surviving = sorted({str(row.get(axis)) for row in good if row.get(axis) is not None})
        axes[axis] = {
            "levels_designed": designed,
            "levels_admissible": surviving,
            # A duplicate level has no rows of its own, so it is not in levels_admissible;
            # it is listed here with the admissible level whose results it shares.
            "duplicate_levels": dup_good.get(axis, {}),
            "collapsed_to_one_level": len(surviving) < 2,
        }

    failed: Counter[str] = Counter()
    for row in rows:
        if row.get("admissible"):
            continue
        gates = row.get("failed_gates")
        if isinstance(gates, str) and gates.strip():
            failed.update(part.strip() for part in gates.split(",") if part.strip())
        elif isinstance(gates, list):
            failed.update(str(part) for part in gates)

    return {
        "sweep_id": sweep_id,
        "fixed_prefix_hash": (payload.get("manifest") or {}).get("fixed_prefix_hash"),
        # Absent on sweeps stored before the version was stamped; None, not an error.
        "engine_version": (payload.get("manifest") or {}).get("engine_version"),
        "scenarios_total": len(rows),
        "scenarios_admissible": len(good),
        "duplicates_skipped": len(duplicates),
        "axes": axes,
        "gate_failures": dict(failed.most_common()),
        "note": SINGLE_LEVEL_NOTE,
        "duplicate_note": DUPLICATE_LEVEL_NOTE,
    }


def _sweep_spread(
    state: SessionState,
    sweep_id: str,
    metric: str = "long_term_mean_speed_mps",
    config_hashes: list[str] | None = None,
) -> dict:
    """Decompose a sweep metric's variance across the five axes."""
    from server.core.sweep import load_sweep

    payload = load_sweep(state, sweep_id)
    rows = admissible_rows(_rows_of(payload))
    if config_hashes is not None:
        wanted = set(config_hashes)
        rows = [row for row in rows if str(row.get("config_hash")) in wanted]

    contributions = decompose_variance(rows, metric)
    duplicates = duplicate_levels(
        rows, (payload.get("manifest") or {}).get("duplicates_skipped") or []
    )
    for entry in contributions:
        entry["duplicate_levels"] = duplicates.get(entry["axis"], {})
    collapsed = [entry["axis"] for entry in contributions if entry["levels"] < 2]
    return {
        "sweep_id": sweep_id,
        "metric": metric,
        "scenarios_analysed": len(rows),
        "contributions": contributions,
        "single_level_axes": collapsed,
        "basis": "first_order_between_group_variance",
        "basis_note": (
            "A first-order decomposition: it attributes nothing to interactions, so these "
            "shares describe main effects and will not account for the whole spread where "
            "axes interact."
        ),
        "single_level_note": SINGLE_LEVEL_NOTE,
        "duplicate_note": DUPLICATE_LEVEL_NOTE,
        "spread": spread_summary(rows, metric),
        "uncertainty_substitution": uncertainty_substitution(rows),
    }


@operation(effect="read", stage="sweep", canvas=False)
@mcp.tool()
def list_sweeps() -> dict:
    """List every scenario sweep persisted in the current session."""
    return _list_sweeps(session)


@operation(effect="read", stage="sweep", canvas=False)
@mcp.tool()
def get_sweep_summary(sweep_id: str) -> dict:
    """Summarise a sweep: which axes varied, which the gates collapsed, and why."""
    return _sweep_summary(session, sweep_id)


@operation(effect="read", stage="sweep", canvas=False)
@mcp.tool()
def analyze_sweep_spread(sweep_id: str, metric: str = "long_term_mean_speed_mps") -> dict:
    """Decompose a sweep metric's variance across the five scenario axes."""
    return _sweep_spread(session, sweep_id, metric)
