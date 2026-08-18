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


# F-07.  IEA Task 43 permits interval-start, -end and -centre labelling and GoKaatru had
# never declared which it assumes.  Reanalysis references are instantaneous, so a mismatch
# is a systematic half-interval offset in every long-term correction rather than noise.
# The convention is a property of the logger and cannot be inferred from the data, so it is
# declared at ingest and overridable per dataset via ``runconfig["timestamp_label"]``.
TIMESTAMP_LABEL_CONVENTION = "interval_start"
TIMESTAMP_LABEL_CHOICES = ("interval_start", "interval_end", "interval_centre")
TIMESTAMP_LABEL_NOTE = (
    "Timestamps are treated as the START of each averaging interval. IEA Task 43 permits "
    "interval-start, interval-end and interval-centre labelling and the file does not say "
    "which it uses, so this is an assumption, not a measurement. Reanalysis references are "
    "instantaneous, so a mismatch shifts the measured series against the reference by half "
    "an interval - five minutes on 10-minute data - in every long-term correction. Set "
    "timestamp_label on the run configuration if the logger labelled interval ends."
)
