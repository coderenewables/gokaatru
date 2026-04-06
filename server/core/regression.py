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
    if abs(sxy) <= 1e-12:
        slope = 0.0 if sxx >= syy else float(np.sign(np.mean(dy) or 1.0) * 1e12)
    else:
        term = syy - sxx
        radical = float(np.sqrt(term * term + 4.0 * sxy * sxy))
        slope = float((term + np.copysign(radical, sxy)) / (2.0 * sxy))
    return slope, float(mean_y - slope * mean_x)


def ols_confidence_intervals(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """Compute approximate 95% OLS confidence intervals using the normal approximation with z = 1.96."""
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
    variance = float(np.sum(residuals**2) / max(1, x_values.size - 2))
    se_slope = float(np.sqrt(variance / sxx))
    se_intercept = float(np.sqrt(variance * (1.0 / x_values.size + (mean_x**2) / sxx)))
    return (slope - 1.96 * se_slope, slope + 1.96 * se_slope), (
        intercept - 1.96 * se_intercept,
        intercept + 1.96 * se_intercept,
    )
