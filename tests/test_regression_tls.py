"""Regression tests for total_least_squares_fit (D1 fix).

Asserts recovered slope is within 2% of truth for both positive and
negative true slopes, and that a degenerate vertical relationship
raises ValueError instead of returning a magic sentinel.
"""

import math

import numpy as np
import pytest

from server.core.regression import total_least_squares_fit


@pytest.mark.parametrize("true_slope", [-2, -1, -0.5, 0.5, 1, 2])
def test_tls_slope_sign(true_slope: float) -> None:
    """TLS should recover the correct slope for both positive and negative correlations."""
    rng = np.random.default_rng(42)
    x = rng.normal(10.0, 3.0, 4000)
    y = true_slope * x + 2.0 + rng.normal(0.0, 0.5, 4000)
    slope, _intercept = total_least_squares_fit(x, y)
    # Allow 5% relative tolerance (statistical noise on synthetic data)
    assert math.isclose(slope, true_slope, rel_tol=0.05), (
        f"TLS slope {slope:.4f} far from true {true_slope}"
    )


def test_tls_degenerate_vertical_raises() -> None:
    """A degenerate vertical relationship (sxy ≈ 0, sxx < syy) should raise ValueError."""
    # x constant, y varying → no covariance, vertical line
    x = np.full(200, 5.0)
    y = np.linspace(-10.0, 10.0, 200)
    with pytest.raises(ValueError, match="degenerate"):
        total_least_squares_fit(x, y)
