"""Sweep orchestration, gates and result schema — design doc §7.6-7.8.

Covers the three properties a sweep has to have before its spread means anything:
nothing is dropped, inadmissible scenarios are excluded from statistics but stay
visible, and every retained scenario traces back to a runconfig that reproduces it.

Also pins the prefix grouping of §5 — leaves sharing a shear-fit set and shear model
must reuse one shear computation, which is what makes the leaf count affordable at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.admissibility import (
    FAIL,
    MARKED,
    NOT_APPLICABLE,
    PASS,
    WARN,
    GateThresholds,
    evaluate_gates,
    observed_cell_fraction,
)
from server.core.scenario_context import scenario_context
from server.core.scenario_pipeline import ScenarioSpec, run_scenario
from server.core.scenario_result import (
    AXIS_COLUMNS,
    ENGINE_VERSION,
    METRIC_COLUMNS,
    config_hash,
    fixed_prefix_hash,
)
from server.core.sensor_selection import resolve_policy
from server.core.sweep import (
    SweepSpec,
    list_sweeps,
    load_scenario_runconfig,
    load_sweep,
    run_sweep,
)
from server.state.session import SessionState
from tests import oracles

HEIGHTS = (40.0, 60.0, 80.0, 100.0)
HUB_M = 120.0
ALPHA = 0.22
MEASURED_INDEX = pd.date_range("2019-01-01", "2020-12-31 23:50", freq="10min", tz="UTC")
LONG_INDEX = pd.date_range("2012-01-01", "2020-12-31 23:00", freq="h", tz="UTC")


def _base_state(tmp_path=None) -> SessionState:
    """A mast whose measured series is genuinely correlated with the reanalysis.

    Building the two independently would leave the LTC with no predictive skill at all —
    a negative R^2 — so every scenario would trip the admissibility gate and the fixture
    would never exercise a plausible regime. Correlation between site and reference is
    the premise MCP rests on, so the fixture has to carry it.
    """
    rng = np.random.default_rng(31)
    long_rng = np.random.default_rng(37)
    era5 = 8.0 + long_rng.weibull(2.0, len(LONG_INDEX)) * 3.0
    era5_series = pd.Series(era5, index=LONG_INDEX)

    # The site sees the same weather as the reference, scaled and with local scatter.
    concurrent = era5_series.reindex(MEASURED_INDEX, method="ffill")
    top = np.clip(
        concurrent.to_numpy() * 0.92 + rng.normal(0.0, 0.6, len(MEASURED_INDEX)), 0.1, None
    )
    measured = pd.DataFrame(
        {f"Spd_{int(h)}m": top * (h / max(HEIGHTS)) ** ALPHA for h in HEIGHTS},
        index=MEASURED_INDEX,
    )
    measured["Dir_100m"] = rng.uniform(0.0, 360.0, len(MEASURED_INDEX))

    state = SessionState()
    state.reset()
    if tmp_path is not None:
        state.workspace_dir = tmp_path
    state.timeseries_df = measured
    state.raw_timeseries_df = measured.copy()
    state.sensor_mapping = {
        float(h): {"speed_col": f"Spd_{int(h)}m", "dir_col": "Dir_100m" if h == 100.0 else None}
        for h in HEIGHTS
    }
    state.sensor_inventory = {
        f"Spd_{int(h)}m": {"height_m": float(h), "sensor_type": "wind_speed"} for h in HEIGHTS
    }
    state.set_measurement_type("mast")
    state.set_hub_height_m(HUB_M)

    state.reanalysis_interpolated = {
        "era5": pd.DataFrame(
            {"Spd_100m": era5, "Dir_100m": long_rng.uniform(0, 360, len(LONG_INDEX))},
            index=LONG_INDEX,
        ),
        "merra2": pd.DataFrame(
            {
                "Spd_50m": np.clip(
                    era5 * 0.86 + 0.4 + long_rng.normal(0, 0.8, len(LONG_INDEX)), 0.0, None
                ),
                "Dir_50m": long_rng.uniform(0, 360, len(LONG_INDEX)),
            },
            index=LONG_INDEX,
        ),
    }
    return state


def _small_spec(**overrides) -> SweepSpec:
    base = dict(
        shear_fit_policies=("nearest_2",),
        reference_policies=("nearest_2",),
        shear_models=("power_law_mean",),
        reference_sources=("era5", "merra2"),
        ltc_algorithms=("variance_ratio", "linear_least_squares"),
        hub_height_m=HUB_M,
    )
    base.update(overrides)
    return SweepSpec(**base)


# ---------------------------------------------------------------------------
# Expansion and counting
# ---------------------------------------------------------------------------


def test_leaf_and_prefix_counts_are_reported_separately():
    """The designer shows both, because they differ by the memoisation factor (§9.1)."""
    spec = SweepSpec(
        shear_fit_policies=("nearest_2", "widest_lever"),
        reference_policies=("nearest_2", "availability_90"),
        shear_models=("power_law_mean", "power_law_momm", "power_law_constant"),
        reference_sources=("era5", "merra2"),
        ltc_algorithms=("variance_ratio", "linear_least_squares", "total_least_squares"),
    )
    assert spec.leaf_count() == 2 * 2 * 3 * 2 * 3
    assert spec.prefix_count() == 2 * 3  # shear depends on fit set x model only
    assert len(spec.leaves()) == spec.leaf_count()


# ---------------------------------------------------------------------------
# The sweep runs, records everything, and persists it
# ---------------------------------------------------------------------------


def test_a_sweep_produces_one_row_per_leaf(tmp_path):
    base = _base_state(tmp_path)
    outcome = run_sweep(base, _small_spec())

    assert outcome["manifest"]["counts"]["planned"] == 4
    assert len(outcome["results"]) == 4
    for row in outcome["results"]:
        for column in AXIS_COLUMNS:
            assert column in row
        for column in METRIC_COLUMNS:
            assert column in row


def test_headline_metrics_are_populated(tmp_path):
    """Both pinned metrics — speed and AEP — must survive to the table (§11)."""
    base = _base_state(tmp_path)
    rows = run_sweep(base, _small_spec())["results"]
    completed = [row for row in rows if row["status"] == "ok"]
    assert completed
    for row in completed:
        assert row["long_term_mean_speed_mps"] > 0.0
        assert row["indicative_gross_aep_mwh"] > 0.0
        assert row["total_uncertainty_pct"] > 0.0


def test_the_sweep_leaves_the_base_session_untouched(tmp_path):
    base = _base_state(tmp_path)
    columns_before = list(base.timeseries_df.columns)
    run_sweep(base, _small_spec())

    assert list(base.timeseries_df.columns) == columns_before
    assert base.shear_table is None
    assert base.ltc_results == {}


def test_a_failing_scenario_becomes_a_row_not_an_omission(tmp_path):
    """A sweep that drops what it cannot compute reports a spread nobody can enumerate."""
    base = _base_state(tmp_path)
    base.sensor_inventory = {}  # no boom redundancy anywhere
    spec = _small_spec(reference_policies=("nearest_2", "redundant_boom"))

    outcome = run_sweep(base, spec)
    rows = outcome["results"]

    assert len(rows) == spec.leaf_count()
    failed = [row for row in rows if row["status"] == "failed"]
    assert len(failed) == 4
    for row in failed:
        assert row["admissible"] is False
        assert row["error"]
        assert row["reference_policy"] == "redundant_boom"


def test_every_scenario_is_persisted_with_a_runconfig(tmp_path):
    """90 scenarios means 90 runconfigs, mapped and downloadable (design doc §7.13)."""
    base = _base_state(tmp_path)
    outcome = run_sweep(base, _small_spec(), sweep_id="fixed")
    manifest = outcome["manifest"]

    assert manifest["sweep_id"] == "fixed"
    assert len(manifest["scenarios"]) == 4

    root = tmp_path / "sweeps" / "fixed"
    assert (root / "manifest.json").is_file()
    assert (root / "results.json").is_file()

    for entry in manifest["scenarios"]:
        if entry["status"] != "ok":
            continue
        path = root / entry["runconfig"]
        assert path.is_file(), entry["runconfig"]
        config = json.loads(path.read_text(encoding="utf-8"))
        assert config["scenario"]["config_hash"] == entry["config_hash"]
        assert config["admissibility"]["thresholds"]["extrapolation_ratio_fail"] == 2.0


def test_a_persisted_sweep_can_be_read_back(tmp_path):
    base = _base_state(tmp_path)
    run_sweep(base, _small_spec(), sweep_id="readback")

    loaded = load_sweep(base, "readback")
    assert loaded["manifest"]["sweep_id"] == "readback"
    assert len(loaded["results"]) == 4

    summaries = list_sweeps(base)
    assert [entry["sweep_id"] for entry in summaries] == ["readback"]

    first_ok = next(e for e in loaded["manifest"]["scenarios"] if e["status"] == "ok")
    config = load_scenario_runconfig(base, "readback", first_ok["config_hash"])
    assert config["scenario"]["ltc_algorithm"] in {"variance_ratio", "linear_least_squares"}


def test_a_crash_mid_sweep_leaves_the_finished_groups_on_disk(monkeypatch, tmp_path):
    """A killed server must not lose the groups it had already run (T12).

    The crash is an unexpected exception, not a ScenarioError, so run_sweep does not
    catch it and it propagates today; that behaviour is pinned rather than changed.
    """
    from server.core import sweep as sweep_module

    spec = _small_spec(shear_fit_policies=("nearest_2", "widest_lever"))
    groups = sweep_module._by_shear_prefix(spec.leaves())
    first_key, second_key = list(groups)[:2]
    real_run_leaf = sweep_module._run_leaf

    def crash_in_second_group(prefix_state, leaf, prefix, thresholds):
        key = (leaf.shear_fit_policy, leaf.shear_model, leaf.analyst_shear_alpha)
        if key == second_key:
            raise RuntimeError("simulated crash")
        return real_run_leaf(prefix_state, leaf, prefix, thresholds)

    monkeypatch.setattr(sweep_module, "_run_leaf", crash_in_second_group)

    base = _base_state(tmp_path)
    with pytest.raises(RuntimeError, match="simulated crash"):
        run_sweep(base, spec, sweep_id="crashed")

    first_group_size = len(groups[first_key])
    loaded = load_sweep(base, "crashed")
    assert loaded["manifest"]["in_progress"] is True
    assert loaded["manifest"]["counts"]["run"] == first_group_size
    assert len(loaded["results"]) == first_group_size
    assert all(row["status"] == "ok" for row in loaded["results"])

    first_ok = next(e for e in loaded["manifest"]["scenarios"] if e["status"] == "ok")
    config = load_scenario_runconfig(base, "crashed", first_ok["config_hash"])
    assert config["scenario"]["config_hash"] == first_ok["config_hash"]

    summaries = list_sweeps(base)
    assert [entry["sweep_id"] for entry in summaries] == ["crashed"]


def test_an_interim_manifest_carries_the_duplicates_found_so_far(monkeypatch, tmp_path):
    """The checkpoint is a full manifest, not a bare row dump (T7 + T12).

    nearest_2 and availability_90 resolve to the same two sensors, so the second leaf of
    the first group is a duplicate. The crash in the second group must not lose it.
    """
    from server.core import sweep as sweep_module

    base = _two_sensor_state(tmp_path)
    spec = _small_spec(
        shear_models=("power_law_mean", "power_law_momm"),
        reference_policies=("nearest_2", "availability_90"),
        reference_sources=("era5",),
        ltc_algorithms=("variance_ratio",),
    )
    second_model = spec.leaves()[-1].shear_model
    real_run_leaf = sweep_module._run_leaf

    def crash_in_second_group(prefix_state, leaf, prefix, thresholds):
        if leaf.shear_model == second_model:
            raise RuntimeError("simulated crash")
        return real_run_leaf(prefix_state, leaf, prefix, thresholds)

    monkeypatch.setattr(sweep_module, "_run_leaf", crash_in_second_group)

    with pytest.raises(RuntimeError, match="simulated crash"):
        run_sweep(base, spec, sweep_id="interim")

    manifest = load_sweep(base, "interim")["manifest"]
    assert manifest["in_progress"] is True
    assert manifest["counts"]["run"] == 1
    assert manifest["counts"]["duplicates_skipped"] == 1
    assert [d["reference_policy"] for d in manifest["duplicates_skipped"]] == ["availability_90"]


def test_a_completed_sweep_carries_no_in_progress_flag(tmp_path):
    base = _base_state(tmp_path)
    run_sweep(base, _small_spec(shear_fit_policies=("nearest_2", "widest_lever")), sweep_id="done")

    manifest = load_sweep(base, "done")["manifest"]
    assert "in_progress" not in manifest
    assert manifest["counts"]["run"] == manifest["counts"]["planned"]


def test_a_transiently_locked_file_is_replaced_on_retry(monkeypatch, tmp_path):
    """Windows refuses a replace while a scanner holds the target; that must not end a sweep."""
    import os

    from server.core import sweep as sweep_module

    real_replace = os.replace
    refusals = {"left": 2}

    def locked_twice(src, dst):
        if refusals["left"] > 0:
            refusals["left"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    delays: list[float] = []
    monkeypatch.setattr(os, "replace", locked_twice)
    monkeypatch.setattr(sweep_module.time, "sleep", delays.append)

    target = tmp_path / "payload.json"
    sweep_module._write_json_atomic(target, {"ok": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
    assert len(delays) == 2


def test_a_file_locked_past_the_retries_is_raised_not_swallowed(monkeypatch, tmp_path):
    import os

    from server.core import sweep as sweep_module

    def always_locked(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(os, "replace", always_locked)
    monkeypatch.setattr(sweep_module.time, "sleep", lambda _s: None)

    with pytest.raises(PermissionError):
        sweep_module._write_json_atomic(tmp_path / "payload.json", {"ok": True})


def test_missing_sweeps_and_scenarios_are_refused_by_name(tmp_path):
    base = _base_state(tmp_path)
    with pytest.raises(ValueError, match="is not available"):
        load_sweep(base, "nope")
    run_sweep(base, _small_spec(), sweep_id="present")
    with pytest.raises(ValueError, match="is not available"):
        load_scenario_runconfig(base, "present", "deadbeef")


# ---------------------------------------------------------------------------
# Prefix grouping — the §5 saving
# ---------------------------------------------------------------------------


def test_leaves_sharing_a_shear_prefix_build_the_table_once(monkeypatch, tmp_path):
    """Recomputing the shear table per leaf is the single largest waste available.

    Four leaves over one (fit set, shear model) pair must cost one shear build, not four.
    """
    from server.tools import shear as shear_tools

    calls: list[str] = []
    real = shear_tools._calculate_shear_timeseries

    def counting(state, height_sensors, *args, **kwargs):
        calls.append(height_sensors)
        return real(state, height_sensors, *args, **kwargs)

    monkeypatch.setattr(shear_tools, "_calculate_shear_timeseries", counting)

    base = _base_state(tmp_path)
    outcome = run_sweep(base, _small_spec())  # 1 prefix, 4 leaves

    assert len(outcome["results"]) == 4
    assert len(calls) == 1, f"shear table rebuilt {len(calls)} times for one prefix"


def test_each_shear_prefix_gets_its_own_build(monkeypatch, tmp_path):
    from server.tools import shear as shear_tools

    calls: list[str] = []
    real = shear_tools._calculate_shear_timeseries

    def counting(state, height_sensors, *args, **kwargs):
        calls.append(height_sensors)
        return real(state, height_sensors, *args, **kwargs)

    monkeypatch.setattr(shear_tools, "_calculate_shear_timeseries", counting)

    base = _base_state(tmp_path)
    spec = _small_spec(
        shear_fit_policies=("nearest_2", "widest_lever"),
        shear_models=("power_law_mean", "power_law_momm"),
    )
    run_sweep(base, spec)

    assert spec.prefix_count() == 4
    assert len(calls) == 4


def test_a_leaf_cannot_disturb_the_prefix_its_siblings_reuse(tmp_path):
    """Leaves fork from the prefix, so one writing a hub column must not affect the next."""
    base = _base_state(tmp_path)
    outcome = run_sweep(base, _small_spec(ltc_algorithms=("variance_ratio",)))
    speeds = {row["reference_source"]: row["long_term_mean_speed_mps"] for row in outcome["results"]}

    # Re-run each source alone; the grouped run must agree with the isolated one.
    for source in ("era5", "merra2"):
        alone = run_sweep(base, _small_spec(reference_sources=(source,), ltc_algorithms=("variance_ratio",)))
        assert alone["results"][0]["long_term_mean_speed_mps"] == pytest.approx(
            speeds[source], rel=1e-12
        )


def test_an_unusable_reference_policy_does_not_fail_its_siblings(tmp_path):
    """The shear prefix is shared, so it must not depend on any one leaf's reference policy.

    With no sensor inventory ``redundant_boom`` is unavailable while ``nearest_2`` is not.
    The usable leaves must come out identical whichever policy is listed first, and only
    the unusable leaves may fail — at the stage that refused them.
    """
    base = _base_state(tmp_path)
    base.sensor_inventory = {}

    forward = run_sweep(base, _small_spec(reference_policies=("redundant_boom", "nearest_2")))
    reverse = run_sweep(base, _small_spec(reference_policies=("nearest_2", "redundant_boom")))

    def usable(rows):
        selected = [row for row in rows if row["reference_policy"] == "nearest_2"]
        return sorted(selected, key=lambda row: (row["reference_source"], row["ltc_algorithm"]))

    forward_ok = usable(forward["results"])
    reverse_ok = usable(reverse["results"])
    assert len(forward_ok) == 4
    assert all(row["status"] == "ok" for row in forward_ok)
    assert forward_ok == reverse_ok

    unusable = [row for row in forward["results"] if row["reference_policy"] == "redundant_boom"]
    assert len(unusable) == 4
    for row in unusable:
        assert row["status"] == "failed"
        assert row["failed_gates"] == "stage:resolve_sensors"
        assert "reference policy unusable" in row["error"]


def _two_sensor_state(tmp_path) -> SessionState:
    """The fixture mast with only its two top sensors, so every policy resolves to them.

    On four sensors the policies all differ. With two there is one sensor pair, and
    ``nearest_2``, ``widest_lever`` and ``availability_90`` all resolve to it.
    """
    base = _base_state(tmp_path)
    for height in (40.0, 60.0):
        column = f"Spd_{int(height)}m"
        del base.sensor_mapping[height]
        del base.sensor_inventory[column]
        base.timeseries_df = base.timeseries_df.drop(columns=column)
        base.raw_timeseries_df = base.raw_timeseries_df.drop(columns=column)
    return base


def test_policies_resolving_to_the_same_sensors_run_once(tmp_path):
    """Two names for one computation: one row, and the second is listed as a duplicate."""
    base = _two_sensor_state(tmp_path)
    resolved = {policy: resolve_policy(base, policy, HUB_M).columns for policy in ("nearest_2", "availability_90")}
    assert resolved["nearest_2"] == resolved["availability_90"] != ()

    spec = _small_spec(
        reference_policies=("nearest_2", "availability_90"),
        reference_sources=("era5",),
        ltc_algorithms=("variance_ratio",),
    )
    events: list = []
    outcome = run_sweep(base, spec, on_progress=events.append, persist=False)
    manifest = outcome["manifest"]
    rows = outcome["results"]

    assert len(rows) == 1
    assert rows[0]["status"] == "ok"
    assert manifest["duplicates_skipped"] == [
        {
            "shear_fit_policy": "nearest_2",
            "reference_policy": "availability_90",
            "same_as": rows[0]["config_hash"],
        }
    ]
    assert manifest["counts"]["duplicates_skipped"] == 1
    assert manifest["counts"]["planned"] == 2

    assert [event.event for event in events].count("scenario_skipped_duplicate") == 1
    assert events[-1].event == "sweep_finished"
    assert (events[-1].completed, events[-1].total) == (2, 2)


def test_duplicates_are_found_across_shear_fit_prefixes(tmp_path):
    """Different fit policies build different shear prefixes; the duplicate still matches."""
    base = _two_sensor_state(tmp_path)
    spec = _small_spec(
        shear_fit_policies=("nearest_2", "availability_90"),
        reference_policies=("nearest_2",),
        reference_sources=("era5",),
        ltc_algorithms=("variance_ratio",),
    )
    outcome = run_sweep(base, spec, persist=False)

    assert len(outcome["results"]) == 1
    skipped = outcome["manifest"]["duplicates_skipped"]
    assert [(entry["shear_fit_policy"], entry["reference_policy"]) for entry in skipped] == [
        ("availability_90", "nearest_2")
    ]
    assert skipped[0]["same_as"] == outcome["results"][0]["config_hash"]


def test_distinct_policies_are_not_deduplicated(tmp_path):
    base = _base_state(tmp_path)
    spec = _small_spec(reference_policies=("nearest_2", "widest_lever"))
    outcome = run_sweep(base, spec, persist=False)

    assert len(outcome["results"]) == spec.leaf_count() == 8
    assert outcome["manifest"]["duplicates_skipped"] == []
    assert outcome["manifest"]["counts"]["duplicates_skipped"] == 0


def test_an_unusable_policy_is_never_matched_to_a_sibling(tmp_path):
    """Both leaves are refused at resolution; neither is merged into the other."""
    base = _base_state(tmp_path)
    base.sensor_inventory = {}
    spec = _small_spec(
        reference_policies=("redundant_boom", "redundant_boom"),
        reference_sources=("era5",),
        ltc_algorithms=("variance_ratio",),
    )
    outcome = run_sweep(base, spec, persist=False)

    assert outcome["manifest"]["duplicates_skipped"] == []
    assert [row["status"] for row in outcome["results"]] == ["failed", "failed"]


def test_config_hash_ignores_policy_names_but_not_resolved_columns():
    """The hash names the computation: labels are out, the resolved sensors are in."""

    def record(fit_name: str, columns: list[str]) -> dict:
        return {
            "spec": {
                "sensor_selection": {"shear_fit": fit_name, "extrapolation_reference": fit_name},
                "shear_model": "power_law_mean",
                "reference_source": "era5",
                "ltc_algorithm": "variance_ratio",
            },
            "sensor_selection": {
                "shear_fit": {"resolved_columns": columns},
                "extrapolation_reference": {"resolved_columns": columns},
            },
        }

    same_sensors = config_hash(record("nearest_2", ["Spd_80m"]), "prefix")
    assert same_sensors == config_hash(record("availability_90", ["Spd_80m"]), "prefix")
    assert same_sensors != config_hash(record("nearest_2", ["Spd_100m"]), "prefix")


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def _report(base, **spec_overrides):
    fields = dict(
        shear_fit_policy="nearest_2",
        reference_policy="nearest_2",
        shear_model="power_law_mean",
        reference_source="era5",
        ltc_algorithm="variance_ratio",
        hub_height_m=HUB_M,
    )
    fields.update(spec_overrides)
    spec = ScenarioSpec(**fields)
    with scenario_context(base) as scenario:
        record = run_scenario(scenario, spec)
        return evaluate_gates(scenario, record, GateThresholds()), scenario, record


def test_a_sound_scenario_passes_its_gates(tmp_path):
    base = _base_state(tmp_path)
    report, _, _ = _report(base)
    assert report.admissible
    assert report.failures == []


def test_a_severe_extrapolation_lever_fails_the_scenario(tmp_path):
    """A 3x lever is the power-law assumption talking, not the measurement."""
    base = _base_state(tmp_path)
    base.set_hub_height_m(320.0)
    report, _, _ = _report(base, hub_height_m=320.0)

    ratio = next(g for g in report.gates if g.name == "extrapolation_ratio")
    assert ratio.status == FAIL
    assert ratio.value > 2.0
    assert report.admissible is False
    assert "extrapolation_ratio" in report.failures


def test_an_analyst_exponent_is_marked_not_failed(tmp_path):
    """Not a defect, but never invisible (design doc §3.A.1)."""
    base = _base_state(tmp_path)
    base.sensor_inventory = {
        "Spd_100m_A": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Spd_100m_B": {"height_m": 100.0, "sensor_type": "wind_speed"},
    }
    report, _, _ = _report(base, shear_fit_policy="redundant_boom", analyst_shear_alpha=0.20)

    provenance = next(g for g in report.gates if g.name == "shear_provenance")
    assert provenance.status == MARKED
    assert provenance.value == 0.20
    assert report.admissible is True
    assert "shear_provenance" in report.marks


def test_gates_with_nothing_to_measure_are_not_applicable_rather_than_passing(tmp_path):
    """An absent check must never be mistaken for a satisfied one."""
    base = _base_state(tmp_path)
    report, _, _ = _report(base, shear_model="log_law_mean")

    alpha = next(g for g in report.gates if g.name == "mean_shear_alpha")
    assert alpha.status == NOT_APPLICABLE
    sector = next(g for g in report.gates if g.name == "sector_records")
    assert sector.status == NOT_APPLICABLE
    # not_applicable must not count as a failure
    assert report.admissible is True


def test_a_bracketed_hub_reports_no_extrapolation_lever(tmp_path):
    base = _base_state(tmp_path)
    base.set_hub_height_m(70.0)
    report, _, _ = _report(base, hub_height_m=70.0)
    ratio = next(g for g in report.gates if g.name == "extrapolation_ratio")
    assert ratio.status == NOT_APPLICABLE
    assert "bracketed" in ratio.detail


def test_thresholds_travel_with_the_scenario(tmp_path):
    """A result's pass/fail must be re-derivable, not trusted (design doc §7.7)."""
    base = _base_state(tmp_path)
    strict = GateThresholds(extrapolation_ratio_warn=1.0001, extrapolation_ratio_fail=1.001)

    outcome = run_sweep(base, _small_spec(), thresholds=strict, sweep_id="strict")
    assert outcome["manifest"]["thresholds"]["extrapolation_ratio_fail"] == 1.001
    completed = [row for row in outcome["results"] if row["status"] == "ok"]
    assert all(row["admissible"] is False for row in completed)
    assert all("extrapolation_ratio" in row["failed_gates"] for row in completed)


def test_a_sweep_with_nothing_admissible_says_so_and_names_the_gate(tmp_path):
    """An empty distribution with nothing explaining it reads as "no signal".

    Measured on a real complex-terrain campaign: every scenario failed the R^2 gate, so
    the engine reported a spread over zero scenarios. That is not a measurement of the
    site, it is a measurement of the threshold, and the manifest has to say which.
    """
    base = _base_state(tmp_path)
    impossible = GateThresholds(extrapolation_ratio_fail=1.0001)

    manifest = run_sweep(base, _small_spec(), thresholds=impossible, persist=False)["manifest"]

    assert manifest["counts"]["admissible"] == 0
    assert manifest["gate_failures"]["extrapolation_ratio"] == manifest["counts"]["completed"]
    assert "No scenario was admissible" in manifest["diagnosis"]
    assert "extrapolation_ratio" in manifest["diagnosis"]


def test_a_healthy_sweep_carries_no_diagnosis(tmp_path):
    """The diagnosis is for the pathological case only; a normal run must not carry one."""
    base = _base_state(tmp_path)
    manifest = run_sweep(base, _small_spec(), persist=False)["manifest"]
    assert manifest["counts"]["admissible"] > 0
    assert manifest["diagnosis"] is None


def test_gate_failures_are_tallied_even_when_some_scenarios_pass(tmp_path):
    base = _base_state(tmp_path)
    manifest = run_sweep(base, _small_spec(), persist=False)["manifest"]
    assert isinstance(manifest["gate_failures"], dict)


def test_inadmissible_scenarios_stay_in_the_table(tmp_path):
    """Excluded from statistics, never from the record."""
    base = _base_state(tmp_path)
    strict = GateThresholds(extrapolation_ratio_fail=1.0001)
    outcome = run_sweep(base, _small_spec(), thresholds=strict)

    assert outcome["manifest"]["counts"]["admissible"] == 0
    assert outcome["manifest"]["counts"]["completed"] == 4
    assert len(outcome["results"]) == 4


# ---------------------------------------------------------------------------
# Cell coverage counts records, not cells
# ---------------------------------------------------------------------------


def test_cell_coverage_requires_a_populated_cell_not_merely_a_touched_one():
    """`_table_fill_report` counts a cell observed on one record (design doc §7.7.2)."""
    index = pd.date_range("2021-01-01", periods=288, freq="h", tz="UTC")
    sparse = pd.DataFrame({"shear_coefficient": np.full(len(index), 0.2)}, index=index)

    generous, _ = observed_cell_fraction(sparse, min_records=1)
    strict, detail = observed_cell_fraction(sparse, min_records=30)

    assert generous > strict
    assert strict == 0.0
    assert detail["min_records_per_cell"] == 30


def test_a_full_campaign_covers_its_cells():
    index = pd.date_range("2019-01-01", "2020-12-31 23:50", freq="10min", tz="UTC")
    full = pd.DataFrame({"shear_coefficient": np.full(len(index), 0.21)}, index=index)
    fraction, detail = observed_cell_fraction(full, min_records=30)
    assert fraction == 1.0
    assert detail["cells_observed"] == 288


def test_coverage_is_not_applicable_without_a_series():
    fraction, detail = observed_cell_fraction(None, min_records=30)
    assert fraction is None
    assert detail == {}


# ---------------------------------------------------------------------------
# Hashing and provenance
# ---------------------------------------------------------------------------


def test_rows_carry_the_manifest_prefix_hash_when_hub_differs_from_the_session(tmp_path):
    """A leaf's hub is its own, not the session's, but the prefix is fixed once per sweep."""
    base = _base_state(tmp_path)
    assert base.get_hub_height_m() == HUB_M
    outcome = run_sweep(base, _small_spec(hub_height_m=100.0), persist=False)

    assert outcome["results"]
    for row in outcome["results"]:
        assert row["fixed_prefix_hash"] == outcome["manifest"]["fixed_prefix_hash"]


def test_identical_configurations_hash_identically(tmp_path):
    base = _base_state(tmp_path)
    first = run_sweep(base, _small_spec(), persist=False)
    second = run_sweep(base, _small_spec(), persist=False)
    assert [row["config_hash"] for row in first["results"]] == [
        row["config_hash"] for row in second["results"]
    ]


def test_a_different_axis_value_changes_the_hash(tmp_path):
    base = _base_state(tmp_path)
    era5 = run_sweep(
        base, _small_spec(reference_sources=("era5",), ltc_algorithms=("variance_ratio",)), persist=False
    )
    merra = run_sweep(
        base, _small_spec(reference_sources=("merra2",), ltc_algorithms=("variance_ratio",)), persist=False
    )
    assert era5["results"][0]["config_hash"] != merra["results"][0]["config_hash"]


def test_a_changed_fixed_prefix_changes_every_hash(tmp_path):
    """Scenarios built on different cleaning are not comparable (design doc §2)."""
    base = _base_state(tmp_path)
    before = run_sweep(base, _small_spec(), persist=False)

    base.cleaning_log = [{"rule": "icing", "removed": 120}]
    after = run_sweep(base, _small_spec(), persist=False)

    assert before["manifest"]["fixed_prefix_hash"] != after["manifest"]["fixed_prefix_hash"]
    assert {row["config_hash"] for row in before["results"]}.isdisjoint(
        row["config_hash"] for row in after["results"]
    )


def test_the_time_a_cleaning_rule_ran_does_not_change_the_prefix(tmp_path):
    """Two analyses with the same cleaning, run a minute apart, are comparable.

    The prefix hashed each log entry's ``applied_at``, so the same rules applied at a
    different second gave a different prefix and a different config hash for every
    scenario; found by the published-numbers harness (P1-0), whose two runs disagreed.
    """
    base = _base_state(tmp_path)
    entry = {"rule_type": "range_check", "sensor": "Spd_100m", "sequence": 1, "records_affected": 7}
    base.cleaning_log = [entry | {"applied_at": "2026-11-19T01:11:22+00:00"}]
    first = fixed_prefix_hash(base)
    base.cleaning_log = [entry | {"applied_at": "2026-11-19T01:12:18+00:00"}]
    assert fixed_prefix_hash(base) == first

    base.cleaning_log = [entry | {"records_affected": 8, "applied_at": "2026-11-19T01:12:18+00:00"}]
    assert fixed_prefix_hash(base) != first


def test_fixed_prefix_hash_matches_an_independent_recomputation(tmp_path):
    """Oracle check: the hash is exactly sha256(sorted-JSON of its seven inputs)[:16].

    Guards the hash itself, independent of ``_stable_hash`` — a change to what the hash
    covers or how it's encoded should break this test, not just the "changes when an
    input changes" tests above.
    """
    base = _base_state(tmp_path)
    base.cleaning_log = [{"rule": "icing", "removed": 120, "applied_at": "2026-11-19T01:11:22+00:00"}]

    expected = oracles.fixed_prefix_hash_oracle(
        cleaning_log=base.cleaning_log,
        reanalysis_identity=base.reanalysis_cache_identity,
        reanalysis_sources=list(base.reanalysis_interpolated),
        sensor_inventory=list(base.sensor_inventory or {}),
        hub_height_m=base.get_hub_height_m(),
        measurement_type=base.get_measurement_type(),
        power_curve=base.get_power_curve_name(),
        engine_version=ENGINE_VERSION,
    )
    assert fixed_prefix_hash(base) == expected


def test_manifest_carries_the_engine_version(tmp_path):
    """Sweeps from different engine versions must be distinguishable on disk."""
    base = _base_state(tmp_path)
    outcome = run_sweep(base, _small_spec(), sweep_id="versioned")
    assert outcome["manifest"]["engine_version"] == ENGINE_VERSION
    assert load_sweep(base, "versioned")["manifest"]["engine_version"] == ENGINE_VERSION


def test_a_manifest_without_the_engine_version_loads_unchanged(tmp_path):
    """Sweeps stored before the stamp existed must read back exactly as they were written."""
    base = _base_state(tmp_path)
    run_sweep(base, _small_spec(), sweep_id="legacy")
    path = Path(base.get_data_dir()) / "sweeps" / "legacy" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["engine_version"]
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    loaded = load_sweep(base, "legacy")
    assert "engine_version" not in loaded["manifest"]
    assert loaded["manifest"] == manifest


def test_progress_events_report_prefixes_and_scenarios(tmp_path):
    base = _base_state(tmp_path)
    events: list = []
    run_sweep(base, _small_spec(), on_progress=events.append, persist=False)
    names = [event.event for event in events]

    assert names[0] == "sweep_started"
    assert names[-1] == "sweep_finished"
    assert names.count("prefix_started") == 1
    assert names.count("scenario_completed") == 4
    assert events[-1].total == 4


def test_a_stop_request_halts_between_scenarios(tmp_path):
    """Cancel must not interrupt a scenario mid-computation and leave a half record."""
    base = _base_state(tmp_path)
    seen: list[int] = []

    def should_stop() -> bool:
        seen.append(len(seen))
        return len(seen) > 2

    outcome = run_sweep(base, _small_spec(), should_stop=should_stop, persist=False)

    assert outcome["manifest"]["stopped_early"] is True
    assert len(outcome["results"]) < 4
    for row in outcome["results"]:
        assert row["status"] == "ok"


def test_gate_statuses_are_columns_on_the_row(tmp_path):
    base = _base_state(tmp_path)
    row = run_sweep(base, _small_spec(), persist=False)["results"][0]
    assert row["gate_extrapolation_ratio"] in {PASS, WARN, FAIL, NOT_APPLICABLE}
    # R^2 is reported as a metric but is deliberately not a gate (see the module docstring
    # of server/core/admissibility.py, and design doc S13.6).
    assert "gate_ltc_r_squared" not in row
    assert "ltc_r_squared" in row
    assert row["gate_shear_provenance"] in {PASS, MARKED}


def test_each_gate_carries_the_value_it_was_reached_on(tmp_path):
    """A status alone says a scenario was excluded; the value says by how much.

    Without it the frontend can name the gate but cannot show whether the threshold or
    the campaign is at fault, which is the question a reader actually has.
    """
    base = _base_state(tmp_path)
    row = run_sweep(base, _small_spec(), persist=False)["results"][0]

    assert "gate_extrapolation_ratio_value" in row
    assert isinstance(row["gate_extrapolation_ratio_value"], float)
    # A gate with nothing to measure reports None rather than a misleading zero.
    assert row["gate_sector_records"] == NOT_APPLICABLE
    assert row["gate_sector_records_value"] is None


def test_the_scenario_runconfig_carries_full_gate_records(tmp_path):
    """A verdict without the number it was reached on is not auditable."""
    base = _base_state(tmp_path)
    outcome = run_sweep(base, _small_spec(), sweep_id="gates")
    entry = next(e for e in outcome["manifest"]["scenarios"] if e["status"] == "ok")
    config = load_scenario_runconfig(base, "gates", entry["config_hash"])

    gates = config["admissibility"]["result"]["gates"]
    assert isinstance(gates, list)
    by_name = {gate["name"]: gate for gate in gates}
    assert by_name["extrapolation_ratio"]["detail"]
    assert set(by_name["extrapolation_ratio"]) == {"name", "status", "value", "detail"}
