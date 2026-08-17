"""Regression tests for D3 — shear speed gate and clamp reporting.

A clean alpha = 0.14 profile must recover 0.14 with a zero clamp fraction; a
near-calm dataset must report a non-zero fraction and the warning field.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from server.state.session import SessionState
from server.tools.shear import (
    SHEAR_CLAMP_WARNING_FRACTION,
    SHEAR_MIN_SPEED_MPS,
    _calculate_shear_timeseries,
    _compute_pairwise_shear,
    _build_shear_table,
)

HEIGHTS = np.array([40.0, 60.0, 80.0])
HEIGHT_SENSORS = json.dumps({"40": "Spd_40m", "60": "Spd_60m", "80": "Spd_80m"})


def _state_from_matrix(speed_matrix: np.ndarray) -> SessionState:
    """Load a (n, 3) speed matrix into a session at the fixture heights."""
    index = pd.date_range("2021-01-01", periods=speed_matrix.shape[0], freq="10min", tz="UTC")
    state = SessionState()
    state.reset()
    state.timeseries_df = pd.DataFrame(
        {"Spd_40m": speed_matrix[:, 0], "Spd_60m": speed_matrix[:, 1], "Spd_80m": speed_matrix[:, 2]},
        index=index,
    )
    return state


def _clean_profile(n: int = 5000, alpha: float = 0.14, seed: int = 0) -> np.ndarray:
    """Build a noise-free power-law profile anchored on well-above-gate speeds."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(5.0, 15.0, n)  # all comfortably above the 3 m/s gate
    return base[:, None] * (HEIGHTS[None, :] / HEIGHTS[0]) ** alpha


class TestEstimatorUnchanged:
    """The estimator itself is correct and must stay that way."""

    def test_recovers_known_alpha(self) -> None:
        alpha, stats = _compute_pairwise_shear(_clean_profile(alpha=0.14), HEIGHTS)
        assert np.allclose(alpha, 0.14)
        assert stats["clamped_fraction"] == 0.0
        assert stats["records_clamped"] == 0

    def test_clean_profile_reports_no_warning(self) -> None:
        _, stats = _compute_pairwise_shear(_clean_profile(), HEIGHTS)
        assert "warning" not in stats


class TestSpeedGate:
    """D3.1 — the valid-record gate defaults to 3.0 m/s, not 0.1."""

    def test_default_is_three_mps(self) -> None:
        assert SHEAR_MIN_SPEED_MPS == 3.0

    def test_near_calm_records_are_excluded(self) -> None:
        # Speeds spanning the gate: only the above-gate rows may contribute.
        matrix = np.repeat(np.array([[0.5, 1.0, 2.0, 6.0, 9.0]]).T, 3, axis=1)
        _, stats = _compute_pairwise_shear(matrix, HEIGHTS)
        assert stats["records_used"] == 2
        assert stats["min_speed_mps"] == 3.0

    def test_gate_is_configurable_and_persisted(self) -> None:
        state = _state_from_matrix(_clean_profile(n=200))
        result = _calculate_shear_timeseries(state, HEIGHT_SENSORS, min_speed_mps=8.0)
        assert result["min_speed_mps"] == 8.0
        # Persisted so the value used is reproducible and visible.
        assert state.runconfig["shear"]["minSpeedMps"] == 8.0
        # A later call with no explicit gate reuses the stored one.
        assert _calculate_shear_timeseries(state, HEIGHT_SENSORS)["min_speed_mps"] == 8.0

    def test_negative_gate_rejected(self) -> None:
        state = _state_from_matrix(_clean_profile(n=200))
        with pytest.raises(ValueError, match="non-negative"):
            _calculate_shear_timeseries(state, HEIGHT_SENSORS, min_speed_mps=-1.0)


class TestClampReporting:
    """D3.2/D3.3 — clamping is counted and warned about, never silent."""

    def test_noisy_data_reports_clamping_and_warning(self) -> None:
        # Independent random speeds per height above the gate: ln(v2/v1) is pure
        # noise across a small height ratio, so alpha frequently exceeds the bound.
        rng = np.random.default_rng(0)
        matrix = rng.uniform(3.1, 25.0, (20000, 3))
        _, stats = _compute_pairwise_shear(matrix, HEIGHTS)

        assert stats["records_clamped"] > 0
        assert stats["clamped_fraction"] > SHEAR_CLAMP_WARNING_FRACTION
        assert "warning" in stats
        # The warning must name the fraction so it is actionable.
        assert f"{stats['clamped_fraction']:.1%}" in stats["warning"]

    def test_alpha_stays_within_bounds(self) -> None:
        rng = np.random.default_rng(1)
        alpha, _ = _compute_pairwise_shear(rng.uniform(3.1, 25.0, (5000, 3)), HEIGHTS)
        finite = alpha[np.isfinite(alpha)]
        assert np.all(np.abs(finite) <= 1.0)

    def test_table_response_carries_clamp_stats(self) -> None:
        state = _state_from_matrix(_clean_profile(n=1000))
        _calculate_shear_timeseries(state, HEIGHT_SENSORS)
        table = _build_shear_table(state, "mean")
        assert table["shear_clamping"]["records_used"] == 1000
        assert table["shear_clamping"]["clamped_fraction"] == 0.0
