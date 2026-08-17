"""Regression tests for D30 — mast-shadow detection must be two-sided.

The old test was `ratio < baseline * 0.95` only, so a shadowed sensor_a — which
produces a *high* ratio — could never be reported, and which sensor got checked
depended on argument order alone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.diagnostics import (
    COMPASS_16,
    MAST_EFFECT_MIN_SECTOR_RECORDS,
    MAST_EFFECT_MIN_SPEED_MPS,
    _compute_mast_effects,
)

# Booms on opposite sides: A is shadowed from the east, B from the west.
SHADOW_A_SECTORS = {"E", "ESE", "ENE"}
SHADOW_B_SECTORS = {"W", "WNW", "WSW"}


def _mast_state(n: int = 40000, seed: int = 5, base_speed: float = 9.0) -> SessionState:
    """Build a paired-anemometer mast where each sensor is shadowed on its own side."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2021-01-01", periods=n, freq="10min", tz="UTC")
    directions = rng.uniform(0.0, 360.0, n)
    speed = rng.normal(base_speed, 1.0, n).clip(min=5.0)

    sector_index = (((np.mod(directions, 360.0) + 11.25) % 360.0) // 22.5).astype(int)
    labels = np.array(COMPASS_16, dtype=object)[sector_index]

    speed_a = speed.copy()
    speed_b = speed.copy()
    # A 12% deficit in each sensor's own shadowed sectors.
    speed_a[np.isin(labels, list(SHADOW_A_SECTORS))] *= 0.88
    speed_b[np.isin(labels, list(SHADOW_B_SECTORS))] *= 0.88

    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {"Spd_A_45m": speed_a, "Spd_B_45m": speed_b, "Dir_45m": directions}, index=index
    )
    return state


class TestTwoSidedDetection:
    """D30.1 — both shadowed sensors must be reported."""

    def test_both_sides_are_flagged(self) -> None:
        result = _compute_mast_effects(_mast_state(), "Spd_A_45m", "Spd_B_45m", "Dir_45m")
        assert SHADOW_A_SECTORS.issubset(set(result["affected_sectors_a"]))
        assert SHADOW_B_SECTORS.issubset(set(result["affected_sectors_b"]))

    def test_result_is_symmetric_under_argument_order(self) -> None:
        """Swapping the sensors must swap the lists, not change what is detected."""
        forward = _compute_mast_effects(_mast_state(), "Spd_A_45m", "Spd_B_45m", "Dir_45m")
        reversed_ = _compute_mast_effects(_mast_state(), "Spd_B_45m", "Spd_A_45m", "Dir_45m")

        assert set(forward["affected_sectors_a"]) == set(reversed_["affected_sectors_b"])
        assert set(forward["affected_sectors_b"]) == set(reversed_["affected_sectors_a"])

    def test_unshadowed_sectors_are_not_flagged(self) -> None:
        result = _compute_mast_effects(_mast_state(), "Spd_A_45m", "Spd_B_45m", "Dir_45m")
        flagged = set(result["affected_sectors_a"]) | set(result["affected_sectors_b"])
        assert "N" not in flagged
        assert "S" not in flagged

    def test_legacy_key_still_means_sensor_b(self) -> None:
        result = _compute_mast_effects(_mast_state(), "Spd_A_45m", "Spd_B_45m", "Dir_45m")
        assert result["affected_sectors"] == result["affected_sectors_b"]


class TestSpeedGate:
    """D30.2 — near-calm ratios are noise and must not be pooled in."""

    def test_default_gate_is_four_mps(self) -> None:
        assert MAST_EFFECT_MIN_SPEED_MPS == 4.0

    def test_below_gate_records_are_excluded(self) -> None:
        state = _mast_state(n=2000)
        # Drive half the records under the gate on sensor A.
        state.timeseries_df.iloc[:1000, state.timeseries_df.columns.get_loc("Spd_A_45m")] = 0.5
        result = _compute_mast_effects(state, "Spd_A_45m", "Spd_B_45m", "Dir_45m")
        assert result["records_used"] == 1000
        assert result["min_speed_mps"] == 4.0

    def test_all_calm_raises_with_the_threshold_named(self) -> None:
        state = _mast_state(n=500)
        state.timeseries_df["Spd_A_45m"] = 0.5
        state.timeseries_df["Spd_B_45m"] = 0.5
        with pytest.raises(ValueError, match="4 m/s"):
            _compute_mast_effects(state, "Spd_A_45m", "Spd_B_45m", "Dir_45m")


class TestSparseSectorSuppression:
    """D30.3 — thin sectors are reported but not flagged."""

    def test_sparse_sector_is_not_flagged(self) -> None:
        state = _mast_state(n=40000)
        result = _compute_mast_effects(
            state, "Spd_A_45m", "Spd_B_45m", "Dir_45m", min_sector_records=100_000
        )
        # Every sector is now "sparse", so nothing may be flagged.
        assert result["affected_sectors_a"] == []
        assert result["affected_sectors_b"] == []
        assert all(not row["sufficient_records"] for row in result["sectors"])

    def test_record_counts_are_reported_per_sector(self) -> None:
        result = _compute_mast_effects(_mast_state(), "Spd_A_45m", "Spd_B_45m", "Dir_45m")
        assert len(result["sectors"]) == 16
        assert all("record_count" in row for row in result["sectors"])
        assert sum(row["record_count"] for row in result["sectors"]) == result["records_used"]
        assert result["min_sector_records"] == MAST_EFFECT_MIN_SECTOR_RECORDS
