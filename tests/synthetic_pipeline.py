"""A synthetic campaign run through the whole pipeline, operation by operation.

One year of 10-minute mast data at three heights, fourteen years of hourly reanalysis on
four nodes, every long-term correction, the ensemble, clipping, uncertainty and a small
sweep. Shared by the disclosure-field and result-model tests, which both need a real
response from as many operations as can run without a network.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from server.core.spatial import bearing_compass, haversine_km
from server.core.sweep import SweepSpec, run_sweep
from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from server.tools.era5 import _store_coordinate

SITE = (55.0, 8.0)
#: Required parameters of the reads, as they apply to the analysed session.
READ_ARGUMENTS: dict[str, object] = {
    "sensor_name": "Spd_100m",
    "speed_sensor": "Spd_100m",
    "sensor_a": "Spd_100m",
    "sensor_b": "Spd_80m",
    "direction_sensor": "Dir_100m",
    "sd_sensor": "Spd_100m_sd",
    "sensor_names": "Spd_100m,Spd_80m",
    "channels": "Spd_100m,Spd_80m",
    "x_channel": "Spd_80m",
    "y_channel": "Spd_100m",
    "sweep_id": "disclosure",
    # Known only once the sweep has run: read_arguments() fills it in.
    "config_hash": "",
    "name": "north",
    "speed_col": "Ensemble_Speed",
    "pressure_pa": 101325.0,
    "temperature_k": 288.15,
    "dewpoint_k": 280.0,
    "pressure_col": "sp",
    "temperature_col": "t2m",
    "dewpoint_col": "d2m",
    "total_pct": 10.0,
    "measurement_pct": 2.0,
    "vertical_pct": 3.0,
    "mcp_pct": 4.0,
    "future_pct": 5.0,
    # A pipeline of the shear steps the synthetic pipeline ran, and a read after them.
    "steps": [
        {"id": "series", "operation": "calculate_shear_timeseries",
         "parameters": {"height_sensors": json.dumps({"80": "Spd_80m", "100": "Spd_100m"})}},
        {"id": "table", "operation": "build_shear_table", "parameters": {}},
        {"id": "weibull", "operation": "compute_weibull_params", "parameters": {"sensor_name": "Spd_100m"}},
    ],
}
#: A selection the reads can name: the northern sector, wrapping through 0.
NORTH = {"kind": "sector", "channel": "Dir_100m", "from_deg": 300.0, "to_deg": 60.0}
NODES = [(54.75, 7.75), (54.75, 8.25), (55.25, 7.75), (55.25, 8.25)]


def read_arguments(state: SessionState) -> dict[str, object]:
    """``READ_ARGUMENTS`` with a scenario of the pipeline's own sweep, whose config hash is only
    known once it has run."""
    from server.core.sweep import load_sweep

    return {**READ_ARGUMENTS, "config_hash": load_sweep(state, "disclosure")["results"][0]["config_hash"]}


def add_met_sensors(state: SessionState) -> None:
    """A temperature and a pressure sensor at 2 m, for the reads that need them (the
    atmospheric diagnostic); added after the pipeline, so its results stay as they were."""
    frame = state.timeseries_df
    frame["Tmp_2m"] = 10.0 + 5.0 * np.sin(np.arange(len(frame)) / 144.0)
    frame["Prs_2m"] = 1010.0
    state.sensor_inventory["Tmp_2m"] = {"height_m": 2.0, "sensor_type": "temperature"}
    state.sensor_inventory["Prs_2m"] = {"height_m": 2.0, "sensor_type": "pressure"}


def _reference(index: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    return np.clip(rng.weibull(2.0, len(index)) * 8.5, 0.2, None)


def run_pipeline(workspace: Path) -> tuple[SessionState, list[tuple[str, dict[str, Any], Any]]]:
    """Run the pipeline in ``workspace``; return the session and every call, in order."""
    rng = np.random.default_rng(23)
    (workspace / "uploads").mkdir(parents=True)
    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    state.persist_result_files = False
    out: dict[str, Any] = {}
    calls: list[tuple[str, dict[str, Any], Any]] = []

    def run(name: str, **arguments: Any) -> None:
        with bind_session(state):
            out[name] = REGISTRY.get(name).fn(**arguments)
        calls.append((name, arguments, out[name]))

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

    state.era5_nodes = [
        {
            "latitude": lat,
            "longitude": lon,
            "distance_km": haversine_km(*SITE, lat, lon),
            "bearing": bearing_compass(*SITE, lat, lon),
        }
        for lat, lon in NODES
    ]
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
    run("get_series_window", channels="Spd_100m")
    run("get_flag_intervals", channels="Spd_100m")

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
    return state, calls
