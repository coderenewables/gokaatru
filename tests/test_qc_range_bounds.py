"""P0-4: the QC diagnostic counts range failures with the range rule's bounds."""

from __future__ import annotations

import numpy as np
import pandas as pd

from server.state.session import SessionState
from server.tools import diagnostics
from server.tools.cleaning import _apply_cleaning_rule
from server.tools.diagnostics import _compute_qc_diagnostics


def _qc_session(sensor_type_inventory: str | None = None) -> SessionState:
    rng = np.random.default_rng(3)
    n = 300
    speeds = rng.uniform(2.0, 20.0, n)
    speeds[:10] = -3.0
    speeds[10:25] = 55.0
    speeds[25:30] = np.nan
    frame = pd.DataFrame({"Spd_80m": speeds}, index=pd.date_range("2024-01-01", periods=n, freq="10min"))
    state = SessionState()
    state.timeseries_df = frame.copy()
    state.raw_timeseries_df = frame.copy()
    if sensor_type_inventory is None:
        state.sensor_mapping = {80.0: {"speed_col": "Spd_80m"}}
    else:
        state.sensor_inventory = {"Spd_80m": {"sensor_type": sensor_type_inventory, "height_m": 80.0}}
    return state


def test_qc_range_failures_match_the_range_rule() -> None:
    rule_state = _qc_session()
    before = int(rule_state.timeseries_df["Spd_80m"].notna().sum())
    _apply_cleaning_rule(rule_state, "range_check", "Spd_80m", "{}")
    removed = before - int(rule_state.timeseries_df["Spd_80m"].notna().sum())

    qc = _compute_qc_diagnostics(_qc_session())
    row = qc["sensors"][0]

    assert removed == 25
    assert row["range_failures"] == removed
    assert (row["range_min"], row["range_max"]) == (0.0, 50.0)
    assert row["range_bounds_source"] == "sensor_type_table"


def test_qc_unknown_type_counts_zero_and_says_so(monkeypatch) -> None:
    """Unreachable via a normal session (candidates are always wind_speed); pinned so the fallback stays honest."""
    state = _qc_session("mystery_sensor")
    monkeypatch.setattr(diagnostics, "_speed_candidates", lambda _state: ["Spd_80m"])
    row = _compute_qc_diagnostics(state)["sensors"][0]

    assert row["range_bounds_source"] == "sensor_data_range"
    assert row["range_failures"] == 0
    assert row["range_min"] == -3.0
    assert row["range_max"] == 55.0
