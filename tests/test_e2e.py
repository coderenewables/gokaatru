"""test_e2e — End-to-end workflow validation for GoKaatru.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from server.state.session import session
from server.tools.cleaning import apply_cleaning_rule, get_cleaning_log
from server.tools.config import save_run_config, update_run_config
from server.tools.data_io import list_sensors, parse_timeseries
from server.tools.extrapolation import extrapolate_to_hub_height
from server.tools.shear import build_shear_table, calculate_shear_timeseries
from server.tools.statistics import compute_weibull_params


def test_full_wra_workflow(sample_timeseries_df: pd.DataFrame, tmp_path: Path, monkeypatch) -> None:
    """Simulate the core wind-resource workflow from ingest through config persistence."""
    monkeypatch.chdir(tmp_path)
    csv_path = tmp_path / "test_data.csv"
    sample_timeseries_df.to_csv(csv_path)

    result = parse_timeseries(str(csv_path))
    assert result["status"] == "ok"

    session.sensor_mapping = {
        100.0: {
            "speed_col": "Spd_100m",
            "dir_col": "Dir_100m",
            "sd_col": "Spd_100m_sd",
            "temp_col": None,
            "pressure_col": None,
        },
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": None, "temp_col": None, "pressure_col": None},
        60.0: {"speed_col": "Spd_60m", "dir_col": None, "sd_col": None, "temp_col": None, "pressure_col": None},
    }

    update_run_config("location.latitude", "52.4")
    update_run_config("location.longitude", "4.8")
    update_run_config("hub_height_m", "150")

    sensors = list_sensors()
    assert len(sensors["sensors"]) >= 3

    apply_cleaning_rule("range_check", "Spd_100m", '{"min": 0.3, "max": 40.0}')
    log = get_cleaning_log()
    assert len(log["entries"]) == 1

    height_sensors = json.dumps({"100": "Spd_100m", "80": "Spd_80m", "60": "Spd_60m"})
    calculate_shear_timeseries(height_sensors)
    build_shear_table("momm")

    extrapolate_to_hub_height(150.0)
    assert session.timeseries_df is not None
    assert "Spd_150m_hub" in session.timeseries_df.columns

    weibull = compute_weibull_params("Spd_100m")
    assert weibull["k"] > 0

    save_result = save_run_config()
    assert Path(save_result["file_path"]).exists()
    assert session.runconfig["hub_height_m"] == 150
