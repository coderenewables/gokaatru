"""The campaign's instruments, each with the statistic columns it logs (P2-12, decisions/0014.2).

The data tree draws them and a flag covers a whole instrument by default, so an instrument's
standard deviation, minimum and maximum columns must be found for any header convention the
data model builder reads, and a column that belongs to no instrument must still be listed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.operations import REGISTRY
from server.state.session import SessionState, bind_session


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    index = pd.date_range("2023-01-01", periods=10, freq="10min", tz="UTC")
    columns = [
        "WS_100m_Avg", "WS_100m_SD", "WS_100m_Max", "WS_100m_Min", "Spd_80m", "Spd_80m_sd", "WD_100m_Avg",
        "AirTemp_100m_Avg", "Spd_40m", "LoggerBattVolt",
    ]
    state.timeseries_df = pd.DataFrame(np.ones((10, len(columns))), index=index, columns=columns)
    state.sensor_inventory = {
        "Spd_80m": {"height_m": 80.0, "sensor_type": "wind_speed"},
        "WS_100m_Avg": {"height_m": 100.0, "sensor_type": "wind_speed", "boom_orientation_deg": 45.0},
        "WD_100m_Avg": {"height_m": 100.0, "sensor_type": "wind_direction"},
        "AirTemp_100m_Avg": {"height_m": 100.0, "sensor_type": "temperature"},
        "Spd_120m": {"height_m": 120.0, "sensor_type": "wind_speed"},
    }
    state.sensor_mapping = {
        100.0: {"speed_col": "WS_100m_Avg", "dir_col": "WD_100m_Avg", "sd_col": "WS_100m_SD",
                "temp_col": "AirTemp_100m_Avg"},
        80.0: {"speed_col": "Spd_80m", "dir_col": None, "sd_col": "Spd_80m_sd"},
    }
    return state


def test_each_instrument_carries_its_statistic_columns_highest_first() -> None:
    state = _state()
    with bind_session(state):
        result = REGISTRY.get("list_instruments").fn()
    by_name = {entry["name"]: entry for entry in result["instruments"]}
    assert [entry["name"] for entry in result["instruments"]] == [
        "Spd_120m", "AirTemp_100m_Avg", "WD_100m_Avg", "WS_100m_Avg", "Spd_80m",
    ]
    assert by_name["WS_100m_Avg"]["statistics"] == ["WS_100m_Max", "WS_100m_Min", "WS_100m_SD"]
    assert by_name["WS_100m_Avg"]["mapped_as"] == "speed_col" and by_name["WS_100m_Avg"]["boom_orientation_deg"] == 45.0
    assert by_name["Spd_80m"]["statistics"] == ["Spd_80m_sd"]
    assert by_name["WD_100m_Avg"]["mapped_as"] == "dir_col" and by_name["WD_100m_Avg"]["statistics"] == []
    assert by_name["Spd_120m"]["in_data"] is False and by_name["Spd_120m"]["mapped_as"] is None
    assert result["heights"] == [120.0, 100.0, 80.0]
    assert {entry["name"]: entry["role"] for entry in result["other_channels"]} == {
        "Spd_40m": "measurement",
        "LoggerBattVolt": "ignored",
    }


def test_without_data_every_instrument_is_listed_with_no_statistics() -> None:
    state = _state()
    state.timeseries_df = None
    with bind_session(state):
        result = REGISTRY.get("list_instruments").fn()
    assert len(result["instruments"]) == 5 and result["other_channels"] == []
    assert all(entry["statistics"] == [] and entry["in_data"] is False for entry in result["instruments"])
