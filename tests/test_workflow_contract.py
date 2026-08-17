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


def test_cyclic_graph_executes_anyway_in_id_order():
    """FINDING (Step 1): a dependency cycle does not stop the run — it silently reorders it.

    ``_ordered_nodes`` falls back to "continue execution in id order" when the
    topological sort cannot consume every node. A cycle means the analyst declared
    an order that cannot be satisfied, so the numbers a run produces afterwards
    are keyed to an order nobody chose. The run reports ``ok`` and the archived
    artifact records no cycle. This should refuse.
    """
    nodes = [_node("b", "list_cleaning_rules"), _node("a", "list_cleaning_rules")]
    edges = [WorkflowExecutionEdge(source="a", target="b"), WorkflowExecutionEdge(source="b", target="a")]
    executor = WorkflowExecutor(SessionState(), nodes, edges)

    ordered = executor._ordered_nodes()
    assert [node.id for node in ordered] == ["a", "b"]  # id order, not dependency order

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


def test_client_supplied_node_status_can_skip_execution():
    """FINDING (Step 1): the browser decides which nodes are already done.

    ``_seed_runtime`` seeds ``node_statuses`` from ``node.status``, which the API
    route copies straight out of the request body, and ``execute_auto`` skips any
    node already ``done`` or ``skipped``. A node marked ``done`` by the client is
    never executed, so a run can report success for a stage that never ran. The
    server keeps no authoritative record of what it actually computed.
    """
    state = SessionState()
    state.reset()
    # This tool raises without loaded data, so executing it would fail loudly.
    would_fail = _node(
        "shear",
        "calculate_shear_timeseries",
        status="done",
        height_sensors=json.dumps({"60": "Spd_60m", "100": "Spd_100m"}),
    )
    events = _drive(WorkflowExecutor(state, [would_fail], []))

    assert not any(event["event_type"] == "node_failed" for event in events)
    assert events[-1]["status"] == "ok"
    assert state.shear_timeseries_df is None  # nothing was computed
    assert state.workflow_execution["node_statuses"]["shear"] == "done"


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
    assert after is before  # same object, never recomputed or invalidated
    assert int(len(after.dropna())) == records_before
    assert float(after.iloc[:, 0].dropna().mean()) == pytest.approx(mean_alpha_before)

    # Recomputing on the cleaned data gives a different answer, so the stale value mattered.
    _calculate_shear_timeseries(state, height_sensors)
    recomputed = state.shear_timeseries_df
    assert recomputed is not None
    assert int(len(recomputed.dropna())) < records_before

    # And no cache-identity field exists that a consumer could check.
    assert not hasattr(state, "shear_data_version")
    assert "data_version" not in {str(key) for key in state.runconfig}


def test_undoing_a_cleaning_rule_silently_deletes_the_hub_height_column():
    """FINDING (Step 1, confirmed): undo rebuilds the working frame from raw and drops derived columns.

    ``extrapolation`` writes its results *into* ``state.timeseries_df`` as new
    columns (``Spd_<hub>m_hub``, ``shear_coefficient``). ``_undo_cleaning_rule``
    rebuilds the frame from ``state.raw_timeseries_df``, which only ``data_io``
    ever writes and which therefore never holds those derived columns. So undoing
    any cleaning rule deletes the hub-height series.

    The dangerous part is the asymmetry: ``ltc_results``, ``ensemble_df`` and
    ``latest_uncertainty`` survive untouched, so the session keeps reporting
    long-term numbers derived from a hub-height column that no longer exists and
    can no longer be reproduced or checked.
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

    _undo_cleaning_rule(state, 0)

    assert hub_column not in state.timeseries_df.columns  # silently gone
    assert "shear_coefficient" not in state.timeseries_df.columns
    # ...while everything derived from it is still presented as current.
    assert "linear_least_squares" in state.ltc_results
    assert state.shear_timeseries_df is not None


def test_reanalysis_is_the_only_stage_with_a_cache_identity_guard():
    """Establish the baseline: exactly one derived artifact tracks what it was built from.

    ``reanalysis_cache_identity`` exists for reanalysis. Shear tables, LTC results,
    the ensemble and the uncertainty result have no equivalent, which is why the
    staleness above goes undetected. Recorded so a fix can extend the existing
    pattern rather than invent a new one.
    """
    state = SessionState()
    state.reset()
    identity_fields = [name for name in vars(state) if "cache_identity" in name or name.endswith("_version")]
    assert identity_fields == ["reanalysis_cache_identity"]
