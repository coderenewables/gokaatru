"""Staleness after cleaning: Step 1 of the logic audit (F-11, F-12).

Moved from ``test_workflow_contract.py`` when the Canvas executor it pinned was retired
(P3-17d): these three never ran through the executor. A long-lived mutable session leaves
derived results describing data no longer in it unless each result records the data version
it was built from.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule
from server.tools.shear import _calculate_shear_timeseries
from tests.oracles import timestamp_index


def _shear_state() -> SessionState:
    """Return a session holding an exact two-height power-law series (alpha = 0.20)."""
    index = timestamp_index("2021-01-01", periods=6 * 24 * 120, step_minutes=10)
    rng = np.random.default_rng(5)
    speed_100 = 6.0 + rng.gamma(shape=4.0, scale=1.0, size=len(index))
    heights = np.array([60.0, 100.0])
    state = SessionState()
    state.reset()
    frame = pd.DataFrame(
        {
            "Spd_60m": speed_100 * (heights[0] / heights[1]) ** 0.20,
            "Spd_100m": speed_100,
        },
        index=index,
    )
    state.timeseries_df = frame
    state.raw_timeseries_df = frame.copy()
    return state


def test_cleaning_does_not_invalidate_a_shear_result_computed_before_it():
    """FINDING (Step 1, confirmed): upstream mutation leaves downstream artifacts stale.

    Shear is computed, then a cleaning rule removes a large share of the records
    it was computed from. ``state.shear_timeseries_df`` is untouched and carries no
    marker of the data version it was derived from, so a later extrapolation node
    uses a shear distribution that describes data no longer in the session. Nothing
    warns, and the archived run records both stages as ``done``.
    """
    state = _shear_state()
    height_sensors = json.dumps({"60": "Spd_60m", "100": "Spd_100m"})

    _calculate_shear_timeseries(state, height_sensors)
    before = state.shear_timeseries_df
    assert before is not None
    records_before = int(len(before.dropna()))
    mean_alpha_before = float(before.iloc[:, 0].dropna().mean())

    # Remove the upper half of the speed distribution — a drastic but legal filter.
    result = _apply_cleaning_rule(state, "range_check", "Spd_100m", json.dumps({"min": 0.0, "max": 9.0}))
    assert int(result["records_affected"]) > 0

    after = state.shear_timeseries_df
    assert after is before  # still not silently recomputed...
    assert int(len(after.dropna())) == records_before
    assert float(after.iloc[:, 0].dropna().mean()) == pytest.approx(mean_alpha_before)

    # ...but it is now flagged as no longer matching the measured data.
    assert state.derived_is_stale("shear_timeseries")
    report = state.staleness_report()
    assert "shear_timeseries" in report["stale_artifacts"]
    assert "warning" in report

    # Recomputing on the cleaned data gives a different answer, so the stale value mattered.
    _calculate_shear_timeseries(state, height_sensors)
    recomputed = state.shear_timeseries_df
    assert recomputed is not None
    assert int(len(recomputed.dropna())) < records_before

    # Recomputing on the current data clears the flag.
    state.stamp_derived("shear_timeseries")
    assert not state.derived_is_stale("shear_timeseries")


def test_undoing_a_cleaning_rule_silently_deletes_the_hub_height_column():
    """FINDING (Step 1, confirmed): undo rebuilds the working frame from raw and drops derived columns.

    ``extrapolation`` writes its results *into* ``state.timeseries_df`` as new
    columns (``Spd_<hub>m_hub``, ``shear_coefficient``). ``_undo_cleaning_rule``
    rebuilds the frame from ``state.raw_timeseries_df``, which only ``data_io``
    ever writes and which therefore never holds those derived columns. So undoing
    any cleaning rule deletes the hub-height series.

    The dangerous part was the asymmetry: ``ltc_results``, ``ensemble_df`` and
    ``latest_uncertainty`` survived untouched, so the session kept reporting long-term
    numbers derived from a hub-height column that no longer existed.

    Undo still rebuilds from raw — that is its job — but it now reports the derived columns
    it removed and bumps the data version, so everything downstream is flagged stale.
    """
    from server.tools.cleaning import _undo_cleaning_rule
    from server.tools.extrapolation import _extrapolate_to_hub_height
    from server.tools.shear import _build_shear_table

    state = _shear_state()
    state.sensor_mapping = {
        60.0: {"speed_col": "Spd_60m", "direction_col": None},
        100.0: {"speed_col": "Spd_100m", "direction_col": None},
    }
    _calculate_shear_timeseries(state, json.dumps({"60": "Spd_60m", "100": "Spd_100m"}))
    _build_shear_table(state)
    _apply_cleaning_rule(state, "range_check", "Spd_100m", json.dumps({"min": 0.0, "max": 40.0}))

    hub = _extrapolate_to_hub_height(state, 120.0, "power_law")
    hub_column = str(hub["column_name"])
    assert hub_column in state.timeseries_df.columns
    assert hub_column not in state.raw_timeseries_df.columns

    # Stand in for downstream long-term results that were derived from the hub column.
    state.ltc_results["linear_least_squares"] = {"metrics": {"r_squared": 0.91}, "df": pd.DataFrame()}

    result = _undo_cleaning_rule(state, 0)

    assert hub_column not in state.timeseries_df.columns  # still removed...
    # ...but no longer silently: the response names it.
    assert hub_column in result["dropped_columns"]
    assert "warning" in result

    # Everything derived from it survives in state, and is flagged as stale.
    assert "linear_least_squares" in state.ltc_results
    assert state.shear_timeseries_df is not None
    assert "hub_height_series" in result["stale_artifacts"]


def test_every_derived_artifact_now_tracks_the_data_version_it_was_built_from():
    """F-11 — FIXED. Regression test: derived artifacts must be stamped and comparable.

    Before the fix, ``reanalysis_cache_identity`` was the *only* artifact that tracked what
    it was built from. Shear tables, LTC results, the ensemble and the uncertainty result
    had no equivalent, which is why cleaning could silently invalidate all of them.

    A monotonic ``data_version`` on the session is bumped by every mutation of the measured
    working data, and each derived artifact records the version it was built from, so any
    consumer can compare.
    """
    state = SessionState()
    state.reset()

    assert state.data_version == 0
    assert state.derived_versions == {}
    assert state.stale_artifacts() == []

    state.stamp_derived("shear_table")
    assert not state.derived_is_stale("shear_table")

    state.bump_data_version()
    assert state.data_version == 1
    assert state.derived_is_stale("shear_table")
    assert state.stale_artifacts() == ["shear_table"]

    report = state.staleness_report()
    assert report["data_version"] == 1
    assert report["stale_artifacts"] == ["shear_table"]
    assert "warning" in report

    # Recomputing clears it.
    state.stamp_derived("shear_table")
    assert state.stale_artifacts() == []
    assert "warning" not in state.staleness_report()
