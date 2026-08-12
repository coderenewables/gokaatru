"""Regression tests for D15+D29 — spike filter uses robust median/MAD detection.

The old centred rolling mean/std was self-masking: a spike inflated the very
statistics used to detect it, so 0 of 3 obvious spikes were removed.

The fix replaces mean/std with median/MAD via a shared helper in
``server.core.validators``, used by both ``cleaning.py`` and ``diagnostics.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from server.core.validators import rolling_median_mad_spike_mask
from server.tools.cleaning import _apply_spike_filter
from server.tools.diagnostics import _spike_count


def _spike_fixture() -> tuple[pd.DataFrame, list[int]]:
    """Return a DataFrame with baseline ~7 m/s noise and three injected spikes.

    Uses a low-noise seed (sigma=0.3) so no baseline value is falsely flagged
    at the default 4-MAD threshold.  Spikes are injected at positions 50, 100, 150
    with values far above the baseline.
    """
    rng = np.random.RandomState(0)
    n = 200
    baseline = 7.0 + rng.normal(0, 0.3, n)
    baseline[50] = 25.0
    baseline[100] = 40.0
    baseline[150] = 60.0
    df = pd.DataFrame({"Spd_80m": baseline})
    return df, [50, 100, 150]


class TestSpikeFilterRemovesSpikes:
    """D15: _apply_spike_filter must detect and remove obvious spikes."""

    def test_removes_all_three_spikes(self) -> None:
        """Three injected spikes at 25/40/60 m/s in ~7 m/s baseline must be removed."""
        df, spike_indices = _spike_fixture()
        mask = np.ones(len(df), dtype=bool)
        removed = _apply_spike_filter(df, "Spd_80m", mask, {})
        assert removed == 3, f"Expected 3 spikes removed, got {removed}"
        for idx in spike_indices:
            assert pd.isna(df.loc[idx, "Spd_80m"]), f"Spike at index {idx} was not removed"

    def test_leaves_baseline_intact(self) -> None:
        """Non-spike records must not be modified."""
        df, spike_indices = _spike_fixture()
        original = df["Spd_80m"].copy()
        mask = np.ones(len(df), dtype=bool)
        _apply_spike_filter(df, "Spd_80m", mask, {})
        non_spike = [i for i in range(len(df)) if i not in spike_indices]
        for idx in non_spike:
            assert df.loc[idx, "Spd_80m"] == pytest.approx(original[idx])

    def test_respects_date_mask(self) -> None:
        """Only records within the date mask should be considered."""
        df, _ = _spike_fixture()
        mask = np.zeros(len(df), dtype=bool)
        mask[50] = True  # Only the 25 m/s spike is in range
        removed = _apply_spike_filter(df, "Spd_80m", mask, {})
        assert removed == 1
        assert pd.isna(df.loc[50, "Spd_80m"])
        assert not pd.isna(df.loc[100, "Spd_80m"])  # outside mask


class TestSpikeCountMatchesFilter:
    """D29: _spike_count must agree with _apply_spike_filter on spike identification."""

    def test_counts_all_three_spikes(self) -> None:
        """QC diagnostics must report the same spikes the filter would remove."""
        df, _ = _spike_fixture()
        count = _spike_count(df["Spd_80m"])
        assert count == 3, f"Expected 3 spikes counted, got {count}"

    def test_filter_and_count_agree(self) -> None:
        """The number removed by the filter must equal the number counted by diagnostics."""
        df, _ = _spike_fixture()
        # Count first (non-mutating)
        count = _spike_count(df["Spd_80m"])
        # Filter (mutating)
        mask = np.ones(len(df), dtype=bool)
        removed = _apply_spike_filter(df, "Spd_80m", mask, {})
        assert removed == count


class TestConstantStretchNotFlagged:
    """Constant stretches (MAD == 0) must not produce false spike detections."""

    def test_stuck_sensor_no_spikes(self) -> None:
        """A constant sensor reading should report 0 spikes."""
        series = pd.Series(np.full(100, 5.0))
        assert _spike_count(series) == 0

    def test_stuck_sensor_filter_no_removals(self) -> None:
        """A constant sensor reading should have 0 removals from spike_filter."""
        df = pd.DataFrame({"Spd_80m": np.full(100, 5.0)})
        mask = np.ones(100, dtype=bool)
        removed = _apply_spike_filter(df, "Spd_80m", mask, {})
        assert removed == 0


class TestSharedHelperConvergence:
    """D15+D29: both call sites must use the same shared algorithm."""

    def test_cleaning_imports_shared_helper(self) -> None:
        """cleaning._apply_spike_filter delegates to rolling_median_mad_spike_mask."""
        import inspect

        from server.tools import cleaning

        source = inspect.getsource(cleaning)
        assert "rolling_median_mad_spike_mask" in source

    def test_diagnostics_imports_shared_helper(self) -> None:
        """diagnostics._spike_count delegates to rolling_median_mad_spike_mask."""
        import inspect

        from server.tools import diagnostics

        source = inspect.getsource(diagnostics)
        assert "rolling_median_mad_spike_mask" in source

    def test_helper_default_window_is_11(self) -> None:
        """The shared helper default window must be 11 (was 6 before D15)."""
        import inspect

        sig = inspect.signature(rolling_median_mad_spike_mask)
        assert sig.parameters["window"].default == 11
