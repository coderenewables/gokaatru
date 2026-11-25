"""The energy sensitivity computes the site's air density itself (P3-4, decisions/0015.9).

It used to read a density the atmospheric diagnostic left in the run configuration, so the
same data gave two answers depending on whether that diagnostic had run first (P1-5b).
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import run_pipeline


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> SessionState:
    state, _ = run_pipeline(tmp_path_factory.mktemp("density") / "pipeline")
    frame = state.timeseries_df
    hours = np.arange(len(frame)) / 6.0
    frame["Tmp_2m"] = 10.0 + 8.0 * np.sin(2 * np.pi * hours / 8766.0)
    frame["Prs_2m"] = 960.0
    state.sensor_inventory["Tmp_2m"] = {"height_m": 2.0, "sensor_type": "temperature"}
    state.sensor_inventory["Prs_2m"] = {"height_m": 2.0, "sensor_type": "pressure"}
    return state


def _call(state: SessionState, operation: str, /, **arguments):
    with bind_session(state):
        return REGISTRY.get(operation).fn(**arguments)


def test_the_answer_does_not_depend_on_the_atmospheric_diagnostic_running_first(analysed) -> None:
    without = copy.deepcopy(analysed)
    first = _call(without, "compute_energy_sensitivity")
    with_diagnostic = copy.deepcopy(analysed)
    _call(with_diagnostic, "compute_atmospheric_conditions")
    second = _call(with_diagnostic, "compute_energy_sensitivity")
    assert first == second
    assert first["density_normalisation"]["applied"] is True


def test_the_density_is_the_measured_mean_and_its_sensors_are_named(analysed) -> None:
    state = copy.deepcopy(analysed)
    diagnostic = _call(state, "compute_atmospheric_conditions")
    basis = _call(state, "compute_energy_sensitivity")["density_normalisation"]
    assert basis["site_density_kgm3"] == round(diagnostic["air_density"]["mean"], 4)
    assert basis["temperature_sensor"] == "Tmp_2m"
    assert basis["pressure_sensor"] == "Prs_2m"
    assert basis["density_records"] == diagnostic["air_density"]["record_count"]
    # 960 hPa at about 10 C: well below the 1.225 kg/m3 the curve was measured at.
    assert basis["speed_factor"] < 0.99


def test_without_a_pressure_sensor_the_normalisation_is_skipped_and_says_why(analysed) -> None:
    state = copy.deepcopy(analysed)
    state.timeseries_df = state.timeseries_df.drop(columns=["Prs_2m"])
    del state.sensor_inventory["Prs_2m"]
    basis = _call(state, "compute_energy_sensitivity")["density_normalisation"]
    assert basis["applied"] is False
    assert "pressure" in basis["reason"]


def test_the_uncertainty_reports_the_same_normalisation(analysed) -> None:
    state = copy.deepcopy(analysed)
    sensitivity = _call(state, "compute_energy_sensitivity")
    uncertainty = _call(
        state, "calculate_uncertainty", measurement_uncertainty_pct=2.0, measurement_height_m=100.0,
        hub_height_m=120.0, shear_method="calculate_shear", mcp_r_squared=0.8, concurrent_hours=8760.0,
        shear_std=0.05,
    )
    assert uncertainty["energy_sensitivity"]["density_normalisation"] == sensitivity["density_normalisation"]


def test_the_atmospheric_diagnostic_is_a_read_again(analysed, tmp_path: Path) -> None:
    state = copy.deepcopy(analysed)
    before = copy.deepcopy(state.runconfig)
    _call(state, "compute_atmospheric_conditions")
    assert state.runconfig == before
    assert REGISTRY.get("compute_atmospheric_conditions").effect == "read"
