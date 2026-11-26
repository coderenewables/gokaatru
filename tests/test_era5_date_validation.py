"""Regression tests for D35: an ERA5 extraction's period and coordinate are checked.

Bug: the extraction accepted any strings for start_date and end_date: a reversed range
silently produced an empty extraction, a malformed date surfaced as a lower-level exception,
and an uncapped span was a cost a caller rarely means.

Fix (D35) was made in the hand-written route's request model only, so the operation, over MCP
and its generated route, never had it. The checks now live in ``_extract_era5_data`` and
``_find_era5_nodes`` (P3-17b), and refuse before anything is read from EarthDataHub.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools import era5
from server.tools.era5 import ERA5_MAX_SPAN_YEARS, _extract_era5_data, _find_era5_nodes


@pytest.fixture
def reads(monkeypatch, tmp_path) -> list[tuple[str, str]]:
    """Every read the extraction would make of the store, answered with a one-row frame."""
    made: list[tuple[str, str]] = []

    def download(_state, _lat, _lon, start, end):
        made.append((start, end))
        return pd.DataFrame({"u100": [1.0], "v100": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp(start)], name="time"))

    monkeypatch.setattr(era5, "_download_era5_frame_with_retry", download)
    monkeypatch.setattr(era5, "_era5_cache_path", lambda *_args: tmp_path / "node.parquet")
    monkeypatch.setattr(era5, "_open_era5_dataset", lambda _state: pytest.fail("the store was opened"))
    return made


def extract(start: object, end: object) -> dict:
    return _extract_era5_data(SessionState(), 52.4, 4.8, str(start), str(end))


class TestPeriod:
    def test_an_iso_date_or_date_time_is_read(self, reads) -> None:
        assert extract("2024-01-01", "2024-12-31")["status"] == "ok"
        assert extract("2024-01-01", "2024-01-01T02:00:00")["status"] == "ok"
        assert len(reads) == 2

    @pytest.mark.parametrize(("start", "end"), [("not-a-date", "2024-12-31"), ("2024-01-01", "Jan 1st")])
    def test_a_malformed_date_is_refused_before_any_read(self, reads, start, end) -> None:
        with pytest.raises(ValueError, match="is not an ISO date"):
            extract(start, end)
        assert reads == []

    def test_a_reversed_range_is_refused(self, reads) -> None:
        with pytest.raises(ValueError, match="end_date.*must be on or after start_date"):
            extract("2024-12-31", "2024-01-01")
        assert reads == []

    def test_one_day_is_a_period(self, reads) -> None:
        assert extract("2024-06-15", "2024-06-15")["status"] == "ok"

    def test_a_span_beyond_the_cap_is_refused(self, reads) -> None:
        with pytest.raises(ValueError, match=f"exceeds maximum of {ERA5_MAX_SPAN_YEARS} years"):
            extract("1900-01-01", "2100-01-01")
        start = date(2000, 1, 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            extract(start, start + timedelta(days=ERA5_MAX_SPAN_YEARS * 365 + 1))
        assert reads == []

    def test_exactly_the_cap_is_read(self, reads) -> None:
        start = date(2000, 1, 1)
        assert extract(start, start + timedelta(days=ERA5_MAX_SPAN_YEARS * 365))["status"] == "ok"

    def test_the_default_period_is_within_the_cap(self, reads) -> None:
        assert _extract_era5_data(SessionState(), 52.4, 4.8)["status"] == "ok"


class TestCoordinate:
    @pytest.mark.parametrize(("latitude", "longitude"), [(91.0, 4.8), (52.4, -181.0)])
    def test_a_coordinate_off_the_globe_is_refused(self, reads, latitude, longitude) -> None:
        with pytest.raises(ValueError, match="is outside"):
            _extract_era5_data(SessionState(), latitude, longitude)
        with pytest.raises(ValueError, match="is outside"):
            _find_era5_nodes(SessionState(), latitude, longitude)
        assert reads == []
