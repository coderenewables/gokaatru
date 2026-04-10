"""extrapolation — Phase 2 MCP tools for hub-height wind extrapolation.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.main import mcp
from server.state.session import SessionState, session


def _hub_column_name(hub_height_m: float) -> str:
    """Format hub-height wind-speed column names using the Phase 2 tool naming convention."""
    return f"Spd_{int(hub_height_m)}m_hub" if float(hub_height_m).is_integer() else f"Spd_{hub_height_m}m_hub"


def _speed_height_map(state: SessionState) -> dict[float, str]:
    """Extract measured speed columns from the loaded sensor mapping."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    mapping = {
        height: sensor_map["speed_col"]
        for height, sensor_map in state.sensor_mapping.items()
        if sensor_map.get("speed_col") in state.timeseries_df.columns
    }
    if not mapping:
        raise ValueError("No valid speed sensors are available in session.sensor_mapping")
    return {height: str(column) for height, column in mapping.items()}


def _lookup_table_values(index: pd.DatetimeIndex, table: pd.DataFrame) -> np.ndarray:
    """Fetch month-hour lookup values for each timestamp in a datetime index."""
    months = index.month.to_numpy(dtype=int) - 1
    hours = index.hour.to_numpy(dtype=int)
    return table.to_numpy(dtype=float)[months, hours]


def _nearest_indices(heights: np.ndarray, valid_mask: np.ndarray, hub_height_m: float) -> np.ndarray:
    """Pick the closest valid measured height to the hub height for each timestamp."""
    distances = np.abs(heights[None, :] - hub_height_m)
    masked = np.where(valid_mask, distances, np.inf)
    return np.argmin(masked, axis=1)


def _interpolation_masks(
    heights: np.ndarray,
    valid_mask: np.ndarray,
    hub_height_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Locate nearest lower and upper valid heights for row-wise log-linear interpolation."""
    lower = np.where(heights[None, :] <= hub_height_m, heights[None, :], -np.inf)
    upper = np.where(heights[None, :] >= hub_height_m, heights[None, :], np.inf)
    lower_masked = np.where(valid_mask, lower, -np.inf)
    upper_masked = np.where(valid_mask, upper, np.inf)
    lower_heights = lower_masked.max(axis=1)
    upper_heights = upper_masked.min(axis=1)
    usable = np.isfinite(lower_heights) & np.isfinite(upper_heights)
    return usable, lower_heights, upper_heights


def _row_values_for_heights(speed_matrix: np.ndarray, heights: np.ndarray, selected: np.ndarray) -> np.ndarray:
    """Select row-wise speeds for the requested row-wise height choices."""
    index_map = {height: idx for idx, height in enumerate(heights.tolist())}
    positions = np.asarray([index_map[float(height)] for height in selected], dtype=int)
    return speed_matrix[np.arange(speed_matrix.shape[0]), positions]


def _power_extrapolate_array(
    reference_speed: np.ndarray,
    reference_height: np.ndarray,
    hub_height_m: float,
    alpha: np.ndarray,
) -> np.ndarray:
    """Vectorize power-law extrapolation over concurrent reference speeds and lookup shear values."""
    return reference_speed * (hub_height_m / reference_height) ** alpha


def _log_extrapolate_array(
    reference_speed: np.ndarray,
    reference_height: np.ndarray,
    hub_height_m: float,
    z0: np.ndarray,
) -> np.ndarray:
    """Vectorize log-law extrapolation with stable clipping of roughness length and heights."""
    z0_safe = np.clip(z0, 1e-6, 1.5)
    ref_safe = np.maximum(reference_height, z0_safe + 1e-6)
    hub_safe = np.maximum(hub_height_m, z0_safe + 1e-6)
    return reference_speed * np.log(hub_safe / z0_safe) / np.log(ref_safe / z0_safe)


def _log_linear_interpolation(
    lower_speed: np.ndarray,
    upper_speed: np.ndarray,
    lower_height: np.ndarray,
    upper_height: np.ndarray,
    hub_height_m: float,
) -> np.ndarray:
    """Interpolate wind speed linearly in log-height space between two measured heights."""
    log_hub = np.log(hub_height_m)
    return lower_speed + (upper_speed - lower_speed) * (log_hub - np.log(lower_height)) / (
        np.log(upper_height) - np.log(lower_height)
    )


def _extrapolate_to_hub_height(state: SessionState, hub_height_m: float, shear_model: str = "power_law") -> dict:
    """Create a hub-height wind-speed series using power-law or log-law shear per IEC 61400-12-1 Annex B."""
    if shear_model not in {"power_law", "log_law"}:
        raise ValueError(f"shear_model must be 'power_law' or 'log_law', got '{shear_model}'")
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    speed_map = _speed_height_map(state)
    heights = np.asarray(list(sorted(speed_map.keys())), dtype=float)
    columns = [speed_map[height] for height in heights]
    speed_matrix = state.timeseries_df[columns].to_numpy(dtype=float)
    valid_mask = np.isfinite(speed_matrix) & (speed_matrix > 0.1)
    result = np.full(speed_matrix.shape[0], np.nan, dtype=float)
    counts = {"direct": 0, "interpolated": 0, "extrapolated": 0}
    if hub_height_m in speed_map:
        column_name = _hub_column_name(hub_height_m)
        state.timeseries_df[column_name] = state.timeseries_df[speed_map[hub_height_m]]
        state.set_hub_height_m(float(hub_height_m))
        return {
            "status": "ok",
            "column_name": column_name,
            "method_counts": {"direct": len(state.timeseries_df), "interpolated": 0, "extrapolated": 0},
        }
    between = float(heights.min()) < hub_height_m < float(heights.max())
    if between:
        usable, lower_heights, upper_heights = _interpolation_masks(heights, valid_mask, hub_height_m)
        interp_rows = usable & (lower_heights < hub_height_m) & (upper_heights > hub_height_m)
        if interp_rows.any():
            lower_speed = _row_values_for_heights(speed_matrix[interp_rows], heights, lower_heights[interp_rows])
            upper_speed = _row_values_for_heights(speed_matrix[interp_rows], heights, upper_heights[interp_rows])
            result[interp_rows] = _log_linear_interpolation(
                lower_speed,
                upper_speed,
                lower_heights[interp_rows],
                upper_heights[interp_rows],
                hub_height_m,
            )
            counts["interpolated"] = int(interp_rows.sum())
    extrap_rows = np.isnan(result) & valid_mask.any(axis=1)
    if extrap_rows.any():
        nearest = _nearest_indices(heights, valid_mask[extrap_rows], hub_height_m)
        ref_heights = heights[nearest]
        ref_speeds = speed_matrix[extrap_rows, :][np.arange(nearest.size), nearest]
        if shear_model == "power_law":
            if state.shear_table is None:
                raise ValueError("Power-law extrapolation requires session.shear_table")
            params = _lookup_table_values(state.timeseries_df.index[extrap_rows], state.shear_table)
            result[extrap_rows] = _power_extrapolate_array(ref_speeds, ref_heights, hub_height_m, params)
        else:
            if state.roughness_table is None:
                raise ValueError("Log-law extrapolation requires session.roughness_table")
            params = _lookup_table_values(state.timeseries_df.index[extrap_rows], state.roughness_table)
            result[extrap_rows] = _log_extrapolate_array(ref_speeds, ref_heights, hub_height_m, params)
        counts["extrapolated"] = int(extrap_rows.sum())
    column_name = _hub_column_name(hub_height_m)
    state.timeseries_df[column_name] = result
    state.set_hub_height_m(float(hub_height_m))
    return {"status": "ok", "column_name": column_name, "method_counts": counts}


def _extrapolate_reanalysis_to_hub(
    state: SessionState,
    hub_height_m: float,
    reference_height_m: float = 100.0,
) -> dict:
    """Extrapolate ERA5 site wind speed to hub height using the session month-hour shear lookup table."""
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolated data is not available. Run ERA5 interpolation tools first")
    if state.shear_table is None:
        raise ValueError("Reanalysis hub-height extrapolation requires session.shear_table")
    reference_col = f"Spd_{int(reference_height_m)}m"
    if reference_col not in state.era5_interpolated_df.columns:
        raise ValueError(f"Reference ERA5 column '{reference_col}' not found in interpolated data")
    shear_values = _lookup_table_values(state.era5_interpolated_df.index, state.shear_table)
    reference_speed = state.era5_interpolated_df[reference_col].to_numpy(dtype=float)
    hub_speed = _power_extrapolate_array(
        reference_speed,
        np.full_like(reference_speed, reference_height_m),
        hub_height_m,
        shear_values,
    )
    column_name = _hub_column_name(hub_height_m)
    state.era5_interpolated_df[column_name] = hub_speed
    return {"status": "ok", "column_name": column_name}


def _extrapolate_all_reanalysis_nodes(
    state: SessionState,
    hub_height_m: float,
    reference_height_m: float = 100.0,
) -> dict:
    """Extrapolate every ERA5/MERRA node and the interpolated series to hub height using the shear table."""
    if state.shear_table is None:
        raise ValueError("Hub-height extrapolation of reanalysis data requires session.shear_table")

    ref_col = f"Spd_{int(reference_height_m)}m"
    hub_col = _hub_column_name(hub_height_m)
    extrapolated_keys: list[str] = []
    skipped_keys: list[str] = []

    # --- individual ERA5 nodes ---
    for key, frame in state.era5_data.items():
        if ref_col not in frame.columns:
            skipped_keys.append(key)
            continue
        shear = _lookup_table_values(frame.index, state.shear_table)
        ref_speed = frame[ref_col].to_numpy(dtype=float)
        frame[hub_col] = _power_extrapolate_array(
            ref_speed, np.full_like(ref_speed, reference_height_m), hub_height_m, shear,
        )
        extrapolated_keys.append(key)

    # --- individual MERRA-2 nodes ---
    merra_data: dict[str, pd.DataFrame] = getattr(state, "merra_data", {})
    for key, frame in merra_data.items():
        if ref_col not in frame.columns:
            skipped_keys.append(f"merra:{key}")
            continue
        shear = _lookup_table_values(frame.index, state.shear_table)
        ref_speed = frame[ref_col].to_numpy(dtype=float)
        frame[hub_col] = _power_extrapolate_array(
            ref_speed, np.full_like(ref_speed, reference_height_m), hub_height_m, shear,
        )
        extrapolated_keys.append(f"merra:{key}")

    # --- interpolated ERA5 at site ---
    interp_done = False
    if state.era5_interpolated_df is not None and ref_col in state.era5_interpolated_df.columns:
        shear = _lookup_table_values(state.era5_interpolated_df.index, state.shear_table)
        ref_speed = state.era5_interpolated_df[ref_col].to_numpy(dtype=float)
        state.era5_interpolated_df[hub_col] = _power_extrapolate_array(
            ref_speed, np.full_like(ref_speed, reference_height_m), hub_height_m, shear,
        )
        interp_done = True

    return {
        "status": "ok",
        "hub_column": hub_col,
        "extrapolated_nodes": extrapolated_keys,
        "skipped_nodes": skipped_keys,
        "interpolated_extrapolated": interp_done,
    }


def _add_shear_to_timeseries(state: SessionState) -> bool:
    """Copy the shear timeseries into the measured dataset if available."""
    if state.shear_timeseries_df is None or state.timeseries_df is None:
        return False
    if "shear_coefficient" in state.shear_timeseries_df.columns:
        state.timeseries_df["shear_coefficient"] = state.shear_timeseries_df["shear_coefficient"]
        return True
    return False


@mcp.tool()
def extrapolate_to_hub_height(hub_height_m: float, shear_model: str = "power_law") -> dict:
    """Create a hub-height wind-speed series using power-law or log-law shear per IEC 61400-12-1 Annex B."""
    return _extrapolate_to_hub_height(session, hub_height_m, shear_model)


@mcp.tool()
def extrapolate_reanalysis_to_hub(hub_height_m: float, reference_height_m: float = 100.0) -> dict:
    """Extrapolate ERA5 site wind speed to hub height using the session month-hour shear lookup table."""
    return _extrapolate_reanalysis_to_hub(session, hub_height_m, reference_height_m)
