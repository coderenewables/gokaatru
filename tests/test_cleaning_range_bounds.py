"""Regression tests for D16 — range_check bounds must follow the sensor type.

The old defaults (0-50) were wind-speed specific but the rule is applied to any
sensor, so running it on a direction channel destroyed everything above 50 deg
and logged the operation as a legitimate cleaning step.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.cleaning import RANGE_CHECK_BOUNDS, RULES, _apply_cleaning_rule

N = 200


def _state_with_sensors() -> SessionState:
    """Session holding one sensor of each physical type, with a typed inventory."""
    index = pd.date_range("2021-01-01", periods=N, freq="10min", tz="UTC")
    frame = pd.DataFrame(
        {
            "Spd_80m": np.linspace(0.0, 30.0, N),
            "Dir_80m": np.linspace(0.0, 359.0, N),
            "T_80m": np.linspace(-20.0, 35.0, N),
            "P_80m": np.linspace(95000.0, 103000.0, N),
            "RH_80m": np.linspace(10.0, 99.0, N),
            "Mystery_80m": np.linspace(-500.0, 500.0, N),
        },
        index=index,
    )
    state = SessionState()
    state.reset()
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_inventory = {
        "Spd_80m": {"height_m": 80.0, "sensor_type": "wind_speed"},
        "Dir_80m": {"height_m": 80.0, "sensor_type": "wind_direction"},
        "T_80m": {"height_m": 80.0, "sensor_type": "temperature"},
        "P_80m": {"height_m": 80.0, "sensor_type": "pressure"},
        "RH_80m": {"height_m": 80.0, "sensor_type": "humidity"},
        "Mystery_80m": {"height_m": 80.0, "sensor_type": "unknown"},
    }
    return state


def _run(state: SessionState, sensor: str, params: dict | None = None) -> dict:
    return _apply_cleaning_rule(state, "range_check", sensor, json.dumps(params or {}))


class TestTypedBounds:
    """D16 — known sensor types use the physical table."""

    def test_direction_channel_is_not_destroyed(self) -> None:
        """The headline defect: 172 of 200 direction records were nulled."""
        state = _state_with_sensors()
        result = _run(state, "Dir_80m")

        assert result["records_affected"] == 0
        assert result["bounds_source"] == "sensor_type_table"
        assert (result["min_applied"], result["max_applied"]) == (0.0, 360.0)
        assert state.timeseries_df["Dir_80m"].notna().sum() == N

    @pytest.mark.parametrize(
        ("sensor", "sensor_type"),
        [
            ("Spd_80m", "wind_speed"),
            ("Dir_80m", "wind_direction"),
            ("T_80m", "temperature"),
            ("P_80m", "pressure"),
            ("RH_80m", "humidity"),
        ],
    )
    def test_each_type_uses_its_own_bounds(self, sensor: str, sensor_type: str) -> None:
        state = _state_with_sensors()
        result = _run(state, sensor)
        expected_min, expected_max = RANGE_CHECK_BOUNDS[sensor_type]

        assert result["sensor_type"] == sensor_type
        assert result["min_applied"] == expected_min
        assert result["max_applied"] == expected_max
        # None of the fixture data is out of physical range.
        assert result["records_affected"] == 0

    def test_out_of_range_speed_is_still_removed(self) -> None:
        """The rule must still do its job on the type it was written for."""
        state = _state_with_sensors()
        state.timeseries_df.loc[state.timeseries_df.index[:3], "Spd_80m"] = 120.0
        result = _run(state, "Spd_80m")
        assert result["records_affected"] == 3


class TestUnknownTypeFallback:
    """DECIDED — unknown type falls back to the sensor's own data range."""

    def test_unknown_type_is_a_no_op(self) -> None:
        state = _state_with_sensors()
        result = _run(state, "Mystery_80m")

        assert result["bounds_source"] == "sensor_data_range"
        assert result["records_affected"] == 0
        assert result["min_applied"] == -500.0
        assert result["max_applied"] == 500.0
        assert state.timeseries_df["Mystery_80m"].notna().sum() == N

    def test_no_op_is_stated_not_implied(self) -> None:
        """The log must not suggest a check happened when none could have."""
        state = _state_with_sensors()
        result = _run(state, "Mystery_80m")
        assert "no-op" in result["note"]

    def test_does_not_fall_back_to_speed_defaults(self) -> None:
        state = _state_with_sensors()
        result = _run(state, "Mystery_80m")
        assert (result["min_applied"], result["max_applied"]) != (0.0, 50.0)


class TestExplicitBoundsWin:
    """Explicit user-supplied bounds always take precedence."""

    def test_explicit_bounds_override_the_table(self) -> None:
        state = _state_with_sensors()
        result = _run(state, "Dir_80m", {"min": 0.0, "max": 50.0})

        assert result["bounds_source"] == "explicit"
        assert result["records_affected"] > 0

    def test_explicit_bounds_override_the_data_range(self) -> None:
        state = _state_with_sensors()
        result = _run(state, "Mystery_80m", {"min": -100.0, "max": 100.0})

        assert result["bounds_source"] == "explicit"
        assert result["records_affected"] > 0


class TestAuditTrail:
    """The cleaning log is an audit artifact — it must record what was applied."""

    def test_log_entry_records_resolved_bounds(self) -> None:
        state = _state_with_sensors()
        _run(state, "Dir_80m")
        entry = state.cleaning_log[-1]

        assert entry["bounds_source"] == "sensor_type_table"
        assert entry["min_applied"] == 0.0
        assert entry["max_applied"] == 360.0

    def test_advertised_defaults_no_longer_carry_speed_bounds(self) -> None:
        """Echoing {"min": 0, "max": 50} back as the default is what caused D16."""
        assert RULES["range_check"] == {}
