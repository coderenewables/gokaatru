"""Regression tests for D32 — diurnal boxplot must disclose downsampling.

Bug: _plot_diurnal_boxplot silently subsampled via _sample_for_boxplot but
did not disclose the sampling in the figure title or return the counts in
the payload.  Quartiles and whiskers represented a subset, not the full record.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.visualization import _plot_diurnal_boxplot, _sample_for_boxplot


def _boxplot_session(n_rows: int, sensor: str = "Spd_80m") -> SessionState:
    """Build a minimal session with n_rows of 10-min wind-speed data."""
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n_rows, freq="10min")
    df = pd.DataFrame({sensor: rng.uniform(2.0, 18.0, n_rows)}, index=idx)
    state = SessionState()
    state.timeseries_df = df
    state.raw_timeseries_df = df.copy()
    return state


class TestSampleForBoxplotHelper:
    """Validate the downsampling helper's threshold behaviour."""

    def test_below_threshold_returns_unchanged(self) -> None:
        values = pd.Series(np.arange(1000))
        result = _sample_for_boxplot(values, maximum_points=2000)
        assert result is values  # same object, no copy

    def test_above_threshold_returns_strided_subset(self) -> None:
        values = pd.Series(np.arange(100_000))
        result = _sample_for_boxplot(values, maximum_points=24000)
        # Striding: step = max(1, 100_000 // 24_000) = 4 → 25_000 points
        assert len(result) < len(values)
        assert len(result) <= 25000  # stride of 4 on 100k

    def test_exact_threshold_returns_unchanged(self) -> None:
        values = pd.Series(np.arange(24000))
        result = _sample_for_boxplot(values, maximum_points=24000)
        assert len(result) == 24000


class TestDiurnalBoxplotDisclosesSampling:
    """Core D32 regression: title annotation and payload counts."""

    def test_no_sampling_title_clean(self) -> None:
        """When data fits within the threshold, title has no sampling suffix."""
        state = _boxplot_session(1000)  # well below 24000
        result = _plot_diurnal_boxplot(state, "Spd_80m")
        assert "sampled" not in result["title"]
        assert result["total_count"] == 1000
        assert result["sampled_count"] == 1000

    def test_sampling_title_annotated(self) -> None:
        """When data exceeds the threshold, title includes sampled/total counts."""
        # 50000 rows exceeds the 24000 default threshold
        state = _boxplot_session(50_000)
        result = _plot_diurnal_boxplot(state, "Spd_80m")

        assert "sampled" in result["title"]
        # Verify format: "sampled: X of Y records"
        match = re.search(r"sampled: ([\d,]+) of ([\d,]+) records", result["title"])
        assert match is not None
        sampled = int(match.group(1).replace(",", ""))
        total = int(match.group(2).replace(",", ""))
        assert sampled < total
        assert total == 50_000

    def test_payload_counts_present(self) -> None:
        """Payload must include total_count and sampled_count keys."""
        state = _boxplot_session(50_000)
        result = _plot_diurnal_boxplot(state, "Spd_80m")
        assert "total_count" in result
        assert "sampled_count" in result
        assert result["total_count"] == 50_000
        assert result["sampled_count"] < result["total_count"]
        # Striding: step = max(1, 50_000 // 24_000) = 2 → 25_000 points
        assert result["sampled_count"] <= 25000

    def test_payload_counts_equal_when_no_sampling(self) -> None:
        """When no downsampling occurs, both counts equal the total."""
        state = _boxplot_session(5000)
        result = _plot_diurnal_boxplot(state, "Spd_80m")
        assert result["total_count"] == result["sampled_count"] == 5000

    def test_plotly_json_title_matches(self) -> None:
        """The Plotly figure's layout title must match the returned title."""
        state = _boxplot_session(50_000)
        result = _plot_diurnal_boxplot(state, "Spd_80m")
        import json

        fig_data = json.loads(result["plotly_json"])
        assert fig_data["layout"]["title"]["text"] == result["title"]
