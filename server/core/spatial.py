"""spatial — Spatial interpolation and distance helpers.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import griddata


def _great_circle_distances_km(points: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Return great-circle distances in km from each (lat, lon) point to the target.

    Vectorised haversine, matching :func:`haversine_km`.  The previous implementation
    took a Euclidean norm over raw degrees, which treats a degree of longitude as a
    degree of latitude.  Meridians converge, so that overweights nodes lying east or
    west: a degree of longitude is 78.6 km at 45 deg N against 111.2 km for a degree of
    latitude (1.41x), 2.00x at 60 deg N and 2.92x at 70 deg N.  Two nodes equidistant in
    degrees but not on the ground were being weighted 50/50 where true distance gives the
    nearer one over 75%.
    """
    radius_km = 6371.0
    lat_rad = np.radians(points[:, 0])
    lon_rad = np.radians(points[:, 1])
    target_lat_rad = np.radians(target[0])
    target_lon_rad = np.radians(target[1])
    delta_lat = target_lat_rad - lat_rad
    delta_lon = target_lon_rad - lon_rad
    a_term = (
        np.sin(delta_lat / 2.0) ** 2
        + np.cos(lat_rad) * np.cos(target_lat_rad) * np.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * radius_km * np.arctan2(np.sqrt(a_term), np.sqrt(np.maximum(1.0 - a_term, 0.0)))


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
    """Apply inverse distance weighting using Shepard's method over great-circle distance.

    Distances are in kilometres, not degrees, so nodes are weighted by how far away they
    actually are rather than by their coordinate offset.
    """
    points_array = np.asarray(points, dtype=float)
    values_array = np.asarray(values, dtype=float)
    target_array = np.asarray(target, dtype=float)
    distances = _great_circle_distances_km(points_array, target_array)
    # One metre: closer than any reanalysis grid resolves, so the target is the node.
    zero_distance = np.where(distances < 1e-3)[0]
    if zero_distance.size:
        return np.asarray(values_array[zero_distance[0]])
    weights = 1.0 / np.maximum(distances, 1e-3) ** power
    weights = weights / weights.sum()
    if values_array.ndim == 1:
        return np.asarray(np.dot(weights, values_array))
    return np.asarray((weights[:, None] * values_array).sum(axis=0))


def bilinear_interpolate(
    points: list[tuple[float, float]],
    values: np.ndarray,
    target: tuple[float, float],
) -> np.ndarray:
    """Interpolate values on a rectangular 2x2 grid cell using bilinear weights."""
    points_array = np.asarray(points, dtype=float)
    values_array = np.asarray(values, dtype=float)
    unique_lats = np.sort(np.unique(points_array[:, 0]))
    unique_lons = np.sort(np.unique(points_array[:, 1]))
    if unique_lats.size != 2 or unique_lons.size != 2:
        raise ValueError("Bilinear interpolation requires exactly two unique latitudes and longitudes")
    lat0, lat1 = float(unique_lats[0]), float(unique_lats[1])
    lon0, lon1 = float(unique_lons[0]), float(unique_lons[1])
    if abs(lat1 - lat0) <= 1e-12 or abs(lon1 - lon0) <= 1e-12:
        raise ValueError("Bilinear interpolation requires non-zero grid spacing")

    def point_value(latitude: float, longitude: float) -> np.ndarray:
        mask = np.isclose(points_array[:, 0], latitude) & np.isclose(points_array[:, 1], longitude)
        if not np.any(mask):
            raise ValueError("Grid cell is missing one or more bilinear corner points")
        return np.asarray(values_array[np.where(mask)[0][0]])

    q11 = point_value(lat0, lon0)
    q12 = point_value(lat0, lon1)
    q21 = point_value(lat1, lon0)
    q22 = point_value(lat1, lon1)
    target_lat, target_lon = float(target[0]), float(target[1])
    lon_fraction = (target_lon - lon0) / (lon1 - lon0)
    lat_fraction = (target_lat - lat0) / (lat1 - lat0)
    lower_band = (1.0 - lon_fraction) * q11 + lon_fraction * q12
    upper_band = (1.0 - lon_fraction) * q21 + lon_fraction * q22
    return np.asarray((1.0 - lat_fraction) * lower_band + lat_fraction * upper_band)


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
    target_lat, target_lon = float(target[0]), float(target[1])
    lat_min, lat_max = float(np.min(points_array[:, 0])), float(np.max(points_array[:, 0]))
    lon_min, lon_max = float(np.min(points_array[:, 1])), float(np.max(points_array[:, 1]))
    inside_cell = lat_min - 1e-12 <= target_lat <= lat_max + 1e-12 and lon_min - 1e-12 <= target_lon <= lon_max + 1e-12
    if len(points) >= 4 and unique_lats == 2 and unique_lons == 2 and inside_cell:
        try:
            return bilinear_interpolate(points, values_array, target), "linear"
        except ValueError:
            pass
    if len(points) < 3 or unique_lats < 2 or unique_lons < 2:
        return idw_interpolate(points, values_array, target), "idw"
    try:
        interpolated = np.asarray(griddata(points_array, values_array, target, method="linear"))
    except (ValueError, RuntimeError):
        return idw_interpolate(points, values_array, target), "idw"
    if np.isnan(interpolated).any():
        return idw_interpolate(points, values_array, target), "idw"
    return interpolated, "linear"
