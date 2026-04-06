"""momm — Mean of Monthly Means utilities.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MEAN_DAYS_IN_MONTH: dict[int, float] = {
    1: 31,
    2: 28.24,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}


def _infer_samples_per_hour(timestamp_index: pd.DatetimeIndex) -> float:
    """Infer samples per hour from modal timestamp spacing per Windographer TR6 MoMM practice."""
    sorted_values = timestamp_index.sort_values().to_numpy(dtype="datetime64[ns]").astype("int64")
    nanoseconds = np.diff(sorted_values)
    positive = nanoseconds[nanoseconds > 0]
    if positive.size == 0:
        return 1.0
    seconds = positive / 1_000_000_000.0
    mode_seconds = float(pd.Series(seconds).mode().iloc[0])
    return max(1.0, 3600.0 / mode_seconds)


def compute_weighted_momm_table(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Build a Windographer TR6 month-hour MoMM table using completeness- and month-length weighting."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("MoMM requires a DatetimeIndex")
    if value_col not in df.columns:
        raise ValueError(f"Column '{value_col}' not found in DataFrame")

    working = df[[value_col]].copy()
    timestamp_index = pd.DatetimeIndex(working.index)
    working["year"] = timestamp_index.year
    working["month"] = timestamp_index.month
    working["hour"] = timestamp_index.hour
    working["days_in_month"] = timestamp_index.days_in_month
    samples_per_hour = _infer_samples_per_hour(timestamp_index)

    grouped = working.groupby(["year", "month", "hour"], observed=False)
    mean_values = grouped[value_col].mean()
    valid_counts = grouped[value_col].count().astype(float)
    actual_days = grouped["days_in_month"].first().astype(float)
    expected_counts = actual_days * samples_per_hour
    completeness = (valid_counts / expected_counts).replace([np.inf, -np.inf], np.nan)
    month_weights = pd.Series(completeness.index.get_level_values("month"), index=completeness.index).map(
        MEAN_DAYS_IN_MONTH
    )

    numerator = (mean_values * completeness * month_weights).groupby(level=["month", "hour"]).sum(min_count=1)
    denominator = (completeness * month_weights).groupby(level=["month", "hour"]).sum(min_count=1)
    weighted = (numerator / denominator).replace([np.inf, -np.inf], np.nan)
    table = weighted.unstack(level="hour")
    return table.reindex(index=range(1, 13), columns=range(24))
