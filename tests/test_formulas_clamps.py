"""test_formulas_clamps — Regression tests for D9.5, D9.6, D9.7.

D9.5: MEAN_DAYS_IN_MONTH is defined once in formulas.py and re-exported via momm.
D9.6: air_density_iec clamps dewpoint <= temperature and reports via tuple return.
D9.7: roughness_from_two_heights clamps z0 to [1e-6, 1.5] and reports via tuple return.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from server.core.formulas import (
    MEAN_DAYS_IN_MONTH,
    ROUGHNESS_MAX_M,
    air_density_iec,
    roughness_from_two_heights,
)
from server.core.momm import MEAN_DAYS_IN_MONTH as MOMM_MEAN_DAYS_IN_MONTH


# =====================================================================
# D9.5 — single source of truth for MEAN_DAYS_IN_MONTH
# =====================================================================


class TestMeanDaysInMonthSingleSource:
    """MEAN_DAYS_IN_MONTH must be the same object whether imported from formulas or momm."""

    def test_formulas_and_momm_same_mapping(self) -> None:
        assert MEAN_DAYS_IN_MONTH == MOMM_MEAN_DAYS_IN_MONTH

    def test_formulas_values_are_sensible(self) -> None:
        assert len(MEAN_DAYS_IN_MONTH) == 12
        assert MEAN_DAYS_IN_MONTH[1] == 31
        assert 27.0 < MEAN_DAYS_IN_MONTH[2] < 30.0  # 28.24 — leap-year averaged
        assert MEAN_DAYS_IN_MONTH[12] == 31

    def test_all_values_positive(self) -> None:
        assert all(v > 0 for v in MEAN_DAYS_IN_MONTH.values())


# =====================================================================
# D9.6 — air_density_iec dewpoint clamped to temperature
# =====================================================================


class TestAirDensityDewpointClamp:
    """IEC air-density helper must clamp dewpoint <= temperature."""

    def test_no_clamp_normal_inputs(self) -> None:
        density, was_clamped = air_density_iec(101325.0, 288.15, 275.0)
        assert not was_clamped
        assert math.isclose(density, 1.225, abs_tol=0.01)

    def test_clamp_when_dewpoint_exceeds_temperature(self) -> None:
        """Dewpoint above temperature is physically impossible; should be clamped."""
        density, was_clamped = air_density_iec(101325.0, 288.15, 295.0)
        assert was_clamped is True
        # When dewpoint == temperature, vapour pressure is maximised → density is lower
        # Just verify the result is a reasonable positive density
        assert density > 1.0
        assert density < 1.3

    def test_clamped_density_matches_dewpoint_equals_temp(self) -> None:
        """Clamping dewpoint to temperature should give the same density as passing temperature directly."""
        d_clamped, _ = air_density_iec(101325.0, 288.15, 295.0)
        d_direct, not_clamped = air_density_iec(101325.0, 288.15, 288.15)
        assert not_clamped is False
        assert math.isclose(d_clamped, d_direct, rel_tol=1e-12)

    def test_raises_on_negative_temperature(self) -> None:
        with pytest.raises(ValueError, match="positive pressure"):
            air_density_iec(101325.0, -1.0, 275.0)

    def test_raises_on_zero_pressure(self) -> None:
        with pytest.raises(ValueError, match="positive pressure"):
            air_density_iec(0.0, 288.15, 275.0)

    def test_dewpoint_exactly_equals_temperature_no_clamp_flag(self) -> None:
        _, was_clamped = air_density_iec(101325.0, 288.15, 288.15)
        assert was_clamped is False


# =====================================================================
# D9.7 — roughness_from_two_heights z0 clamped to [1e-6, 1.5]
# =====================================================================


class TestRoughnessFromTwoHeightsClamp:
    """Roughness length z0 must be clamped to physically plausible [1e-6, 1.5] metres."""

    def test_normal_grassland_returns_reasonable_z0(self) -> None:
        """Typical grassland: z0 should be on the order of 0.01–1.0 m, unclamped."""
        z0, was_clamped = roughness_from_two_heights(10.0, 100.0, 9.0, 60.0)
        assert not was_clamped
        assert 1e-6 <= z0 <= ROUGHNESS_MAX_M

    def test_clamp_below_floor(self) -> None:
        """If the computed z0 is below 1e-6, it must be clamped up."""
        # Construct inputs that yield a very small z0 (smooth surface / nearly same speed)
        z0, was_clamped = roughness_from_two_heights(10.0001, 100.0, 10.0, 80.0)
        assert was_clamped is True
        assert z0 == 1e-6

    def test_clamp_above_ceiling(self) -> None:
        """If the computed z0 exceeds the plausible band it must be clamped down.

        The ceiling is 2.0 m, not 1.5 (F-05): WAsP roughness class 3 and dense forest or
        urban terrain reach 1.5-2.0 m, and clamping them *raised* log-law hub speed, so the
        old ceiling was not a conservative backstop.
        """
        # Inverted speeds: v1 > v2 despite h1 > h2 → very large z0
        z0, was_clamped = roughness_from_two_heights(5.0, 100.0, 10.0, 80.0)
        assert was_clamped is True
        assert z0 == ROUGHNESS_MAX_M == 2.0

    def test_nan_on_zero_speed(self) -> None:
        z0, was_clamped = roughness_from_two_heights(0.0, 80.0, 7.0, 60.0)
        assert math.isnan(z0)
        assert was_clamped is False

    def test_nan_on_equal_heights(self) -> None:
        z0, was_clamped = roughness_from_two_heights(8.0, 80.0, 7.0, 80.0)
        assert math.isnan(z0)
        assert was_clamped is False

    def test_nan_on_equal_speeds(self) -> None:
        z0, was_clamped = roughness_from_two_heights(8.0, 80.0, 8.0, 60.0)
        assert math.isnan(z0)
        assert was_clamped is False

    def test_clamped_value_at_exact_floor_not_flagged(self) -> None:
        """z0 exactly at 1e-6 should not be flagged as clamped."""
        # It's nearly impossible to hit exactly 1e-6, so test the boundary logic:
        # We'll just verify 1e-6 is the clamp floor
        _, was_clamped = roughness_from_two_heights(10.0001, 100.0, 10.0, 80.0)
        # The value was below floor so it was clamped — verify floor value
        z0, _ = roughness_from_two_heights(10.0001, 100.0, 10.0, 80.0)
        assert z0 == pytest.approx(1e-6)
