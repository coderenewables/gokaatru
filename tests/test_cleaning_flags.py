"""Every record cleaning removes carries a flag saying which rule, why, who and when, and
raw data with the flags applied is exactly the clean series (P1-11, decisions/0010)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from server.operations import acting_as
from server.state.project import ProjectStore
from server.state.session import SessionState
from server.tools.cleaning import (
    FLAG_REASONS,
    _apply_cleaning_rule,
    _clean_series,
    _get_cleaning_log,
    _preview_cleaning_rule,
    _undo_cleaning_rule,
)
from tests.test_dry_run import RULES, _populate


def _state() -> SessionState:
    state = SessionState()
    state.reset()
    _populate(state)
    return state


def _same(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    """Bit-for-bit equal, NaN for NaN, on the same index and columns."""
    if not left.index.equals(right.index) or list(left.columns) != list(right.columns):
        return False
    a, b = left.to_numpy(dtype=float), right.to_numpy(dtype=float)
    return bool(np.array_equal(a, b, equal_nan=True))


def _reproduces(state: SessionState) -> bool:
    working = state.timeseries_df
    raw_columns = [column for column in state.raw_timeseries_df.columns if column in working.columns]
    rebuilt = _clean_series(state.raw_timeseries_df[raw_columns], working.index, state.cleaning_flags)
    return _same(rebuilt, working[raw_columns])


@pytest.mark.parametrize(("rule", "sensor", "params", "start", "end"), RULES, ids=[rule[0] for rule in RULES])
def test_a_rules_flags_are_exactly_the_records_it_removed(rule, sensor, params, start, end) -> None:
    state = _state()
    before = state.timeseries_df[sensor].isna()

    with acting_as("user"):
        applied = _apply_cleaning_rule(state, rule, sensor, params, start, end)

    flags = state.cleaning_flags
    if rule == "timestamp_gap_fill":
        assert flags.empty
        return
    after = state.timeseries_df[sensor].isna()
    removed = state.timeseries_df.index[after.to_numpy() & ~before.reindex(after.index, fill_value=True).to_numpy()]
    assert len(flags) == applied["records_affected"] == len(removed)
    assert pd.DatetimeIndex(flags["timestamp"]).equals(pd.DatetimeIndex(removed))
    assert set(flags["reason"]) == {FLAG_REASONS[rule]}
    assert set(flags["actor"]) == {"user"}
    assert set(flags["rule_sequence"]) == {1}


def test_raw_data_with_the_flags_applied_is_the_clean_series() -> None:
    state = _state()
    for rule, sensor, params, start, end in RULES:
        _apply_cleaning_rule(state, rule, sensor, params, start, end)
        assert _reproduces(state), rule
    _undo_cleaning_rule(state, 1)
    assert _reproduces(state)


def test_undo_removes_the_rules_flags_and_keeps_who_applied_the_rest() -> None:
    state = _state()
    with acting_as("user"):
        _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
    with acting_as("assistant:openai/gpt-4o"):
        _apply_cleaning_rule(state, "stuck_sensor", "Spd_100m", "{}")
    with acting_as("canvas"):
        _apply_cleaning_rule(state, "expression_filter", "Spd_100m", json.dumps({"expression": "Spd_100m > 15"}))
    times = state.cleaning_flags.groupby("rule_sequence")["flagged_at"].first()

    with acting_as("user"):
        _undo_cleaning_rule(state, 1)

    flags = state.cleaning_flags
    assert set(flags["rule_type"]) == {"range_check", "expression_filter"}
    assert flags.groupby("rule_sequence")["actor"].first().to_dict() == {1: "user", 2: "canvas"}
    assert flags.groupby("rule_sequence")["flagged_at"].first().to_dict() == {1: times[1], 2: times[3]}
    assert _reproduces(state)


def test_a_rule_that_only_flags_on_replay_keeps_its_own_actor_and_time() -> None:
    """A period is excluded, then a filter over the same period finds nothing left to remove.
    Undoing the exclusion lets the replayed filter flag the period: the flags are the
    filter's, applied by the assistant, not the undo's."""
    state = _state()
    period = ("2023-02-01", "2023-02-03")
    with acting_as("user"):
        _apply_cleaning_rule(state, "custom_period_exclude", "Spd_100m", "{}", *period)
    with acting_as("assistant:openai/gpt-4o"):
        later = _apply_cleaning_rule(
            state, "expression_filter", "Spd_100m", json.dumps({"expression": "Spd_100m >= 0"}), *period
        )
    applied = state.cleaning_log[1]
    assert later["records_affected"] == 0 and applied["actor"] == "assistant:openai/gpt-4o"

    with acting_as("user"):
        _undo_cleaning_rule(state, 0)

    flags = state.cleaning_flags
    assert len(flags) > 200 and set(flags["rule_type"]) == {"expression_filter"}
    assert set(flags["actor"]) == {"assistant:openai/gpt-4o"}
    assert set(flags["flagged_at"]) == {applied["applied_at"]}
    replayed = state.cleaning_log[0]
    assert replayed["actor"] == "assistant:openai/gpt-4o" and replayed["applied_at"] == applied["applied_at"]


def test_who_applied_a_rule_is_not_part_of_the_prefix() -> None:
    from server.core.scenario_result import fixed_prefix_hash

    hashes = []
    for actor in ("user", "assistant:openai/gpt-4o"):
        state = _state()
        with acting_as(actor):
            _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
        hashes.append(fixed_prefix_hash(state))
    assert hashes[0] == hashes[1]


def test_the_log_summarises_the_flags() -> None:
    state = _state()
    _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
    summary = _get_cleaning_log(state)["flags"]
    assert summary == {
        "flagged_records": 10,
        "by_rule": [
            {
                "rule_sequence": 1,
                "rule_type": "range_check",
                "reason": "out_of_range",
                "sensor": "Spd_100m",
                "records": 10,
            }
        ],
    }


def test_a_preview_adds_no_flags() -> None:
    state = _state()
    _preview_cleaning_rule(state, "range_check", "Spd_100m", "{}")
    assert state.cleaning_flags.empty


def test_flags_survive_the_project_store(tmp_path: Path) -> None:
    state = _state()
    state.workspace_dir = tmp_path
    _apply_cleaning_rule(state, "range_check", "Spd_100m", "{}")
    _apply_cleaning_rule(state, "stuck_sensor", "Spd_100m", "{}")
    ProjectStore(tmp_path).save(state)

    restored = SessionState()
    ProjectStore(tmp_path).load(restored)
    pd.testing.assert_frame_equal(restored.cleaning_flags, state.cleaning_flags)
    assert _reproduces(restored)


@pytest.mark.parametrize("name", ["boxkite", "horns_rev", "launakalana"])
def test_on_each_campaign_the_flags_reproduce_the_cleaned_series(name: str) -> None:
    """The published-numbers cleaning sequence, undo included, on real data."""
    from server.state.session import get_active_session
    from tests import published_numbers as harness

    campaign = harness.CAMPAIGNS[name]
    if not all(path.exists() for path in campaign.files()):
        pytest.skip(f"campaign files not present for {name}")
    recorder = harness.Recorder()
    harness._load(campaign, recorder)
    harness._clean(campaign, recorder)
    state = get_active_session()

    assert not state.cleaning_flags.empty
    assert _reproduces(state)
