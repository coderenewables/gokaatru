"""validators — Shared validation helpers for Phase 1 data handling.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import pandas as pd


def validate_dataframe_has_columns(df: pd.DataFrame, required: list[str]) -> None:
    """Raise on missing columns per the GoKaatru Phase 1 data validation contract."""
    missing = [column for column in required if column not in df.columns]
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"Missing required columns: {missing_text}")


def validate_positive(value: float, name: str) -> None:
    """Raise on non-positive numeric inputs per IEC-style input validation practice."""
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")


def validate_timestamp_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a DatetimeIndex exists using the Phase 1 Timestamp-column convention."""
    if isinstance(df.index, pd.DatetimeIndex):
        return df.sort_index()
    if "Timestamp" not in df.columns:
        raise ValueError("DataFrame must have a DatetimeIndex or a 'Timestamp' column")
    result = df.copy()
    parsed = pd.to_datetime(result["Timestamp"], errors="coerce")
    if parsed.isna().all():
        raise ValueError("'Timestamp' column could not be parsed as datetimes")
    result = result.loc[parsed.notna()].copy()
    result.index = pd.DatetimeIndex(parsed.loc[parsed.notna()])
    return result.drop(columns=["Timestamp"]).sort_index()


def detect_timestep_minutes(df: pd.DataFrame) -> int:
    """Infer the modal timestamp interval in minutes from a DatetimeIndex per Phase 1 rules."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Timestep detection requires a DatetimeIndex")
    deltas = df.index.to_series().sort_values().diff().dropna()
    minutes = deltas.dt.total_seconds().div(60)
    positive = minutes[minutes > 0]
    if positive.empty:
        raise ValueError("Could not infer timestep from fewer than two valid timestamps")
    return int(round(float(positive.mode().iloc[0])))
