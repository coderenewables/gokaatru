"""Ingest, timebase and resampling integrity — Step 2 of the logic audit.

Every timebase error is silent and contaminates 100% of downstream numbers, so this
step is about what the ingest path refuses as much as what it accepts.

Headline: the deliberate guards are good — cadence detection is modal, the whitelist
refuses a repaired cadence, a missing timezone refuses outright, and internal storage is
UTC throughout. The findings are the cases nobody chose: a whole class of sites that
cannot import at all, duplicate timestamps that survive unreported, and a resampling
threshold that is defensible but undeclared.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

import server.main  # noqa: F401 — establishes tool-module import order
from server.core.momm import _infer_samples_per_hour
from server.core.validators import (
    TIMESTAMP_LABEL_CONVENTION,
    detect_timestep_minutes,
    to_utc_index,
)
from server.state.session import SessionState
from server.tools.data_io import (
    _apply_timezone_to_index,
    _cadence_aligned_series,
    _detect_timestamp_column,
    _extract_timezone,
    _parse_timeseries,
)
from server.tools.ltc import (
    HOURLY_COVERAGE_MINIMUM,
    MEASURED_COLUMN,
    _align_timestamp_label,
    _prepare_short_term,
)


@pytest.fixture
def workspace():
    """Return a temporary session workspace with an uploads directory."""
    root = Path(tempfile.mkdtemp())
    (root / "uploads").mkdir()
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _state_with_index(index: pd.DatetimeIndex) -> SessionState:
    """Return a session holding a naive-index frame ready for timezone application."""
    state = SessionState()
    state.reset()
    frame = pd.DataFrame({"Spd": np.arange(len(index), dtype=float)}, index=index)
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    return state


# ---------------------------------------------------------------------------
# Verified correct
# ---------------------------------------------------------------------------


def test_cadence_detection_is_modal_and_survives_gaps_and_duplicates():
    """VERIFIED: neither a long outage nor a repeated stamp shifts the inferred cadence."""
    index = list(pd.date_range("2021-01-01", periods=200, freq="10min"))
    index.append(index[-1] + pd.Timedelta(days=3))  # a long outage
    index.insert(50, index[50])  # a duplicated stamp (zero diff)
    frame = pd.DataFrame({"x": np.ones(len(index))}, index=pd.DatetimeIndex(index).sort_values())
    assert detect_timestep_minutes(frame) == 10


@pytest.mark.parametrize("minutes", [1, 2, 5, 10, 15, 30, 60])
def test_every_whitelisted_cadence_is_accepted(minutes: int) -> None:
    """VERIFIED: the accepted cadences round-trip."""
    index = pd.date_range("2021-01-01", periods=100, freq=f"{minutes}min")
    frame = pd.DataFrame({"x": np.ones(len(index))}, index=index)
    assert detect_timestep_minutes(frame) == minutes


@pytest.mark.parametrize("minutes", [3, 7, 20, 45, 90, 1440])
def test_a_cadence_outside_the_whitelist_is_refused(minutes: int) -> None:
    """VERIFIED: a silently repaired cadence would propagate into every gap statistic.

    Refusing is the right call — but note it also means a legitimately daily or monthly
    derived series cannot pass through this helper, which is why `clipping.py` derives its
    own cadence rather than calling it.
    """
    index = pd.date_range("2021-01-01", periods=100, freq=f"{minutes}min")
    frame = pd.DataFrame({"x": np.ones(len(index))}, index=index)
    with pytest.raises(ValueError, match="not a supported cadence"):
        detect_timestep_minutes(frame)


def test_a_datamodel_without_a_timezone_is_refused():
    """VERIFIED: a wrong timezone assumption is silent and corrupts every LTC, so it refuses."""
    with pytest.raises(ValueError, match="does not declare a timezone"):
        _extract_timezone({"measurement_location": [{"logger_main_config": [{}]}]})

    source, tz = _extract_timezone(
        {"measurement_location": [{"logger_main_config": [{"offset_from_utc_hrs": 5.5}]}]}
    )
    assert source == "offset_from_utc_hrs"
    assert tz.utcoffset(None) == pd.Timedelta(hours=5.5).to_pytimedelta()

    source_iana, tz_iana = _extract_timezone(
        {"measurement_location": [{"timezone": "Asia/Kolkata"}]}
    )
    assert source_iana == "timezone"
    assert str(tz_iana) == "Asia/Kolkata"


def test_internal_storage_is_utc_after_localisation():
    """VERIFIED: ingest converts local time to tz-aware UTC and every join enforces it."""
    state = _state_with_index(pd.date_range("2021-06-01", periods=48, freq="h"))
    _apply_timezone_to_index(state, ZoneInfo("Asia/Kolkata"))

    assert str(state.timeseries_df.index.tz) == "UTC"
    # 00:00 IST is 18:30 UTC the previous day.
    assert state.timeseries_df.index[0] == pd.Timestamp("2021-05-31 18:30", tz="UTC")
    assert str(to_utc_index(state.timeseries_df).index.tz) == "UTC"


def test_cadence_alignment_tolerates_a_drifting_logger_clock():
    """VERIFIED: `_cadence_aligned_series` snaps to the dominant phase within a quarter step."""
    base = pd.date_range("2021-01-01 00:03", periods=60, freq="10min")
    jitter = pd.to_timedelta(np.random.default_rng(1).integers(-60, 61, len(base)), unit="s")
    series = pd.Series(np.arange(len(base), dtype=float), index=base + jitter)

    aligned = _cadence_aligned_series(series, 10)

    # Output is on a strict 10-minute grid...
    spacings = aligned.index.to_series().diff().dropna().unique()
    assert len(spacings) == 1
    assert spacings[0] == pd.Timedelta(minutes=10)
    # ...essentially every jittered record survives (edge steps may fall outside)...
    assert len(aligned) >= len(base) - 1
    assert int(aligned.notna().sum()) >= len(base) - 1
    # ...and the logger's own phase is preserved rather than being snapped to the hour.
    assert set(aligned.index.minute % 10) != {0}


def test_day_first_dates_with_days_above_twelve_are_refused():
    """VERIFIED: an unparseable date column raises rather than silently dropping most rows."""
    dates = [f"{day:02d}/03/2021 00:00" for day in range(1, 29)]
    frame = pd.DataFrame({"Timestamp": dates, "Spd": np.arange(len(dates), dtype=float)})
    with pytest.raises(ValueError, match="Could not detect a timestamp column"):
        _detect_timestamp_column(frame)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def test_a_dst_observing_timezone_falls_back_to_standard_time():
    """F-64 (HIGH) — FIXED. Regression test: a DST campaign must import, and say how.

    The bug: ``_apply_timezone_to_index`` called ``tz_localize(tz)`` with pandas' defaults
    (``ambiguous="raise"``, ``nonexistent="raise"``), so any campaign in a DST-observing
    IANA zone raised the moment it spanned either transition — every site in Europe, most
    of North America, Australia, New Zealand and Chile. The message advised passing a
    pandas keyword unreachable from a file upload.

    The fix keeps strict localisation as the first attempt, because when it succeeds
    nothing should be inferred. On failure it falls back to the zone's **standard-time**
    offset — a logger clock almost always runs on fixed local standard time, and a
    campaign that occupies the spring-forward gap is direct evidence of exactly that —
    and returns `timezone_resolution`, the offset used, and a warning.
    """
    autumn = _state_with_index(pd.date_range("2021-10-31 00:00", "2021-10-31 05:00", freq="30min"))
    autumn_result = _apply_timezone_to_index(autumn, ZoneInfo("Europe/Berlin"))
    assert autumn_result["timezone_resolution"] == "standard_offset"
    assert autumn_result["standard_offset_hours"] == pytest.approx(1.0)  # CET, not CEST
    assert "warning" in autumn_result
    assert str(autumn.timeseries_df.index.tz) == "UTC"
    assert str(autumn.raw_timeseries_df.index.tz) == "UTC"

    spring = _state_with_index(pd.date_range("2021-03-28 00:00", "2021-03-28 05:00", freq="30min"))
    spring_result = _apply_timezone_to_index(spring, ZoneInfo("Europe/Berlin"))
    assert spring_result["timezone_resolution"] == "standard_offset"
    assert spring.timeseries_df.index[0] == pd.Timestamp("2021-03-27 23:00", tz="UTC")

    # Southern hemisphere: standard time is the *July* offset there.
    sydney = _state_with_index(pd.date_range("2021-04-04 00:00", "2021-04-04 05:00", freq="30min"))
    sydney_result = _apply_timezone_to_index(sydney, ZoneInfo("Australia/Sydney"))
    assert sydney_result["timezone_resolution"] == "standard_offset"
    assert sydney_result["standard_offset_hours"] == pytest.approx(10.0)  # AEST, not AEDT

    # A campaign that does not span a transition still localises strictly — nothing
    # is inferred when the timestamps are unambiguous.
    clean = _state_with_index(pd.date_range("2021-06-01", periods=48, freq="h"))
    clean_result = _apply_timezone_to_index(clean, ZoneInfo("Europe/Berlin"))
    assert clean_result["timezone_resolution"] == "strict"
    assert clean.timeseries_df.index[0] == pd.Timestamp("2021-05-31 22:00", tz="UTC")  # CEST

    # And a no-DST zone is unaffected.
    kolkata = _state_with_index(pd.date_range("2021-10-31 00:00", "2021-10-31 05:00", freq="30min"))
    assert _apply_timezone_to_index(kolkata, ZoneInfo("Asia/Kolkata"))["timezone_resolution"] == "strict"

    # The explicit-offset path still avoids the question entirely.
    _, tz = _extract_timezone(
        {"measurement_location": [{"logger_main_config": [{"offset_from_utc_hrs": 1.0}]}]}
    )
    fixed = _state_with_index(pd.date_range("2021-10-31 00:00", "2021-10-31 05:00", freq="30min"))
    assert _apply_timezone_to_index(fixed, tz)["timezone_resolution"] == "strict"
    assert str(fixed.timeseries_df.index.tz) == "UTC"


def test_duplicate_timestamps_are_collapsed_and_reported(workspace: Path) -> None:
    """F-65 (MEDIUM) — FIXED. A repeated timestamp is collapsed, not double-weighted.

    The bug: ``_parse_timeseries`` sorted the index but never checked for duplicates. The
    repeated stamp was included in the reported row count, nothing in the response mentioned
    it, and every downstream ``groupby`` over the index — MoMM, diurnal profiles, monthly
    stats, coverage — then counted that interval twice. The cadence detector was immune
    because zero diffs are filtered out before the modal spacing is taken, so nothing else
    caught it either.

    The fix averages the repeats rather than dropping one: where they disagree neither copy
    has a better claim, and the mean is the only resolution that does not depend on file
    order. The count and a warning travel with the ingest response.
    """
    index = list(pd.date_range("2021-01-01", periods=200, freq="10min"))
    index.insert(10, index[10])
    values = np.arange(len(index), dtype=float)
    pd.DataFrame({"Timestamp": index, "Spd": values}).to_csv(
        workspace / "uploads" / "dup.csv", index=False
    )

    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    result = _parse_timeseries(state, "dup.csv")

    assert result["rows"] == 200  # 200 distinct intervals, reported as 200
    assert result["duplicate_timestamps"] == 1
    assert result["duplicate_timestamps_distinct"] == 1
    assert result["duplicate_resolution"] == "averaged"
    assert "counted twice by every month-hour grouping" in result["warning"]

    # The duplicate is gone from the working data, and the survivor is the mean of the two.
    assert int(state.timeseries_df.index.duplicated().sum()) == 0
    sizes = state.timeseries_df.groupby(state.timeseries_df.index).size()
    assert int((sizes > 1).sum()) == 0
    assert float(state.timeseries_df["Spd"].iloc[10]) == pytest.approx((values[10] + values[11]) / 2.0)

    # A clean file says so rather than staying silent about the check.
    pd.DataFrame(
        {"Timestamp": pd.date_range("2021-01-01", periods=200, freq="10min"), "Spd": values[:200]}
    ).to_csv(workspace / "uploads" / "clean.csv", index=False)
    clean_state = SessionState()
    clean_state.reset()
    clean_state.workspace_dir = workspace
    clean = _parse_timeseries(clean_state, "clean.csv")
    assert clean["duplicate_timestamps"] == 0


def test_hourly_resampling_declares_its_coverage_gate(workspace: Path) -> None:
    """F-66 (MEDIUM) — FIXED. The 50% gate is a named constant and is reported.

    ``_prepare_short_term`` keeps any hour whose coverage reaches half its expected
    sub-hourly samples, so a 1-of-6 hour is dropped and a 3-of-6 hour is kept and averaged
    as though it were full. 50% is a defensible threshold and the behaviour is unchanged.

    What was not defensible is that it was a bare literal (``coverage >= 0.5``) appearing in
    no response, no constant and no documentation — while a half-populated hour carries
    higher variance than a full one, feeding straight into the variance-ratio LTC the README
    already flags as variance-sensitive.
    """
    index = pd.date_range("2021-01-01", periods=6 * 24 * 10, freq="10min", tz="UTC")

    def prepared_with(hour: str, valid_samples: int) -> tuple[pd.DataFrame, dict]:
        frame = pd.DataFrame({MEASURED_COLUMN: np.full(len(index), 8.0)}, index=index)
        window = (frame.index >= f"2021-01-01 {hour}") & (frame.index < f"2021-01-01 {int(hour[:2]) + 1:02d}:00")
        frame.loc[frame.index[window][valid_samples:], MEASURED_COLUMN] = np.nan
        return _prepare_short_term(frame)

    sparse, sparse_report = prepared_with("05:00", valid_samples=1)
    half, half_report = prepared_with("07:00", valid_samples=3)

    assert pd.Timestamp("2021-01-01 05:00", tz="UTC") not in sparse.index  # 1 of 6 dropped
    assert pd.Timestamp("2021-01-01 07:00", tz="UTC") in half.index  # 3 of 6 kept

    # The threshold, the expected sample count and what it did are all in the response.
    assert half_report["hourly_resampled"] is True
    assert half_report["hourly_coverage_minimum"] == HOURLY_COVERAGE_MINIMUM == 0.5
    assert half_report["hourly_expected_samples"] == 6.0
    assert half_report["hours_kept_partially_populated"] == 1
    assert sparse_report["hours_dropped_below_minimum"] == 1
    assert "noisier than a full one" in half_report["hourly_coverage_note"]


def test_momm_samples_per_hour_floor_is_correct_not_a_bug():
    """F-13 — measured away to nothing. The floor of 1.0 is the right denominator.

    The finding held that ``max(1.0, 3600 / spacing)`` overstates expected counts by up to
    24x for cadences coarser than hourly. Measuring it says otherwise, and the reasoning was
    the wrong way round.

    MoMM groups by ``(year, month, hour-of-day)``. For any hour-aligned cadence coarser than
    an hour, a given hour-of-day is sampled at most once per day, so a non-empty group holds
    exactly ``days_in_month`` records — which is ``days_in_month * 1.0``. The floor is the
    correct expected count; the "true" fractional value would understate the denominator by
    the same 24x the finding attributed to the floor, and would report a daily series as 24x
    complete.

    Measured on a full year: for 3-hourly, 6-hourly and daily data every non-empty
    month-hour group holds exactly the number of days in the month.
    """
    def index_for(freq: str) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(pd.date_range("2021-01-01", periods=60, freq=freq, tz="UTC"))

    assert _infer_samples_per_hour(index_for("10min")) == pytest.approx(6.0)
    assert _infer_samples_per_hour(index_for("h")) == pytest.approx(1.0)
    assert _infer_samples_per_hour(index_for("D")) == pytest.approx(1.0)

    # The claim under test: for coarse cadences the real records-per-group is days_in_month,
    # so samples_per_hour = 1.0 makes expected == actual and completeness == 1.0.
    for freq in ("3h", "6h", "D"):
        full_year = pd.date_range("2021-01-01", "2021-12-31 23:00", freq=freq, tz="UTC")
        january = full_year[full_year.month == 1]
        per_group = pd.Series(1, index=january).groupby(january.hour).size().unique()
        assert list(per_group) == [31], f"{freq}: expected 31 records per non-empty hour group"
        assert _infer_samples_per_hour(pd.DatetimeIndex(full_year)) * 31 == 31.0


def test_ambiguous_day_month_dates_swap_silently_but_are_caught_downstream():
    """FINDING F-67 (L): DD/MM parses as MM/DD when every day is 12 or below.

    ``pd.to_datetime`` is called with no ``dayfirst`` and no explicit format, so a
    DD/MM/YYYY column whose days all fall on or below 12 parses **100% successfully** with
    month and day transposed: a 12-day March campaign becomes a series spanning January to
    December.

    It is caught downstream, but only incidentally: the swapped series has a ~monthly
    spacing, which the cadence whitelist refuses. So the guard exists and is not
    deliberate, and the error message names the cadence rather than the date format.
    """
    dates = [f"{day:02d}/03/2021 00:00" for day in range(1, 13)]
    _, parsed = _detect_timestamp_column(
        pd.DataFrame({"Timestamp": dates, "Spd": np.arange(12.0)})
    )

    assert int(parsed.notna().sum()) == 12  # every row "parses"
    assert parsed.dropna().iloc[0] == pd.Timestamp("2021-01-03")  # 01/03 -> 3 January
    assert parsed.dropna().iloc[-1] == pd.Timestamp("2021-12-03")  # 12/03 -> 3 December

    # The incidental downstream guard.
    frame = pd.DataFrame({"Spd": np.arange(12.0)}, index=pd.DatetimeIndex(parsed)).sort_index()
    with pytest.raises(ValueError, match="not a supported cadence"):
        detect_timestep_minutes(frame)


def test_timestamp_label_is_declared_and_applied():
    """F-07 (MEDIUM) — FIXED. The interval convention is declared, and honoured in matching.

    IEA Task 43 permits a timestamp to label the start, the end or the centre of its
    averaging interval. Nothing in the ingest path declared which convention was assumed,
    nothing in the datamodel reader looked for it, and no response reported it — while a
    mismatch against an instantaneous reanalysis reference is a systematic half-interval
    offset applied to every record of every LTC, a shift rather than noise, so it does not
    average out.

    The convention is a property of the logger and cannot be inferred from the data, so it
    is declared at ingest (assumed interval-start) and overridable per run. When it is
    overridden, the measured index is shifted onto interval-start before matching.
    """
    index = pd.date_range("2021-01-01", periods=200, freq="10min", tz="UTC")
    frame = pd.DataFrame({MEASURED_COLUMN: np.arange(len(index), dtype=float)}, index=index)

    state = SessionState()
    state.reset()

    # The default is stated rather than silent.
    unshifted, disclosure = _align_timestamp_label(state, frame)
    assert disclosure["timestamp_label"] == TIMESTAMP_LABEL_CONVENTION == "interval_start"
    assert disclosure["timestamp_shift_minutes"] == 0.0
    assert unshifted.index[0] == index[0]

    # An interval-end logger is shifted back a full interval, so a 10:10 stamp describes
    # the flow from 10:00 to 10:10 and is matched against the 10:00 reference.
    state.runconfig["timestamp_label"] = "interval_end"
    shifted, end_disclosure = _align_timestamp_label(state, frame)
    assert end_disclosure["timestamp_shift_minutes"] == 10.0
    assert shifted.index[0] == index[0] - pd.Timedelta(minutes=10)
    assert "shifted back 10 minutes" in end_disclosure["timestamp_shift_note"]

    # Interval-centre is half of that.
    state.runconfig["timestamp_label"] = "interval_centre"
    centred, centre_disclosure = _align_timestamp_label(state, frame)
    assert centre_disclosure["timestamp_shift_minutes"] == 5.0
    assert centred.index[0] == index[0] - pd.Timedelta(minutes=5)

    # An unrecognised convention is refused rather than quietly treated as the default.
    state.runconfig["timestamp_label"] = "whenever"
    with pytest.raises(ValueError, match="timestamp_label must be one of"):
        _align_timestamp_label(state, frame)


def test_ingest_declares_the_timestamp_label_it_assumed(workspace: Path) -> None:
    """The assumption is visible at ingest, where the analyst can still correct it."""
    index = pd.date_range("2021-01-01", periods=200, freq="10min")
    pd.DataFrame(
        {"Timestamp": index, "Spd": np.arange(len(index), dtype=float)}
    ).to_csv(workspace / "uploads" / "plain.csv", index=False)

    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    result = _parse_timeseries(state, "plain.csv")

    assert result["timestamp_label"] == "interval_start"
    assert result["timestamp_label_basis"] == "assumed"
    assert "half an interval" in result["timestamp_label_note"]


def test_hour_of_day_bins_declare_the_utc_clock():
    """F-02 (MEDIUM) — FIXED. UTC-hour bins now say they are UTC, and offer the local map.

    Ingest converts every index to UTC (D8) and nothing converts back, so all hour-of-day
    binning counts UTC hours. The binning itself is left alone — a table and its lookup
    share the clock, so the physics is self-consistent — but the hours are analyst-facing,
    and a 14:00 local peak at UTC+5:30 was reported at 08:30 with nothing saying so.
    """
    from datetime import timedelta, timezone as dt_timezone

    from server.tools.statistics import _compute_diurnal_profile

    index = pd.date_range("2021-01-01", periods=24 * 90, freq="h", tz="UTC")
    # A clean diurnal cycle peaking at 08:00 UTC, which is 13:30 at UTC+5:30.
    speed = 8.0 + 2.0 * np.cos(2 * np.pi * (index.hour - 8) / 24)
    state = SessionState()
    state.reset()
    frame = pd.DataFrame({"Spd_100m": speed}, index=index)
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    state.sensor_mapping = {100.0: {"speed_col": "Spd_100m", "dir_col": None, "sd_col": None, "temp_col": None}}

    # Without a declared timezone the basis is still stated, and the limitation is named.
    profile = _compute_diurnal_profile(state, "Spd_100m")
    assert profile["hour_basis"] == "utc"
    assert profile["site_utc_offset_hours"] is None
    assert "hours_local" not in profile
    assert "cannot be mapped to site local time" in profile["local_hour_note"]

    # With one, the local hours travel alongside and the peak reads correctly.
    state.timezone = dt_timezone(timedelta(hours=5, minutes=30))
    located = _compute_diurnal_profile(state, "Spd_100m")
    assert located["site_utc_offset_hours"] == pytest.approx(5.5)
    peak_utc = int(np.nanargmax(located["mean_speeds"]))
    assert peak_utc == 8
    assert located["hours_local"][peak_utc] == 13  # 08:00 UTC is 13:30 local
