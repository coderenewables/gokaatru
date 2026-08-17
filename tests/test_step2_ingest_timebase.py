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
from server.core.validators import detect_timestep_minutes, to_utc_index
from server.state.session import SessionState
from server.tools.data_io import (
    _apply_timezone_to_index,
    _cadence_aligned_series,
    _detect_timestamp_column,
    _extract_timezone,
    _parse_timeseries,
)
from server.tools.ltc import MEASURED_COLUMN, _prepare_short_term


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


def test_duplicate_timestamps_survive_ingest_unreported(workspace: Path) -> None:
    """FINDING F-65 (M): a repeated timestamp is kept, counted, and double-weighted.

    ``_parse_timeseries`` sorts the index but never checks for duplicates. The repeated
    stamp is included in the reported row count and nothing in the response mentions it.
    Every downstream ``groupby`` over the index — MoMM, diurnal profiles, monthly stats,
    coverage — then counts that interval twice.

    Loggers produce duplicates routinely: a restart, an overlapping export, or a manual
    file concatenation. The cadence detector is immune (zero diffs are filtered out), so
    nothing else catches it either.
    """
    index = list(pd.date_range("2021-01-01", periods=200, freq="10min"))
    index.insert(10, index[10])
    pd.DataFrame(
        {"Timestamp": index, "Spd": np.arange(len(index), dtype=float)}
    ).to_csv(workspace / "uploads" / "dup.csv", index=False)

    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    result = _parse_timeseries(state, "dup.csv")

    assert result["rows"] == 201  # the duplicate is counted as a record
    assert int(state.timeseries_df.index.duplicated().sum()) == 1
    assert "duplicate_timestamps" not in result

    # And it double-counts in exactly the operation every statistic uses.
    sizes = state.timeseries_df.groupby(state.timeseries_df.index).size()
    assert int((sizes > 1).sum()) == 1


def test_hourly_resampling_accepts_a_half_empty_hour(workspace: Path) -> None:
    """FINDING F-66 (M): a 3-of-6 hour becomes an 'hourly mean' with no disclosure.

    ``_prepare_short_term`` keeps any hour whose coverage is at least 0.5 of the expected
    sub-hourly samples. A 1-of-6 hour is correctly dropped; a 3-of-6 hour is kept and
    averaged as though it were a full hour.

    50% is a defensible threshold, but it is a hardcoded literal that appears in no
    response and no documentation, and a half-populated hour carries higher variance than
    a full one — which feeds straight into the variance-ratio LTC that the README already
    flags as variance-sensitive.
    """
    index = pd.date_range("2021-01-01", periods=6 * 24 * 10, freq="10min", tz="UTC")

    def prepared_with(hour: str, valid_samples: int) -> pd.DataFrame:
        frame = pd.DataFrame({MEASURED_COLUMN: np.full(len(index), 8.0)}, index=index)
        window = (frame.index >= f"2021-01-01 {hour}") & (frame.index < f"2021-01-01 {int(hour[:2]) + 1:02d}:00")
        frame.loc[frame.index[window][valid_samples:], MEASURED_COLUMN] = np.nan
        return _prepare_short_term(frame)

    sparse = prepared_with("05:00", valid_samples=1)
    half = prepared_with("07:00", valid_samples=3)

    assert pd.Timestamp("2021-01-01 05:00", tz="UTC") not in sparse.index  # 1 of 6 dropped
    assert pd.Timestamp("2021-01-01 07:00", tz="UTC") in half.index  # 3 of 6 kept

    import inspect

    from server.tools import ltc as ltc_module

    source = inspect.getsource(ltc_module._prepare_short_term)
    assert "coverage >= 0.5" in source
    assert "MIN_HOURLY_COVERAGE" not in source  # the threshold is not even a named constant


def test_momm_samples_per_hour_floor_misweights_coarse_cadences():
    """FINDING F-13 (M, confirmed from Step 1): the floor of 1.0 breaks sub-hourly weighting.

    ``_infer_samples_per_hour`` returns ``max(1.0, 3600 / spacing)``, so every cadence
    coarser than hourly reports 1.0:

        10-minute -> 6.0     (correct)
        hourly    -> 1.0     (correct)
        daily     -> 1.0     (true value 0.0417 — a **24x** overstatement of expected counts)
        monthly   -> 1.0     (true value ~0.00137)

    Expected counts are then far too high, completeness is under-estimated for every
    month-hour cell, and the weighting stops discriminating. A long-term derived series is
    exactly the case that hits this.
    """
    def index_for(freq: str) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(pd.date_range("2021-01-01", periods=60, freq=freq, tz="UTC"))

    assert _infer_samples_per_hour(index_for("10min")) == pytest.approx(6.0)
    assert _infer_samples_per_hour(index_for("h")) == pytest.approx(1.0)
    assert _infer_samples_per_hour(index_for("D")) == pytest.approx(1.0)  # should be 1/24
    assert _infer_samples_per_hour(index_for("MS")) == pytest.approx(1.0)  # should be ~1/730


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


def test_timestamp_label_semantics_are_never_declared(workspace: Path) -> None:
    """FINDING F-07 (M, carried from Step 1): interval-start vs interval-end is never stated.

    IEA Task 43 permits a timestamp to label the start, the end or the centre of its
    averaging interval. Nothing in the ingest path declares which convention is assumed,
    nothing in the datamodel reader looks for it, and no response reports it.

    A mismatch against an instantaneous reanalysis reference is a systematic half-interval
    offset applied to every record of every LTC — 5 minutes on 10-minute data, and the
    error is a shift rather than noise, so it does not average out.
    """
    index = pd.date_range("2021-01-01", periods=200, freq="10min")
    pd.DataFrame(
        {"Timestamp": index, "Spd": np.arange(len(index), dtype=float)}
    ).to_csv(workspace / "uploads" / "plain.csv", index=False)

    state = SessionState()
    state.reset()
    state.workspace_dir = workspace
    result = _parse_timeseries(state, "plain.csv")

    for absent in ("timestamp_convention", "interval_label", "timestamp_basis"):
        assert absent not in result
    assert "timestamp_convention" not in state.runconfig

    import inspect

    from server.tools import data_io as data_io_module

    assert "interval" not in inspect.getsource(data_io_module._detect_timestamp_column).lower()
