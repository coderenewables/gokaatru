"""air_density — Phase 3 MCP tools for IEC moist-air density calculations.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from server.core.formulas import air_density_iec, moist_air_density, saturation_vapour_pressure_pa
from server.main import mcp
from server.state.session import session

# Plausible physical bands, used to detect the unit a column is recorded in rather
# than assuming one.  The vectorised path previously assumed Kelvin and Pascals with
# no guard: measured temperature is stored in Celsius (the cleaning range_check bounds
# are -60..60 degC), so dividing by ~15 instead of ~288 overstated density about
# nineteenfold with nothing to reveal it.
_KELVIN_MIN, _KELVIN_MAX = 180.0, 340.0
_CELSIUS_MIN, _CELSIUS_MAX = -90.0, 60.0
_PASCAL_MIN, _PASCAL_MAX = 50_000.0, 120_000.0
_HECTOPASCAL_MIN, _HECTOPASCAL_MAX = 500.0, 1_200.0


def _to_kelvin(values: np.ndarray, label: str) -> tuple[np.ndarray, str]:
    """Return (kelvin, detected_unit), refusing a series that matches neither band."""
    median = float(np.nanmedian(values))
    if _KELVIN_MIN <= median <= _KELVIN_MAX:
        return values, "K"
    if _CELSIUS_MIN <= median <= _CELSIUS_MAX:
        return values + 273.15, "degC"
    raise ValueError(
        f"Column '{label}' has a median of {median:g}, which is neither a plausible "
        f"Kelvin ({_KELVIN_MIN:g}-{_KELVIN_MAX:g}) nor Celsius ({_CELSIUS_MIN:g}-{_CELSIUS_MAX:g}) "
        "temperature. Air density cannot be computed without knowing the unit."
    )


def _to_pascal(values: np.ndarray, label: str) -> tuple[np.ndarray, str]:
    """Return (pascals, detected_unit), refusing a series that matches neither band."""
    median = float(np.nanmedian(values))
    if _PASCAL_MIN <= median <= _PASCAL_MAX:
        return values, "Pa"
    if _HECTOPASCAL_MIN <= median <= _HECTOPASCAL_MAX:
        return values * 100.0, "hPa"
    raise ValueError(
        f"Column '{label}' has a median of {median:g}, which is neither a plausible "
        f"Pascal ({_PASCAL_MIN:g}-{_PASCAL_MAX:g}) nor hectoPascal "
        f"({_HECTOPASCAL_MIN:g}-{_HECTOPASCAL_MAX:g}) pressure. Air density cannot be "
        "computed without knowing the unit."
    )


def _source_frame(source: str) -> pd.DataFrame:
    """Resolve the requested air-density source dataframe from session state."""
    if source == "era5":
        if session.era5_interpolated_df is None:
            raise ValueError("ERA5 interpolated dataframe is not available")
        return session.era5_interpolated_df
    if source == "measured":
        if session.timeseries_df is None:
            raise ValueError("Measured timeseries dataframe is not available")
        return session.timeseries_df
    raise ValueError(f"source must be 'era5' or 'measured', got '{source}'")


@mcp.tool()
def compute_air_density(pressure_pa: float, temperature_k: float, dewpoint_k: float) -> dict:
    """Compute moist-air density from pressure and dew point per IEC 61400-12-1 Section A.5."""
    density, dewpoint_clamped = air_density_iec(pressure_pa, temperature_k, dewpoint_k)
    result = {
        "status": "ok",
        "pressure_pa": pressure_pa,
        "temperature_k": temperature_k,
        "dewpoint_k": dewpoint_k,
        "air_density_kg_m3": density,
    }
    if dewpoint_clamped:
        result["warning"] = (
            "dewpoint exceeded temperature and was clamped to temperature "
            f"({temperature_k:.1f} K); check sensor calibration"
        )
    return result


@mcp.tool()
def compute_air_density_timeseries(
    pressure_col: str,
    temperature_col: str,
    dewpoint_col: str,
    source: str = "era5",
) -> dict:
    """Compute an air-density timeseries from dataframe columns using the IEC moist-air density equation."""
    frame = _source_frame(source)
    missing = [column for column in [pressure_col, temperature_col, dewpoint_col] if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing air-density input columns: {', '.join(missing)}")

    # Detect the recorded unit rather than assuming it.  ERA5 delivers Kelvin and
    # Pascals; measured campaign data is stored in Celsius, and the two were previously
    # indistinguishable to this function.
    temperature, temperature_unit = _to_kelvin(frame[temperature_col].to_numpy(dtype=float), temperature_col)
    dewpoint, dewpoint_unit = _to_kelvin(frame[dewpoint_col].to_numpy(dtype=float), dewpoint_col)
    pressure, pressure_unit = _to_pascal(frame[pressure_col].to_numpy(dtype=float), pressure_col)

    # Clamp dewpoint to temperature (physical impossibility guard, matches air_density_iec).
    n_clamped = int(np.count_nonzero(dewpoint > temperature))
    dewpoint = np.minimum(dewpoint, temperature)

    # Shared with the scalar path so the two cannot drift apart.
    vapour_pressure_pa = saturation_vapour_pressure_pa(dewpoint - 273.15)
    density = moist_air_density(pressure, temperature, vapour_pressure_pa)
    frame["air_density_kg_m3"] = density
    valid = frame["air_density_kg_m3"].dropna()
    if valid.empty:
        raise ValueError("No valid air-density values could be computed from the selected columns")
    result: dict = {
        "status": "ok",
        "mean_density": float(valid.mean()),
        "min_density": float(valid.min()),
        "max_density": float(valid.max()),
        "record_count": int(valid.count()),
        "units_detected": {
            "temperature": temperature_unit,
            "dewpoint": dewpoint_unit,
            "pressure": pressure_unit,
        },
        # Density is valid at the height the pressure was measured, not at hub height.
        # No barometric correction is applied anywhere in the pipeline; see the note.
        "height_basis": "pressure_sensor_height",
        "height_note": (
            "Density applies at the pressure sensor's height. It is not corrected to hub "
            "height, where air is thinner by roughly 1.2% per 100 m of separation."
        ),
    }
    if n_clamped > 0:
        result["dewpoint_clamped_count"] = n_clamped
        result["warning"] = (
            f"{n_clamped} records had dewpoint > temperature; clamped to temperature "
            "before density calculation — check sensor calibration"
        )
    return result
