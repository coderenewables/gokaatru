"""A flag drawn on a chart is one rule over the whole instrument (P2-3, decisions/0014.1-3).

``exclude_selection`` freezes the selection's definition into the rule, sets every listed
column missing on the records it holds, and carries the analyst's reason on every flag. The
gate: where an older rule describes the same records, the two give the same flags, record
for record.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from server.operations import REGISTRY, acting_as
from server.state.session import SessionState, bind_session
from server.tools.cleaning import (
    MANUAL_FLAG_REASONS,
    RULES,
    _apply_cleaning_rule,
    _change_summary,
    _get_cleaning_log,
    _preview_cleaning_rule,
    _undo_cleaning_rule,
)
from tests.test_cleaning_flags import _reproduces, _same
from tests.test_dry_run import _fingerprint, _populate

INSTRUMENT = ["Spd_100m", "Spd_100m_sd"]
FEBRUARY = {"kind": "time_range", "start": "2023-02-01T00:00:00Z", "end": "2023-02-03T00:00:00Z"}


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    _populate(state)
    return state


def _params(definition: dict, reason: str = "icing", note: str = "", sensors: list[str] | None = None) -> str:
    return json.dumps({"definition": definition, "sensors": INSTRUMENT if sensors is None else sensors,
                       "reason": reason, "note": note})


def _flagged(state: SessionState, sensor: str) -> pd.DatetimeIndex:
    flags = state.cleaning_flags
    return pd.DatetimeIndex(flags.loc[flags["sensor"] == sensor, "timestamp"]).sort_values()


def test_one_flag_action_is_one_log_entry_over_every_column() -> None:
    state = _state()
    with acting_as("user"):
        applied = _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", _params(FEBRUARY, note="cups iced"))

    assert len(state.cleaning_log) == 1
    entry = state.cleaning_log[0]
    assert entry["rule_type"] == "exclude_selection" and entry["sensor"] == "Spd_100m"
    assert entry["params"]["definition"] == FEBRUARY and entry["params"]["note"] == "cups iced"
    assert entry["description"] == "from 2023-02-01T00:00:00Z to before 2023-02-03T00:00:00Z"
    assert entry["reason"] == "icing"
    february = state.timeseries_df.index[(state.timeseries_df.index >= "2023-02-01") &
                                         (state.timeseries_df.index < "2023-02-03")]
    assert entry["selected_records"] == len(february) == 288
    assert entry["affected_by_sensor"] == {"Spd_100m": 288, "Spd_100m_sd": 288}
    assert applied["records_affected"] == entry["records_affected"] == 576
    for column in INSTRUMENT:
        assert _flagged(state, column).equals(february)
        assert state.timeseries_df.loc[february, column].isna().all()
    assert state.timeseries_df["Dir_100m"].notna().all(), "an unticked column is untouched"
    flags = state.cleaning_flags
    assert set(flags["reason"]) == {"icing"} and set(flags["rule_sequence"]) == {1}
    assert set(flags["actor"]) == {"user"} and set(flags["rule_type"]) == {"exclude_selection"}
    assert _reproduces(state)


def test_a_period_flags_what_custom_period_exclude_flags() -> None:
    drawn, typed = _state(), _state()
    _apply_cleaning_rule(drawn, "exclude_selection", "Spd_100m", _params(FEBRUARY, sensors=[]))
    # custom_period_exclude's end is inclusive; the selection's is not, so the typed rule
    # ends on the last record before the drawn end.
    last = drawn.timeseries_df.index[drawn.timeseries_df.index < pd.Timestamp(FEBRUARY["end"])][-1]
    _apply_cleaning_rule(typed, "custom_period_exclude", "Spd_100m", "{}", "2023-02-01", last.isoformat())

    assert _flagged(drawn, "Spd_100m").equals(_flagged(typed, "Spd_100m"))
    assert _same(drawn.timeseries_df, typed.timeseries_df)


def test_a_box_flags_what_the_old_forms_expression_filter_flags() -> None:
    drawn, typed = _state(), _state()
    box = {
        "kind": "intersection",
        "of": [
            {"kind": "band", "channel": "Spd_100m", "min": 4.0, "max": 9.5},
            {"kind": "band", "channel": "Tmp_100m", "min": 2.0, "max": 11.0},
        ],
    }
    _apply_cleaning_rule(drawn, "exclude_selection", "Spd_100m", _params(box, reason="suspect", sensors=[]))
    expression = "Spd_100m >= 4.0 and Spd_100m < 9.5 and Tmp_100m >= 2.0 and Tmp_100m < 11.0"
    _apply_cleaning_rule(typed, "expression_filter", "Spd_100m", json.dumps({"expression": expression}))

    assert len(_flagged(drawn, "Spd_100m")) > 1000
    assert _flagged(drawn, "Spd_100m").equals(_flagged(typed, "Spd_100m"))
    assert _same(drawn.timeseries_df, typed.timeseries_df)


def test_sectors_on_the_paired_vane_flag_what_tower_shadow_flags_but_its_closing_edge() -> None:
    """tower_shadow includes its closing edge; a selection's sector does not. On every other
    record they agree; on the closing edge they differ by exactly the records on it."""
    drawn, typed = _state(), _state()
    for state in (drawn, typed):
        state.timeseries_df["Dir_100m"] = np.round(state.timeseries_df["Dir_100m"])
        state.raw_timeseries_df["Dir_100m"] = state.timeseries_df["Dir_100m"]
    sector = {"kind": "sector", "channel": "Dir_100m", "from_deg": 340.0, "to_deg": 25.0}
    _apply_cleaning_rule(drawn, "exclude_selection", "Spd_100m", _params(sector, reason="mast_or_boom_effect",
                                                                       sensors=[]))
    _apply_cleaning_rule(typed, "tower_shadow", "Spd_100m", json.dumps({"exclude_sectors": [340.0, 25.0]}))

    frame = typed.raw_timeseries_df
    on_edge = frame.index[(frame["Dir_100m"] == 25.0) & frame["Spd_100m"].notna()]
    assert len(on_edge) > 0
    assert _flagged(typed, "Spd_100m").equals(_flagged(drawn, "Spd_100m").union(on_edge))
    assert _flagged(drawn, "Spd_100m").intersection(on_edge).empty


def test_the_preview_is_the_change_applying_makes() -> None:
    state = _state()
    fingerprint = _fingerprint(state)
    before = state.timeseries_df.copy()
    params = _params(FEBRUARY)

    preview = _preview_cleaning_rule(state, "exclude_selection", "Spd_100m", params)

    assert _fingerprint(state) == fingerprint and state.cleaning_flags.empty
    _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", params)
    assert preview["changes"] == _change_summary(before, state.timeseries_df)
    assert preview["affected_by_sensor"] == {"Spd_100m": 288, "Spd_100m_sd": 288}


def test_undo_restores_the_series_bit_for_bit_and_replay_keeps_the_reason() -> None:
    state = _state()
    original = state.timeseries_df.copy()
    _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
    after_range = state.timeseries_df.copy()
    _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", _params(FEBRUARY, reason="maintenance"))

    # Undoing the earlier rule replays this one: same records, same reason.
    _undo_cleaning_rule(state, 0)
    assert [entry["rule_type"] for entry in state.cleaning_log] == ["exclude_selection"]
    assert set(state.cleaning_flags["reason"]) == {"maintenance"}
    assert _reproduces(state)

    _undo_cleaning_rule(state, 0)
    assert _same(state.timeseries_df, original)
    assert state.cleaning_flags.empty

    replay = _state()
    _apply_cleaning_rule(replay, "range_check", "Spd_100m", "{}")
    _apply_cleaning_rule(replay, "exclude_selection", "Spd_100m", _params(FEBRUARY))
    _undo_cleaning_rule(replay, 1)
    assert _same(replay.timeseries_df, after_range)


def test_undo_last_change_reverses_a_drawn_flag() -> None:
    state = _state()
    original = state.timeseries_df.copy()
    with bind_session(state):
        REGISTRY.get("apply_cleaning_rule").fn(rule_type="exclude_selection", sensor="Spd_100m",
                                               params=_params(FEBRUARY))
        REGISTRY.get("undo_last_change").fn()
    assert _same(state.timeseries_df, original) and state.cleaning_log == []


def test_a_later_rule_on_a_flagged_column_reports_the_order_dependence() -> None:
    state = _state()
    _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", _params(FEBRUARY))
    later = _apply_cleaning_rule(state, "range_check", "Spd_100m_sd", "{}")
    listed = later["order_dependence"]["applied_before_on_this_sensor"]
    assert listed == [{"sequence": 1, "rule_type": "exclude_selection", "sensor": "Spd_100m"}]
    assert "warning" in later["order_dependence"]


def test_the_log_summary_carries_the_reason() -> None:
    state = _state()
    _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", _params(FEBRUARY, reason="suspect"))
    rows = _get_cleaning_log(state)["flags"]["by_rule"]
    assert {(row["sensor"], row["reason"], row["records"]) for row in rows} == {
        ("Spd_100m", "suspect", 288),
        ("Spd_100m_sd", "suspect", 288),
    }


def test_the_rule_and_its_reasons_are_listed() -> None:
    assert set(RULES["exclude_selection"]) == {"definition", "sensors", "reason", "note"}
    assert MANUAL_FLAG_REASONS == (
        "icing", "maintenance", "instrument_fault", "mast_or_boom_effect", "logger_or_transfer_fault", "suspect",
        "other",
    )


@pytest.mark.parametrize(
    ("params", "dates", "message"),
    [
        ({"definition": FEBRUARY, "reason": "frost"}, ("", ""), "'reason' must be one of"),
        ({"definition": FEBRUARY, "reason": "other", "note": "  "}, ("", ""), "needs a note"),
        ({"definition": FEBRUARY, "reason": "icing"}, ("2023-02-01", ""), "give no start_date"),
        ({"reason": "icing"}, ("", ""), "needs the selection's 'definition'"),
        ({"definition": "north", "reason": "icing"}, ("", ""), "needs the selection's 'definition'"),
        ({"definition": FEBRUARY, "reason": "icing", "sensors": ["Spd_100m_sd", "Spd_100m_sd"]}, ("", ""), "twice"),
        ({"definition": FEBRUARY, "reason": "icing", "sensors": ["Nope"]}, ("", ""), "'Nope' not found"),
        ({"definition": {"kind": "band", "channel": "Nope", "min": 1}, "reason": "icing"}, ("", ""),
         "exclude_selection: Channel 'Nope'"),
        ({"definition": FEBRUARY, "reason": "icing", "note": 3}, ("", ""), "must be text"),
    ],
)
def test_a_flag_that_cannot_be_applied_as_written_is_refused(params: dict, dates: tuple, message: str) -> None:
    state = _state()
    with pytest.raises(ValueError, match=message):
        _apply_cleaning_rule(state, "exclude_selection", "Spd_100m", json.dumps(params), *dates)
    assert state.cleaning_log == [] and state.cleaning_flags.empty


def test_other_with_a_note_is_accepted() -> None:
    state = _state()
    _apply_cleaning_rule(state, "exclude_selection", "Spd_100m",
                         _params(FEBRUARY, reason="other", note="bird on the cup"))
    assert state.cleaning_log[0]["params"]["note"] == "bird on the cup"
