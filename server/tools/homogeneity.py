"""homogeneity — Phase 4 MCP tools for Pettitt homogeneity screening of reanalysis datasets.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.main import mcp
from server.state.session import SessionState, session


def _wind_speed_column(frame: pd.DataFrame) -> str:
    """Pick the first available wind-speed column using the Phase 3 ERA5 naming conventions."""
    for column in ["Spd_100m_hub", "Spd_100m", "corrected_wind_speed", "Ensemble_Speed"]:
        if column in frame.columns:
            return column
    raise ValueError("No wind-speed column found for homogeneity analysis")


def _to_indexed_frame(frame_like: object) -> pd.DataFrame:
    """Normalize stored session payloads to a datetime-indexed dataframe for time-based statistics."""
    frame = pd.DataFrame(frame_like).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.DatetimeIndex(frame.index)
    return frame.sort_index()


def _pettitt_test(values: np.ndarray) -> tuple[int, float]:
    """Compute Pettitt's change-point statistic with $p \approx 2 \\exp(-6K^2/(n^3+n^2))$."""
    n_values = len(values)
    if n_values < 3:
        return 0, 1.0
    ranks = pd.Series(values).rank(method="average").to_numpy(dtype=float)
    indices = np.arange(1, n_values + 1, dtype=float)
    statistic = 2.0 * np.cumsum(ranks) - indices * (n_values + 1)
    change_index = int(np.argmax(np.abs(statistic)))
    k_value = float(np.max(np.abs(statistic)))
    p_value = float(min(1.0, 2.0 * np.exp((-6.0 * k_value**2) / (n_values**3 + n_values**2))))
    return change_index, p_value


def _trend_per_year(series: pd.Series) -> float:
    """Estimate linear trend per year from annual or monthly aggregates using least squares."""
    if len(series) < 2:
        return 0.0
    elapsed_years = (series.index - series.index[0]).days.to_numpy(dtype=float) / 365.25
    values = series.to_numpy(dtype=float)
    centered_x = elapsed_years - float(np.mean(elapsed_years))
    centered_y = values - float(np.mean(values))
    denominator = float(np.sum(centered_x**2))
    if denominator <= 1e-12:
        return 0.0
    return float(np.sum(centered_x * centered_y) / denominator)


def _recommended_start_year(series: pd.Series) -> int:
    """Return the earliest suffix start year whose Pettitt test no longer indicates non-homogeneity at $p < 0.01$."""
    years = sorted(series.index.year.unique().tolist())
    for year in years:
        subset = series[series.index.year >= year]
        if len(subset) < 3:
            continue
        _, p_value = _pettitt_test(subset.to_numpy(dtype=float))
        if p_value >= 0.01:
            return int(year)
    return int(years[-1])


def _analyze_homogeneity(state: SessionState, method: str = "annual") -> dict:
    """Run Pettitt homogeneity screening on ERA5 node series aggregated annually or monthly."""
    if method not in {"annual", "monthly"}:
        raise ValueError(f"method must be 'annual' or 'monthly', got '{method}'")
    if not state.era5_data:
        raise ValueError("At least one ERA5 dataset is required for homogeneity analysis")
    datasets: list[dict[str, object]] = []
    for name, frame_like in sorted(state.era5_data.items()):
        frame = _to_indexed_frame(frame_like)
        speed_col = _wind_speed_column(frame)
        frequency = "YE" if method == "annual" else "ME"
        aggregated = frame[speed_col].resample(frequency).mean().dropna()
        if len(aggregated) < 3:
            continue
        _, p_value = _pettitt_test(aggregated.to_numpy(dtype=float))
        datasets.append(
            {
                "name": f"ERA5_{name}",
                "recommended_start_year": _recommended_start_year(aggregated),
                "pettitt_p_value": p_value,
                "trend_per_year": _trend_per_year(aggregated),
            }
        )
    return {"datasets": datasets}


def _apply_homogeneity_cutoff(state: SessionState, cutoff_year: int) -> dict:
    """Trim interpolated ERA5 data to a recommended homogeneous period start year."""
    if state.era5_interpolated_df is None:
        raise ValueError("Interpolated ERA5 dataframe is not available")
    frame = _to_indexed_frame(state.era5_interpolated_df)
    rows_before = int(len(frame))
    trimmed = frame[frame.index.year >= cutoff_year].copy()
    state.era5_interpolated_df = trimmed
    return {
        "status": "ok",
        "rows_before": rows_before,
        "rows_after": int(len(trimmed)),
        "cutoff_year": int(cutoff_year),
    }


@mcp.tool()
def analyze_homogeneity(method: str = "annual") -> dict:
    """Run Pettitt homogeneity screening on ERA5 node series aggregated annually or monthly."""
    return _analyze_homogeneity(session, method)


@mcp.tool()
def apply_homogeneity_cutoff(cutoff_year: int) -> dict:
    """Trim interpolated ERA5 data to a recommended homogeneous period start year."""
    return _apply_homogeneity_cutoff(session, cutoff_year)
