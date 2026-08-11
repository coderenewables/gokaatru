"""test_executor_concurrency — Session isolation across concurrent workflow runs.

Part of GoKaatru MCP Server.

The executor used to bind the active session by mutating a module-level
`session` attribute on the tool module for the duration of each call.

Under a single asyncio loop that is safe: every tool function is synchronous,
so there is no await point between the set and the restore. It breaks as soon
as runs execute in *threads* — which is exactly what parallel sweep trials
require, because blocking tool functions give no parallelism on one loop.

Two distinct failures appear under threads:
  1. Runs observe each other's session (silently wrong numbers, no exception).
  2. The restore writes back a value captured during a race, so the module
     attribute is permanently left as a raw SessionState instead of the
     SessionProxy — corrupting every later call in the process, single
     threaded or not.

Binding through `bind_session()` (a ContextVar, which is per-thread) avoids
both. These tests pin that behaviour.
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import server.core.executor as executor_module
from server.core.executor import WorkflowExecutionNode, WorkflowExecutor
from server.state.session import SessionProxy, SessionState

THREAD_COUNT = 8


@pytest.fixture
def probe_tool(monkeypatch: pytest.MonkeyPatch):
    """Register a probe tool reporting which session the tool body observed."""
    import server.tools.ensemble as host_module

    def probe_session_identity(marker: str) -> dict:
        """Report, via the node summary message, which session the tool body saw."""
        del marker
        # Widen the interleaving window the way a real tool's work would.
        time.sleep(0.002)
        return {"status": "ok", "message": f"observed={host_module.session.session_id}"}

    probe_session_identity.__module__ = host_module.__name__
    monkeypatch.setattr(host_module, "probe_session_identity", probe_session_identity, raising=False)
    monkeypatch.setattr(executor_module, "_TOOL_REGISTRY", None, raising=False)
    yield host_module
    monkeypatch.setattr(executor_module, "_TOOL_REGISTRY", None, raising=False)


def _executor_for(session_id: str) -> WorkflowExecutor:
    """Build a single-node executor bound to a uniquely identifiable session."""
    state = SessionState()
    state.session_id = session_id
    node = WorkflowExecutionNode(
        id="probe",
        kind="operation",
        label="probe",
        template_id="probe_session_identity",
        config={"marker": session_id},
        status="pending",
    )
    return WorkflowExecutor(state, [node], [])


def _drive(executor: WorkflowExecutor) -> None:
    """Run one executor to completion on its own event loop, in the calling thread."""

    async def consume() -> None:
        async for _event in executor.execute_auto():
            pass

    asyncio.run(consume())


def _observed(executor: WorkflowExecutor) -> object:
    """Return the probe node's recorded summary for one executor."""
    return executor.state.workflow_execution["node_results"]["probe"]


def test_threaded_executors_do_not_share_session_binding(probe_tool) -> None:
    """Runs executing in parallel threads must each observe their own session."""
    executors = [_executor_for(f"session-{index}") for index in range(THREAD_COUNT)]

    with ThreadPoolExecutor(max_workers=THREAD_COUNT) as pool:
        list(pool.map(_drive, executors))

    leaks = [
        f"session-{index} observed {_observed(executor)}"
        for index, executor in enumerate(executors)
        if _observed(executor) != f"observed=session-{index}"
    ]
    assert not leaks, f"session leaked across concurrent runs: {leaks}"


def test_module_session_attribute_survives_concurrent_runs(probe_tool) -> None:
    """The tool module must still expose the SessionProxy after parallel runs."""
    executors = [_executor_for(f"session-{index}") for index in range(THREAD_COUNT)]

    with ThreadPoolExecutor(max_workers=THREAD_COUNT) as pool:
        list(pool.map(_drive, executors))

    assert isinstance(probe_tool.session, SessionProxy), (
        "tool module `session` was left as a raw SessionState; later calls in this "
        "process would read the wrong session even without concurrency"
    )


def test_single_run_still_binds_correct_session(probe_tool) -> None:
    """A lone run must keep observing its own session (no behaviour change)."""
    executor = _executor_for("solo-session")

    _drive(executor)

    assert _observed(executor) == "observed=solo-session"
