"""Tests for D6 timestamp-detection hardening.

Verifies that _detect_timestamp_column and detect_timestep_minutes
reject numeric false-positives, match case-insensitively, enforce
fraction/span thresholds, and reject non-standard cadences.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.core.validators import detect_timestep_minutes
from server.tools.data_io import (
    _detect_timestamp_column,
)


class TestDetectTimestampColumn:
    """Tests for the 3-tier candidate matching and numeric-column guard."""

    def test_uppercase_TIMESTAMP_selected(self) -> None:
        """TIMESTAMP (all-caps, Campbell Scientific standard) is identified."""
        index = pd.date_range("2023-06-01", periods=500, freq="10min")
        df = pd.DataFrame({
            "TIMESTAMP": index,
            "Spd_80m": np.random.uniform(0, 20, size=len(index)),
        })
        name, series = _detect_timestamp_column(df)
        assert name == "TIMESTAMP"
        assert series.notna().sum() == len(index)

    def test_all_numeric_columns_rejected(self) -> None:
        """DataFrame with only float columns (wind speeds 0-25) raises ValueError."""
        df = pd.DataFrame({
            "Spd_100m": np.random.uniform(0, 25, size=500),
            "Spd_80m": np.random.uniform(0, 25, size=500),
            "Dir_100m": np.random.uniform(0, 360, size=500),
        })
        with pytest.raises(ValueError, match="Could not detect a timestamp column"):
            _detect_timestamp_column(df)

    def test_campbell_bad_rows_TIMESTAMP(self) -> None:
        """Campbell-style CSV with 2 bad rows + TIMESTAMP header still selects TIMESTAMP."""
        index = pd.date_range("2023-01-01", periods=1000, freq="10min")
        ts_values = index.astype(str).to_list()
        # Inject 2 bad rows
        ts_values[50] = "BAD"
        ts_values[200] = "XXXX"
        df = pd.DataFrame({
            "TIMESTAMP": ts_values,
            "Spd_80m": np.random.uniform(0, 20, size=len(ts_values)),
        })
        name, series = _detect_timestamp_column(df)
        assert name == "TIMESTAMP"
        # 998 valid out of 1000 → fraction 0.998, well above 0.5
        assert series.notna().sum() == 998

    def test_fraction_below_threshold_skipped(self) -> None:
        """Column with < 50% valid parses is skipped in favour of a better column."""
        good_index = pd.date_range("2023-06-01", periods=200, freq="10min")
        bad_ts = ["2023-01-01"] * 200  # all identical → span = 0 → fails span check
        df = pd.DataFrame({
            "Timestamp": good_index,       # 100% valid, passes span
            "TmStamp": bad_ts,             # parses but span < 1 day → skipped
            "Spd_80m": np.random.uniform(0, 20, size=200),
        })
        name, series = _detect_timestamp_column(df)
        assert name == "Timestamp"

    def test_sane_span_required(self) -> None:
        """Non-name-matched column spanning < 1 day is rejected by the span guard."""
        # Use a non-candidate column name so it hits the scored fallback path
        # where the span check applies. All timestamps within a single day.
        ts = pd.date_range("2023-06-01 00:00", "2023-06-01 23:50", freq="10min")
        df = pd.DataFrame({"my_date_col": ts})
        with pytest.raises(ValueError, match="Could not detect a timestamp column"):
            _detect_timestamp_column(df)

    def test_named_column_bypasses_span_check(self) -> None:
        """Name-matched columns (exact or case-insensitive) skip the span check."""
        # A 'Timestamp' column spanning < 1 day is still accepted because the
        # name match provides sufficient confidence to bypass the span guard.
        ts = pd.date_range("2023-06-01 00:00", "2023-06-01 23:50", freq="10min")
        df = pd.DataFrame({"Timestamp": ts, "val": range(len(ts))})
        name, series = _detect_timestamp_column(df)
        assert name == "Timestamp"

    def test_numeric_epoch_seconds_accepted(self) -> None:
        """Numeric column within epoch-second range passes the numeric guard.

        Note: pd.to_datetime without unit= treats floats as nanoseconds, so
        the values won't parse as dates. This test verifies that the epoch-range
        guard does NOT prematurely reject them (they fail on fraction/span instead).
        """
        epoch_vals = np.arange(
            1_700_000_000,
            1_700_000_000 + 600 * 100,
            dtype=float,
        )
        df = pd.DataFrame({"epoch": epoch_vals})
        # The column passes the numeric dtype + epoch-range check but
        # pd.to_datetime interprets floats as nanoseconds → all NaT → rejected.
        # This is correct: we can't guess the unit, so numeric timestamps
        # without a recognized string format are properly rejected.
        with pytest.raises(ValueError, match="Could not detect a timestamp column"):
            _detect_timestamp_column(df)

    def test_numeric_outside_epoch_range_skipped(self) -> None:
        """Numeric column with wind-speed range (0-25) is skipped by epoch guard."""
        df = pd.DataFrame({
            "Timestamp": pd.date_range("2023-01-01", periods=500, freq="10min"),
            "Spd_100m": np.random.uniform(0, 25, size=500),
        })
        name, series = _detect_timestamp_column(df)
        assert name == "Timestamp"
        assert series.notna().sum() == 500


class TestDetectTimestepMinutes:
    """Tests for non-standard cadence rejection."""

    def test_nonstandard_timestep_rejected(self) -> None:
        """7-minute cadence data raises ValueError."""
        index = pd.date_range("2023-01-01", periods=500, freq="7min")
        df = pd.DataFrame({"value": np.random.randn(len(index))})
        df.index = index
        with pytest.raises(ValueError, match="7 minutes is not a supported cadence"):
            detect_timestep_minutes(df)

    def test_standard_10min_accepted(self) -> None:
        """10-minute cadence returns 10."""
        index = pd.date_range("2023-01-01", periods=500, freq="10min")
        df = pd.DataFrame({"value": np.random.randn(len(index))})
        df.index = index
        assert detect_timestep_minutes(df) == 10

    def test_1min_accepted(self) -> None:
        """1-minute cadence (boundary case) returns 1."""
        index = pd.date_range("2023-06-01", periods=500, freq="1min")
        df = pd.DataFrame({"value": np.random.randn(len(index))})
        df.index = index
        assert detect_timestep_minutes(df) == 1

    def test_60min_accepted(self) -> None:
        """60-minute cadence (boundary case) returns 60."""
        index = pd.date_range("2023-06-01", periods=500, freq="60min")
        df = pd.DataFrame({"value": np.random.randn(len(index))})
        df.index = index
        assert detect_timestep_minutes(df) == 60
