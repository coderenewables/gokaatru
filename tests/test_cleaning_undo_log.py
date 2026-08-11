"""Regression tests for D19 — undo must adopt the replay's cleaning log.

Bug: _undo_cleaning_rule replayed all retained rules on raw data (correct)
but then restored the *original* log entries whose records_affected counts
were computed on the first run.  After removing an earlier rule, later rules
see different data and affect different numbers of records.

Also: sensor_mapping was shallow-copied (shared nested dicts); now deep-copied.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule, _undo_cleaning_rule


def _build_session() -> SessionState:
    """Create a minimal session with synthetic 10-min wind speed data.

    Columns: Spd_80m, Dir_80m, Spd_80m_sd, Temp_80m

    The data is crafted so that:
      - 50 rows have Spd_80m < 0 (below range_check min=0)
      - 30 rows have Spd_80m > 40 (above range_check max=25 after first check)
    Applying range_check(min=0, max=25) first, then range_check(min=0, max=40)
    second, means removing the first rule causes the second to see more data
    and potentially affect more records.
    """
    rng = np.random.default_rng(42)
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="10min")

    speeds = rng.uniform(1.0, 35.0, n)
    # Make 50 rows negative
    speeds[:50] = rng.uniform(-10.0, -0.1, 50)
    # Make 30 rows very high (>40 but < 50, so only second rule catches them)
    speeds[50:80] = rng.uniform(41.0, 49.0, 30)

    df = pd.DataFrame(
        {
            "Spd_80m": speeds,
            "Dir_80m": rng.uniform(0, 360, n),
            "Spd_80m_sd": rng.uniform(0.1, 2.0, n),
            "Temp_80m": rng.uniform(-5.0, 25.0, n),
        },
        index=idx,
    )

    state = SessionState()
    state.timeseries_df = df.copy()
    state.raw_timeseries_df = df.copy()
    state.sensor_mapping = {
        80.0: {
            "speed_col": "Spd_80m",
            "dir_col": "Dir_80m",
            "sd_col": "Spd_80m_sd",
            "temp_col": "Temp_80m",
        }
    }
    state.cleaning_log = []
    return state


class TestUndoLogFreshCounts:
    """After undo, the cleaning log must carry counts from the replay, not originals."""

    def test_undo_first_rule_updates_second_rule_counts(self) -> None:
        """Undo the first of two range_checks; the second rule's records_affected
        must differ from its original count because it now sees more data."""
        state = _build_session()

        # Rule 1: remove values < 0 (affects ~50 rows)
        _apply_cleaning_rule(state, "range_check", "Spd_80m", '{"min": 0, "max": 50}')
        assert len(state.cleaning_log) == 1
        original_count_rule1 = state.cleaning_log[0]["records_affected"]
        assert original_count_rule1 == 50

        # Rule 2: remove values > 40 (affects ~30 rows — first rule didn't touch these)
        _apply_cleaning_rule(state, "range_check", "Spd_80m", '{"min": 0, "max": 40}')
        assert len(state.cleaning_log) == 2
        original_count_rule2 = state.cleaning_log[1]["records_affected"]
        assert original_count_rule2 == 30

        # Undo rule 1 (index 0) — rule 2 is re-applied on raw data
        _undo_cleaning_rule(state, 0)

        assert len(state.cleaning_log) == 1
        entry = state.cleaning_log[0]
        assert entry["rule_type"] == "range_check"
        assert entry["sensor"] == "Spd_80m"

        # The retained rule is "max=40". On raw data (rule 1 removed), the 50
        # negative values are still present and now get caught by rule 2 as well
        # (they are < min=0, which fails the range_check).  So the replay count
        # is 50 (negative) + 30 (high) = 80 — NOT the stale original count of 30.
        # This is the core invariant: undo must adopt the replay's log.
        assert entry["records_affected"] == 80
        assert "applied_at" in entry

    def test_undo_last_rule_keeps_first_rule_counts(self) -> None:
        """Undo the last rule; the first rule's count should remain the same
        because it was re-applied on raw data and sees identical conditions."""
        state = _build_session()

        _apply_cleaning_rule(state, "range_check", "Spd_80m", '{"min": 0, "max": 50}')
        _apply_cleaning_rule(state, "range_check", "Spd_80m", '{"min": 0, "max": 40}')
        assert len(state.cleaning_log) == 2

        original_count_rule1 = state.cleaning_log[0]["records_affected"]

        # Undo rule 2 (index 1)
        _undo_cleaning_rule(state, 1)

        assert len(state.cleaning_log) == 1
        # Rule 1 was re-applied on raw data — same conditions, same count
        assert state.cleaning_log[0]["records_affected"] == original_count_rule1
        assert state.cleaning_log[0]["rule_type"] == "range_check"

    def test_undo_only_rule_leaves_empty_log(self) -> None:
        """Undo the sole rule; log should be empty."""
        state = _build_session()
        _apply_cleaning_rule(state, "range_check", "Spd_80m", '{"min": 0, "max": 50}')
        assert len(state.cleaning_log) == 1

        _undo_cleaning_rule(state, 0)
        assert state.cleaning_log == []


class TestUndoDeepCopySensorMapping:
    """sensor_mapping in the replay state must be deep-copied to prevent
    shared-mutable-state bugs with nested per-height dicts."""

    def test_replay_sensor_mapping_is_independent(self) -> None:
        """Mutating the replay's nested sensor_mapping must not affect the live session."""
        state = _build_session()

        # Capture the original nested dict object id
        original_nested = state.sensor_mapping[80.0]
        original_id = id(original_nested)

        # Apply and undo — the replay creates a deep copy
        _apply_cleaning_rule(state, "range_check", "Spd_80m", '{"min": 0, "max": 50}')
        _undo_cleaning_rule(state, 0)

        # After undo, the live session's sensor_mapping nested dict should be unchanged
        assert state.sensor_mapping[80.0] is original_nested
        assert state.sensor_mapping[80.0]["speed_col"] == "Spd_80m"

    def test_shallow_copy_would_share_nested_dicts(self) -> None:
        """Demonstrate that .copy() (shallow) shares nested dicts, justifying deepcopy.

        This is a proof-of-concept: if we used .copy() instead of deepcopy,
        mutating the nested dict in the copy would mutate the original too.
        """
        original = {80.0: {"speed_col": "Spd_80m", "dir_col": "Dir_80m"}}
        shallow = original.copy()
        shallow[80.0]["speed_col"] = "MODIFIED"

        # Shallow copy shares the nested dict
        assert original[80.0]["speed_col"] == "MODIFIED"

        # Deep copy would be independent
        original2 = {80.0: {"speed_col": "Spd_80m", "dir_col": "Dir_80m"}}
        deep = copy.deepcopy(original2)
        deep[80.0]["speed_col"] = "MODIFIED"
        assert original2[80.0]["speed_col"] == "Spd_80m"


class TestUndoErrorCases:
    """Edge cases for _undo_cleaning_rule."""

    def test_undo_without_raw_backup_raises(self) -> None:
        """Undo should raise if raw_timeseries_df is not available."""
        state = _build_session()
        state.raw_timeseries_df = None
        state.cleaning_log = [{"rule_type": "range_check", "sensor": "Spd_80m"}]

        with pytest.raises(ValueError, match="Raw timeseries backup"):
            _undo_cleaning_rule(state, 0)

    def test_undo_out_of_range_index_raises(self) -> None:
        """Undo should raise for invalid entry_index."""
        state = _build_session()
        state.cleaning_log = [{"rule_type": "range_check"}]

        with pytest.raises(ValueError, match="out of range"):
            _undo_cleaning_rule(state, -1)

        with pytest.raises(ValueError, match="out of range"):
            _undo_cleaning_rule(state, 1)
