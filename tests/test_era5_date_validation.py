"""Regression tests for D35 — ERA5 date inputs must be validated.

Bug: ExtractEra5Request accepted plain strings for start_date/end_date with
no format validation, no end >= start check, and no maximum span cap.  A
reversed range silently produced an empty extraction; malformed dates surfaced
as lower-level exceptions; uncapped spans were a cost/latency issue.

Fix: Use datetime.date types (Pydantic parses and validates ISO dates),
model validator for ordering and span cap (30 years), and return effective
range in response.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from server.api.schemas import ERA5_MAX_SPAN_YEARS, ExtractEra5Request


class TestExtractEra5RequestDateParsing:
    """Pydantic must parse ISO date strings into datetime.date objects."""

    def test_iso_string_parses(self) -> None:
        req = ExtractEra5Request(
            latitude=52.4, longitude=4.8,
            start_date="2024-01-01", end_date="2024-12-31",
        )
        assert isinstance(req.start_date, date)
        assert isinstance(req.end_date, date)
        assert req.start_date == date(2024, 1, 1)
        assert req.end_date == date(2024, 12, 31)

    def test_date_objects_accepted(self) -> None:
        req = ExtractEra5Request(
            latitude=52.4, longitude=4.8,
            start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
        )
        assert req.start_date == date(2024, 1, 1)

    def test_defaults_are_dates(self) -> None:
        req = ExtractEra5Request(latitude=52.4, longitude=4.8)
        assert isinstance(req.start_date, date)
        assert isinstance(req.end_date, date)

    def test_malformed_date_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExtractEra5Request(
                latitude=52.4, longitude=4.8,
                start_date="not-a-date", end_date="2024-12-31",
            )

    def test_malformed_date_rejected_end(self) -> None:
        with pytest.raises(ValidationError):
            ExtractEra5Request(
                latitude=52.4, longitude=4.8,
                start_date="2024-01-01", end_date="Jan 1st",
            )


class TestExtractEra5RequestDateOrdering:
    """end_date must be on or after start_date."""

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValidationError, match="end_date.*must be on or after start_date"):
            ExtractEra5Request(
                latitude=52.4, longitude=4.8,
                start_date="2024-12-31", end_date="2024-01-01",
            )

    def test_equal_dates_pass(self) -> None:
        req = ExtractEra5Request(
            latitude=52.4, longitude=4.8,
            start_date="2024-06-15", end_date="2024-06-15",
        )
        assert req.start_date == req.end_date

    def test_normal_range_passes(self) -> None:
        req = ExtractEra5Request(
            latitude=52.4, longitude=4.8,
            start_date="2020-01-01", end_date="2024-12-31",
        )
        assert req.end_date > req.start_date


class TestExtractEra5RequestSpanCap:
    """Requested span must not exceed ERA5_MAX_SPAN_YEARS."""

    def test_span_exceeds_max_raises(self) -> None:
        max_days = ERA5_MAX_SPAN_YEARS * 365
        with pytest.raises(ValidationError, match=f"exceeds maximum of {ERA5_MAX_SPAN_YEARS} years"):
            ExtractEra5Request(
                latitude=52.4, longitude=4.8,
                start_date="1900-01-01", end_date="2100-01-01",
            )

    def test_span_at_max_passes(self) -> None:
        # Default span (2000-01-01 to 2025-12-31) = ~9496 days < 30*365 = 10950
        req = ExtractEra5Request(latitude=52.4, longitude=4.8)
        assert req.start_date < req.end_date

    def test_one_day_over_max_raises(self) -> None:
        max_days = ERA5_MAX_SPAN_YEARS * 365
        start = date(2000, 1, 1)
        end = start + timedelta(days=max_days + 1)  # one day over
        with pytest.raises(ValidationError, match="exceeds maximum"):
            ExtractEra5Request(
                latitude=52.4, longitude=4.8,
                start_date=start, end_date=end,
            )

    def test_exactly_max_days_passes(self) -> None:
        max_days = ERA5_MAX_SPAN_YEARS * 365
        start = date(2000, 1, 1)
        end = start + timedelta(days=max_days)
        req = ExtractEra5Request(
            latitude=52.4, longitude=4.8,
            start_date=start, end_date=end,
        )
        assert (req.end_date - req.start_date).days == max_days


class TestExtractEra5RequestLatitudeLongitude:
    """Existing coordinate constraints must still work alongside date validation."""

    def test_latitude_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ExtractEra5Request(latitude=91.0, longitude=4.8)

    def test_longitude_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ExtractEra5Request(latitude=52.4, longitude=-181.0)
