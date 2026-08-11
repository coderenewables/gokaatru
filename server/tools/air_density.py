"""air_density — Phase 3 MCP tools for IEC moist-air density calculations.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import pandas as pd

from server.core.formulas import air_density_iec
from server.main import mcp
from server.state.session import session


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
    pressure = frame[pressure_col].to_numpy(dtype=float)
    temperature = frame[temperature_col].to_numpy(dtype=float)
    dewpoint = frame[dewpoint_col].to_numpy(dtype=float)

    # Clamp dewpoint to temperature (physical impossibility guard, matches air_density_iec)
    clamped_mask = dewpoint > temperature
    n_clamped = int(clamped_mask.sum())
    dewpoint = np.minimum(dewpoint, temperature)

    dewpoint_c = dewpoint - 273.15
    vapor_pressure_pa = 6.1078 * 10 ** (7.5 * dewpoint_c / (237.3 + dewpoint_c)) * 100.0
    density = ((pressure - vapor_pressure_pa) / 287.05 + vapor_pressure_pa / 461.5) / temperature
    frame["air_density_kg_m3"] = density
    valid = frame["air_density_kg_m3"].dropna()
    result: dict = {
        "status": "ok",
        "mean_density": float(valid.mean()),
        "min_density": float(valid.min()),
        "max_density": float(valid.max()),
        "record_count": int(valid.count()),
    }
    if n_clamped > 0:
        result["dewpoint_clamped_count"] = n_clamped
        result["warning"] = (
            f"{n_clamped} records had dewpoint > temperature; clamped to temperature "
            "before density calculation — check sensor calibration"
        )
    return result
