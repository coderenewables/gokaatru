"""regression — Robust and orthogonal regression helpers.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np


def _flatten_xy(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Normalize paired regression inputs to 1-D float arrays for least-squares fitting."""
    x_values = np.asarray(x, dtype=float).reshape(-1)
    y_values = np.asarray(y, dtype=float).reshape(-1)
    if x_values.size != y_values.size:
        raise ValueError(f"x and y must have the same length, got {x_values.size} and {y_values.size}")
    if x_values.size == 0:
        raise ValueError("Regression requires at least one data point")
    return x_values, y_values


def _r_squared(y_true: np.ndarray, y_hat: np.ndarray) -> float:
    """Compute coefficient of determination using the standard least-squares definition."""
    residual_sum = float(np.sum((y_true - y_hat) ** 2))
    total_sum = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return 0.0 if total_sum == 0.0 else float(1.0 - residual_sum / total_sum)


def _vector_norm(values: np.ndarray) -> float:
    """Compute Euclidean norm without NumPy linalg."""
    return float(np.sqrt(np.sum(np.square(values))))


def _weighted_line_fit(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Fit a weighted straight line using closed-form weighted least squares."""
    weight_sum = float(np.sum(weights))
    if weight_sum <= 0.0:
        raise ValueError("Weighted regression requires positive total weight")
    mean_x = float(np.sum(weights * x) / weight_sum)
    mean_y = float(np.sum(weights * y) / weight_sum)
    centered_x = x - mean_x
    centered_y = y - mean_y
    denominator = float(np.sum(weights * centered_x * centered_x))
    if abs(denominator) <= 1e-12:
        return 0.0, mean_y
    numerator = float(np.sum(weights * centered_x * centered_y))
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    return float(slope), float(intercept)


def robust_huber_fit(
    x: np.ndarray,
    y: np.ndarray,
    delta: float = 1.35,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> tuple[float, float, np.ndarray, float]:
    """Fit IRLS with Huber loss using MAD-scaled residuals per robust regression practice."""
    x_values, y_values = _flatten_xy(x, y)
    slope, intercept = _weighted_line_fit(x_values, y_values, np.ones_like(x_values))
    beta = np.array([slope, intercept], dtype=float)
    for _ in range(max_iter):
        residuals = y_values - (beta[0] * x_values + beta[1])
        mad = 1.4826 * np.median(np.abs(residuals))
        scale = mad if np.isfinite(mad) and mad > 1e-12 else max(1e-12, float(np.std(residuals)))
        z_scores = residuals / scale
        weights = np.ones_like(z_scores)
        mask = np.abs(z_scores) > delta
        weights[mask] = delta / np.abs(z_scores[mask])
        slope_new, intercept_new = _weighted_line_fit(x_values, y_values, weights)
        beta_new = np.array([slope_new, intercept_new], dtype=float)
        if _vector_norm(beta_new - beta) <= tol * (_vector_norm(beta) + 1e-12):
            beta = beta_new
            break
        beta = beta_new
    y_hat = beta[0] * x_values + beta[1]
    return float(beta[0]), float(beta[1]), y_hat, _r_squared(y_values, y_hat)


def total_least_squares_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Fit an orthogonal regression line using covariance closed forms for total least squares."""
    x_values, y_values = _flatten_xy(x, y)
    if x_values.size < 2:
        raise ValueError(f"TLS requires at least 2 points, got {x_values.size}")
    mean_x = float(np.mean(x_values))
    mean_y = float(np.mean(y_values))
    dx = x_values - mean_x
    dy = y_values - mean_y
    sxx = float(np.sum(dx * dx))
    syy = float(np.sum(dy * dy))
    sxy = float(np.sum(dx * dy))
    # Degeneracy is judged against the magnitude of the data rather than an
    # absolute threshold: subtracting the mean of a constant column leaves
    # round-off of order 1e-30, not exactly zero, so a plain `syy > sxx`
    # comparison would read that noise as real vertical spread.
    epsilon = 1e-20 * float(x_values.size) * max(1.0, mean_x * mean_x, mean_y * mean_y)
    if abs(sxy) <= epsilon:
        # No covariance: the major axis lies along one of the coordinate axes.
        # Real spread in y with none in x is a vertical line, whose slope is
        # undefined.  Otherwise — including constant y and the fully-constant
        # case — the orthogonal fit is the horizontal line y = mean_y.
        if syy > epsilon and syy > sxx:
            raise ValueError("TLS is undefined for a degenerate (vertical) relationship")
        slope = 0.0
    else:
        term = syy - sxx
        radical = float(np.sqrt(term * term + 4.0 * sxy * sxy))
        slope = float((term + radical) / (2.0 * sxy))
    return slope, float(mean_y - slope * mean_x)


def residual_lag1_autocorrelation(residuals: np.ndarray) -> float:
    """Return the lag-1 autocorrelation of a residual series, clipped to [0, 0.999).

    Negative autocorrelation would *shrink* the interval, which is not a direction this
    correction is willing to claim from a single lag, so it floors at zero.
    """
    values = np.asarray(residuals, dtype=float).ravel()
    if values.size < 3:
        return 0.0
    centred = values - float(np.mean(values))
    denominator = float(np.sum(centred**2))
    if denominator <= 0.0:
        return 0.0
    phi = float(np.sum(centred[:-1] * centred[1:]) / denominator)
    return float(min(max(phi, 0.0), 0.999))


def effective_sample_size(n: int, phi: float) -> float:
    """Return the AR(1) effective sample size ``n (1 - phi) / (1 + phi)``.

    Consecutive hourly wind records carry much of the same information, so ``n`` records
    are worth far fewer independent ones.  At the phi = 0.85 that is ordinary for hourly
    wind, 20 000 records are worth about 1 620.
    """
    if n <= 0:
        return 0.0
    return float(max(2.0, n * (1.0 - phi) / (1.0 + phi)))


def ols_confidence_intervals(
    x: np.ndarray,
    y: np.ndarray,
    autocorrelation_corrected: bool = True,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Compute 95% OLS confidence intervals for the slope and intercept.

    Uses the t-distribution, since the residual variance is estimated from the same sample
    rather than known (D9.4).  The normal approximation this replaces was anti-conservative
    at small n.

    Textbook OLS intervals assume independent, identically distributed residuals, and wind
    speed is strongly autocorrelated: consecutive 10-minute or hourly records carry much of
    the same information, so the effective sample size is a small fraction of ``n``.
    Because the standard errors scale as ``1/sqrt(n)``, using the raw record count made the
    intervals far too narrow — measured at **3.47x** on n = 20 000 hourly records with AR(1)
    residuals at phi = 0.85, where the effective sample size is 8.3% of n (F-41).

    The default now applies an AR(1) effective-sample-size correction estimated from the
    residuals' own lag-1 autocorrelation.  That is an approximation, not a rigorous
    treatment — a block bootstrap would be better and longer-range dependence is not
    captured — so the result is still a *lower* bound on the true uncertainty, just a far
    less misleading one.  Pass ``autocorrelation_corrected=False`` for the raw i.i.d.
    interval when comparing against a tool that reports one.
    """
    from scipy.stats import t as student_t

    x_values, y_values = _flatten_xy(x, y)
    if x_values.size < 3:
        return None, None
    mean_x = float(np.mean(x_values))
    mean_y = float(np.mean(y_values))
    sxx = float(np.sum((x_values - mean_x) ** 2))
    if sxx <= 0.0:
        return None, None
    slope = float(np.sum((x_values - mean_x) * (y_values - mean_y)) / sxx)
    intercept = float(mean_y - slope * mean_x)
    residuals = y_values - (slope * x_values + intercept)
    degrees_of_freedom = max(1, x_values.size - 2)
    variance = float(np.sum(residuals**2) / degrees_of_freedom)
    se_slope = float(np.sqrt(variance / sxx))
    se_intercept = float(np.sqrt(variance * (1.0 / x_values.size + (mean_x**2) / sxx)))
    if autocorrelation_corrected:
        phi = residual_lag1_autocorrelation(residuals)
        n_eff = effective_sample_size(int(x_values.size), phi)
        # Standard errors scale as 1/sqrt(n); replacing n with n_eff widens both by the
        # same factor, and the degrees of freedom follow the independent count too.
        inflation = float(np.sqrt(x_values.size / n_eff))
        se_slope *= inflation
        se_intercept *= inflation
        degrees_of_freedom = max(1, int(n_eff) - 2)
    # t rather than z: the residual variance is estimated, not known (D9.4).
    critical = float(student_t.ppf(0.975, degrees_of_freedom))
    return (slope - critical * se_slope, slope + critical * se_slope), (
        intercept - critical * se_intercept,
        intercept + critical * se_intercept,
    )
