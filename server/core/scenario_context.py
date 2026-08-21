"""scenario_context — run one scenario without disturbing the session it came from.

Every analysis tool reads and writes one long-lived ``SessionState``: cleaning rewrites
``timeseries_df`` in place, extrapolation appends a hub column to it, the shear stage
replaces ``shear_table``, and the LTC stage accumulates into ``ltc_results``. That is
fine for a single interactive analysis and fatal for a sweep — the second scenario would
inherit and overwrite the first's derived state, so nothing could be compared and the
"spread" would be an artefact of execution order (design doc §7.2).

**The fork policy is explicit, not a deep copy of everything.**
``copy.deepcopy(state)`` would be correct and unaffordable: the measured timeseries plus
four ERA5 nodes, four MERRA-2 nodes and two interpolated site series run to tens of
megabytes, and a sweep has thousands of leaves. So each field is classified:

``SHARED``
    Inputs a scenario reads and never writes — the sensor inventory, the cleaning log,
    the raw timeseries, the node lists. Passed by reference. If a scenario ever writes
    to one of these it is a bug in that tool, not a reason to copy it here.

``FORKED``
    Frames a scenario demonstrably mutates. ``timeseries_df`` gains a hub column and a
    shear column; the reanalysis frames gain a hub column whose values depend on the
    scenario's own shear table. These are copied.

``RESET``
    Derived outputs that must start empty so a scenario cannot read a sibling's result
    and mistake it for its own.

The classification is asserted against ``SessionState.reset()`` in the tests, so a field
added to the session without being classified here fails loudly rather than silently
defaulting to shared.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from typing import Any, Iterator

from server.state.session import SessionState, bind_session

#: Read-only inputs, passed by reference. Copying these is the whole cost of a fork.
SHARED_FIELDS: tuple[str, ...] = (
    "session_id",
    "workspace_dir",
    "created_at",
    "updated_at",
    "project_name",
    "coordinate",
    "measurement_type",
    "hub_height_m",
    "raw_timeseries_df",
    "sensor_mapping",
    "sensor_inventory",
    "cleaning_log",
    "brighthub_token",
    "era5_nodes",
    "merra_nodes",
    "reanalysis_cache_identity",
    "timezone",
    "windkit_data",
    "scenarios",
    "workflow_runs",
    "data_version",
)

#: Frames a scenario writes into, so each needs its own copy.
FORKED_FIELDS: tuple[str, ...] = (
    "timeseries_df",
    "era5_data",
    "merra_data",
    "reanalysis_interpolated",
)

#: Derived outputs, cleared so a scenario starts from nothing.
RESET_FIELDS: tuple[str, ...] = (
    "shear_timeseries_df",
    "shear_clamp_stats",
    "roughness_timeseries_df",
    "roughness_clip_stats",
    "shear_table",
    "roughness_table",
    "ltc_results",
    "ensemble_df",
    "clipping_result",
    "ltc_matching_disclosure",
    "latest_uncertainty",
    "derived_versions",
    "executed_nodes",
    "workflow_execution",
)

#: Handled explicitly rather than by category.
_EXPLICIT_FIELDS: tuple[str, ...] = (
    "runconfig",
    "active_reference_source",
    "persist_result_files",
)


def classified_fields() -> set[str]:
    """Return every field this module classifies, for the coverage assertion in tests."""
    return set(SHARED_FIELDS) | set(FORKED_FIELDS) | set(RESET_FIELDS) | set(_EXPLICIT_FIELDS)


def _fork_value(value: Any) -> Any:
    """Copy one mutable analysis artefact, shallowly where its members are themselves frames."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: _fork_value(item) for key, item in value.items()}
    copy_method = getattr(value, "copy", None)
    if callable(copy_method):
        try:
            return copy_method(deep=True)
        except TypeError:
            return copy_method()
    return copy.deepcopy(value)


#: Derived artefacts produced by the shear stage. A leaf forked from a completed
#: prefix keeps these instead of rebuilding them, which is the whole point of grouping
#: leaves by prefix (design doc §5).
SHEAR_STAGE_FIELDS: tuple[str, ...] = (
    "shear_timeseries_df",
    "shear_clamp_stats",
    "roughness_timeseries_df",
    "roughness_clip_stats",
    "shear_table",
    "roughness_table",
)


def fork_state(
    base: SessionState,
    *,
    runconfig_overrides: dict[str, Any] | None = None,
    persist_result_files: bool = False,
    reference_source: str | None = None,
    keep_derived: tuple[str, ...] = (),
) -> SessionState:
    """Return an isolated ``SessionState`` for one scenario.

    ``persist_result_files`` defaults to False because the caller is a sweep: an LTC
    result over a 20-year hourly reference is ~10 MB and nothing reads the intermediate
    files. The in-memory results are unaffected.

    ``keep_derived`` names derived fields to carry over instead of clearing — used when
    forking a *leaf from a completed prefix*, so the shear table and hub series computed
    once are reused by every downstream LTC choice rather than recomputed per leaf.
    Every name must be a reset field; keeping something else would silently share state
    the fork exists to separate.
    """
    unknown = set(keep_derived) - set(RESET_FIELDS)
    if unknown:
        raise ValueError(f"keep_derived may only name reset fields; got {sorted(unknown)}")

    scenario = SessionState.__new__(SessionState)
    scenario.__dict__.clear()

    for name in SHARED_FIELDS:
        setattr(scenario, name, getattr(base, name))
    for name in FORKED_FIELDS:
        setattr(scenario, name, _fork_value(getattr(base, name)))

    # Reset by constructing a throwaway session rather than restating the empty values
    # here — that keeps the empty shapes in one place (`SessionState.reset`) and stops
    # this module drifting from it.
    blank = SessionState()
    kept = set(keep_derived)
    for name in RESET_FIELDS:
        if name in kept:
            setattr(scenario, name, _fork_value(getattr(base, name)))
        else:
            setattr(scenario, name, copy.deepcopy(getattr(blank, name)))

    scenario.runconfig = copy.deepcopy(base.runconfig)
    if runconfig_overrides:
        scenario.runconfig.update(copy.deepcopy(runconfig_overrides))
    scenario.active_reference_source = base.active_reference_source
    scenario.persist_result_files = bool(persist_result_files)
    if reference_source is not None:
        scenario.set_active_reference_source(reference_source)
    return scenario


@contextmanager
def scenario_context(
    base: SessionState,
    *,
    runconfig_overrides: dict[str, Any] | None = None,
    persist_result_files: bool = False,
    reference_source: str | None = None,
    keep_derived: tuple[str, ...] = (),
) -> Iterator[SessionState]:
    """Fork a scenario state and bind it for the duration of the block.

    Binding is what makes the MCP tools operate on the scenario: they reach state through
    the ``session`` proxy, which resolves through a ``ContextVar``. So a scenario runs the
    same code an interactive analysis does, against different state, with no tool needing
    to know a sweep is happening.

    The binding is per execution context, so scenarios can run concurrently in threads
    without seeing each other's state.
    """
    scenario = fork_state(
        base,
        runconfig_overrides=runconfig_overrides,
        persist_result_files=persist_result_files,
        reference_source=reference_source,
        keep_derived=keep_derived,
    )
    with bind_session(scenario):
        yield scenario


def fork_cost_bytes(base: SessionState) -> dict[str, int]:
    """Report what a fork of this session would copy, in bytes, per forked field.

    A sweep's practical limit is memory per concurrent worker, and that limit is set here
    rather than by the number of scenarios. Exposed so a sweep can size its pool against
    the real dataset instead of a guess.
    """
    costs: dict[str, int] = {}
    for name in FORKED_FIELDS:
        value = getattr(base, name, None)
        costs[name] = _nbytes(value)
    costs["total"] = sum(costs.values())
    return costs


def _nbytes(value: Any) -> int:
    """Best-effort in-memory size of a frame, or of a dict of frames."""
    if value is None:
        return 0
    if isinstance(value, dict):
        return sum(_nbytes(item) for item in value.values())
    usage = getattr(value, "memory_usage", None)
    if callable(usage):
        try:
            return int(usage(deep=True).sum())
        except TypeError:
            return int(usage().sum())
    return 0
