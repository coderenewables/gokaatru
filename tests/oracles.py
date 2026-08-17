"""oracles — analytic ground-truth generators for the logic audit.

Step 1 of the logic audit. Every generator here produces data whose correct
answer is known in closed form, so a tool can be checked against physics rather
than against its own previous output. Regression tests pin behaviour; these pin
*correctness*.

Nothing in this module imports from ``server``: an oracle that shares code with
the thing it verifies is not an oracle.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VON_KARMAN = 0.4

# Standard sea-level atmosphere (ISA / ICAO), the anchor for density checks.
ISA_PRESSURE_PA = 101325.0
ISA_TEMPERATURE_K = 288.15
ISA_DRY_DENSITY = 1.225  # kg/m3


def power_law_profile(heights_m: np.ndarray, v_ref: float, h_ref: float, alpha: float) -> np.ndarray:
    """Return exact power-law speeds V(z) = v_ref * (z / h_ref) ** alpha."""
    heights = np.asarray(heights_m, dtype=float)
    return v_ref * (heights / h_ref) ** alpha


def log_law_profile(heights_m: np.ndarray, z0_m: float, ustar: float = 0.35) -> np.ndarray:
    """Return exact neutral log-law speeds V(z) = (ustar / kappa) * ln(z / z0)."""
    heights = np.asarray(heights_m, dtype=float)
    return (ustar / VON_KARMAN) * np.log(heights / z0_m)


def dry_air_density(pressure_pa: float, temperature_k: float) -> float:
    """Return dry-air density from the ideal gas law — the upper bound on moist density."""
    return pressure_pa / (287.05 * temperature_k)


def magnus_saturation_vapour_pressure_pa(temperature_c: float) -> float:
    """Return saturation vapour pressure over water (Magnus/Tetens, hPa form scaled to Pa).

    Independent restatement of the relation the tool under test uses, so a
    transcription error in either one shows up as a mismatch.
    """
    return 100.0 * 6.1078 * 10.0 ** (7.5 * temperature_c / (237.3 + temperature_c))


def moist_air_density(pressure_pa: float, temperature_k: float, dewpoint_k: float) -> float:
    """Return moist-air density by partial pressures, computed independently of the server."""
    vapour_pa = magnus_saturation_vapour_pressure_pa(dewpoint_k - 273.15)
    return (pressure_pa - vapour_pa) / (287.05 * temperature_k) + vapour_pa / (461.5 * temperature_k)


def timestamp_index(
    start: str,
    periods: int,
    step_minutes: int = 10,
    tz: str | None = "UTC",
) -> pd.DatetimeIndex:
    """Return a regular DatetimeIndex at a fixed cadence, UTC-aware by default."""
    return pd.date_range(start, periods=periods, freq=f"{step_minutes}min", tz=tz)


def weibull_series(
    index: pd.DatetimeIndex,
    scale_a: float,
    shape_k: float,
    seed: int = 1234,
) -> pd.Series:
    """Return exact Weibull(A, k) draws — the fit under test must recover A and k."""
    rng = np.random.default_rng(seed)
    return pd.Series(scale_a * rng.weibull(shape_k, len(index)), index=index)


def diurnal_series(
    index: pd.DatetimeIndex,
    mean: float = 7.0,
    amplitude: float = 2.0,
    peak_hour_local: int = 14,
    utc_offset_hours: float = 0.0,
) -> pd.Series:
    """Return a sinusoidal series peaking at ``peak_hour_local`` in *local* time.

    ``utc_offset_hours`` is the site's offset from UTC. The index is UTC, so the
    peak lands at ``peak_hour_local - utc_offset_hours`` in index hours. Any tool
    that reports the peak at the UTC hour is binning on the wrong clock.
    """
    hours_utc = index.hour + index.minute / 60.0
    local_hours = hours_utc + utc_offset_hours
    phase = 2.0 * np.pi * (local_hours - peak_hour_local) / 24.0
    return pd.Series(mean + amplitude * np.cos(phase), index=index)


def linear_pair(
    index: pd.DatetimeIndex,
    slope: float,
    intercept: float,
    noise_sigma: float = 0.0,
    reference_mean: float = 8.0,
    reference_sigma: float = 2.5,
    seed: int = 99,
) -> pd.DataFrame:
    """Return (reference, target) with target = slope * reference + intercept + noise.

    Least-squares must recover ``slope`` and ``intercept``; with ``noise_sigma``
    on the target only, total least squares is biased and ordinary least squares
    is not, which is how the two are told apart.
    """
    rng = np.random.default_rng(seed)
    reference = rng.normal(reference_mean, reference_sigma, len(index))
    reference = np.clip(reference, 0.1, None)
    target = slope * reference + intercept
    if noise_sigma > 0:
        target = target + rng.normal(0.0, noise_sigma, len(index))
    return pd.DataFrame({"reference": reference, "target": target}, index=index)


def directional_series(index: pd.DatetimeIndex, directions_deg: list[float]) -> pd.Series:
    """Return a direction series cycling through ``directions_deg`` for circular-stats checks."""
    repeated = np.resize(np.asarray(directions_deg, dtype=float), len(index))
    return pd.Series(repeated, index=index)


# --- Energy conversion ------------------------------------------------------
# GoKaatru computes no AEP, so Step 10 supplies its own turbine. A representative
# modern onshore machine: 4.2 MW, 150 m rotor (238 W/m2 specific power), IEC IIA.
# Stated explicitly because the AEP sensitivity factor is turbine-specific.
WTG_RATED_KW = 4200.0
WTG_CUT_IN_MPS = 3.0
WTG_CUT_OUT_MPS = 25.0
HOURS_PER_YEAR = 8766.0  # 365.25 days, leap-averaged

_PC_SPEED = np.arange(0.0, 31.0, 1.0)
_PC_POWER = np.array(
    [
        0, 0, 0, 60, 250, 570, 1000, 1600, 2300, 3050, 3700, 4100, 4200, 4200,
        4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200,
        0, 0, 0, 0, 0,
    ],
    dtype=float,
)


def turbine_power_kw(speed: np.ndarray) -> np.ndarray:
    """Interpolate the power curve linearly in speed, with hard cut-in and cut-out.

    Linear interpolation on the published bins is the IEC 61400-12-1 convention; a
    spline would overshoot near the knee and around rated power.
    """
    values = np.interp(speed, _PC_SPEED, _PC_POWER, left=0.0, right=0.0)
    outside = (speed < WTG_CUT_IN_MPS) | (speed > WTG_CUT_OUT_MPS)
    return np.where(outside, 0.0, values)


def gross_aep_mwh(speed: np.ndarray) -> float:
    """Gross single-turbine AEP: mean power over the series times hours per year."""
    valid = np.asarray(speed, dtype=float)
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        raise ValueError("AEP requires at least one finite wind-speed value")
    return float(np.mean(turbine_power_kw(valid)) / 1000.0 * HOURS_PER_YEAR)


def energy_sensitivity_factor(speed: np.ndarray, epsilon: float = 0.01) -> float:
    """Return S = d(ln AEP) / d(ln U), the elasticity of energy to wind speed.

    Computed by central difference on the actual long-term series rather than from
    a rule of thumb, because S depends on where the site's speed distribution sits
    against the power curve: it approaches 3 in the cubic region and falls towards
    0 once most hours are at rated power.
    """
    if not 0.0 < epsilon < 0.5:
        raise ValueError("epsilon must be a small positive fraction")
    series = np.asarray(speed, dtype=float)
    upper = gross_aep_mwh(series * (1.0 + epsilon))
    lower = gross_aep_mwh(series * (1.0 - epsilon))
    return float((np.log(upper) - np.log(lower)) / (np.log1p(epsilon) - np.log1p(-epsilon)))


def exceedance_factor(uncertainty_pct: float, level: str) -> float:
    """Return the normal-quantile exceedance factor for P75/P90/P99 on any basis."""
    quantiles = {"p50": 0.0, "p75": 0.674, "p90": 1.282, "p99": 2.326}
    if level not in quantiles:
        raise ValueError(f"level must be one of {sorted(quantiles)}, got '{level}'")
    return 1.0 - quantiles[level] * uncertainty_pct / 100.0


def complete_year_index(year: int = 2021, step_minutes: int = 10, tz: str | None = "UTC") -> pd.DatetimeIndex:
    """Return every timestamp in one calendar year at a fixed cadence, with no gaps."""
    return pd.date_range(
        f"{year}-01-01 00:00",
        f"{year}-12-31 23:59",
        freq=f"{step_minutes}min",
        tz=tz,
    )
