"""test_uploaded_dataset — Detailed regression coverage for the checked-in Boxkite upload dataset.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from server.tools.data_io import _get_data_coverage, _list_sensors
from server.tools.extrapolation import extrapolate_to_hub_height
from server.tools.shear import build_shear_table, calculate_shear_timeseries
from server.tools.statistics import _sensor_statistics


def test_uploaded_dataset_parses_expected_metadata(uploaded_dataset_session) -> None:
    """Verify the real upload fixtures parse into the expected Boxkite metadata and mapped sensors."""
    state = uploaded_dataset_session

    assert state.project_name == "HKW-B-FLS-Boxkite"
    assert state.measurement_type == "lidar"
    assert state.coordinate is not None
    assert state.coordinate.latitude == pytest.approx(52.57005)
    assert state.coordinate.longitude == pytest.approx(3.737733)
    assert len(state.timeseries_df) == 73532
    assert state.timeseries_df.index.min().isoformat() == "2019-02-10T09:00:00"
    assert state.timeseries_df.index.max().isoformat() == "2021-02-11T23:50:00"
    assert state.timeseries_df.columns.tolist() == [
        "Spd_80m",
        "Spd_100m",
        "Spd_120m",
        "Spd_140m",
        "Spd_160m",
        "Spd_180m",
        "Spd_200m",
        "Spd_250m",
        "Dir_80m",
        "Dir_100m",
        "Dir_120m",
        "Dir_140m",
        "Dir_160m",
        "Dir_180m",
        "Dir_200m",
        "Dir_250m",
    ]
    assert list(state.sensor_mapping.keys()) == [250.0, 200.0, 180.0, 160.0, 140.0, 120.0, 100.0, 80.0]
    assert state.sensor_mapping[250.0]["speed_col"] == "Spd_250m"
    assert state.sensor_mapping[100.0]["dir_col"] == "Dir_100m"


def test_uploaded_dataset_sensor_inventory_and_coverage(uploaded_dataset_session) -> None:
    """Verify the real uploaded dataset yields the expected sensor inventory and gap statistics."""
    state = uploaded_dataset_session

    sensors = _list_sensors(state)["sensors"]
    coverage_100m = _get_data_coverage(state, "Spd_100m")
    coverage_250m_dir = _get_data_coverage(state, "Dir_250m")

    assert len(sensors) == 16
    assert sensors[0]["name"] == "Spd_250m"
    assert sensors[0]["record_count"] == 64460
    assert sensors[-1]["name"] == "Dir_80m"
    assert sensors[-1]["record_count"] == 63882
    assert coverage_100m["total_records"] == 105498
    assert coverage_100m["valid_records"] == 65879
    assert coverage_100m["coverage_pct"] == pytest.approx(62.445733568408876)
    assert coverage_100m["largest_gap_minutes"] == 314310
    assert coverage_100m["gaps_over_1_hour"] == 118
    assert coverage_250m_dir["valid_records"] == 62401
    assert coverage_250m_dir["coverage_pct"] == pytest.approx(59.14898860641908)
    assert coverage_250m_dir["largest_gap_minutes"] == 335760


def test_uploaded_dataset_statistics_shear_and_extrapolation(uploaded_dataset_session) -> None:
    """Verify downstream analytics remain stable when driven by the checked-in Boxkite upload data."""
    state = uploaded_dataset_session
    height_sensors = json.dumps(
        {
            "250": "Spd_250m",
            "200": "Spd_200m",
            "180": "Spd_180m",
            "160": "Spd_160m",
            "140": "Spd_140m",
            "120": "Spd_120m",
            "100": "Spd_100m",
            "80": "Spd_80m",
        }
    )

    stats_100m = _sensor_statistics(state, "Spd_100m")
    shear = calculate_shear_timeseries(height_sensors)
    shear_table = build_shear_table("mean")
    extrapolation = extrapolate_to_hub_height(150.0)
    hub_series = state.timeseries_df["Spd_150m_hub"].dropna()

    assert stats_100m["count"] == 65879
    assert stats_100m["mean"] == pytest.approx(9.313042572291627)
    assert stats_100m["weibull_k"] == pytest.approx(2.1475840014111824)
    assert stats_100m["percentiles"]["p90"] == pytest.approx(15.537668000000005)
    assert len(stats_100m["monthly_means"]) == 12
    assert len(stats_100m["diurnal_means"]) == 24

    assert shear["status"] == "ok"
    assert shear["records"] == 66066
    assert shear["mean_shear"] == pytest.approx(0.06056611979501554)
    assert shear["median_shear"] == pytest.approx(0.05103837285018659)
    assert shear["std_shear"] == pytest.approx(0.17613917816330288)

    table = np.asarray(shear_table["table"], dtype=float)
    assert table.shape == (12, 24)
    assert np.isfinite(table).all()
    assert float(table.mean()) == pytest.approx(0.06175280233439187)

    assert extrapolation["status"] == "ok"
    assert extrapolation["column_name"] == "Spd_150m_hub"
    assert extrapolation["method_counts"] == {"direct": 0, "interpolated": 65519, "extrapolated": 757}
    assert hub_series.mean() == pytest.approx(9.612453740272263)
    assert hub_series.min() == pytest.approx(0.5296561162417128)
    assert hub_series.max() == pytest.approx(31.42907866480829)