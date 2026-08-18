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


# Physically plausible roughness-length band (F-05).  The ceiling used to be 1.5 m, which
# truncates forest and dense-urban terrain: WAsP roughness class 3 and above reach 1.5-2.0 m
# and city centres go higher still.  The clamp *raises* log-law hub-height speed, so a
# ceiling that bites is not a conservative backstop - it makes the site look windier than
# the profile says.  2.0 m covers the standard classes; anything above that is far more
# likely a bad fit than real terrain, so the clamp still exists and still reports itself.
ROUGHNESS_MIN_M = 1e-6
ROUGHNESS_MAX_M = 2.0


def roughness_from_two_heights(v1: float, h1: float, v2: float, h2: float) -> tuple[float, bool]:
    """Compute roughness length from two heights using the IEC logarithmic profile relationship.

    Returns (z0, was_clamped).  The raw z0 is clamped to the physically plausible range
    ``[ROUGHNESS_MIN_M, ROUGHNESS_MAX_M]`` metres, matching the guard applied in
    ``_fit_rowwise_log_profile`` (shear.py) and the extrapolation tool.
    """
    if min(v1, v2) <= 0 or min(h1, h2) <= 0 or h1 == h2 or v1 == v2:
        return float(np.nan), False
    exponent = (v2 * math.log(h1) - v1 * math.log(h2)) / (v2 - v1)
    z0 = float(math.exp(exponent))
    was_clamped = z0 < ROUGHNESS_MIN_M or z0 > ROUGHNESS_MAX_M
    z0 = float(np.clip(z0, ROUGHNESS_MIN_M, ROUGHNESS_MAX_M))
    return z0, was_clamped


DRY_AIR_GAS_CONSTANT = 287.05  # J/(kg K)
WATER_VAPOUR_GAS_CONSTANT = 461.5  # J/(kg K)


def saturation_vapour_pressure_pa(temperature_c):
    """Saturation vapour pressure over water, Magnus form, in Pascals.

    Array-safe, and the single definition of this relation in the codebase: it was
    previously written out three times (here, in the vectorised density tool, and in
    the measured-atmosphere module) with two different coefficient sets, which could
    drift independently.  Checked against Buck (1996) from -20 to +45 degC: within
    0.8% at -20 degC and 0.15% above freezing, which is worth at most 0.004% of
    density.

    Uses the over-water coefficients at all temperatures.  Below freezing the true
    saturation pressure over ice is lower — up to 28% lower at -25 degC — but because
    vapour is such a small fraction of total pressure when it is that cold, the
    resulting density error is under 0.011%.  Not worth a phase switch.
    """
    return 100.0 * 6.1078 * 10 ** (7.5 * temperature_c / (237.3 + temperature_c))


def moist_air_density(pressure_pa, temperature_k, vapour_pressure_pa):
    """Moist-air density by partial pressures, per IEC 61400-12-1 Section A.5. Array-safe."""
    dry_air = (pressure_pa - vapour_pressure_pa) / DRY_AIR_GAS_CONSTANT
    water_vapour = vapour_pressure_pa / WATER_VAPOUR_GAS_CONSTANT
    return (dry_air + water_vapour) / temperature_k


STANDARD_GRAVITY = 9.80665  # m/s2


def adjust_density_to_height(density, temperature_k, from_height_m: float, to_height_m: float):
    """Scale a density from the height it was measured at to another height. Array-safe.

    Pressure falls with height as ``p(z2) = p(z1) * exp(-g*dz/(R*T))`` and, at a fixed
    temperature, density follows pressure. Air thins by roughly 1.2% per 100 m, so using a
    density derived from a 2 m pressure sensor at a 150 m hub overstates it by about 1.8% —
    and power density scales linearly with density, so that is a direct overstatement of
    the resource.

    The isothermal form is used deliberately: the exact hypsometric equation needs the mean
    temperature of the layer, and over the 100-200 m that separates a pressure sensor from
    a hub the difference between that and the measured temperature is far below the 1.2%
    the correction itself is worth.
    """
    delta_z = float(to_height_m) - float(from_height_m)
    return density * np.exp(-STANDARD_GRAVITY * delta_z / (DRY_AIR_GAS_CONSTANT * temperature_k))


def air_density_iec(
    pressure_pa: float, temperature_k: float, dewpoint_k: float
) -> tuple[float, bool]:
    """Compute moist-air density from pressure and dew point per IEC 61400-12-1 Section A.5.

    Returns (density, was_dewpoint_clamped).  When dewpoint exceeds
    temperature (sensor fault or supersaturation), dewpoint is clamped to
    temperature to prevent vapour pressure above saturation from distorting
    the density.
    """
    if pressure_pa <= 0 or temperature_k <= 0 or dewpoint_k <= 0:
        raise ValueError("Air density requires positive pressure, temperature, and dew point")
    was_clamped = dewpoint_k > temperature_k
    if was_clamped:
        dewpoint_k = temperature_k
    vapour_pressure_pa = saturation_vapour_pressure_pa(dewpoint_k - 273.15)
    return float(moist_air_density(pressure_pa, temperature_k, vapour_pressure_pa)), was_clamped
