"""Scenario isolation — design doc §7.2.

Every analysis tool reads and writes one long-lived `SessionState`. Run two scenarios
against it in sequence and the second inherits and overwrites the first's derived
state, so the "spread" a sweep reports would be an artefact of execution order rather
than of methodology.

These tests pin the three properties that make a fork correct: shared inputs stay
shared (or the fork is unaffordable), mutated frames are genuinely isolated (or
scenarios corrupt each other), and derived slots start empty (or a scenario reads a
sibling's result and reports it as its own).
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.scenario_context import (
    FORKED_FIELDS,
    RESET_FIELDS,
    SHARED_FIELDS,
    classified_fields,
    fork_cost_bytes,
    fork_state,
    scenario_context,
)
from server.state.session import SessionState, get_active_session, session

INDEX = pd.date_range("2021-01-01", periods=500, freq="h", tz="UTC")


def _base_state() -> SessionState:
    rng = np.random.default_rng(9)
    frame = pd.DataFrame(
        {"Spd_80m": 8.0 + rng.normal(0, 1, len(INDEX)), "Spd_100m": 8.5 + rng.normal(0, 1, len(INDEX))},
        index=INDEX,
    )
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {
        80.0: {"speed_col": "Spd_80m", "dir_col": None},
        100.0: {"speed_col": "Spd_100m", "dir_col": None},
    }
    state.sensor_inventory = {"Spd_80m": {"height_m": 80.0, "sensor_type": "wind_speed"}}
    state.set_hub_height_m(120.0)
    state.era5_data = {"52.0_5.0": pd.DataFrame({"Spd_100m": np.full(len(INDEX), 9.0)}, index=INDEX)}
    state.merra_data = {"52.0_5.0": pd.DataFrame({"Spd_50m": np.full(len(INDEX), 8.0)}, index=INDEX)}
    state.reanalysis_interpolated = {
        "era5": pd.DataFrame({"Spd_100m": np.full(len(INDEX), 9.0)}, index=INDEX),
        "merra2": pd.DataFrame({"Spd_50m": np.full(len(INDEX), 8.0)}, index=INDEX),
    }
    return state


# ---------------------------------------------------------------------------
# The classification must stay complete
# ---------------------------------------------------------------------------


def test_every_session_field_is_classified():
    """A field added to SessionState must be classified, not silently default to shared.

    Defaulting to shared is the dangerous direction: a new mutable derived field would
    be passed by reference and scenarios would quietly corrupt each other.
    """
    fields = set(SessionState().__dict__)
    assert fields - classified_fields() == set(), "unclassified SessionState fields"
    assert classified_fields() - fields == set(), "classified fields that do not exist"


def test_the_three_categories_do_not_overlap():
    assert not set(SHARED_FIELDS) & set(FORKED_FIELDS)
    assert not set(SHARED_FIELDS) & set(RESET_FIELDS)
    assert not set(FORKED_FIELDS) & set(RESET_FIELDS)


# ---------------------------------------------------------------------------
# Sharing, forking, resetting
# ---------------------------------------------------------------------------


def test_read_only_inputs_are_shared_by_reference():
    """Copying these is the entire cost of a fork, and a scenario never writes them."""
    base = _base_state()
    scenario = fork_state(base)

    assert scenario.raw_timeseries_df is base.raw_timeseries_df
    assert scenario.sensor_inventory is base.sensor_inventory
    assert scenario.sensor_mapping is base.sensor_mapping
    assert scenario.cleaning_log is base.cleaning_log


def test_mutated_frames_are_isolated():
    """A scenario appending a hub column must not touch the base or its siblings."""
    base = _base_state()
    first = fork_state(base)
    second = fork_state(base)

    first.timeseries_df["Spd_120m_hub"] = 10.0
    first.era5_data["52.0_5.0"]["Spd_120m_hub"] = 11.0
    first.reanalysis_interpolated["era5"]["Spd_120m_hub"] = 12.0

    assert "Spd_120m_hub" not in base.timeseries_df.columns
    assert "Spd_120m_hub" not in second.timeseries_df.columns
    assert "Spd_120m_hub" not in base.era5_data["52.0_5.0"].columns
    assert "Spd_120m_hub" not in second.era5_data["52.0_5.0"].columns
    assert "Spd_120m_hub" not in base.reanalysis_interpolated["era5"].columns
    assert "Spd_120m_hub" not in second.reanalysis_interpolated["era5"].columns


def test_adding_a_reanalysis_node_does_not_leak_to_the_base():
    """The containers are forked too, not just the frames inside them."""
    base = _base_state()
    scenario = fork_state(base)
    scenario.era5_data["99.0_9.0"] = pd.DataFrame({"Spd_100m": [1.0]})
    assert "99.0_9.0" not in base.era5_data


def test_derived_outputs_start_empty():
    """A scenario must not be able to read a sibling's result and report it as its own."""
    base = _base_state()
    base.ltc_results = {"variance_ratio": {"df": pd.DataFrame(), "metrics": {"r_squared": 0.9}}}
    base.shear_table = pd.DataFrame(np.full((12, 24), 0.2))
    base.latest_uncertainty = {"total_uncertainty_pct": 5.0}

    scenario = fork_state(base)

    assert scenario.ltc_results == {}
    assert scenario.shear_table is None
    assert scenario.latest_uncertainty is None
    assert scenario.derived_versions == {}
    # The base keeps its own results.
    assert "variance_ratio" in base.ltc_results


def test_runconfig_overrides_apply_to_the_scenario_only():
    base = _base_state()
    base.runconfig["shear_aggregation"] = "mean"

    scenario = fork_state(base, runconfig_overrides={"shear_aggregation": "momm"})

    assert scenario.runconfig["shear_aggregation"] == "momm"
    assert base.runconfig["shear_aggregation"] == "mean"
    # Inherited keys survive the override.
    assert scenario.runconfig["hub_height_m"] == 120.0


def test_reference_source_can_be_selected_per_scenario():
    """Axis C is a per-scenario choice, so the fork must be able to set it."""
    base = _base_state()
    scenario = fork_state(base, reference_source="merra2")

    assert scenario.active_reference_source == "merra2"
    assert "Spd_50m" in scenario.era5_interpolated_df.columns
    assert base.active_reference_source == "era5"


def test_result_files_are_off_by_default_in_a_scenario():
    """~10 MB per LTC result over 9,000 leaves is ~90 GB nothing reads (design doc §7.2)."""
    base = _base_state()
    assert base.persist_result_files is True
    assert fork_state(base).persist_result_files is False
    assert fork_state(base, persist_result_files=True).persist_result_files is True


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_context_binds_the_scenario_for_the_duration_of_the_block():
    """Tools reach state through the `session` proxy, so binding is what redirects them."""
    base = _base_state()
    outer = get_active_session()

    with scenario_context(base, runconfig_overrides={"marker": "inside"}) as scenario:
        assert get_active_session() is scenario
        assert session.runconfig["marker"] == "inside"

    assert get_active_session() is outer
    assert "marker" not in base.runconfig


def test_binding_is_restored_even_when_the_scenario_raises():
    base = _base_state()
    outer = get_active_session()
    with pytest.raises(RuntimeError):
        with scenario_context(base):
            raise RuntimeError("scenario failed")
    assert get_active_session() is outer


def test_concurrent_scenarios_do_not_see_each_others_state():
    """Binding is per execution context, which is what allows a worker pool at all."""
    base = _base_state()
    seen: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def run(tag: str) -> None:
        with scenario_context(base, runconfig_overrides={"tag": tag}) as scenario:
            scenario.ltc_results[tag] = {"df": pd.DataFrame(), "metrics": {}}
            barrier.wait(timeout=5)  # both inside their context at once
            seen[tag] = (session.runconfig["tag"], sorted(session.ltc_results))

    threads = [threading.Thread(target=run, args=(tag,)) for tag in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert seen["a"] == ("a", ["a"])
    assert seen["b"] == ("b", ["b"])
    assert base.ltc_results == {}


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_fork_cost_is_reported_per_field():
    """A sweep sizes its worker pool against this, not against a guess."""
    base = _base_state()
    costs = fork_cost_bytes(base)

    assert set(costs) == set(FORKED_FIELDS) | {"total"}
    assert costs["timeseries_df"] > 0
    assert costs["total"] == sum(costs[name] for name in FORKED_FIELDS)


def test_shared_inputs_cost_nothing_to_fork():
    """A shared field contributes zero, however large it gets — that is the point of sharing."""
    base = _base_state()
    before = fork_cost_bytes(base)["total"]

    # Grow the shared raw frame twentyfold. It is passed by reference, so a fork of the
    # bigger session must cost exactly what the smaller one did.
    base.raw_timeseries_df = pd.concat([base.raw_timeseries_df] * 20)

    assert "raw_timeseries_df" not in fork_cost_bytes(base)
    assert fork_cost_bytes(base)["total"] == before
