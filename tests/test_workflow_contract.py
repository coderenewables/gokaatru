"""Workflow-contract integrity — Step 1 of the logic audit.

The canvas DAG is the only place an analyst declares intent about *order*. These
tests pin what the executor actually guarantees, because every later audit step
assumes the pipeline it is auditing ran in the order the graph describes and on
data that was current when each stage ran.

Findings recorded here are workflow-integrity issues, not math errors: they let
correct math run on the wrong inputs.
"""
from __future__ import annotations

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from server.core.executor import WorkflowExecutionEdge, WorkflowExecutionNode, WorkflowExecutor
from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule
from server.tools.shear import _calculate_shear_timeseries
from tests.oracles import timestamp_index


def _node(node_id: str, template_id: str, status: str = "pending", **config: object) -> WorkflowExecutionNode:
    """Build one operation node as the API route builds it from the client payload."""
    return WorkflowExecutionNode(
        id=node_id,
        kind="operation",
        label=node_id,
        template_id=template_id,
        config=dict(config),
        status=status,
    )


def _drive(executor: WorkflowExecutor) -> list[dict[str, object]]:
    """Run one executor to completion and collect every emitted event."""

    async def consume() -> list[dict[str, object]]:
        return [event async for event in executor.execute_auto()]

    return asyncio.run(consume())


def _shear_state() -> SessionState:
    """Return a session holding an exact two-height power-law series (alpha = 0.20)."""
    index = timestamp_index("2021-01-01", periods=6 * 24 * 120, step_minutes=10)
    rng = np.random.default_rng(5)
    speed_100 = 6.0 + rng.gamma(shape=4.0, scale=1.0, size=len(index))
    heights = np.array([60.0, 100.0])
    state = SessionState()
    state.reset()
    frame = pd.DataFrame(
        {
            "Spd_60m": speed_100 * (heights[0] / heights[1]) ** 0.20,
            "Spd_100m": speed_100,
        },
        index=index,
    )
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    return state


# ---------------------------------------------------------------------------
# Ordering guarantees
# ---------------------------------------------------------------------------


def test_topological_order_is_respected_for_an_acyclic_graph():
    """A declared dependency must be honoured, and ties broken deterministically by id."""
    nodes = [_node("c", "list_cleaning_rules"), _node("a", "list_cleaning_rules"), _node("b", "list_cleaning_rules")]
    edges = [WorkflowExecutionEdge(source="a", target="b"), WorkflowExecutionEdge(source="b", target="c")]
    executor = WorkflowExecutor(SessionState(), nodes, edges)
    assert [node.id for node in executor._ordered_nodes()] == ["a", "b", "c"]


def test_cyclic_graph_is_refused_rather_than_reordered():
    """F-08 (MEDIUM) — FIXED. A dependency cycle now stops the run instead of reordering it.

    The bug: ``_ordered_nodes`` fell back to "continue execution in id order" when the
    topological sort could not consume every node. A cycle means the analyst declared an
    order that cannot be satisfied, so the numbers a run produced afterwards were keyed to an
    order nobody chose — and the run reported ``ok`` with the archived artifact recording no
    cycle at all.

    The sort still returns a deterministic order (callers inspect it), but the nodes caught
    in the cycle are recorded, and both ``execute_auto`` and ``execute_step`` refuse.
    """
    nodes = [_node("b", "list_cleaning_rules"), _node("a", "list_cleaning_rules")]
    edges = [WorkflowExecutionEdge(source="a", target="b"), WorkflowExecutionEdge(source="b", target="a")]
    executor = WorkflowExecutor(SessionState(), nodes, edges)

    ordered = executor._ordered_nodes()
    assert [node.id for node in ordered] == ["a", "b"]  # deterministic, but arbitrary
    assert executor._cycle_nodes == ["a", "b"]

    with pytest.raises(ValueError, match="dependency cycle"):
        _drive(executor)

    stepper = WorkflowExecutor(SessionState(), nodes, edges)
    with pytest.raises(ValueError, match="dependency cycle"):
        asyncio.run(stepper.execute_step())


def test_an_acyclic_graph_still_runs():
    """The cycle guard must not fire on an ordinary dependency chain."""
    nodes = [_node("b", "list_cleaning_rules"), _node("a", "list_cleaning_rules")]
    edges = [WorkflowExecutionEdge(source="a", target="b")]
    executor = WorkflowExecutor(SessionState(), nodes, edges)

    assert [node.id for node in executor._ordered_nodes()] == ["a", "b"]
    assert executor._cycle_nodes == []
    events = _drive(executor)
    assert events[-1]["status"] == "ok"
    assert not any(event["event_type"] == "node_failed" for event in events)


def test_edges_are_not_validated_against_the_data_dependency():
    """FINDING (Step 1): canvas edges are advisory; the real dependency is session state.

    Ordering comes only from the edges the browser sends. A node whose inputs are
    produced by another node still runs whenever the edges say so, and is caught
    only if the tool itself happens to check its own preconditions. Two nodes with
    a genuine data dependency but no edge between them run in id order.
    """
    nodes = [_node("z_producer", "list_cleaning_rules"), _node("a_consumer", "list_cleaning_rules")]
    executor = WorkflowExecutor(SessionState(), nodes, [])
    # No edges: the consumer runs first purely because "a" sorts before "z".
    assert [node.id for node in executor._ordered_nodes()] == ["a_consumer", "z_producer"]


def test_client_supplied_node_status_cannot_fabricate_completion():
    """F-10 (HIGH) — FIXED. Regression test: only the server can certify a node as done.

    The bug: ``_seed_runtime`` seeded ``node_statuses`` straight from the request body, and
    ``execute_auto`` skipped anything already ``done`` or ``skipped``. A node marked ``done``
    by the client was never executed, so a run could report success for a stage that never
    ran, and the server kept no authoritative record of what it had computed.

    The fix corroborates rather than refuses — stepping still needs the client to say where
    it got to, so a ``done`` is honoured only for nodes this session actually executed.
    Anything else is reset to pending and re-run, which is the safe direction.
    """
    state = SessionState()
    state.reset()
    # This tool raises without loaded data, so executing it fails loudly rather than
    # being silently skipped.
    claimed = _node(
        "shear",
        "calculate_shear_timeseries",
        status="done",
        height_sensors=json.dumps({"60": "Spd_60m", "100": "Spd_100m"}),
    )
    events = _drive(WorkflowExecutor(state, [claimed], []))

    assert any(event["event_type"] == "node_failed" for event in events)
    assert events[-1]["status"] == "error"
    assert state.workflow_execution["unverified_completions"] == ["shear"]


def test_a_verified_completion_is_still_skipped():
    """The counterpart: once the server has run a node, a later `done` claim is trusted."""
    state = SessionState()
    state.reset()
    node = _node("rules", "list_cleaning_rules")
    _drive(WorkflowExecutor(state, [node], []))
    assert state.executed_nodes == {"rules"}

    events = _drive(WorkflowExecutor(state, [_node("rules", "list_cleaning_rules", status="done")], []))
    assert not any(event["event_type"] == "node_started" for event in events)
    assert state.workflow_execution["unverified_completions"] == []


def test_a_node_that_actually_runs_without_its_input_fails_loudly():
    """The counterpart: when a precondition-checking tool does run early, it raises."""
    state = SessionState()
    state.reset()
    node = _node(
        "shear",
        "calculate_shear_timeseries",
        status="pending",
        height_sensors=json.dumps({"60": "Spd_60m", "100": "Spd_100m"}),
    )
    events = _drive(WorkflowExecutor(state, [node], []))
    assert any(event["event_type"] == "node_failed" for event in events)


# ---------------------------------------------------------------------------
# Staleness: the hazard a long-lived mutable session creates
# ---------------------------------------------------------------------------


def test_cleaning_does_not_invalidate_a_shear_result_computed_before_it():
    """FINDING (Step 1, confirmed): upstream mutation leaves downstream artifacts stale.

    Shear is computed, then a cleaning rule removes a large share of the records
    it was computed from. ``state.shear_timeseries_df`` is untouched and carries no
    marker of the data version it was derived from, so a later extrapolation node
    uses a shear distribution that describes data no longer in the session. Nothing
    warns, and the archived run records both stages as ``done``.
    """
    state = _shear_state()
    height_sensors = json.dumps({"60": "Spd_60m", "100": "Spd_100m"})

    _calculate_shear_timeseries(state, height_sensors)
    before = state.shear_timeseries_df
    assert before is not None
    records_before = int(len(before.dropna()))
    mean_alpha_before = float(before.iloc[:, 0].dropna().mean())

    # Remove the upper half of the speed distribution — a drastic but legal filter.
    result = _apply_cleaning_rule(state, "range_check", "Spd_100m", json.dumps({"min": 0.0, "max": 9.0}))
    assert int(result["records_affected"]) > 0

    after = state.shear_timeseries_df
    assert after is before  # still not silently recomputed...
    assert int(len(after.dropna())) == records_before
    assert float(after.iloc[:, 0].dropna().mean()) == pytest.approx(mean_alpha_before)

    # ...but it is now flagged as no longer matching the measured data.
    assert state.derived_is_stale("shear_timeseries")
    report = state.staleness_report()
    assert "shear_timeseries" in report["stale_artifacts"]
    assert "warning" in report

    # Recomputing on the cleaned data gives a different answer, so the stale value mattered.
    _calculate_shear_timeseries(state, height_sensors)
    recomputed = state.shear_timeseries_df
    assert recomputed is not None
    assert int(len(recomputed.dropna())) < records_before

    # Recomputing on the current data clears the flag.
    state.stamp_derived("shear_timeseries")
    assert not state.derived_is_stale("shear_timeseries")


def test_undoing_a_cleaning_rule_silently_deletes_the_hub_height_column():
    """FINDING (Step 1, confirmed): undo rebuilds the working frame from raw and drops derived columns.

    ``extrapolation`` writes its results *into* ``state.timeseries_df`` as new
    columns (``Spd_<hub>m_hub``, ``shear_coefficient``). ``_undo_cleaning_rule``
    rebuilds the frame from ``state.raw_timeseries_df``, which only ``data_io``
    ever writes and which therefore never holds those derived columns. So undoing
    any cleaning rule deletes the hub-height series.

    The dangerous part was the asymmetry: ``ltc_results``, ``ensemble_df`` and
    ``latest_uncertainty`` survived untouched, so the session kept reporting long-term
    numbers derived from a hub-height column that no longer existed.

    Undo still rebuilds from raw — that is its job — but it now reports the derived columns
    it removed and bumps the data version, so everything downstream is flagged stale.
    """
    from server.tools.extrapolation import _extrapolate_to_hub_height
    from server.tools.cleaning import _undo_cleaning_rule
    from server.tools.shear import _build_shear_table

    state = _shear_state()
    state.sensor_mapping = {
        60.0: {"speed_col": "Spd_60m", "direction_col": None},
        100.0: {"speed_col": "Spd_100m", "direction_col": None},
    }
    _calculate_shear_timeseries(state, json.dumps({"60": "Spd_60m", "100": "Spd_100m"}))
    _build_shear_table(state)
    _apply_cleaning_rule(state, "range_check", "Spd_100m", json.dumps({"min": 0.0, "max": 40.0}))

    hub = _extrapolate_to_hub_height(state, 120.0, "power_law")
    hub_column = str(hub["column_name"])
    assert hub_column in state.timeseries_df.columns
    assert hub_column not in state.raw_timeseries_df.columns

    # Stand in for downstream long-term results that were derived from the hub column.
    state.ltc_results["linear_least_squares"] = {"metrics": {"r_squared": 0.91}, "df": pd.DataFrame()}

    result = _undo_cleaning_rule(state, 0)

    assert hub_column not in state.timeseries_df.columns  # still removed...
    # ...but no longer silently: the response names it.
    assert hub_column in result["dropped_columns"]
    assert "warning" in result

    # Everything derived from it survives in state, and is flagged as stale.
    assert "linear_least_squares" in state.ltc_results
    assert state.shear_timeseries_df is not None
    assert "hub_height_series" in result["stale_artifacts"]


def test_every_derived_artifact_now_tracks_the_data_version_it_was_built_from():
    """F-11 — FIXED. Regression test: derived artifacts must be stamped and comparable.

    Before the fix, ``reanalysis_cache_identity`` was the *only* artifact that tracked what
    it was built from. Shear tables, LTC results, the ensemble and the uncertainty result
    had no equivalent, which is why cleaning could silently invalidate all of them.

    A monotonic ``data_version`` on the session is bumped by every mutation of the measured
    working data, and each derived artifact records the version it was built from, so any
    consumer can compare.
    """
    state = SessionState()
    state.reset()

    assert state.data_version == 0
    assert state.derived_versions == {}
    assert state.stale_artifacts() == []

    state.stamp_derived("shear_table")
    assert not state.derived_is_stale("shear_table")

    state.bump_data_version()
    assert state.data_version == 1
    assert state.derived_is_stale("shear_table")
    assert state.stale_artifacts() == ["shear_table"]

    report = state.staleness_report()
    assert report["data_version"] == 1
    assert report["stale_artifacts"] == ["shear_table"]
    assert "warning" in report

    # Recomputing clears it.
    state.stamp_derived("shear_table")
    assert state.stale_artifacts() == []
    assert "warning" not in state.staleness_report()
