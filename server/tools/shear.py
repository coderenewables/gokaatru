"""shear — Phase 2 MCP tools for shear and roughness analysis.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from server.core.momm import compute_weighted_momm_table
from server.main import mcp
from server.state.session import SessionState, session


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


def _compute_pairwise_shear(speed_matrix: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Compute row-wise weighted shear from all valid height pairs using IEC power-law geometry."""
    numerator = np.zeros(speed_matrix.shape[0], dtype=float)
    denominator = np.zeros(speed_matrix.shape[0], dtype=float)
    valid_pairs = np.zeros(speed_matrix.shape[0], dtype=int)
    for start in range(len(heights) - 1):
        for end in range(start + 1, len(heights)):
            x_term = float(np.log(heights[end] / heights[start]))
            weights = abs(x_term)
            v1 = speed_matrix[:, start]
            v2 = speed_matrix[:, end]
            mask = np.isfinite(v1) & np.isfinite(v2) & (v1 > 0.1) & (v2 > 0.1)
            log_ratio = np.full(speed_matrix.shape[0], np.nan, dtype=float)
            log_ratio[mask] = np.log(v2[mask] / v1[mask])
            numerator[mask] += weights * x_term * log_ratio[mask]
            denominator[mask] += weights * x_term**2
            valid_pairs[mask] += 1
    result = np.full(speed_matrix.shape[0], np.nan, dtype=float)
    usable = (valid_pairs > 0) & (denominator > 0)
    result[usable] = numerator[usable] / denominator[usable]
    return result


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
    result[valid_rows] = np.clip(z0[valid_rows], 1e-6, 1.5)
    return result


def _complete_table(table: pd.DataFrame, fallback: float) -> pd.DataFrame:
    """Ensure a month-hour lookup table covers all 12 months and 24 hours with fallback fill values."""
    return table.reindex(index=range(1, 13), columns=range(24)).fillna(fallback)


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
    fallback = float(np.exp(working["log_z0"].dropna().mean())) if not working["log_z0"].dropna().empty else 0.0002
    return np.exp(_aggregate_table(working, "log_z0", aggregation, np.log(fallback)))


def _sector_label(index: int, num_sectors: int) -> str:
    """Format direction-sector labels as start-end degree bins."""
    width = 360.0 / num_sectors
    return f"{int(index * width)}-{int((index + 1) * width)}"


def _aggr_momm_table(df: pd.DataFrame, height_map: dict[float, str]) -> pd.DataFrame:
    """Build an aggregate MoMM shear table by deriving alpha from per-height MoMM wind tables."""
    speeds = df[list(height_map.values())]
    valid = speeds.notna().all(axis=1) & (speeds > 0.1).all(axis=1)
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
    for month in range(1, 13):
        for hour in range(24):
            speeds_at_bin = np.asarray([table.loc[month, hour] for table in tables], dtype=float)
            result.loc[month, hour] = _compute_pairwise_shear(speeds_at_bin.reshape(1, -1), heights)[0]
    fallback = float(np.nanmean(result.to_numpy())) if np.isfinite(result.to_numpy()).any() else 0.143
    return result.fillna(fallback)


def _calculate_shear_timeseries(state: SessionState, height_sensors: str) -> dict:
    """Calculate timestamp-wise power-law shear coefficients per IEC 61400-12-1 Section B.2."""
    df = _require_timeseries(state)
    height_map = _parse_height_sensors(height_sensors)
    _require_columns(df, height_map)
    heights = np.asarray(list(height_map.keys()), dtype=float)
    speed_matrix = df[list(height_map.values())].to_numpy(dtype=float)
    shear_values = _compute_pairwise_shear(speed_matrix, heights)
    state.shear_timeseries_df = pd.DataFrame({"shear_coefficient": shear_values}, index=df.index)
    valid = state.shear_timeseries_df["shear_coefficient"].dropna()
    return {
        "status": "ok",
        "records": int(valid.count()),
        "mean_shear": float(valid.mean()),
        "median_shear": float(valid.median()),
        "std_shear": float(valid.std(ddof=0)),
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
    valid = state.roughness_timeseries_df["roughness_length"].dropna()
    return {
        "status": "ok",
        "records": int(valid.count()),
        "mean_roughness": float(valid.mean()),
        "median_roughness": float(valid.median()),
        "std_roughness": float(valid.std(ddof=0)),
    }


def _build_shear_table(state: SessionState, aggregation: str = "mean") -> dict:
    """Build a 12x24 power-law shear lookup table using mean, median, or Windographer MoMM aggregation."""
    if aggregation not in {"mean", "median", "momm"}:
        raise ValueError(f"aggregation must be one of mean, median, momm, got '{aggregation}'")
    if state.shear_timeseries_df is None:
        raise ValueError("Shear timeseries is not available. Run calculate_shear_timeseries first")
    valid = state.shear_timeseries_df.dropna()
    fallback = float(valid["shear_coefficient"].mean()) if not valid.empty else 0.143
    state.shear_table = _aggregate_table(valid, "shear_coefficient", aggregation, fallback)
    return {"method": "power_law", "aggregation": aggregation, "table": state.shear_table.values.tolist()}


def _build_roughness_table(state: SessionState, aggregation: str = "mean") -> dict:
    """Build a 12x24 roughness lookup table in log-space per IEC logarithmic profile practice."""
    if aggregation not in {"mean", "median", "momm"}:
        raise ValueError(f"aggregation must be one of mean, median, momm, got '{aggregation}'")
    if state.roughness_timeseries_df is None:
        raise ValueError("Roughness timeseries is not available. Run calculate_roughness_timeseries first")
    valid = state.roughness_timeseries_df.dropna()
    state.roughness_table = _aggregate_roughness_table(valid, aggregation)
    return {"method": "log_law", "aggregation": aggregation, "table": state.roughness_table.values.tolist()}


def _build_sector_shear_tables(
    state: SessionState,
    direction_sensor: str,
    num_sectors: int = 12,
    aggregation: str = "mean",
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
    sectors: dict[str, list[list[float]]] = {}
    indices = (((joined[direction_sensor] + width / 2.0) % 360.0) // width).astype(int)
    for sector in range(num_sectors):
        sector_df = joined.loc[indices == sector, ["shear_coefficient"]]
        if sector_df.empty:
            continue
        fallback = float(sector_df["shear_coefficient"].mean()) if not sector_df.empty else 0.143
        table = _aggregate_table(sector_df, "shear_coefficient", aggregation, fallback)
        sectors[_sector_label(sector, num_sectors)] = table.values.tolist()
    return {"sectors": sectors}


def _build_aggr_momm_shear_table(state: SessionState, height_sensors: str) -> dict:
    """Build an aggregate MoMM shear table by deriving alpha from per-height Windographer MoMM wind tables."""
    df = _require_timeseries(state)
    height_map = _parse_height_sensors(height_sensors)
    _require_columns(df, height_map)
    state.shear_table = _aggr_momm_table(df, height_map)
    return {"method": "power_law", "aggregation": "aggr_momm", "table": state.shear_table.values.tolist()}


@mcp.tool()
def calculate_shear_timeseries(height_sensors: str) -> dict:
    """Calculate timestamp-wise power-law shear coefficients per IEC 61400-12-1 Section B.2."""
    return _calculate_shear_timeseries(session, height_sensors)


@mcp.tool()
def calculate_roughness_timeseries(height_sensors: str) -> dict:
    """Calculate timestamp-wise roughness lengths from U versus ln(z) fits per IEC 61400-12-1 Section B.3."""
    return _calculate_roughness_timeseries(session, height_sensors)


@mcp.tool()
def build_shear_table(aggregation: str = "mean") -> dict:
    """Build a 12x24 power-law shear lookup table using mean, median, or Windographer MoMM aggregation."""
    return _build_shear_table(session, aggregation)


@mcp.tool()
def build_roughness_table(aggregation: str = "mean") -> dict:
    """Build a 12x24 roughness lookup table in log-space per IEC logarithmic profile practice."""
    return _build_roughness_table(session, aggregation)


@mcp.tool()
def build_sector_shear_tables(direction_sensor: str, num_sectors: int = 12, aggregation: str = "mean") -> dict:
    """Build direction-sector-specific 12x24 shear tables using IEC directional binning and chosen aggregation."""
    return _build_sector_shear_tables(session, direction_sensor, num_sectors, aggregation)


@mcp.tool()
def build_aggr_momm_shear_table(height_sensors: str) -> dict:
    """Build an aggregate MoMM shear table by deriving alpha from per-height Windographer MoMM wind tables."""
    return _build_aggr_momm_shear_table(session, height_sensors)
