"""The sweep estimate says what the run will skip and refuse (P3-8, decisions/0015.6).

The matrix designer shows it as cells are ticked, so it must agree with the run: the
duplicates it names are the leaves the run skips, and the leaves it calls unavailable are
the ones the run refuses, with the same stage.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from server.core.sweep import estimate_sweep, run_sweep
from tests.test_sweep import _base_state, _small_spec, _two_sensor_state

AXES = ("shear_fit_policy", "reference_policy", "shear_model", "reference_source", "ltc_algorithm")


def _axes(record: dict) -> tuple:
    return tuple(record.get(axis) for axis in AXES)


def test_the_estimate_names_the_duplicates_the_run_skips(tmp_path) -> None:
    # Two sensors: nearest_2 and availability_90 pick the same pair.
    state = _two_sensor_state(tmp_path)
    spec = _small_spec(
        reference_policies=("nearest_2", "availability_90"),
        reference_sources=("era5", "merra2"),
        ltc_algorithms=("variance_ratio",),
    )
    estimate = estimate_sweep(state, spec)
    manifest = run_sweep(state, spec, persist=False)["manifest"]
    skipped = Counter((d["shear_fit_policy"], d["reference_policy"]) for d in manifest["duplicates_skipped"])
    named = Counter((d["shear_fit_policy"], d["reference_policy"]) for d in estimate["duplicates"])
    assert named == skipped and sum(skipped.values()) > 0
    assert estimate["counts"]["duplicates"] == manifest["counts"]["duplicates_skipped"]
    assert estimate["counts"]["would_run"] == manifest["counts"]["run"]


def test_the_estimate_names_the_leaves_the_run_refuses(tmp_path) -> None:
    # The base mast has no boom redundancy, so redundant_boom is unusable.
    state = _base_state(tmp_path)
    spec = _small_spec(
        shear_fit_policies=("nearest_2", "redundant_boom"),
        reference_policies=("nearest_2", "redundant_boom"),
        shear_models=("power_law_mean", "power_law_sector_12"),
        reference_sources=("era5",),
        ltc_algorithms=("variance_ratio",),
    )
    estimate = estimate_sweep(state, spec)
    outcome = run_sweep(state, spec, persist=False)
    refused = {_axes(row): row["failed_gates"] for row in outcome["results"] if row["status"] == "failed"}
    predicted = {_axes(entry): entry["stage"] for entry in estimate["unavailable"]}
    assert set(predicted) == set(refused) and refused
    for axes, stage in predicted.items():
        assert f"stage:{stage}" in refused[axes]
    assert estimate["counts"]["unavailable"] == len(refused)


def test_a_missing_reference_source_and_an_unknown_correction_are_unavailable(tmp_path) -> None:
    state = _base_state(tmp_path)
    del state.reanalysis_interpolated["merra2"]
    spec = _small_spec(ltc_algorithms=("variance_ratio", "cubic_spline"))
    estimate = estimate_sweep(state, spec)
    reasons = {
        (entry["reference_source"], entry["ltc_algorithm"]): entry["reason"] for entry in estimate["unavailable"]
    }
    assert set(reasons) == {("merra2", "variance_ratio"), ("merra2", "cubic_spline"), ("era5", "cubic_spline")}
    assert "merra2" in reasons[("merra2", "variance_ratio")]
    assert "cubic_spline" in reasons[("era5", "cubic_spline")]


def test_the_estimate_reports_the_counts_the_designer_shows(tmp_path) -> None:
    state = _base_state(tmp_path)
    spec = _small_spec()
    estimate = estimate_sweep(state, spec)
    counts = estimate["counts"]
    assert counts["planned"] == spec.leaf_count() == counts["would_run"] + counts["duplicates"] + counts["unavailable"]
    assert counts["prefixes"] == spec.prefix_count()
    assert estimate["duplicates_basis"].startswith("assuming")
    assert np.isfinite(counts["planned"])
