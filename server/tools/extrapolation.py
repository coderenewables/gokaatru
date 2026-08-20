"""extrapolation — Phase 2 MCP tools for hub-height wind extrapolation.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.core.formulas import ROUGHNESS_MAX_M, ROUGHNESS_MIN_M
from server.core.reanalysis import get_reference_source, reference_source_names
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


ALPHA_CLAMP_BAND = (-1.0, 1.0)

# How many re-clamped alpha values the most recent extrapolation hit.  Normally zero,
# because the table was clamped when it was built — but the fallback fill and the aggregate
# MoMM path can both reach this function with an unclamped value, and a clamp that fires
# changes the hub speed without saying so (F-27).
_alpha_reclamp_count = 0


def _power_extrapolate_array(
    reference_speed: np.ndarray,
    reference_height: np.ndarray,
    hub_height_m: float,
    alpha: np.ndarray,
) -> np.ndarray:
    """Vectorize power-law extrapolation over concurrent reference speeds and lookup shear values."""
    # Clamp the shear exponent to a physically plausible band so a corrupt or
    # extreme lookup cell cannot amplify reference speeds into non-physical hub
    # values. This mirrors the clamp applied when the shear table is built.
    global _alpha_reclamp_count
    lower, upper = ALPHA_CLAMP_BAND
    alpha_array = np.asarray(alpha, dtype=float)
    finite = np.isfinite(alpha_array)
    _alpha_reclamp_count = int(np.count_nonzero(finite & ((alpha_array < lower) | (alpha_array > upper))))
    alpha_safe = np.clip(alpha_array, lower, upper)
    return reference_speed * (hub_height_m / reference_height) ** alpha_safe


def _log_extrapolate_array(
    reference_speed: np.ndarray,
    reference_height: np.ndarray,
    hub_height_m: float,
    z0: np.ndarray,
) -> np.ndarray:
    """Vectorize log-law extrapolation with stable clipping of roughness length and heights."""
    z0_safe = np.clip(z0, ROUGHNESS_MIN_M, ROUGHNESS_MAX_M)
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


# Ratio of hub height to the reference height above which an extrapolation stops being
# an interpolation-grade inference.  Common practice treats roughly 1.5x the top
# measurement height as the limit of a defensible power-law extrapolation; beyond about
# 2x the profile assumption is doing most of the work.  Neither bound refuses here —
# the analyst may have good reason — but both are reported, because the ratio was
# previously invisible: a 40/60 m mast would be extrapolated to a 200 m hub silently.
EXTRAPOLATION_RATIO_WARN = 1.5
EXTRAPOLATION_RATIO_SEVERE = 2.0


def _extrapolation_lever(
    heights: np.ndarray,
    valid_mask: np.ndarray,
    hub_height_m: float,
    extrap_rows: np.ndarray,
) -> dict[str, object]:
    """Summarize how far above its reference height each extrapolated record was carried.

    The reference height is chosen per record by ``_nearest_indices``, so it drops to a
    lower sensor whenever the top one is missing and the lever silently grows for those
    records.  Reporting the distribution rather than a single number is what makes that
    visible.
    """
    if not extrap_rows.any():
        return {
            "extrapolated_records": 0,
            "reference_height_m": None,
            "extrapolation_ratio": None,
            "warning": None,
        }
    nearest = _nearest_indices(heights, valid_mask[extrap_rows], hub_height_m)
    reference_heights = heights[nearest]
    ratios = hub_height_m / reference_heights
    max_ratio = float(np.max(ratios))
    summary: dict[str, object] = {
        "extrapolated_records": int(extrap_rows.sum()),
        "reference_height_m": {
            "min": float(np.min(reference_heights)),
            "max": float(np.max(reference_heights)),
            "most_common": float(heights[int(np.bincount(nearest, minlength=heights.size).argmax())]),
        },
        "extrapolation_ratio": {
            "min": float(np.min(ratios)),
            "max": max_ratio,
            "mean": float(np.mean(ratios)),
        },
        "extrapolation_ratio_warn_threshold": EXTRAPOLATION_RATIO_WARN,
        "records_above_warn_threshold": int(np.count_nonzero(ratios > EXTRAPOLATION_RATIO_WARN)),
        "warning": None,
    }
    if max_ratio > EXTRAPOLATION_RATIO_SEVERE:
        summary["warning"] = (
            f"Hub height {hub_height_m:g} m is up to {max_ratio:.2f}x the reference height used "
            f"({float(np.min(reference_heights)):g} m at the extreme). Beyond "
            f"{EXTRAPOLATION_RATIO_SEVERE:g}x the power-law assumption, not the measurement, "
            "determines the hub-height speed. Treat this result as indicative and do not "
            "report it without stating the extrapolation ratio."
        )
    elif max_ratio > EXTRAPOLATION_RATIO_WARN:
        summary["warning"] = (
            f"Hub height {hub_height_m:g} m is up to {max_ratio:.2f}x the reference height used, "
            f"above the {EXTRAPOLATION_RATIO_WARN:g}x ratio normally treated as the limit of a "
            "defensible power-law extrapolation. Report the ratio alongside the result."
        )
    return summary


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
            "extrapolated_records": 0,
            "reference_height_m": float(hub_height_m),
            "extrapolation_ratio": 1.0,
            "warning": None,
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
    state.stamp_derived("hub_height_series")
    lever = _extrapolation_lever(heights, valid_mask, hub_height_m, extrap_rows)

    # Also extrapolate all reanalysis nodes (ERA5 nodes, MERRA-2 nodes, and the
    # interpolated site series) to hub height using the shear table. This is a
    # best-effort side-effect: it runs when a shear table and reanalysis data are
    # available. It used to be wrapped in a bare `except: pass`, so a genuine failure was
    # as silent as a legitimate skip (F-22); the reason is now reported either way.
    reanalysis_result: dict[str, object] | None = None
    if state.shear_table is None:
        reanalysis_result = {
            "status": "skipped",
            "reason": "no_shear_table",
            "wrote_hub_column": False,
        }
    elif not (state.era5_data or state.era5_interpolated_df is not None):
        reanalysis_result = {
            "status": "skipped",
            "reason": "no_reanalysis_data",
            "wrote_hub_column": False,
        }
    else:
        try:
            reanalysis_result = _extrapolate_all_reanalysis_nodes(state, float(hub_height_m))
        except (ValueError, KeyError) as exc:
            reanalysis_result = {
                "status": "failed",
                "reason": str(exc),
                "wrote_hub_column": False,
                "warning": (
                    "Reanalysis hub-height extrapolation failed and the measured series was "
                    f"still written: {exc}. Any long-term correction expecting the reanalysis "
                    "hub column will fail or reuse a stale one."
                ),
            }

    response: dict[str, object] = {
        "status": "ok",
        "column_name": column_name,
        "method_counts": counts,
        # F-21: `method_counts` reported the split without saying the two paths use
        # different physics, so a single hub series could silently be a blend of both.
        "method_models": {
            "direct": "measured at hub height, no model applied",
            "interpolated": "linear interpolation in ln(z) between the bracketing sensors",
            "extrapolated": (
                f"{shear_model} using the month-hour "
                f"{'shear' if shear_model == 'power_law' else 'roughness'} table"
            ),
        },
        "method_note": (
            "Records inside the mast range are interpolated log-linearly; records outside it "
            "use the shear or roughness table. Both are defensible, but they are different "
            "physical models and the divergence grows with shear - measured at hub 80 m "
            "between 60 m and 100 m: +0.03% at alpha 0.10, +0.13% at 0.20, +0.39% at 0.35. "
            "A hub series with counts in both rows is a blend of the two."
        ),
        "method_is_mixed": bool(counts["interpolated"] and counts["extrapolated"]),
        # F-27: the profile is neutral throughout. There is no Monin-Obukhov length, no
        # Richardson number and no stability class anywhere in the pipeline; the 12x24
        # month-hour table is the empirical stability proxy. That is a legitimate industry
        # approach and arguably implicit in the table's existence, but it was never stated.
        "stability_treatment": "neutral_profile_with_month_hour_table",
        "stability_note": (
            "No explicit atmospheric stability correction is applied. The profile is neutral, "
            "and the 12x24 month-hour shear table stands in for stability by capturing its "
            "diurnal and seasonal signature empirically. A site with strong nocturnal "
            "stratification will have that captured only to the extent the campaign observed "
            "it in the same month-hour cells."
        ),
        "alpha_reclamped_records": _alpha_reclamp_count,
        "alpha_clamp_band": list(ALPHA_CLAMP_BAND),
        "reanalysis": reanalysis_result,
        **lever,
        **state.staleness_report(),
    }
    if _alpha_reclamp_count:
        response["alpha_clamp_warning"] = (
            f"{_alpha_reclamp_count:,} records used a shear exponent outside "
            f"{ALPHA_CLAMP_BAND} and were clamped to the band before extrapolation. The shear "
            "table is clamped when it is built, so this can only come from a fallback fill or "
            "the aggregate MoMM path — a clamped alpha changes the hub speed it produces."
        )
    if response["method_is_mixed"]:
        response["method_warning"] = (
            f"{counts['interpolated']:,} records were interpolated in ln(z) and "
            f"{counts['extrapolated']:,} were extrapolated with the {shear_model} table, so "
            "this hub series is produced by two different physical models. That happens when "
            "the bracketing sensors drop out intermittently."
        )
    if lever.get("warning"):
        response["warning"] = lever["warning"]
    # Surfaced under its own key rather than competing with the lever warning: a leg that
    # wrote nothing and an over-long lever are separate problems and both need saying.
    if isinstance(reanalysis_result, dict) and reanalysis_result.get("warning"):
        response["reanalysis_warning"] = reanalysis_result["warning"]
    return response


def _extrapolate_reanalysis_to_hub(
    state: SessionState,
    hub_height_m: float,
    reference_height_m: float | None = None,
    source: str | None = None,
) -> dict:
    """Extrapolate one reanalysis site series to hub height using the month-hour shear table.

    ``reference_height_m`` defaults to the source's *native* height rather than to
    100 m: ERA5 is served at 100 m and MERRA-2 at 50 m, so a fixed default silently
    produced the wrong lever for MERRA-2 - or, more often, raised a missing-column
    error, because ``Spd_100m`` is not a MERRA-2 column at all (design doc S6.3).
    """
    descriptor = get_reference_source(source or state.active_reference_source)
    frame = state.reanalysis_interpolated.get(descriptor.name)
    if frame is None:
        raise ValueError(
            f"{descriptor.label} interpolated data is not available. Run reanalysis interpolation first"
        )
    if state.shear_table is None:
        raise ValueError("Reanalysis hub-height extrapolation requires session.shear_table")
    height = descriptor.native_height_m if reference_height_m is None else float(reference_height_m)
    reference_col = f"Spd_{int(height)}m"
    if reference_col not in frame.columns:
        raise ValueError(
            f"Reference {descriptor.label} column '{reference_col}' not found in interpolated data"
        )
    shear_values = _lookup_table_values(frame.index, state.shear_table)
    reference_speed = frame[reference_col].to_numpy(dtype=float)
    hub_speed = _power_extrapolate_array(
        reference_speed,
        np.full_like(reference_speed, height),
        hub_height_m,
        shear_values,
    )
    column_name = _hub_column_name(hub_height_m)
    frame[column_name] = hub_speed
    return {
        "status": "ok",
        "column_name": column_name,
        "reference_source": descriptor.name,
        "reference_height_m": height,
    }


def _extrapolate_all_reanalysis_nodes(
    state: SessionState,
    hub_height_m: float,
    reference_height_m: float | None = None,
) -> dict:
    """Extrapolate every ERA5/MERRA-2 node and both site series to hub height.

    The reference column is resolved **per source**. It used to be one column name
    derived from a fixed 100 m default and applied to everything, so every MERRA-2
    node was skipped for want of a ``Spd_100m`` it can never have - the mechanical
    reason MERRA-2 was downloaded, cached and then used for nothing (design doc
    S6.3). Passing ``reference_height_m`` explicitly still overrides, but then
    applies to all sources and is only meaningful when they share a height.
    """
    if state.shear_table is None:
        raise ValueError("Hub-height extrapolation of reanalysis data requires session.shear_table")

    hub_col = _hub_column_name(hub_height_m)
    extrapolated_keys: list[str] = []
    skipped_keys: list[str] = []
    reference_columns: dict[str, str] = {}

    def _extrapolate_frame(frame: pd.DataFrame, descriptor, label: str) -> bool:
        height = (
            descriptor.native_height_m if reference_height_m is None else float(reference_height_m)
        )
        ref_col = f"Spd_{int(height)}m"
        reference_columns[descriptor.name] = ref_col
        if ref_col not in frame.columns:
            skipped_keys.append(label)
            return False
        shear = _lookup_table_values(frame.index, state.shear_table)
        ref_speed = frame[ref_col].to_numpy(dtype=float)
        frame[hub_col] = _power_extrapolate_array(
            ref_speed, np.full_like(ref_speed, height), hub_height_m, shear,
        )
        extrapolated_keys.append(label)
        return True

    era5 = get_reference_source("era5")
    merra2 = get_reference_source("merra2")

    for key, frame in state.era5_data.items():
        _extrapolate_frame(frame, era5, key)

    merra_data: dict[str, pd.DataFrame] = getattr(state, "merra_data", {})
    for key, frame in merra_data.items():
        _extrapolate_frame(frame, merra2, f"merra:{key}")

    # --- interpolated site series, one per reference source ---
    # F-22: the interpolated series was only ever touched when the reference column was
    # present, and it never reached `skipped_nodes` - that list collected node keys only.
    # With ERA5 present but carrying just 10 m winds this returned status "ok" with both
    # lists empty, having written nothing at all, and LTC then either failed on a missing
    # column or silently reused a hub column from an earlier run.
    interpolated_done: list[str] = []
    for name in reference_source_names():
        frame = state.reanalysis_interpolated.get(name)
        if frame is None:
            continue
        if _extrapolate_frame(frame, get_reference_source(name), f"interpolated_site_series:{name}"):
            interpolated_done.append(name)

    interp_done = bool(interpolated_done)
    wrote_anything = bool(extrapolated_keys)
    result: dict[str, object] = {
        "status": "ok" if wrote_anything else "no_op",
        "hub_column": hub_col,
        "reference_columns": reference_columns,
        "extrapolated_nodes": extrapolated_keys,
        "skipped_nodes": skipped_keys,
        "interpolated_extrapolated": interp_done,
        "interpolated_sources": interpolated_done,
        "wrote_hub_column": wrote_anything,
    }
    if not wrote_anything:
        expected = ", ".join(sorted(set(reference_columns.values()))) or "the reference column"
        result["warning"] = (
            f"No reanalysis series was extrapolated to hub height: none of them carries its "
            f"reference column ({expected}). Nothing wrote '{hub_col}', so any long-term "
            "correction that expects it will either fail on the missing column or reuse a "
            "stale one from an earlier run. Check that the reanalysis download included the "
            "native-height winds for each source."
        )
    elif skipped_keys:
        result["warning"] = (
            f"{len(skipped_keys)} reanalysis series were skipped for want of their reference "
            f"column ({reference_columns}): {skipped_keys}."
        )
    return result


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
def extrapolate_reanalysis_to_hub(
    hub_height_m: float, reference_height_m: float | None = None
) -> dict:
    """Extrapolate ERA5 site wind speed to hub height using the session month-hour shear lookup table."""
    return _extrapolate_reanalysis_to_hub(session, hub_height_m, reference_height_m)
