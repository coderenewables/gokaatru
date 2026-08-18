"""shear — Phase 2 MCP tools for shear and roughness analysis.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from server.core.formulas import ROUGHNESS_MAX_M, ROUGHNESS_MIN_M
from server.core.momm import compute_weighted_momm_table
from server.main import mcp
from server.state.session import SessionState, session

# Minimum speed for a record to contribute to a shear estimate (D3).  Below a few
# m/s, ln(v2/v1) is dominated by anemometer noise rather than by the profile, and
# that noise is what produces the extreme alpha values the clamp exists to
# suppress.  The former 0.1 m/s gate admitted essentially every calm record.
SHEAR_MIN_SPEED_MPS = 3.0

# Physically plausible band for the power-law exponent.  Typical alpha is
# 0.05-0.40; stable nocturnal profiles reach ~0.6.  Kept as a backstop against
# non-physical extrapolation, but a high clamp rate is a data-quality signal, not
# something to hide — hence the statistics below.
SHEAR_ALPHA_BOUND = 1.0

# Clamp rate above which the response carries an explicit warning.
SHEAR_CLAMP_WARNING_FRACTION = 0.05

# Last-resort fallbacks, reachable only when a table has no finite cell at all.  Named
# rather than inlined because substituting a generic value for a site-specific one is a
# methodology choice: 0.143 is the one-seventh power law and 0.0002 m is open-water
# roughness.  Both are now reported via `fallback_source` so the substitution is visible.
DEFAULT_FALLBACK_ALPHA = 0.143
DEFAULT_FALLBACK_Z0_M = 0.0002

# F-20.  Directional shear drives hub-height speed, and the sector tables had no
# record gate at all: 20 records in one sector produced a full 288-cell table of which
# 285 cells were that sector's own mean.  SpeedSort already requires 200 records before
# it trusts a sector fit and mast-shadow detection requires 50; this matches SpeedSort,
# which is the closer analogue.  Overridable per run via runconfig["shear"].
SECTOR_SHEAR_MIN_RECORDS = 200


def _parse_height_sensors(height_sensors: str) -> dict[float, str]:
    """Parse the height-to-column JSON mapping used by the Phase 2 shear tools."""
    raw_mapping = json.loads(height_sensors)
    if isinstance(raw_mapping, list):
        inferred: dict[float, str] = {}
        for sensor_name in raw_mapping:
            if not isinstance(sensor_name, str):
                raise ValueError("height_sensors list entries must be sensor name strings")
            match = re.search(r"_(\d+(?:\.\d+)?)m(?:_|$)", sensor_name, flags=re.IGNORECASE)
            if not match:
                raise ValueError(
                    f"Could not infer measurement height from sensor '{sensor_name}'. "
                    "Use names like Spd_180m or provide an explicit mapping."
                )
            inferred[float(match.group(1))] = sensor_name
        raw_mapping = inferred

    if not isinstance(raw_mapping, dict):
        raise ValueError("height_sensors must decode to a JSON object mapping heights to column names or a list of sensor names")

    parsed = {float(height): str(column) for height, column in raw_mapping.items()}
    if len(parsed) < 2:
        raise ValueError(f"Shear requires >=2 heights, got {len(parsed)}")
    return dict(sorted(parsed.items()))


def _require_timeseries(state: SessionState) -> pd.DataFrame:
    """Return the loaded timeseries dataframe required by the Phase 2 shear workflow."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return state.timeseries_df


def _require_columns(df: pd.DataFrame, height_map: dict[float, str]) -> None:
    """Validate that all selected sensor columns exist in the loaded timeseries dataframe."""
    missing = [column for column in height_map.values() if column not in df.columns]
    if missing:
        raise ValueError(f"Missing height sensor columns: {', '.join(missing)}")


def _compute_pairwise_shear(
    speed_matrix: np.ndarray,
    heights: np.ndarray,
    min_speed_mps: float = SHEAR_MIN_SPEED_MPS,
) -> tuple[np.ndarray, dict[str, object]]:
    """Compute row-wise weighted shear from all valid height pairs using IEC power-law geometry.

    Returns the alpha series alongside clamping statistics (D3).  The estimator
    itself is unchanged — it recovers alpha exactly on a clean profile — but the
    valid-record gate and the reporting around it are not cosmetic: a clamped
    alpha of 1.0 turns 8.7 m/s at 150 m into 15.0 m/s, a 72% overestimate, and
    the previous implementation applied that clamp with no record of how often.
    """
    numerator = np.zeros(speed_matrix.shape[0], dtype=float)
    denominator = np.zeros(speed_matrix.shape[0], dtype=float)
    valid_pairs = np.zeros(speed_matrix.shape[0], dtype=int)
    for start in range(len(heights) - 1):
        for end in range(start + 1, len(heights)):
            x_term = float(np.log(heights[end] / heights[start]))
            weights = abs(x_term)
            v1 = speed_matrix[:, start]
            v2 = speed_matrix[:, end]
            mask = np.isfinite(v1) & np.isfinite(v2) & (v1 > min_speed_mps) & (v2 > min_speed_mps)
            log_ratio = np.full(speed_matrix.shape[0], np.nan, dtype=float)
            log_ratio[mask] = np.log(v2[mask] / v1[mask])
            numerator[mask] += weights * x_term * log_ratio[mask]
            denominator[mask] += weights * x_term**2
            valid_pairs[mask] += 1
    result = np.full(speed_matrix.shape[0], np.nan, dtype=float)
    usable = (valid_pairs > 0) & (denominator > 0)
    result[usable] = numerator[usable] / denominator[usable]
    clamped = usable & (np.abs(result) > SHEAR_ALPHA_BOUND)
    result[usable] = np.clip(result[usable], -SHEAR_ALPHA_BOUND, SHEAR_ALPHA_BOUND)
    return result, _clamp_stats(int(usable.sum()), int(clamped.sum()), min_speed_mps)


def _clamp_stats(records_used: int, records_clamped: int, min_speed_mps: float) -> dict[str, object]:
    """Summarize shear clamping, warning when the clamp fired often enough to matter (D3)."""
    fraction = float(records_clamped / records_used) if records_used else 0.0
    stats: dict[str, object] = {
        "records_used": records_used,
        "records_clamped": records_clamped,
        "clamped_fraction": fraction,
        "min_speed_mps": float(min_speed_mps),
    }
    if fraction > SHEAR_CLAMP_WARNING_FRACTION:
        stats["warning"] = (
            f"{fraction:.1%} of shear records ({records_clamped:,} of {records_used:,}) were clamped to "
            f"|alpha| = {SHEAR_ALPHA_BOUND}. A clamped exponent is non-physical and inflates "
            f"hub-height extrapolation; treat this as a data-quality signal and check the "
            f"anemometer pair and the {min_speed_mps:g} m/s speed gate."
        )
    return stats


def _merge_clamp_stats(parts: list[dict[str, object]], min_speed_mps: float) -> dict[str, object]:
    """Combine per-bin clamp statistics into one summary for aggregate shear tables."""
    used = sum(int(part["records_used"]) for part in parts)
    clamped = sum(int(part["records_clamped"]) for part in parts)
    return _clamp_stats(used, clamped, min_speed_mps)


def _resolve_min_speed(state: SessionState, min_speed_mps: float | None) -> float:
    """Resolve the shear speed gate from the caller, else runconfig, else the default (D3)."""
    if min_speed_mps is None:
        return state.get_shear_min_speed_mps(SHEAR_MIN_SPEED_MPS)
    resolved = float(min_speed_mps)
    if resolved < 0.0:
        raise ValueError(f"min_speed_mps must be non-negative, got {resolved}")
    state.set_shear_min_speed_mps(resolved)
    return resolved


def _fit_rowwise_log_profile(speed_matrix: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Fit row-wise U versus ln(z) regressions to estimate roughness length from valid sensors."""
    log_heights = np.log(heights)
    valid = np.isfinite(speed_matrix) & (speed_matrix > 0.5)
    counts = valid.sum(axis=1)
    masked_x = valid * log_heights[None, :]
    masked_y = np.where(valid, speed_matrix, 0.0)
    mean_x = np.divide(masked_x.sum(axis=1), counts, out=np.zeros_like(counts, dtype=float), where=counts > 0)
    mean_y = np.divide(masked_y.sum(axis=1), counts, out=np.zeros_like(counts, dtype=float), where=counts > 0)
    centered_x = np.where(valid, log_heights[None, :] - mean_x[:, None], 0.0)
    centered_y = np.where(valid, speed_matrix - mean_y[:, None], 0.0)
    sxx = np.sum(centered_x**2, axis=1)
    sxy = np.sum(centered_x * centered_y, axis=1)
    slopes = np.divide(sxy, sxx, out=np.full_like(sxy, np.nan, dtype=float), where=sxx > 0)
    intercepts = mean_y - slopes * mean_x
    z0 = np.exp(-intercepts / slopes)
    valid_rows = (counts >= 2) & np.isfinite(slopes) & (slopes > 0.1)
    result = np.full(speed_matrix.shape[0], np.nan, dtype=float)
    result[valid_rows] = np.clip(z0[valid_rows], ROUGHNESS_MIN_M, ROUGHNESS_MAX_M)
    return result


def _complete_table(table: pd.DataFrame, fallback: float) -> pd.DataFrame:
    """Ensure a month-hour lookup table covers all 12 months and 24 hours with fallback fill values."""
    return table.reindex(index=range(1, 13), columns=range(24)).fillna(fallback)


def _table_fill_report(table: pd.DataFrame, source: pd.DataFrame) -> dict[str, object]:
    """Report which month-hour cells the campaign never observed (D3, audit F-19).

    ``_complete_table`` fills absent cells with the series mean so the lookup always
    resolves.  That is deliberate — extrapolation applies the table to the *reanalysis*
    series, which spans every month of the year — but it means a six-month campaign
    produces a full 12x24 table indistinguishable from a full-year one.  The fill count
    travels with the table so the reader knows how much of it is synthetic.
    """
    observed = pd.MultiIndex.from_arrays([source.index.month, source.index.hour]).unique()
    observed_cells = {(int(month), int(hour)) for month, hour in observed}
    total_cells = 12 * 24
    filled = total_cells - len(observed_cells)
    months_observed = sorted({month for month, _ in observed_cells})
    report: dict[str, object] = {
        "cells_observed": len(observed_cells),
        "cells_total": total_cells,
        "filled_cells": filled,
        "filled_fraction": float(filled / total_cells),
        "months_observed": months_observed,
        "months_missing": [month for month in range(1, 13) if month not in months_observed],
    }
    if filled:
        report["warning"] = (
            f"{filled} of {total_cells} month-hour cells ({filled / total_cells:.0%}) were never "
            f"observed and carry the series mean instead. Months absent from the campaign: "
            f"{report['months_missing']}. Extrapolation applies this table to the full "
            "long-term reference series, so those months are corrected with a synthetic value."
        )
    return report


def _aggregate_table(df: pd.DataFrame, value_col: str, aggregation: str, fallback: float) -> pd.DataFrame:
    """Aggregate a monthly-hourly lookup table using mean, median, or Windographer MoMM."""
    if aggregation == "momm":
        table = compute_weighted_momm_table(df[[value_col]].copy(), value_col)
    else:
        table = df.assign(month=df.index.month, hour=df.index.hour).pivot_table(
            values=value_col,
            index="month",
            columns="hour",
            aggfunc=aggregation,
        )
    return _complete_table(table, fallback)


def _aggregate_roughness_table(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    """Aggregate roughness in log-space before exponentiating back to physical z0 values."""
    working = df.copy()
    working["log_z0"] = np.log(working["roughness_length"])
    fallback = float(np.exp(working["log_z0"].dropna().mean())) if not working["log_z0"].dropna().empty else DEFAULT_FALLBACK_Z0_M
    return np.exp(_aggregate_table(working, "log_z0", aggregation, np.log(fallback)))


def _sector_label(index: int, num_sectors: int) -> str:
    """Format direction-sector labels as start-end degree bins."""
    width = 360.0 / num_sectors
    return f"{int(index * width)}-{int((index + 1) * width)}"


def _aggr_momm_table(
    df: pd.DataFrame,
    height_map: dict[float, str],
    min_speed_mps: float = SHEAR_MIN_SPEED_MPS,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build an aggregate MoMM shear table by deriving alpha from per-height MoMM wind tables."""
    speeds = df[list(height_map.values())]
    valid = speeds.notna().all(axis=1) & (speeds > min_speed_mps).all(axis=1)
    concurrent = speeds.loc[valid]
    if concurrent.empty:
        raise ValueError("Aggregate MoMM shear requires concurrent valid data across all selected heights")
    heights = np.asarray(list(height_map.keys()), dtype=float)
    tables = [
        compute_weighted_momm_table(
            concurrent[[column]].rename(columns={column: str(height)}),
            str(height),
        )
        for height, column in height_map.items()
    ]
    result = pd.DataFrame(np.nan, index=range(1, 13), columns=range(24), dtype=float)
    bin_stats: list[dict[str, object]] = []
    for month in range(1, 13):
        for hour in range(24):
            speeds_at_bin = np.asarray([table.loc[month, hour] for table in tables], dtype=float)
            alpha, stats = _compute_pairwise_shear(speeds_at_bin.reshape(1, -1), heights, min_speed_mps)
            result.loc[month, hour] = alpha[0]
            bin_stats.append(stats)
    fallback = float(np.nanmean(result.to_numpy())) if np.isfinite(result.to_numpy()).any() else DEFAULT_FALLBACK_ALPHA
    return result.fillna(fallback), _merge_clamp_stats(bin_stats, min_speed_mps)


def _calculate_shear_timeseries(
    state: SessionState,
    height_sensors: str,
    min_speed_mps: float | None = None,
) -> dict:
    """Calculate timestamp-wise power-law shear coefficients per IEC 61400-12-1 Section B.2."""
    df = _require_timeseries(state)
    height_map = _parse_height_sensors(height_sensors)
    _require_columns(df, height_map)
    resolved_min_speed = _resolve_min_speed(state, min_speed_mps)
    heights = np.asarray(list(height_map.keys()), dtype=float)
    speed_matrix = df[list(height_map.values())].to_numpy(dtype=float)
    shear_values, clamp_stats = _compute_pairwise_shear(speed_matrix, heights, resolved_min_speed)
    state.shear_timeseries_df = pd.DataFrame({"shear_coefficient": shear_values}, index=df.index)
    state.shear_clamp_stats = clamp_stats
    state.stamp_derived("shear_timeseries")
    valid = state.shear_timeseries_df["shear_coefficient"].dropna()
    return {
        "status": "ok",
        "records": int(valid.count()),
        "mean_shear": float(valid.mean()),
        "median_shear": float(valid.median()),
        "std_shear": float(valid.std(ddof=0)),
        **clamp_stats,
    }


def _calculate_roughness_timeseries(state: SessionState, height_sensors: str) -> dict:
    """Calculate timestamp-wise roughness lengths from U versus ln(z) fits per IEC 61400-12-1 Section B.3."""
    df = _require_timeseries(state)
    height_map = _parse_height_sensors(height_sensors)
    _require_columns(df, height_map)
    heights = np.asarray(list(height_map.keys()), dtype=float)
    speed_matrix = df[list(height_map.values())].to_numpy(dtype=float)
    roughness = _fit_rowwise_log_profile(speed_matrix, heights)
    state.roughness_timeseries_df = pd.DataFrame({"roughness_length": roughness}, index=df.index)
    state.stamp_derived("roughness_timeseries")
    valid = state.roughness_timeseries_df["roughness_length"].dropna()
    return {
        "status": "ok",
        "records": int(valid.count()),
        "mean_roughness": float(valid.mean()),
        "median_roughness": float(valid.median()),
        "std_roughness": float(valid.std(ddof=0)),
    }


def _parse_sensor_names(sensor_names: str) -> list[str]:
    """Parse optional comma-separated sensor names supplied by the browser overview."""
    return [name.strip() for name in sensor_names.split(",") if name.strip()]


def _mapped_height_sensors(state: SessionState, field_name: str) -> dict[float, str]:
    """Return valid mapped sensor columns of one type keyed by their measurement height."""
    df = _require_timeseries(state)
    mapped = {
        float(height): str(mapping[field_name])
        for height, mapping in state.sensor_mapping.items()
        if mapping.get(field_name) in df.columns
    }
    return dict(sorted(mapped.items()))


def _resolve_height_sensors(state: SessionState, sensor_names: str, field_name: str) -> dict[float, str]:
    """Use explicit overview choices when supplied, otherwise use mapped sensors of the requested type."""
    selected = _parse_sensor_names(sensor_names)
    if selected:
        return _parse_height_sensors(json.dumps(selected))
    return _mapped_height_sensors(state, field_name)


def _compute_veer(direction_matrix: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Calculate signed directional veer in degrees per 100 m between outer valid heights."""
    result = np.full(direction_matrix.shape[0], np.nan, dtype=float)
    for row_index, row in enumerate(direction_matrix):
        valid_indices = np.flatnonzero(np.isfinite(row))
        if len(valid_indices) < 2:
            continue
        lower = valid_indices[0]
        upper = valid_indices[-1]
        direction_change = (row[upper] - row[lower] + 180.0) % 360.0 - 180.0
        height_span = heights[upper] - heights[lower]
        if height_span > 0:
            result[row_index] = direction_change / height_span * 100.0
    return result


def _profile_fit_metrics(height_map: dict[float, str], df: pd.DataFrame) -> dict[str, object]:
    """Fit mean vertical wind profile in power-law and log-law coordinates for overview metrics.

    The means are taken over records where **every** selected height is valid.  Averaging
    each column over its own records instead lets the heights describe different periods:
    on a site with 0.10 summer and 0.32 winter shear whose 100 m sensor was lost for one
    summer, the per-column fit returned alpha 0.244 against a concurrent-record answer of
    0.320 — an error of -0.076, worth -3.0% on hub-height speed at 150 m.  Losing a top
    sensor for a season is ordinary (icing, lightning, maintenance), so this is the normal
    case rather than an edge one.

    ``records_used`` and ``records_available`` report how much the concurrency requirement
    cost, so a profile fitted on a thin overlap is visible as such.
    """
    heights = np.asarray(list(height_map.keys()), dtype=float)
    columns = list(height_map.values())
    concurrent = df[columns].dropna()
    if concurrent.empty:
        raise ValueError(
            "Vertical profile requires records where every selected height is valid; the "
            "selected sensors have no concurrent coverage."
        )
    mean_speeds = np.asarray([concurrent[column].mean() for column in columns], dtype=float)
    valid = np.isfinite(mean_speeds) & (mean_speeds > 0)
    if valid.sum() < 2:
        raise ValueError("Vertical profile requires valid mean wind speeds at two or more heights")
    log_height = np.log(heights[valid])
    log_speed = np.log(mean_speeds[valid])
    alpha, log_intercept = np.polyfit(log_height, log_speed, 1)
    predicted_log_speed = alpha * log_height + log_intercept
    residual = float(np.sum((log_speed - predicted_log_speed) ** 2))
    total = float(np.sum((log_speed - log_speed.mean()) ** 2))
    power_r_squared = 1.0 if total == 0 else float(1.0 - residual / total)
    log_slope, log_intercept_linear = np.polyfit(log_height, mean_speeds[valid], 1)
    roughness_length = float(np.exp(-log_intercept_linear / log_slope)) if log_slope > 0 else float("nan")
    return {
        "mean_profile": [
            {"height_m": float(height), "mean_speed": float(speed)}
            for height, speed in zip(heights[valid], mean_speeds[valid], strict=True)
        ],
        "power_law_alpha": float(alpha),
        "power_law_alpha_basis": "log_log_fit_to_concurrent_mean_profile",
        "power_law_r_squared": power_r_squared,
        "roughness_length_m": roughness_length,
        "records_used": int(len(concurrent)),
        "records_available": int(len(df)),
        "concurrent_fraction": float(len(concurrent) / len(df)) if len(df) else 0.0,
    }


def _vertical_structure_series(
    state: SessionState,
    speed_sensors: str = "",
    direction_sensors: str = "",
    min_speed_mps: float | None = None,
) -> tuple[pd.Series, pd.Series | None, dict[str, object]]:
    """Derive timestamp-wise alpha and optional veer series without mutating the session state."""
    df = _require_timeseries(state)
    speed_map = _resolve_height_sensors(state, speed_sensors, "speed_col")
    if len(speed_map) < 2:
        raise ValueError("Vertical structure requires at least two wind-speed heights")
    _require_columns(df, speed_map)
    resolved_min_speed = (
        state.get_shear_min_speed_mps(SHEAR_MIN_SPEED_MPS) if min_speed_mps is None else float(min_speed_mps)
    )
    heights = np.asarray(list(speed_map.keys()), dtype=float)
    alpha_values, clamp_stats = _compute_pairwise_shear(
        df[list(speed_map.values())].to_numpy(dtype=float), heights, resolved_min_speed
    )
    alpha = pd.Series(alpha_values, index=df.index, name="alpha")
    direction_map = _resolve_height_sensors(state, direction_sensors, "dir_col")
    veer: pd.Series | None = None
    if len(direction_map) >= 2:
        _require_columns(df, direction_map)
        direction_heights = np.asarray(list(direction_map.keys()), dtype=float)
        veer = pd.Series(
            _compute_veer(df[list(direction_map.values())].to_numpy(dtype=float), direction_heights),
            index=df.index,
            name="veer_deg_per_100m",
        )
    return alpha, veer, {**_profile_fit_metrics(speed_map, df), "shear_clamping": clamp_stats}


def _compute_vertical_structure(
    state: SessionState,
    speed_sensors: str = "",
    direction_sensors: str = "",
    min_speed_mps: float | None = None,
) -> dict:
    """Summarize measured profile, shear alpha, and optional wind veer for the Sensor Overview."""
    alpha, veer, profile = _vertical_structure_series(state, speed_sensors, direction_sensors, min_speed_mps)
    valid_alpha = alpha.dropna()
    if valid_alpha.empty:
        raise ValueError("No concurrent valid wind-speed records are available for shear analysis")
    result: dict[str, object] = {
        **profile,
        "alpha": {
            "record_count": int(valid_alpha.count()),
            "mean": float(valid_alpha.mean()),
            "median": float(valid_alpha.median()),
            "std": float(valid_alpha.std(ddof=0)),
            "p10": float(valid_alpha.quantile(0.10)),
            "p90": float(valid_alpha.quantile(0.90)),
        },
        "veer": None,
    }
    if veer is not None:
        valid_veer = veer.dropna()
        if not valid_veer.empty:
            result["veer"] = {
                "record_count": int(valid_veer.count()),
                "mean_deg_per_100m": float(valid_veer.mean()),
                "std_deg_per_100m": float(valid_veer.std(ddof=0)),
            }
    return result


def _build_shear_table(state: SessionState, aggregation: str = "mean") -> dict:
    """Build a 12x24 power-law shear lookup table using mean, median, or Windographer MoMM aggregation."""
    if aggregation not in {"mean", "median", "momm"}:
        raise ValueError(f"aggregation must be one of mean, median, momm, got '{aggregation}'")
    if state.shear_timeseries_df is None:
        raise ValueError("Shear timeseries is not available. Run calculate_shear_timeseries first")
    valid = state.shear_timeseries_df.dropna()
    fallback = float(valid["shear_coefficient"].mean()) if not valid.empty else DEFAULT_FALLBACK_ALPHA
    fallback_source = "series_mean" if not valid.empty else "one_seventh_power_law_default"
    state.shear_table = _aggregate_table(valid, "shear_coefficient", aggregation, fallback)
    state.stamp_derived("shear_table")
    coverage = _table_fill_report(state.shear_table, valid)
    response: dict[str, object] = {
        "method": "power_law",
        "aggregation": aggregation,
        "table": state.shear_table.values.tolist(),
        # Every shear-table response carries the clamp statistics of the series it
        # was built from, so the table is never read without them (D3).
        "shear_clamping": state.shear_clamp_stats or {},
        "fallback_alpha": fallback,
        "fallback_source": fallback_source,
        "table_coverage": coverage,
        # The 24 columns are UTC hours, and the extrapolation lookup uses the same clock,
        # so the physics is self-consistent — but the column labels are not local (F-02).
        **state.clock_disclosure(),
    }
    if coverage.get("warning"):
        response["warning"] = coverage["warning"]
    return response


def _build_roughness_table(state: SessionState, aggregation: str = "mean") -> dict:
    """Build a 12x24 roughness lookup table in log-space per IEC logarithmic profile practice."""
    if aggregation not in {"mean", "median", "momm"}:
        raise ValueError(f"aggregation must be one of mean, median, momm, got '{aggregation}'")
    if state.roughness_timeseries_df is None:
        raise ValueError("Roughness timeseries is not available. Run calculate_roughness_timeseries first")
    valid = state.roughness_timeseries_df.dropna()
    state.roughness_table = _aggregate_roughness_table(valid, aggregation)
    state.stamp_derived("roughness_table")
    return {
        "method": "log_law",
        "aggregation": aggregation,
        "table": state.roughness_table.values.tolist(),
        **state.clock_disclosure(),
    }


def _resolve_sector_minimum(state: SessionState, requested: int | None) -> int:
    """Return the per-sector record minimum, from the caller, the runconfig, or the default."""
    if requested is not None:
        return max(0, int(requested))
    shear = state.runconfig.get("shear")
    if isinstance(shear, dict):
        value = shear.get("minSectorRecords")
        if isinstance(value, (int, float)):
            return max(0, int(value))
    return SECTOR_SHEAR_MIN_RECORDS


def _build_sector_shear_tables(
    state: SessionState,
    direction_sensor: str,
    num_sectors: int = 12,
    aggregation: str = "mean",
    min_sector_records: int | None = None,
) -> dict:
    """Build direction-sector-specific 12x24 shear tables using IEC directional binning and chosen aggregation."""
    if aggregation not in {"mean", "median", "momm"}:
        raise ValueError(f"aggregation must be one of mean, median, momm, got '{aggregation}'")
    if num_sectors <= 0:
        raise ValueError(f"num_sectors must be positive, got {num_sectors}")
    df = _require_timeseries(state)
    if direction_sensor not in df.columns:
        raise ValueError(f"Direction sensor '{direction_sensor}' not found in loaded timeseries")
    if state.shear_timeseries_df is None:
        raise ValueError("Shear timeseries is not available. Run calculate_shear_timeseries first")
    joined = state.shear_timeseries_df.join(df[[direction_sensor]], how="inner").dropna()
    width = 360.0 / num_sectors
    minimum = _resolve_sector_minimum(state, min_sector_records)
    sectors: dict[str, list[list[float]]] = {}
    sector_records: dict[str, int] = {}
    sector_coverage: dict[str, dict[str, object]] = {}
    excluded: list[dict[str, object]] = []
    indices = (((joined[direction_sensor] + width / 2.0) % 360.0) // width).astype(int)
    for sector in range(num_sectors):
        label = _sector_label(sector, num_sectors)
        sector_df = joined.loc[indices == sector, ["shear_coefficient"]]
        count = int(len(sector_df))
        sector_records[label] = count
        if count < minimum:
            # A bare ``continue`` used to drop these silently, so a sector absent for want
            # of data was indistinguishable from a sector the wind never came from (F-20).
            excluded.append({
                "sector": label,
                "records": count,
                "reason": "empty" if count == 0 else "below_minimum_records",
            })
            continue
        fallback = float(sector_df["shear_coefficient"].mean())
        table = _aggregate_table(sector_df, "shear_coefficient", aggregation, fallback)
        sectors[label] = table.values.tolist()
        sector_coverage[label] = _table_fill_report(table, sector_df)
    response: dict[str, object] = {
        "sectors": sectors,
        "shear_clamping": state.shear_clamp_stats or {},
        "min_sector_records": int(minimum),
        "sector_record_counts": sector_records,
        "sectors_excluded": excluded,
        "sector_coverage": sector_coverage,
        **state.clock_disclosure(),
    }
    thin = [
        label
        for label, report in sector_coverage.items()
        if float(report.get("filled_fraction", 0.0)) > 0.5
    ]
    if excluded:
        response["warning"] = (
            f"{len(excluded)} of {num_sectors} sectors were not tabulated because they hold "
            f"fewer than {minimum} records. Directional shear drives hub-height speed, and "
            "SpeedSort already requires 200 records per sector before trusting a sector fit."
        )
    if thin:
        response["coverage_warning"] = (
            f"Sectors {thin} produced a full 12x24 table from a partial month-hour coverage; "
            "more than half of each of those tables is that sector's own mean rather than an "
            "observation."
        )
    return response


def _build_aggr_momm_shear_table(
    state: SessionState,
    height_sensors: str,
    min_speed_mps: float | None = None,
) -> dict:
    """Build an aggregate MoMM shear table by deriving alpha from per-height Windographer MoMM wind tables."""
    df = _require_timeseries(state)
    height_map = _parse_height_sensors(height_sensors)
    _require_columns(df, height_map)
    resolved_min_speed = _resolve_min_speed(state, min_speed_mps)
    state.shear_table, clamp_stats = _aggr_momm_table(df, height_map, resolved_min_speed)
    state.shear_clamp_stats = clamp_stats
    state.stamp_derived("shear_table")
    return {
        "method": "power_law",
        "aggregation": "aggr_momm",
        "table": state.shear_table.values.tolist(),
        "shear_clamping": clamp_stats,
    }


@mcp.tool()
def calculate_shear_timeseries(height_sensors: str, min_speed_mps: float | None = None) -> dict:
    """Calculate timestamp-wise power-law shear coefficients per IEC 61400-12-1 Section B.2.

    ``min_speed_mps`` gates which records contribute (default 3.0 m/s): below
    that, ln(v2/v1) is anemometer noise rather than profile. The resolved value
    and the clamping statistics are returned with the result.
    """
    return _calculate_shear_timeseries(session, height_sensors, min_speed_mps)


@mcp.tool()
def calculate_roughness_timeseries(height_sensors: str) -> dict:
    """Calculate timestamp-wise roughness lengths from U versus ln(z) fits per IEC 61400-12-1 Section B.3."""
    return _calculate_roughness_timeseries(session, height_sensors)


@mcp.tool()
def compute_vertical_structure(
    speed_sensors: str = "",
    direction_sensors: str = "",
    min_speed_mps: float | None = None,
) -> dict:
    """Summarize multi-height power-law shear, profile fit, roughness, and optional wind veer."""
    return _compute_vertical_structure(session, speed_sensors, direction_sensors, min_speed_mps)


@mcp.tool()
def build_shear_table(aggregation: str = "mean") -> dict:
    """Build a 12x24 power-law shear lookup table using mean, median, or Windographer MoMM aggregation."""
    return _build_shear_table(session, aggregation)


@mcp.tool()
def build_roughness_table(aggregation: str = "mean") -> dict:
    """Build a 12x24 roughness lookup table in log-space per IEC logarithmic profile practice."""
    return _build_roughness_table(session, aggregation)


@mcp.tool()
def build_sector_shear_tables(
    direction_sensor: str,
    num_sectors: int = 12,
    aggregation: str = "mean",
    min_sector_records: int | None = None,
) -> dict:
    """Build direction-sector-specific 12x24 shear tables using IEC directional binning and chosen aggregation."""
    return _build_sector_shear_tables(
        session, direction_sensor, num_sectors, aggregation, min_sector_records
    )


@mcp.tool()
def build_aggr_momm_shear_table(height_sensors: str, min_speed_mps: float | None = None) -> dict:
    """Build an aggregate MoMM shear table by deriving alpha from per-height Windographer MoMM wind tables."""
    return _build_aggr_momm_shear_table(session, height_sensors, min_speed_mps)
