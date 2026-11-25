"""The operations a sweep scenario's stages share with the canvas (P3-7b, decisions/0015.1).

A scenario must answer the same whether it runs in a sweep leaf, where its results are the
only ones, or in a campaign that also holds an ensemble, a clipping run and other tables.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import run_pipeline

HUB = "Spd_120m_hub"
IGNORED = {"data_version", "stale_artifacts", "stale_reasons", "warning", "derived_inputs"}


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> SessionState:
    state, _ = run_pipeline(tmp_path_factory.mktemp("scenario-steps") / "pipeline")
    return state


def _call(state: SessionState, operation: str, /, **arguments):
    with bind_session(state):
        return REGISTRY.get(operation).fn(**arguments)


def _answer(result: dict) -> dict:
    return {key: value for key, value in result.items() if key not in IGNORED}


def test_a_scenario_uncertainty_ignores_what_else_the_session_holds(analysed) -> None:
    arguments = {"algorithm": "variance_ratio", "shear_model": "power_law_mean", "reference_heights": [80.0, 100.0]}
    full = copy.deepcopy(analysed)
    assert full.ensemble_df is not None and full.clipping_result is not None
    in_campaign = _call(full, "calculate_scenario_uncertainty", **arguments)

    leaf = copy.deepcopy(analysed)
    leaf.ensemble_df = None
    leaf.clipping_result = None
    leaf.roughness_table = None
    leaf.ltc_results = {"variance_ratio": leaf.ltc_results["variance_ratio"]}
    alone = _call(leaf, "calculate_scenario_uncertainty", **arguments)

    assert _answer(in_campaign) == _answer(alone)
    assert in_campaign["energy_sensitivity"]["measured_on"] == "ltc:variance_ratio"
    assert in_campaign["inputs"]["iav_pct"] == 6.0


def test_a_log_law_scenario_takes_the_log_law_constant_whatever_tables_exist(analysed) -> None:
    state = copy.deepcopy(analysed)
    assert state.shear_table is not None and state.roughness_table is not None
    result = _call(
        state, "calculate_scenario_uncertainty",
        algorithm="variance_ratio", shear_model="log_law_mean", reference_heights=[80.0, 100.0],
    )
    assert result["inputs"]["shear_method"] == "log_law"


def test_an_unknown_shear_model_or_a_correction_not_run_is_refused(analysed) -> None:
    state = copy.deepcopy(analysed)
    with pytest.raises(ValueError, match="shear_model must be one of"):
        _call(state, "calculate_scenario_uncertainty", algorithm="variance_ratio", shear_model="cubic")
    del state.ltc_results["speedsort"]
    with pytest.raises(ValueError, match="No 'speedsort' long-term correction"):
        _call(state, "calculate_scenario_uncertainty", algorithm="speedsort", shear_model="power_law_mean")


def _with_second_source(state: SessionState) -> SessionState:
    state = copy.deepcopy(state)
    era5 = state.reanalysis_interpolated["era5"]
    state.reanalysis_interpolated["merra2"] = pd.DataFrame(
        {"Spd_50m": era5["Spd_100m"] * 0.9, "Dir_50m": era5["Dir_100m"]}, index=era5.index
    )
    return state


def test_a_correction_named_against_a_source_uses_it_for_that_call_only(analysed) -> None:
    named = _with_second_source(analysed)
    config = copy.deepcopy(named.runconfig)
    by_name = _call(named, "run_ltc_variance_ratio", short_col=HUB, long_col="Spd_50m", reference_source="merra2")
    assert named.active_reference_source == "era5"
    assert named.runconfig == config

    switched = _with_second_source(analysed)
    switched.set_active_reference_source("merra2")
    by_switch = _call(switched, "run_ltc_variance_ratio", short_col=HUB, long_col="Spd_50m")
    assert _answer(by_name) == _answer(by_switch)
    era5 = analysed.ltc_results["variance_ratio"]["metrics"]
    assert by_name["metrics"] != era5


def test_an_unknown_source_is_refused(analysed) -> None:
    with pytest.raises(ValueError):
        _call(copy.deepcopy(analysed), "run_ltc_variance_ratio", short_col=HUB, long_col="Spd_100m",
              reference_source="nope")


def test_the_constant_table_holds_the_exponent_given_or_the_series_mean(analysed) -> None:
    state = copy.deepcopy(analysed)
    given = _call(state, "build_constant_shear_table", alpha=0.21)
    assert given["shear_source"] == "analyst_supplied"
    assert state.shear_table.shape == (12, 24) and np.all(state.shear_table.to_numpy() == 0.21)

    mean = float(state.shear_timeseries_df["shear_coefficient"].dropna().mean())
    site = _call(state, "build_constant_shear_table")
    assert (site["shear_source"], site["aggregation"]) == ("fitted", "site_constant")
    assert np.all(state.shear_table.to_numpy() == mean)

    state.shear_timeseries_df = None
    with pytest.raises(ValueError, match="shear series is empty"):
        _call(state, "build_constant_shear_table")


def test_extrapolation_from_named_reference_columns_uses_only_them(analysed) -> None:
    from server.tools.extrapolation import _extrapolate_to_hub_height

    through_operation = copy.deepcopy(analysed)
    _call(through_operation, "extrapolate_to_hub_height", hub_height_m=120.0, reference_columns=["Spd_80m"],
          extrapolate_reanalysis=False)
    direct = copy.deepcopy(analysed)
    _extrapolate_to_hub_height(direct, 120.0, "power_law", ["Spd_80m"], False)
    pd.testing.assert_series_equal(through_operation.timeseries_df[HUB], direct.timeseries_df[HUB])
    assert not through_operation.timeseries_df[HUB].equals(analysed.timeseries_df[HUB])
    assert json.dumps(sorted(through_operation.reanalysis_interpolated)) == json.dumps(
        sorted(analysed.reanalysis_interpolated)
    )
