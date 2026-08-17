"""Regression tests for D27 — BrightHub upstream cleaning must be recorded.

BrightHub cleans the data before GoKaatru sees it. The cleaning log is presented
as the record of what was removed and used as an audit artifact, so it has to say
that upstream processing happened even though GoKaatru cannot quantify or undo it.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule, _undo_cleaning_rule

N = 120


def _csv_text() -> str:
    index = pd.date_range("2021-01-01", periods=N, freq="10min")
    frame = pd.DataFrame(
        {
            "Timestamp": index.strftime("%Y-%m-%d %H:%M:%S"),
            "Spd_80m": np.linspace(4.0, 14.0, N),
            "Dir_80m": np.linspace(0.0, 359.0, N),
        }
    )
    return frame.to_csv(index=False)


def _datamodel() -> dict:
    return {
        "measurement_location": [
            {
                "name": "Test Mast",
                "latitude_ddeg": 52.0,
                "longitude_ddeg": 4.0,
                "measurement_station_type_id": "mast",
                # Required since D8: ingest refuses to guess a campaign timezone.
                "logger_main_config": [{"offset_from_utc_hrs": 0}],
                "measurement_point": [
                    {"name": "Spd_80m", "height_m": 80.0, "measurement_type_id": "wind_speed"},
                    {"name": "Dir_80m", "height_m": 80.0, "measurement_type_id": "wind_direction"},
                ],
            }
        ]
    }


@pytest.fixture
def imported_session(tmp_path):
    """Import a synthetic BrightHub location with the upstream flags exercised."""
    from server.tools.brighthub import brighthub_import_location

    state = SessionState()
    state.reset()
    state.workspace_dir = tmp_path
    state.brighthub_token = "test-token"

    with (
        patch("server.tools.brighthub.get_active_session", return_value=state),
        patch("server.tools.brighthub.session", state),
        patch("server.tools.brighthub._require_token", return_value="test-token"),
        patch("server.tools.brighthub.get_data_model", return_value=_datamodel()),
        patch("server.tools.brighthub.fetch_timeseries_csv", return_value=_csv_text()),
    ):
        result = brighthub_import_location(
            "uuid-1234",
            name="Test Mast",
            apply_cleaning_log=True,
            apply_calibration=True,
            apply_deadband_offset=False,
            apply_orientation_offset=True,
        )
    return state, result


class TestProvenanceEntry:
    """D27.1 — the flags are recorded at the head of the cleaning log."""

    def test_entry_is_first_in_the_log(self, imported_session) -> None:
        state, _ = imported_session
        assert state.cleaning_log
        assert state.cleaning_log[0]["rule_type"] == "brighthub_upstream_processing"
        assert state.cleaning_log[0]["source"] == "brighthub"

    def test_entry_records_the_applied_flags(self, imported_session) -> None:
        state, _ = imported_session
        params = state.cleaning_log[0]["params"]
        assert params["apply_cleaning_log"] is True
        assert params["apply_calibration"] is True
        assert params["apply_device_orientation_offset"] is True
        assert params["apply_wind_vane_deadband_offset"] is False

    def test_entry_is_marked_upstream_and_non_undoable(self, imported_session) -> None:
        state, _ = imported_session
        entry = state.cleaning_log[0]
        assert entry["upstream"] is True
        assert entry["undoable"] is False
        # GoKaatru cannot know how many records upstream cleaning touched.
        assert entry["records_affected"] is None

    def test_entry_does_not_claim_a_record_count(self, imported_session) -> None:
        state, _ = imported_session
        assert "cannot report how many records" in state.cleaning_log[0]["note"]


class TestImportResponse:
    """D27.2 — the flags are surfaced in the import response too."""

    def test_response_carries_upstream_flags(self, imported_session) -> None:
        _, result = imported_session
        assert result["upstream_processing"]["apply_cleaning_log"] is True
        assert result["upstream_processing"]["apply_calibration"] is True
        assert result["upstream_processing_note"]


class TestNonUndoable:
    """The provenance entry must survive undo and must not be undoable itself."""

    def test_undoing_provenance_is_refused(self, imported_session) -> None:
        state, _ = imported_session
        with pytest.raises(ValueError, match="cannot reverse"):
            _undo_cleaning_rule(state, 0)

    def test_provenance_survives_undo_of_a_real_rule(self, imported_session) -> None:
        state, _ = imported_session
        _apply_cleaning_rule(state, "range_check", "Spd_80m", json.dumps({"min": 0.0, "max": 10.0}))
        assert len(state.cleaning_log) == 2

        _undo_cleaning_rule(state, 1)

        assert state.cleaning_log[0]["rule_type"] == "brighthub_upstream_processing"
        assert len(state.cleaning_log) == 1
        # The undone rule's effect is reversed.
        assert state.timeseries_df["Spd_80m"].notna().sum() == N

    def test_remaining_rules_excludes_provenance(self, imported_session) -> None:
        state, _ = imported_session
        _apply_cleaning_rule(state, "range_check", "Spd_80m", json.dumps({"min": 0.0, "max": 10.0}))
        result = _undo_cleaning_rule(state, 1)
        assert result["remaining_rules"] == 0


class TestReplayUsesSensorInventory:
    """Replay must resolve range_check bounds the same way the original run did (D16 + D27)."""

    def test_typed_bounds_survive_replay(self, imported_session) -> None:
        state, _ = imported_session
        # Two rules: a typed direction check (no-op) then a speed check.
        _apply_cleaning_rule(state, "range_check", "Dir_80m", "{}")
        _apply_cleaning_rule(state, "range_check", "Spd_80m", json.dumps({"min": 0.0, "max": 10.0}))
        removed_before = int(state.timeseries_df["Spd_80m"].isna().sum())
        assert removed_before > 0

        # Undo the direction no-op; the speed rule must replay identically.
        _undo_cleaning_rule(state, 1)

        assert int(state.timeseries_df["Spd_80m"].isna().sum()) == removed_before
        replayed = state.cleaning_log[-1]
        assert replayed["sensor"] == "Spd_80m"
        assert replayed["bounds_source"] == "explicit"
