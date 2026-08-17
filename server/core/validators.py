"""validators — Shared validation helpers for Phase 1 data handling.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# Mapping of sensor_mapping field names to their physical sensor type.  Lives in
# core rather than tools/data_io so modules can share it without dragging in
# server.main and creating an import cycle.
SENSOR_FIELDS = {
    "speed_col": "wind_speed",
    "dir_col": "wind_direction",
    "temp_col": "temperature",
    "pressure_col": "pressure",
    "humidity_col": "humidity",
}


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
    parsed = pd.to_datetime(result["Timestamp"], errors="coerce", utc=True)
    if parsed.isna().all():
        raise ValueError("'Timestamp' column could not be parsed as datetimes")
    result = result.loc[parsed.notna()].copy()
    result.index = pd.DatetimeIndex(parsed.loc[parsed.notna()])
    return result.drop(columns=["Timestamp"]).sort_index()


def to_utc_index(obj: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Return ``obj`` with a tz-aware UTC DatetimeIndex, leaving values untouched.

    Internal storage is tz-aware UTC (D8), but not every ingest path gets there:
    file ingest localizes from the datamodel timezone, BrightHub import strips tz,
    and directly-seeded session state is naive.  Joining a naive index against an
    aware one yields an empty frame rather than an error, so every module that
    inner-joins measured, reference and LTC-result series funnels its index
    through this helper first.

    A naive index is assumed to already be UTC — the localization decision belongs
    to ingest, not to the join.
    """
    if not isinstance(obj.index, pd.DatetimeIndex):
        return obj
    if obj.index.tz is None:
        result = obj.copy()
        result.index = obj.index.tz_localize("UTC")
        return result
    if str(obj.index.tz) == "UTC":
        return obj
    result = obj.copy()
    result.index = obj.index.tz_convert("UTC")
    return result


_ACCEPTED_TIMESTEPS = {1, 2, 5, 10, 15, 30, 60}


def detect_timestep_minutes(df: pd.DataFrame) -> int:
    """Infer the modal timestamp interval in minutes from a DatetimeIndex per Phase 1 rules."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("Timestep detection requires a DatetimeIndex")
    deltas = df.index.to_series().sort_values().diff().dropna()
    minutes = deltas.dt.total_seconds().div(60)
    positive = minutes[minutes > 0]
    if positive.empty:
        raise ValueError("Could not infer timestep from fewer than two valid timestamps")
    inferred = int(round(float(positive.mode().iloc[0])))
    if inferred < 1 or inferred not in _ACCEPTED_TIMESTEPS:
        raise ValueError(
            f"Inferred timestep of {inferred} minutes is not a supported cadence "
            f"(expected one of {sorted(_ACCEPTED_TIMESTEPS)} minutes). "
            "This usually means the timestamp column was misidentified — "
            "check that the time column parses as dates."
        )
    return inferred


def rolling_median_mad_spike_mask(series: pd.Series, window: int = 11, sigma: float = 4.0) -> pd.Series:
    """Return boolean mask identifying spikes using robust median/MAD outlier detection.

    Median/MAD is not biased by the outlier itself, unlike mean/std where the
    spike inflates its own window statistics.  The 1.4826 scaling factor makes MAD
    consistent with standard deviation for Gaussian data.

    Constant stretches (MAD == 0) produce a False mask — stuck-sensor detection
    is handled separately by the ``stuck_sensor`` cleaning rule.

    Both ``cleaning.py`` and ``diagnostics.py`` call this shared helper so the
    spike algorithm cannot silently diverge between the filter and the QC panel.
    """
    median = series.rolling(window=window, center=True, min_periods=2).median()
    mad = (series - median).abs().rolling(window=window, center=True, min_periods=2).median() * 1.4826
    # Constant stretches → MAD = 0 → avoid division by zero → mask is all False
    mad = mad.replace(0.0, np.nan)
    return (series - median).abs() > sigma * mad
