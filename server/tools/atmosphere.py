"""Measured atmospheric-condition summaries for the Sensor Overview."""
from __future__ import annotations

import pandas as pd

from server.core.formulas import moist_air_density, saturation_vapour_pressure_pa
from server.main import mcp
from server.state.session import SessionState, session

# ISA sea-level density, the reference the density correction factor is quoted against.
ISA_SEA_LEVEL_DENSITY = 1.225


def _require_frame(state: SessionState) -> pd.DataFrame:
    """Return the loaded measured frame needed for atmospheric analysis."""
    if state.timeseries_df is None:
        raise ValueError("Timeseries data is not loaded")
    return state.timeseries_df


def _find_sensor(state: SessionState, sensor_type: str, requested: str = "") -> str:
    """Resolve an explicit sensor or the first valid inventory/mapping sensor of the requested type."""
    frame = _require_frame(state)
    if requested:
        if requested not in frame.columns:
            raise ValueError(f"Sensor column '{requested}' not found in loaded timeseries")
        return requested
    inventory_match = next(
        (
            name for name, metadata in state.sensor_inventory.items()
            if metadata.get("sensor_type") == sensor_type and name in frame.columns
        ),
        None,
    )
    if inventory_match:
        return inventory_match
    field_name = {"temperature": "temp_col", "pressure": "pressure_col", "humidity": "humidity_col"}[sensor_type]
    mapped_match = next((mapping.get(field_name) for mapping in state.sensor_mapping.values() if mapping.get(field_name) in frame.columns), None)
    if isinstance(mapped_match, str):
        return mapped_match
    raise ValueError(f"No {sensor_type} sensor is available in the loaded dataset")


def _temperature_kelvin(values: pd.Series) -> pd.Series:
    """Normalize a measured temperature series supplied in degC or K to Kelvin."""
    valid = values.dropna()
    if valid.empty:
        return values.astype(float)
    return values.astype(float) + 273.15 if float(valid.median()) < 170.0 else values.astype(float)


def _pressure_pa(values: pd.Series) -> pd.Series:
    """Normalize a measured pressure series supplied in hPa or Pa to Pascals."""
    valid = values.dropna()
    if valid.empty:
        return values.astype(float)
    return values.astype(float) * 100.0 if float(valid.median()) < 2000.0 else values.astype(float)


def _density_series(temperature: pd.Series, pressure: pd.Series, humidity: pd.Series | None) -> pd.Series:
    """Compute moist-air density from measured temperature, pressure, and optional relative humidity.

    With no humidity sensor the air is treated as dry.  That is the only option
    available, but it is not neutral: it overstates density by roughly 0.5% over a
    temperate year and 0.7% over warm hours, and power density scales linearly with
    density.  ``_compute_atmospheric_conditions`` reports the assumption so the bias
    is attributable.
    """
    temperature_k = _temperature_kelvin(temperature)
    pressure_pa = _pressure_pa(pressure)
    valid_temperature = temperature_k.between(180.0, 340.0)
    valid_pressure = pressure_pa.between(50_000.0, 120_000.0)
    if humidity is None:
        vapor_pressure = pd.Series(0.0, index=temperature.index)
        valid_humidity = pd.Series(True, index=temperature.index)
    else:
        relative_humidity = humidity.astype(float)
        valid_humidity = relative_humidity.between(0.0, 100.0)
        relative_humidity = relative_humidity.where(valid_humidity)
        # Shared with core.formulas so this module cannot drift from the IEC path.
        saturation_pressure = saturation_vapour_pressure_pa(temperature_k - 273.15)
        vapor_pressure = saturation_pressure * relative_humidity / 100.0
    density = moist_air_density(pressure_pa, temperature_k, vapor_pressure)
    return density.where(valid_temperature & valid_pressure & valid_humidity).rename("air_density_kg_m3")


def _clean_atmospheric_series(values: pd.Series, sensor_type: str) -> pd.Series:
    """Remove common invalid sentinel values using broad physical ranges in the recorded unit."""
    numeric = values.astype(float)
    if sensor_type == "temperature":
        kelvin = _temperature_kelvin(numeric)
        return numeric.where(kelvin.between(180.0, 340.0))
    if sensor_type == "pressure":
        pascal = _pressure_pa(numeric)
        return numeric.where(pascal.between(50_000.0, 120_000.0))
    if sensor_type == "humidity":
        return numeric.where(numeric.between(0.0, 100.0))
    return numeric


def _series_summary(values: pd.Series) -> dict[str, object]:
    """Summarize a measured or derived atmospheric series and its monthly/diurnal climatology."""
    valid = values.dropna()
    if valid.empty:
        raise ValueError("No valid atmospheric observations are available")
    monthly = valid.groupby(valid.index.month).mean().reindex(range(1, 13))
    diurnal = valid.groupby(valid.index.hour).mean().reindex(range(24))
    return {
        "record_count": int(valid.count()),
        "mean": float(valid.mean()),
        "min": float(valid.min()),
        "max": float(valid.max()),
        "std": float(valid.std(ddof=0)),
        "monthly_means": [float(value) if pd.notna(value) else None for value in monthly],
        "diurnal_means": [float(value) if pd.notna(value) else None for value in diurnal],
    }


def _atmospheric_series(
    state: SessionState,
    temperature_sensor: str = "",
    pressure_sensor: str = "",
    humidity_sensor: str = "",
) -> tuple[pd.Series, str, str, str | None]:
    """Resolve inputs and calculate the session's measured air-density series."""
    frame = _require_frame(state)
    temperature_name = _find_sensor(state, "temperature", temperature_sensor)
    pressure_name = _find_sensor(state, "pressure", pressure_sensor)
    humidity_name: str | None = None
    if humidity_sensor:
        humidity_name = _find_sensor(state, "humidity", humidity_sensor)
    else:
        try:
            humidity_name = _find_sensor(state, "humidity")
        except ValueError:
            humidity_name = None
    humidity = frame[humidity_name] if humidity_name else None
    density = _density_series(frame[temperature_name], frame[pressure_name], humidity)
    return density, temperature_name, pressure_name, humidity_name


def _compute_atmospheric_conditions(
    state: SessionState,
    temperature_sensor: str = "",
    pressure_sensor: str = "",
    humidity_sensor: str = "",
) -> dict:
    """Return measured atmospheric and density summaries for the Sensor Overview."""
    frame = _require_frame(state)
    density, temperature_name, pressure_name, humidity_name = _atmospheric_series(
        state,
        temperature_sensor,
        pressure_sensor,
        humidity_sensor,
    )
    result: dict[str, object] = {
        "temperature_sensor": temperature_name,
        "pressure_sensor": pressure_name,
        "humidity_sensor": humidity_name,
        "temperature": _series_summary(_clean_atmospheric_series(frame[temperature_name], "temperature")),
        "pressure": _series_summary(_clean_atmospheric_series(frame[pressure_name], "pressure")),
        "air_density": {
            **_series_summary(density),
            "density_correction_factor": float(density.dropna().mean() / ISA_SEA_LEVEL_DENSITY),
            "humidity_basis": "measured" if humidity_name else "assumed_dry",
            "height_basis": "pressure_sensor_height",
        },
        "humidity": _series_summary(_clean_atmospheric_series(frame[humidity_name], "humidity")) if humidity_name else None,
    }
    if humidity_name is None:
        result["air_density"]["warning"] = (
            "No humidity sensor was available, so the air is treated as dry. That overstates "
            "density by roughly 0.5% over a temperate year and 0.7% over warm hours, and power "
            "density scales linearly with density."
        )
    return result


@mcp.tool()
def compute_atmospheric_conditions(
    temperature_sensor: str = "",
    pressure_sensor: str = "",
    humidity_sensor: str = "",
) -> dict:
    """Summarize measured temperature, pressure, humidity, and derived moist-air density."""
    return _compute_atmospheric_conditions(session, temperature_sensor, pressure_sensor, humidity_sensor)