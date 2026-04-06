"""spatial — Spatial interpolation and distance helpers.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import griddata


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km using the standard haversine formula with R = 6371 km."""
    radius_km = 6371.0
    lat1_rad, lon1_rad = np.radians([lat1, lon1])
    lat2_rad, lon2_rad = np.radians([lat2, lon2])
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    a_term = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2.0) ** 2
    )
    return float(2.0 * radius_km * np.arctan2(np.sqrt(a_term), np.sqrt(1.0 - a_term)))


def bearing_compass(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    """Return an 8-point compass bearing from point 1 to point 2 using standard azimuth geometry."""
    lat1_rad, lat2_rad = np.radians([lat1, lat2])
    delta_lon = np.radians(lon2 - lon1)
    y_term = np.sin(delta_lon) * np.cos(lat2_rad)
    x_term = np.cos(lat1_rad) * np.sin(lat2_rad) - np.sin(lat1_rad) * np.cos(lat2_rad) * np.cos(delta_lon)
    azimuth_deg = (np.degrees(np.arctan2(y_term, x_term)) + 360.0) % 360.0
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return directions[int((azimuth_deg + 22.5) // 45) % 8]


def idw_interpolate(
    points: list[tuple[float, float]],
    values: np.ndarray,
    target: tuple[float, float],
    power: int = 2,
) -> np.ndarray:
    """Apply inverse distance weighting interpolation using Shepard's method with power weighting."""
    points_array = np.asarray(points, dtype=float)
    values_array = np.asarray(values, dtype=float)
    target_array = np.asarray(target, dtype=float)
    distances = np.linalg.norm(points_array - target_array, axis=1)
    zero_distance = np.where(distances < 1e-12)[0]
    if zero_distance.size:
        return np.asarray(values_array[zero_distance[0]])
    weights = 1.0 / np.maximum(distances, 1e-12) ** power
    weights = weights / weights.sum()
    if values_array.ndim == 1:
        return np.asarray(np.dot(weights, values_array))
    return np.asarray((weights[:, None] * values_array).sum(axis=0))


def interpolate_spatial(
    points: list[tuple[float, float]],
    values: np.ndarray,
    target: tuple[float, float],
) -> tuple[np.ndarray, str]:
    """Use linear griddata first, then fall back to IDW for degenerate or NaN spatial solutions."""
    points_array = np.asarray(points, dtype=float)
    values_array = np.asarray(values, dtype=float)
    unique_lats = np.unique(points_array[:, 0]).size
    unique_lons = np.unique(points_array[:, 1]).size
    if len(points) < 3 or unique_lats < 2 or unique_lons < 2:
        return idw_interpolate(points, values_array, target), "idw"
    try:
        interpolated = np.asarray(griddata(points_array, values_array, target, method="linear"))
    except (ValueError, RuntimeError):
        return idw_interpolate(points, values_array, target), "idw"
    if np.isnan(interpolated).any():
        return idw_interpolate(points, values_array, target), "idw"
    return interpolated, "linear"
