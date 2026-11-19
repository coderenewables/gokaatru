"""Disclosure fields are declared, documented and actually returned (P1-7, decisions/0009).

Every field an operation declares in ``disclosure`` must have a row in README's "Disclosure
fields" table, every field in that table must belong to a declared operation (or be listed
here as coming from somewhere else), and a synthetic pipeline run must find each declared
field in its operation's response.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from server.core.sweep import SweepSpec, run_sweep
from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from server.tools.era5 import _store_coordinate

README = Path(__file__).resolve().parents[1] / "README.md"

# Rows of the README table that no operation returns, and where they come from instead.
NOT_FROM_AN_OPERATION = {
    "duplicates_skipped": "the sweep manifest; the sweep engine is HTTP-only",
    "is_interpolation": "derive_uncertainty_inputs, called by the sweep",
    "provenance.is_interpolation": "derive_uncertainty_inputs, called by the sweep",
    "inputs": "names where is_interpolation sits in that row, not a field of its own",
    "extrapolate_reanalysis": "the sweep's extrapolate stage detail, not the tool's response",
    "reanalysis_status": "the sweep's extrapolate stage detail, not the tool's response",
}

# Declared fields a response carries only in some situations, and why this run does not.
CONDITIONAL = {
    ("run_clipping_analysis", "excluded_reason"): "only when a year fails the completeness gate",
    ("list_sweeps", "in_progress"): "only on a checkpoint of an unfinished sweep",
    ("brighthub_import_location", "upstream_processing"): "a network operation, not run here",
}


def _readme_fields() -> set[str]:
    text = README.read_text(encoding="utf-8")
    section = text.split("### Disclosure fields", 1)[1].split("\n### ", 1)[0]
    fields: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        fields.update(re.findall(r"`([^`]+)`", line.split("|")[1]))
    return fields


def _declared() -> dict[str, set[str]]:
    return {op.name: set(op.disclosure) for op in REGISTRY if op.disclosure}


def test_every_declared_field_has_a_readme_row() -> None:
    documented = _readme_fields()
    undocumented = {
        f"{name}.{field}" for name, fields in _declared().items() for field in fields if field not in documented
    }
    assert undocumented == set()


def test_every_readme_row_belongs_to_an_operation_or_is_accounted_for() -> None:
    declared = set().union(*_declared().values())
    unclaimed = _readme_fields() - declared - set(NOT_FROM_AN_OPERATION)
    assert unclaimed == set()


# ---------------------------------------------------------------------------
# A synthetic pipeline, to see each declared field in a real response
# ---------------------------------------------------------------------------

SITE = (55.0, 8.0)
NODES = [(54.75, 7.75), (54.75, 8.25), (55.25, 7.75), (55.25, 8.25)]


def _paths(value: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.add(path)
            found |= _paths(item, path)
    elif isinstance(value, list):
        for item in value:
            found |= _paths(item, prefix)
    return found


def _carries(response: Any, field: str) -> bool:
    return any(path == field or path.endswith(f".{field}") for path in _paths(response))


def _reference(index: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    return np.clip(rng.weibull(2.0, len(index)) * 8.5, 0.2, None)


@pytest.fixture(scope="module")
def responses(tmp_path_factory) -> dict[str, Any]:
    rng = np.random.default_rng(23)
    workspace = tmp_path_factory.mktemp("disclosure")
    (workspace / "uploads").mkdir()
    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    state.persist_result_files = False
    out: dict[str, Any] = {}

    def run(name: str, **arguments: Any) -> None:
        with bind_session(state):
            out[name] = REGISTRY.get(name).fn(**arguments)

    long_index = pd.date_range("2008-01-01", "2021-12-31 23:00", freq="h")
    reference = _reference(long_index, rng)
    measured_index = pd.date_range("2021-01-01", "2021-12-31 23:50", freq="10min")
    on_measured = pd.Series(reference, index=long_index).reindex(measured_index, method="ffill").to_numpy()
    top = np.clip(1.05 * on_measured + rng.normal(0, 0.8, len(measured_index)), 0.1, None)
    frame = pd.DataFrame(
        {
            "Timestamp": measured_index.strftime("%Y-%m-%d %H:%M"),
            "Spd_100m": top,
            "Spd_80m": top * 0.8 ** 0.14,
            "Spd_60m": top * 0.6 ** 0.14,
            "Spd_100m_sd": top * 0.12,
            "Dir_100m": rng.uniform(0, 360, len(measured_index)),
        }
    )
    frame = pd.concat([frame, frame.iloc[[10]]]).sort_values("Timestamp")
    frame.to_csv(workspace / "uploads" / "mast.csv", index=False)
    state.runconfig["site"] = {"timezone": "UTC"}
    run("parse_timeseries", file_path=str(workspace / "uploads" / "mast.csv"))
    state.sensor_mapping = {
        100.0: {"speed_col": "Spd_100m", "dir_col": "Dir_100m", "sd_col": "Spd_100m_sd"},
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None},
        60.0: {"speed_col": "Spd_60m", "dir_col": None, "sd_col": None},
    }
    state.sensor_inventory = {
        "Spd_100m": {"height_m": 100.0, "sensor_type": "wind_speed"},
        "Spd_80m": {"height_m": 80.0, "sensor_type": "wind_speed"},
        "Spd_60m": {"height_m": 60.0, "sensor_type": "wind_speed"},
        "Dir_100m": {"height_m": 100.0, "sensor_type": "wind_direction"},
    }
    state.set_measurement_type("mast")
    state.set_hub_height_m(120.0)
    _store_coordinate(state, *SITE)

    run("apply_cleaning_rule", rule_type="range_check", sensor="Spd_100m", params="{}")
    pair = json.dumps({"80": "Spd_80m", "100": "Spd_100m"})
    run("calculate_shear_timeseries", height_sensors=pair)
    run("build_aggr_momm_shear_table", height_sensors=pair)
    run("build_sector_shear_tables", direction_sensor="Dir_100m")
    run("calculate_roughness_timeseries", height_sensors=pair)
    run("build_roughness_table")
    run("calculate_shear_timeseries", height_sensors=pair)
    run("build_shear_table")
    run("compute_diurnal_profile", sensor_name="Spd_100m")

    state.era5_nodes = [{"latitude": lat, "longitude": lon} for lat, lon in NODES]
    state.era5_data = {
        f"{float(lat)}_{float(lon)}": pd.DataFrame(
            {
                "Spd_100m": reference * rng.uniform(0.97, 1.03),
                "Dir_100m": rng.uniform(0, 360, len(long_index)),
                "t2m": rng.normal(283, 4, len(long_index)),
                "sp": rng.normal(101000, 400, len(long_index)),
                "d2m": rng.normal(278, 3, len(long_index)),
            },
            index=long_index.tz_localize("UTC"),
        )
        for lat, lon in NODES
    }
    run("interpolate_era5_to_site", source="era5")
    run("extrapolate_to_hub_height", hub_height_m=120.0)
    hub = out["extrapolate_to_hub_height"]["column_name"]

    for name in ("run_ltc_linear_least_squares", "run_ltc_total_least_squares", "run_ltc_variance_ratio"):
        run(name, short_col=hub, long_col="Spd_100m")
    run("run_ltc_speedsort", short_col=hub, long_col="Spd_100m", long_dir_col="Dir_100m")
    run("run_ltc_xgboost", short_col=hub, long_col="Spd_100m")
    run("run_ensemble", measured_col=hub)
    run("run_clipping_analysis", speed_col="Ensemble_Speed", source="ensemble")
    run(
        "calculate_uncertainty",
        measurement_uncertainty_pct=2.0,
        measurement_height_m=100.0,
        hub_height_m=120.0,
        shear_method="calculate_shear",
        mcp_r_squared=0.8,
        concurrent_hours=8760.0,
        shear_std=0.05,
    )
    run("compute_energy_sensitivity", speed_uncertainty_pct=5.0)
    for name in ("compute_weibull_params",):
        run(name, sensor_name="Spd_100m")
    for name in ("compute_mcp_readiness", "compute_turbulence_analysis", "compute_extreme_winds"):
        run(name, speed_sensor="Spd_100m")
    run("compute_qc_diagnostics")

    state.reanalysis_interpolated = {"era5": state.era5_interpolated_df.copy()}
    spec = SweepSpec(
        shear_fit_policies=("nearest_2",),
        reference_policies=("nearest_2",),
        shear_models=("power_law_mean",),
        reference_sources=("era5",),
        ltc_algorithms=("variance_ratio", "linear_least_squares", "total_least_squares"),
        hub_height_m=120.0,
    )
    sweep_id = run_sweep(state, spec, sweep_id="disclosure", persist=True)["manifest"]["sweep_id"]
    run("list_sweeps")
    run("get_sweep_summary", sweep_id=sweep_id)
    run("analyze_sweep_spread", sweep_id=sweep_id)
    run("get_fixed_prefix_hash")
    return out


@pytest.mark.parametrize(
    ("name", "field"),
    sorted((op.name, field) for op in REGISTRY for field in op.disclosure),
)
def test_a_declared_field_is_in_its_operations_response(responses, name: str, field: str) -> None:
    if (name, field) in CONDITIONAL:
        pytest.skip(CONDITIONAL[(name, field)])
    assert name in responses, f"the synthetic pipeline does not run {name}"
    assert _carries(responses[name], field), f"{name} did not return {field}"
