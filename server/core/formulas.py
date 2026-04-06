"""formulas — IEC and extrapolation formula helpers.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import math

import numpy as np

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


def power_law_extrapolate(v_ref: float, h_ref: float, h_target: float, alpha: float) -> float:
    """Compute V(h_target) = V(h_ref) * (h_target / h_ref)^alpha per IEC 61400-12-1 Section B.2."""
    if v_ref < 0 or h_ref <= 0 or h_target <= 0:
        raise ValueError("Power law requires non-negative speed and positive reference and target heights")
    return float(v_ref * (h_target / h_ref) ** alpha)


def log_law_extrapolate(v_ref: float, h_ref: float, h_target: float, z0: float) -> float:
    """Compute V(h_target) from the logarithmic wind profile per IEC 61400-12-1 Section B.3."""
    if v_ref < 0 or h_ref <= 0 or h_target <= 0 or z0 <= 0:
        raise ValueError("Log law requires non-negative speed and positive heights and roughness length")
    if h_ref <= z0 or h_target <= z0:
        raise ValueError(f"Log law requires heights greater than z0, got h_ref={h_ref}, h_target={h_target}, z0={z0}")
    return float(v_ref * math.log(h_target / z0) / math.log(h_ref / z0))


def shear_from_two_heights(v1: float, h1: float, v2: float, h2: float) -> float:
    """Compute power-law shear alpha = ln(v2/v1) / ln(h2/h1) per IEC 61400-12-1 Section B.2."""
    if min(v1, v2) <= 0 or min(h1, h2) <= 0 or h1 == h2:
        return float(np.nan)
    return float(math.log(v2 / v1) / math.log(h2 / h1))


def roughness_from_two_heights(v1: float, h1: float, v2: float, h2: float) -> float:
    """Compute roughness length from two heights using the IEC logarithmic profile relationship."""
    if min(v1, v2) <= 0 or min(h1, h2) <= 0 or h1 == h2 or v1 == v2:
        return float(np.nan)
    exponent = (v2 * math.log(h1) - v1 * math.log(h2)) / (v2 - v1)
    return float(math.exp(exponent))


def air_density_iec(pressure_pa: float, temperature_k: float, dewpoint_k: float) -> float:
    """Compute moist-air density from pressure and dew point per IEC 61400-12-1 Section A.5."""
    if pressure_pa <= 0 or temperature_k <= 0 or dewpoint_k <= 0:
        raise ValueError("Air density requires positive pressure, temperature, and dew point")
    dewpoint_c = dewpoint_k - 273.15
    vapor_pressure_hpa = 6.1078 * 10 ** (7.5 * dewpoint_c / (237.3 + dewpoint_c))
    vapor_pressure_pa = vapor_pressure_hpa * 100.0
    dry_air = (pressure_pa - vapor_pressure_pa) / 287.05
    water_vapor = vapor_pressure_pa / 461.5
    return float((dry_air + water_vapor) / temperature_k)
