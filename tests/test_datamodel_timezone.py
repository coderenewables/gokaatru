"""A data model cannot declare another timezone for records already put into UTC (P2-7a).

The first data model localises the record index and converts it to UTC. A later one that
declared a different timezone used to leave the index as the first converted it while the
session recorded the new zone, so every local-time figure would have been read with an
offset the records were never converted with.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.datamodel_builder import _build_data_model


def _state(workspace: Path) -> SessionState:
    state = SessionState()
    state.reset()
    (workspace / "uploads").mkdir(parents=True)
    state.workspace_dir = workspace
    index = pd.date_range("2023-01-01", periods=500, freq="10min")
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(
        {"Spd_80m": rng.weibull(2.0, 500) * 7.0, "Dir_80m": rng.uniform(0, 360, 500)}, index=index
    )
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    return state


def _spec(offset: float) -> dict:
    return {
        "location": {"name": "Bench", "offset_from_utc_hrs": offset},
        "points": [
            {"name": "Spd_80m", "measurement_type_id": "wind_speed", "height_m": 80.0},
            {"name": "Dir_80m", "measurement_type_id": "wind_direction", "height_m": 80.0},
        ],
    }


def test_a_rebuild_with_the_same_timezone_is_accepted(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _build_data_model(state, _spec(1))
    converted = state.timeseries_df.index.copy()
    assert str(converted[0]) == "2022-12-31 23:00:00+00:00"
    _build_data_model(state, _spec(1))
    assert state.timeseries_df.index.equals(converted)


def test_a_rebuild_with_another_timezone_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _build_data_model(state, _spec(1))
    before = (str(state.timezone), dict(state.runconfig["site"]), state.timeseries_df.index.copy())
    refusal = "put into UTC with the timezone UTC\\+01:00; this data model declares UTC\\+02:00"
    with pytest.raises(ValueError, match=refusal):
        _build_data_model(state, _spec(2))
    assert (str(state.timezone), dict(state.runconfig["site"])) == before[:2]
    assert state.timeseries_df.index.equals(before[2])
