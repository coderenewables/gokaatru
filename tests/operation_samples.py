"""A real response from every operation, as it crosses the wire (P1-19).

The synthetic pipeline (``tests/synthetic_pipeline.py``) supplies the analysis operations;
the reads then run on its analysed session, each selectable one also on a selection; the
changes the pipeline does not make run after them; and the network operations run on
sessions of their own against the fakes ``tests/test_brighthub_workflow.py`` and
``tests/test_phase3.py`` use. Each response is serialised as the generated route serialises
it (Pydantic's JSON mode, NaN as null), so a model that accepts these accepts the wire.
"""
from __future__ import annotations

import inspect
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pydantic import TypeAdapter

from server.operations import REGISTRY
from server.state.session import SessionState, bind_session
from tests.synthetic_pipeline import NODES, NORTH, READ_ARGUMENTS, SITE, run_pipeline
from tests.test_operation_routes import _populate

_WIRE = TypeAdapter(Any)



def wire(result: Any) -> str:
    return _WIRE.dump_json(result).decode("utf-8")


class Samples:
    def __init__(self) -> None:
        self.by_operation: dict[str, list[str]] = defaultdict(list)
        self.previews: dict[str, list[str]] = defaultdict(list)

    def call(self, state: SessionState, operation: str, /, **arguments: Any) -> Any:
        with bind_session(state):
            result = REGISTRY.get(operation).fn(**arguments)
        self.by_operation[operation].append(wire(result))
        return result

    def preview(self, state: SessionState, operation: str, /, **arguments: Any) -> Any:
        with bind_session(state):
            result = REGISTRY.get(operation).dry_run(**arguments)
        self.previews[operation].append(wire(result))
        return result


def _reads(samples: Samples, state: SessionState, overrides: dict[str, object] | None = None) -> None:
    """Every read, and every selectable one on a selection too. With ``overrides`` the reads
    run on another campaign, where a refusal is expected and skipped."""
    values = {**READ_ARGUMENTS, **(overrides or {})}
    samples.call(state, "define_selection", name="north", definition=NORTH)
    for declared in REGISTRY:
        if declared.effect != "read" or declared.network:
            continue
        parameters = inspect.signature(declared.fn).parameters.values()
        arguments = {
            parameter.name: values[parameter.name]
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
        }
        for extra in ({}, {"selection": "north"}) if declared.selectable else ({},):
            try:
                samples.call(state, declared.name, **arguments, **extra)
            except ValueError:
                if overrides is None:
                    raise


def _changes(samples: Samples, state: SessionState, workspace: Path) -> None:
    """The changes the pipeline does not make, in an order each can run in."""
    samples.preview(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_80m", params="{}")
    samples.call(state, "apply_cleaning_rule", rule_type="range_check", sensor="Spd_80m", params="{}")
    samples.preview(state, "undo_cleaning_rule", entry_index=1)
    samples.call(state, "undo_cleaning_rule", entry_index=1)
    drawn = json.dumps({
        "definition": {"kind": "time_range", "start": "2021-01-10T00:00:00Z", "end": "2021-01-11T00:00:00Z"},
        "sensors": ["Spd_100m_sd"],
        "reason": "icing",
        "note": "",
    })
    samples.preview(state, "apply_cleaning_rule", rule_type="exclude_selection", sensor="Spd_100m", params=drawn)
    samples.call(state, "apply_cleaning_rule", rule_type="exclude_selection", sensor="Spd_100m", params=drawn)
    samples.call(state, "get_cleaning_log")
    samples.call(state, "undo_last_change")
    samples.preview(state, "remove_sensors", sensor_names=["Spd_60m"])
    samples.call(state, "remove_sensors", sensor_names=["Spd_60m", "Nope"])
    samples.call(state, "undo_last_change")
    samples.call(state, "redo_last_change")
    samples.call(state, "undo_last_change")
    samples.call(state, "update_run_config", key="project_name", value='"Synthetic"')
    samples.call(state, "undo_last_change")
    samples.call(state, "redo_last_change")
    samples.call(state, "get_operation_log", limit=5)
    samples.call(state, "save_run_config")
    samples.call(state, "load_run_config")
    band = {"kind": "band", "channel": "Spd_100m", "min": 5.0}
    samples.call(state, "define_selection", name="scratch", definition=band)
    samples.call(state, "delete_selection", name="scratch")
    lasso = {
        "kind": "polygon",
        "x_channel": "Spd_60m",
        "y_channel": "Spd_100m",
        "vertices": [[2.0, 2.0], [12.0, 3.0], [10.0, 14.0]],
    }
    samples.call(state, "define_selection", name="lasso", definition=lasso)
    samples.call(state, "delete_selection", name="lasso")
    # Another height than the pipeline's 120 m, so the call writes a column of its own.
    samples.call(state, "extrapolate_reanalysis_to_hub", hub_height_m=110.0, reference_height_m=100.0)
    samples.call(state, "apply_homogeneity_cutoff", cutoff_year=2010)

    frame = state.timeseries_df
    frame["Tmp_2m"] = 10.0 + 5.0 * np.sin(np.arange(len(frame)) / 144.0)
    frame["Prs_2m"] = 1010.0
    state.sensor_inventory["Tmp_2m"] = {"height_m": 2.0, "sensor_type": "temperature"}
    state.sensor_inventory["Prs_2m"] = {"height_m": 2.0, "sensor_type": "pressure"}
    samples.call(state, "compute_atmospheric_conditions", temperature_sensor="Tmp_2m", pressure_sensor="Prs_2m")

    lat, lon = NODES[0]
    node = state.era5_data[f"{float(lat)}_{float(lon)}"]
    node["u100"] = node["Spd_100m"] * 0.6
    node["v100"] = node["Spd_100m"] * -0.8
    samples.call(state, "compute_era5_wind_speed", latitude=lat, longitude=lon)

    samples.call(state, "earthdatahub_set_credential", pat="synthetic-pat")
    samples.call(state, "earthdatahub_status")
    samples.call(state, "earthdatahub_clear_credential")
    samples.call(state, "brighthub_logout")

    built = samples.call(
        state,
        "build_data_model",
        spec={
            "location": {"name": "Synthetic", "offset_from_utc_hrs": 0},
            "points": [
                {"name": "Spd_100m", "measurement_type_id": "wind_speed", "height_m": 100.0},
                {"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 80.0},
                {"name": "Dir_100m", "measurement_type_id": "wind_direction", "height_m": 100.0},
            ],
        },
    )
    samples.call(state, "parse_datamodel", file_path=built["file_path"])
    edited = {
        "location": {"name": "Synthetic", "offset_from_utc_hrs": 0},
        "points": [
            {"name": "Spd_100m", "measurement_type_id": "wind_speed", "height_m": 100.0},
            {"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 82.0},
            {"name": "Dir_100m", "measurement_type_id": "wind_direction", "height_m": 100.0},
        ],
    }
    samples.call(state, "build_data_model", spec=edited)
    samples.call(state, "draft_data_model")
    samples.call(state, "undo_last_change")
    samples.call(state, "redo_last_change")


def _payload(latitude: float, longitude: float, dataset: str) -> dict:
    height = 100 if dataset == "ERA5" else 50
    index = pd.date_range("2024-01-01", periods=48, freq="h", tz="UTC")
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timeseries_data": {
            "data": [
                {
                    "timestamp": stamp.isoformat().replace("+00:00", "Z"),
                    f"Spd_{height}m_mps": 8.0 + (i % 5),
                    f"Dir_{height}m_deg": float(10 * i % 360),
                    "Tmp_2m_degC": 10.0,
                    "Prs_0m_hPa": 1010.0,
                }
                for i, stamp in enumerate(index)
            ]
        },
    }


def _network(samples: Samples, workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The network operations, each against a fake of what it calls."""
    era5_nodes = [{"latitude_ddeg": lat, "longitude_ddeg": lon, "distance_km": 20.0} for lat, lon in NODES]
    merra_nodes = [
        {"latitude_ddeg": lat + 0.1, "longitude_ddeg": lon + 0.1, "distance_km": 25.0} for lat, lon in NODES
    ]
    location = {"uuid": "site-uuid", "name": "Synthetic", "latitude_ddeg": SITE[0], "longitude_ddeg": SITE[1]}
    csv = "Timestamp,Spd_100m,Dir_100m\n" + "".join(
        f"2024-01-01T{hour:02d}:{minute:02d}:00,{8 + minute / 60:.2f},{(hour * 15) % 360}\n"
        for hour in range(24)
        for minute in range(0, 60, 10)
    )
    datamodel = {
        "author": "synthetic",
        "measurement_location": [
            {
                "name": "Synthetic",
                "latitude_ddeg": SITE[0],
                "longitude_ddeg": SITE[1],
                "measurement_station_type_id": "mast",
                "logger_main_config": [{"offset_from_utc_hrs": 0, "date_from": "2024-01-01T00:00:00"}],
                "measurement_point": [
                    {
                        "name": "Spd_100m",
                        "measurement_type_id": "wind_speed",
                        "height_m": 100.0,
                        "logger_measurement_config": [
                            {
                                "date_from": "2024-01-01T00:00:00",
                                "column_name": [{"column_name": "Spd_100m", "statistic_type_id": "avg"}],
                            }
                        ],
                    },
                    {
                        "name": "Dir_100m",
                        "measurement_type_id": "wind_direction",
                        "height_m": 100.0,
                        "logger_measurement_config": [
                            {
                                "date_from": "2024-01-01T00:00:00",
                                "column_name": [{"column_name": "Dir_100m", "statistic_type_id": "avg"}],
                            }
                        ],
                    },
                ],
            }
        ],
    }
    monkeypatch.setattr("server.tools.brighthub.authenticate", lambda *_args, **_kwargs: {"id_token": "token"})
    monkeypatch.setattr("server.tools.brighthub.list_measurement_locations", lambda *_args: [location])
    monkeypatch.setattr("server.tools.brighthub.get_data_model", lambda *_args: datamodel)
    monkeypatch.setattr("server.tools.brighthub.fetch_timeseries_csv", lambda *_args, **_kwargs: csv)
    monkeypatch.setattr(
        "server.tools.brighthub.fetch_reanalysis_nodes",
        lambda *_args: {"era5_nodes": era5_nodes, "merra2_nodes": merra_nodes},
    )
    monkeypatch.setattr(
        "server.tools.brighthub.download_reanalysis_data",
        lambda _token, nodes, dataset: [_payload(n["latitude_ddeg"], n["longitude_ddeg"], dataset) for n in nodes],
    )

    def fresh(name: str) -> SessionState:
        state = SessionState()
        state.reset()
        state.workspace_dir = workspace / name
        (state.workspace_dir / "uploads").mkdir(parents=True)
        state.persist_result_files = False
        return state

    brighthub = fresh("brighthub")
    samples.call(brighthub, "brighthub_login", client_id="synthetic-id", client_secret="synthetic-secret")
    samples.call(brighthub, "brighthub_status")
    samples.call(brighthub, "brighthub_list_locations")
    samples.call(brighthub, "brighthub_get_data_model", uuid="site-uuid")
    samples.call(brighthub, "brighthub_import_location", uuid="site-uuid", name="Synthetic")
    samples.call(brighthub, "brighthub_find_reanalysis_nodes", latitude=SITE[0], longitude=SITE[1])
    samples.call(brighthub, "brighthub_download_reanalysis", dataset="ERA5", nodes_json=json.dumps(era5_nodes))
    samples.call(brighthub, "brighthub_prepare_reanalysis", latitude=SITE[0], longitude=SITE[1])
    samples.call(brighthub, "brighthub_logout")

    lats = [SITE[0] - 0.25, SITE[0], SITE[0] + 0.25]
    lons = [SITE[1] - 0.25, SITE[1], SITE[1] + 0.25]
    times = pd.date_range("2024-01-01", periods=6, freq="h")
    shape = (len(times), len(lats), len(lons))
    dataset = xr.Dataset(
        data_vars={
            "u100": (("valid_time", "latitude", "longitude"), np.ones(shape)),
            "v100": (("valid_time", "latitude", "longitude"), np.full(shape, 2.0)),
            "sp": (("valid_time", "latitude", "longitude"), np.full(shape, 101325.0)),
            "t2m": (("valid_time", "latitude", "longitude"), np.full(shape, 288.15)),
            "d2m": (("valid_time", "latitude", "longitude"), np.full(shape, 280.15)),
        },
        coords={"valid_time": times, "latitude": lats, "longitude": lons},
    )
    era5 = fresh("era5")
    monkeypatch.setattr("server.tools.era5._open_era5_dataset", lambda *_args: dataset)
    monkeypatch.setattr(
        "server.tools.era5._era5_cache_path",
        lambda latitude, longitude: era5.workspace_dir / f"node_{latitude}_{longitude}.parquet",
    )
    samples.call(era5, "find_era5_nodes", latitude=SITE[0] + 0.1, longitude=SITE[1] + 0.1)
    samples.call(
        era5, "extract_era5_data",
        latitude=SITE[0], longitude=SITE[1], start_date="2024-01-01", end_date="2024-01-01T05:00:00",
    )


def collect(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Samples:
    samples = Samples()
    state, calls = run_pipeline(workspace / "pipeline")
    for name, _, result in calls:
        samples.by_operation[name].append(wire(result))
    _reads(samples, state)
    # A 120-day mast with met channels and no reanalysis reaches branches a full year does not:
    # partial-year warnings, unobserved months, measured density.
    short = SessionState()
    _populate(short)
    _reads(samples, short, {"pressure_col": "Prs_2m", "temperature_col": "Tmp_2m", "dewpoint_col": "Dew_2m"})
    _changes(samples, state, workspace)
    _network(samples, workspace, monkeypatch)
    return samples
