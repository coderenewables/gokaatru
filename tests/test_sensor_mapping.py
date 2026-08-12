"""Tests for D7 sensor mapping boom-pair resolution.

Verifies that _build_sensor_mapping collects all sensors per height,
resolves boom pairs deterministically, and persists resolution to runconfig.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.state.session import session
from server.tools.data_io import (
    _build_sensor_mapping,
    _parse_datamodel,
    _parse_timeseries,
)


def _make_points(
    sensors: list[dict],
) -> list[dict[str, object]]:
    """Wrap sensor definitions in the structure _extract_measurement_points would return."""
    return [
        {
            "name": s["name"],
            "height_m": s["height_m"],
            "measurement_type_id": s["type"],
            **({"is_primary": s.get("is_primary")} if "is_primary" in s else {}),
        }
        for s in sensors
    ]


class TestBuildSensorMapping:
    """Unit tests for the rewritten _build_sensor_mapping."""

    def test_single_sensor_per_height(self) -> None:
        """Standard datamodel, no boom pairs → mapping unchanged from prior behavior."""
        points = _make_points([
            {"name": "Spd_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Dir_80m", "height_m": 80.0, "type": "wind_direction"},
            {"name": "Spd_60m", "height_m": 60.0, "type": "wind_speed"},
        ])
        mapping, log = _build_sensor_mapping(points)
        assert log == []
        assert 80.0 in mapping
        assert mapping[80.0]["speed_col"] == "Spd_80m"
        assert mapping[80.0]["dir_col"] == "Dir_80m"
        assert mapping[80.0]["sd_col"] == "Spd_80m_sd"
        assert mapping[60.0]["speed_col"] == "Spd_60m"

    def test_boom_pair_resolved_by_primary(self) -> None:
        """Two speed sensors at same height, one with is_primary: true → primary wins."""
        points = _make_points([
            {"name": "Spd_N_80m", "height_m": 80.0, "type": "wind_speed", "is_primary": True},
            {"name": "Spd_S_80m", "height_m": 80.0, "type": "wind_speed", "is_primary": False},
        ])
        mapping, log = _build_sensor_mapping(points)
        assert mapping[80.0]["speed_col"] == "Spd_N_80m"
        assert len(log) == 1
        assert log[0]["resolution"] == "primary_flag"
        assert log[0]["chosen"] == "Spd_N_80m"

    def test_boom_pair_resolved_by_name(self) -> None:
        """Two speed sensors, no primary flag → alphabetical name selection."""
        points = _make_points([
            {"name": "Spd_S_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Spd_N_80m", "height_m": 80.0, "type": "wind_speed"},
        ])
        mapping, log = _build_sensor_mapping(points)
        assert mapping[80.0]["speed_col"] == "Spd_N_80m"
        assert len(log) == 1
        assert log[0]["resolution"] == "name_alphabetical"

    def test_boom_pair_resolved_by_coverage(self) -> None:
        """Two speed sensors, no primary, timeseries loaded → higher coverage wins."""
        points = _make_points([
            {"name": "Spd_S_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Spd_N_80m", "height_m": 80.0, "type": "wind_speed"},
        ])
        # Create a timeseries where Spd_S_80m has more valid data
        index = pd.date_range("2023-06-01", periods=200, freq="10min")
        ts_df = pd.DataFrame({
            "Spd_N_80m": np.random.randn(len(index)),
            "Spd_S_80m": np.random.randn(len(index)),
        }, index=index)
        ts_df.loc[ts_df.index[:100], "Spd_N_80m"] = np.nan  # 50% coverage
        # Spd_S_80m has 100% coverage → wins
        mapping, log = _build_sensor_mapping(points, timeseries_df=ts_df)
        assert mapping[80.0]["speed_col"] == "Spd_S_80m"
        assert log[0]["resolution"] == "coverage"

    def test_three_sensors_same_height(self) -> None:
        """Three speed sensors at same height → resolves to one."""
        points = _make_points([
            {"name": "Spd_E_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Spd_W_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Spd_N_80m", "height_m": 80.0, "type": "wind_speed", "is_primary": True},
        ])
        mapping, log = _build_sensor_mapping(points)
        assert mapping[80.0]["speed_col"] == "Spd_N_80m"
        assert log[0]["chosen"] == "Spd_N_80m"

    def test_datamodel_order_independence(self) -> None:
        """Same boom-pair sensors in different JSON order → identical mapping output."""
        order_a = _make_points([
            {"name": "Spd_S_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Spd_N_80m", "height_m": 80.0, "type": "wind_speed"},
        ])
        order_b = _make_points([
            {"name": "Spd_N_80m", "height_m": 80.0, "type": "wind_speed"},
            {"name": "Spd_S_80m", "height_m": 80.0, "type": "wind_speed"},
        ])
        mapping_a, _ = _build_sensor_mapping(order_a)
        mapping_b, _ = _build_sensor_mapping(order_b)
        assert mapping_a[80.0]["speed_col"] == mapping_b[80.0]["speed_col"]

    def test_output_type_backward_compatible(self) -> None:
        """Output type is dict[float, dict[str, str | None]] as required by 10+ consumers."""
        points = _make_points([
            {"name": "Spd_80m", "height_m": 80.0, "type": "wind_speed"},
        ])
        mapping, _ = _build_sensor_mapping(points)
        # Verify dict[float, dict[str, str | None]]
        for height, sensor_map in mapping.items():
            assert isinstance(height, float)
            assert isinstance(sensor_map, dict)
            for key, value in sensor_map.items():
                assert isinstance(key, str)
                assert value is None or isinstance(value, str)


class TestSensorResolutionInRunconfig:
    """Integration test for resolution persistence via _parse_datamodel."""

    def test_resolution_persisted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After boom-pair resolution, runconfig contains sensor_resolution entry."""
        session.reset()
        uploads = tmp_path / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(session, "workspace_dir", tmp_path)

        # Create a datamodel with boom pair
        dm = {
            "measurement_location": [
                {
                    "name": "TestBoom",
                    "latitude_ddeg": 10.0,
                    "longitude_ddeg": 20.0,
                    "logger_main_config": [{"offset_from_utc_hrs": 0}],
                    "measurement_point": [
                        {"name": "Spd_N_80m", "height_m": 80.0, "measurement_type_id": "wind_speed",
                         "is_primary": True},
                        {"name": "Spd_S_80m", "height_m": 80.0, "measurement_type_id": "wind_speed"},
                        {"name": "Dir_80m", "height_m": 80.0, "measurement_type_id": "wind_direction"},
                    ],
                }
            ]
        }
        dm_path = uploads / "test_boom.json"
        dm_path.write_text(json.dumps(dm), encoding="utf-8")

        # Also create a matching timeseries so the mapping isn't pruned
        index = pd.date_range("2023-06-01", periods=200, freq="10min")
        ts_df = pd.DataFrame({
            "Timestamp": index,
            "Spd_N_80m": range(len(index)),
            "Spd_S_80m": range(len(index)),
            "Dir_80m": range(len(index)),
        })
        ts_path = uploads / "test_ts.csv"
        ts_df.to_csv(ts_path, index=False)

        _parse_timeseries(session, "test_ts.csv")
        _parse_datamodel(session, "test_boom.json")

        site = session.runconfig.get("site", {})
        assert "sensor_resolution" in site
        assert len(site["sensor_resolution"]) >= 1
        assert site["sensor_resolution"][0]["chosen"] == "Spd_N_80m"
