"""Cleaning flags as intervals rebuild the flag table exactly (P2-4).

The timeline draws flags as bands, one per run of consecutive working records flagged by
one rule application. Expanding every interval back to its records must give the flag table
itself, record for record, with the rule, reason, actor and time of each.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from server.operations import acting_as
from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule, _undo_cleaning_rule
from server.tools.flags import MAX_FLAG_INTERVALS, _flag_intervals
from tests.test_dry_run import _populate

CHANNELS = "Spd_100m,Spd_100m_sd,Dir_100m,Tmp_100m"
COLUMNS = ["timestamp", "sensor", "rule_sequence", "rule_type", "reason", "actor", "flagged_at"]


def _cleaned() -> SessionState:
    """Scattered, run-shaped and drawn flags, two actors, gap fill, and an undo replayed."""
    state = SessionState()
    state.reset()
    _populate(state)
    drawn = {
        "definition": {
            "kind": "union",
            "of": [
                {"kind": "time_range", "start": "2023-01-20T00:00:00Z", "end": "2023-01-20T06:00:00Z"},
                {"kind": "band", "channel": "Spd_100m", "min": 14.0},
            ],
        },
        "sensors": ["Spd_100m_sd"],
        "reason": "suspect",
        "note": "",
    }
    with acting_as("user"):
        _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
        _apply_cleaning_rule(state, "stuck_sensor", "Spd_100m", "{}")
        _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", json.dumps(drawn))
    with acting_as("assistant:openai/gpt-4o"):
        _apply_cleaning_rule(state, "icing_filter", "Spd_100m", "{}")
        _apply_cleaning_rule(state, "custom_period_exclude", "Tmp_100m", "{}", "2023-02-10", "2023-02-11 12:00")
        _apply_cleaning_rule(state, "timestamp_gap_fill", "Spd_100m", "{}")
        _apply_cleaning_rule(state, "expression_filter", "Dir_100m", json.dumps({"expression": "Dir_100m < 10"}))
    _undo_cleaning_rule(state, 1)
    return state


def _expanded(state: SessionState, result: dict) -> pd.DataFrame:
    index = pd.DatetimeIndex(state.timeseries_df.index)
    rows = []
    for sensor, channel in result["channels"].items():
        for interval in channel["intervals"]:
            first = index.get_loc(pd.Timestamp(interval["first"]))
            last = index.get_loc(pd.Timestamp(interval["last"]))
            assert last - first + 1 == interval["records"]
            following = index[last + 1].isoformat() if last + 1 < len(index) else None
            assert interval["next"] == following
            for position in range(first, last + 1):
                rows.append({
                    "timestamp": index[position],
                    "sensor": sensor,
                    "rule_sequence": interval["rule_sequence"],
                    **{key: interval[key] for key in ("rule_type", "reason", "actor", "flagged_at")},
                })
    return _canonical(pd.DataFrame(rows, columns=COLUMNS))


def _canonical(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame[COLUMNS].copy()
    frame["timestamp"] = pd.DatetimeIndex(frame["timestamp"]).tz_convert("UTC")
    frame["rule_sequence"] = frame["rule_sequence"].astype("int64")
    for column in ("sensor", "rule_type", "reason", "actor", "flagged_at"):
        frame[column] = frame[column].astype(str)
    return frame.sort_values(["sensor", "timestamp"]).reset_index(drop=True)


def test_the_intervals_rebuild_the_flag_table_exactly() -> None:
    state = _cleaned()
    result = _flag_intervals(state, CHANNELS)
    flags = state.cleaning_flags
    # Six flagging rules applied, the stuck-sensor one undone.
    assert set(flags["rule_type"]) == {
        "range_check", "exclude_selection", "icing_filter", "custom_period_exclude", "expression_filter",
    }
    assert len(set(flags["actor"])) == 2
    assert result["unplaced_flags"] == 0 and result["truncated"] is False
    assert result["records"] == len(state.timeseries_df)
    pd.testing.assert_frame_equal(_expanded(state, result), _canonical(flags))
    for name, channel in result["channels"].items():
        assert channel["flagged_records"] == int((flags["sensor"] == name).sum())
    # Runs break where the rule changes, not only at gaps: no two touching intervals of a
    # channel share a rule application.
    index = pd.DatetimeIndex(state.timeseries_df.index)
    for channel in result["channels"].values():
        for before, after in zip(channel["intervals"], channel["intervals"][1:]):
            touching = index.get_loc(pd.Timestamp(after["first"])) == index.get_loc(pd.Timestamp(before["last"])) + 1
            assert not (touching and before["rule_sequence"] == after["rule_sequence"])


def test_a_window_holds_exactly_the_flags_inside_it() -> None:
    state = _cleaned()
    start, end = "2023-01-15T03:00:00+00:00", "2023-02-10T18:00:00+00:00"
    result = _flag_intervals(state, CHANNELS, start, end)
    flags = _canonical(state.cleaning_flags)
    inside = flags[(flags["timestamp"] >= pd.Timestamp(start)) & (flags["timestamp"] < pd.Timestamp(end))]
    pd.testing.assert_frame_equal(_expanded(state, result), inside.reset_index(drop=True))
    index = pd.DatetimeIndex(state.timeseries_df.index)
    assert result["records"] == int(((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end))).sum())


def test_past_the_limit_intervals_are_cut_and_counts_stay_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    import server.tools.flags as flags_module

    state = _cleaned()
    full = _flag_intervals(state, CHANNELS)
    monkeypatch.setattr(flags_module, "MAX_FLAG_INTERVALS", 5)
    cut = _flag_intervals(state, CHANNELS)
    assert full["interval_count"] > 5 and cut["interval_count"] == 5 and cut["truncated"] is True
    assert cut["interval_limit"] == 5 and MAX_FLAG_INTERVALS == 20000
    for name, channel in cut["channels"].items():
        assert channel["flagged_records"] == full["channels"][name]["flagged_records"]


def test_no_flags_is_an_empty_answer_not_a_refusal() -> None:
    state = SessionState()
    state.reset()
    _populate(state)
    result = _flag_intervals(state, "Spd_100m")
    assert result["channels"] == {"Spd_100m": {"flagged_records": 0, "intervals": []}}
    assert result["interval_count"] == 0 and result["unplaced_flags"] == 0


@pytest.mark.parametrize(
    ("channels", "start", "message"),
    [
        ("", "", "at least one channel"),
        ("Nope", "", "No channel named Nope"),
        ("Spd_100m,Spd_100m", "", "named twice"),
        ("Spd_100m", "2023-01-02 00:00", "no UTC offset"),
    ],
)
def test_refusals(channels: str, start: str, message: str) -> None:
    state = _cleaned()
    with pytest.raises(ValueError, match=message):
        _flag_intervals(state, channels, start)
