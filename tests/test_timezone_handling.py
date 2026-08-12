"""Tests for D8 per-campaign timezone handling.

Verifies that timezone is extracted from the datamodel, applied to
timeseries indexes, persisted to runconfig, and that ERA5 indexes
are tz-aware UTC.
"""
from __future__ import annotations

import json
from datetime import timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from server.state.session import session
from server.tools.data_io import (
    _apply_timezone_to_index,
    _extract_timezone,
    _parse_datamodel,
    _parse_timeseries,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = REPO_ROOT / "data" "uploads"


def _make_datamodel(offset_hrs: int | float = 0, *, iana: str | None = None) -> dict:
    """Build a minimal IEA Task 43 datamodel stub for testing."""
    dm: dict = {
        "measurement_location": [
            {
                "name": "TestSite",
                "latitude_ddeg": 10.0,
                "longitude_ddeg": 20.0,
                "logger_main_config": [
                    {"offset_from_utc_hrs": offset_hrs}
                ],
                "measurement_point": [
                    {
                        "name": "Spd_80m",
                        "height_m": 80.0,
                        "measurement_type_id": "wind_speed",
                    },
                    {
                        "name": "Dir_80m",
                        "height_m": 80.0,
                        "measurement_type_id": "wind_direction",
                    },
                ],
            }
        ]
    }
    if iana is not None:
        dm["measurement_location"][0]["timezone"] = iana
        # Remove offset when IANA is provided so the test is unambiguous
        dm["measurement_location"][0]["logger_main_config"] = [{}]
    return dm


def _write_datamodel(tmp_path: Path, dm: dict) -> Path:
    path = tmp_path / "test_datamodel.json"
    path.write_text(json.dumps(dm), encoding="utf-8")
    return path


def _write_timeseries(tmp_path: Path, tz_naive: bool = True) -> Path:
    """Create a small CSV timeseries for testing."""
    index = pd.date_range("2023-06-01", periods=200, freq="10min")
    df = pd.DataFrame({
        "Timestamp": index,
        "Spd_80m": range(len(index)),
        "Dir_80m": range(len(index)),
    })
    path = tmp_path / "test_timeseries.csv"
    df.to_csv(path, index=False)
    return path


class TestExtractTimezone:
    """Unit tests for _extract_timezone helper."""

    def test_offset_zero_utc(self) -> None:
        source, tz = _extract_timezone(_make_datamodel(0))
        assert source == "offset_from_utc_hrs"
        assert tz == timezone.utc

    def test_offset_530(self) -> None:
        source, tz = _extract_timezone(_make_datamodel(5.5))
        assert source == "offset_from_utc_hrs"
        assert tz == timezone(timedelta(hours=5.5))

    def test_offset_negative(self) -> None:
        source, tz = _extract_timezone(_make_datamodel(-5))
        assert source == "offset_from_utc_hrs"
        assert tz == timezone(timedelta(hours=-5))

    def test_iana_timezone(self) -> None:
        source, tz = _extract_timezone(_make_datamodel(0, iana="Europe/London"))
        assert source == "timezone"
        assert str(tz) == "Europe/London"

    def test_no_timezone_raises(self) -> None:
        dm = _make_datamodel(0)
        dm["measurement_location"][0]["logger_main_config"] = [{}]
        with pytest.raises(ValueError, match="does not declare a timezone"):
            _extract_timezone(dm)


class TestApplyTimezoneToIndex:
    """Unit tests for _apply_timezone_to_index helper."""

    def test_converts_naive_to_utc(self) -> None:
        index = pd.date_range("2023-06-01", periods=100, freq="10min")
        session.reset()
        session.timeseries_df = pd.DataFrame({"a": range(len(index))}, index=index)
        session.raw_timeseries_df = session.timeseries_df.copy()
        _apply_timezone_to_index(session, timezone(timedelta(hours=5.5)))
        assert session.timeseries_df.index.tz is not None
        assert str(session.timeseries_df.index.tz) == "UTC"
        assert session.raw_timeseries_df.index.tz is not None

    def test_idempotent_on_aware(self) -> None:
        index = pd.date_range("2023-06-01", periods=100, freq="10min", tz="UTC")
        session.reset()
        session.timeseries_df = pd.DataFrame({"a": range(len(index))}, index=index)
        _apply_timezone_to_index(session, timezone(timedelta(hours=5.5)))
        # Already tz-aware → no-op (tz is not None)
        assert str(session.timeseries_df.index.tz) == "UTC"


class TestTimezoneIntegration:
    """Integration tests for full parse_datamodel + parse_timeseries flow."""

    def _setup_workspace(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """Create an uploads dir under tmp_path and set it as workspace_dir."""
        uploads = tmp_path / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(session, "workspace_dir", tmp_path)
        return uploads

    def test_timeseries_after_datamodel(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Import datamodel first (sets timezone), then timeseries → index is tz-aware UTC."""
        session.reset()
        uploads = self._setup_workspace(tmp_path, monkeypatch)
        _write_datamodel(uploads, _make_datamodel(5.5))
        # Parse datamodel — sets timezone on session
        _parse_datamodel(session, "test_datamodel.json")
        assert session.timezone is not None
        # Now parse timeseries — should immediately convert to UTC
        _write_timeseries(uploads)
        _parse_timeseries(session, "test_timeseries.csv")
        assert session.timeseries_df.index.tz is not None
        assert str(session.timeseries_df.index.tz) == "UTC"

    def test_timeseries_before_datamodel(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Import timeseries first (tz-naive), then datamodel → index becomes tz-aware UTC."""
        session.reset()
        uploads = self._setup_workspace(tmp_path, monkeypatch)
        _write_timeseries(uploads)
        _parse_timeseries(session, "test_timeseries.csv")
        assert session.timeseries_df.index.tz is None
        # Now import datamodel — should convert existing timeseries
        _write_datamodel(uploads, _make_datamodel(0))
        _parse_datamodel(session, "test_datamodel.json")
        assert session.timeseries_df.index.tz is not None
        assert str(session.timeseries_df.index.tz) == "UTC"

    def test_timezone_in_runconfig(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """After datamodel import, runconfig contains timezone string and source."""
        session.reset()
        uploads = self._setup_workspace(tmp_path, monkeypatch)
        _write_datamodel(uploads, _make_datamodel(5.5))
        _parse_datamodel(session, "test_datamodel.json")
        site = session.runconfig.get("site", {})
        assert "timezone" in site
        assert site["timezone_source"] == "offset_from_utc_hrs"

    def test_offset_shift_preserves_timestamps(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Timeseries loaded in UTC+5:30 should have index shifted back by 5.5 hours."""
        session.reset()
        uploads = self._setup_workspace(tmp_path, monkeypatch)
        # Write a timeseries with a known first timestamp
        _write_timeseries(uploads)
        _parse_timeseries(session, "test_timeseries.csv")
        original_first = session.timeseries_df.index[0]
        # Import datamodel with UTC+5:30 offset
        _write_datamodel(uploads, _make_datamodel(5.5))
        _parse_datamodel(session, "test_datamodel.json")
        shifted_first = session.timeseries_df.index[0]
        # Original was naive local time → after conversion: UTC = local - 5.5h
        expected_utc = original_first.tz_localize(
            timezone(timedelta(hours=5.5))
        ).tz_convert("UTC")
        assert shifted_first == expected_utc
