"""powercurve — generic turbine power curves and wind-speed-to-energy sensitivity.

GoKaatru reports uncertainty on a **wind-speed** basis, because that is what the
pipeline measures: every component of the uncertainty model is a percentage of wind
speed.  In wind resource assessment, however, P50/P75/P90 normally name *energy*
exceedances, and the two differ by the site's energy sensitivity factor

    S = d(ln AEP) / d(ln U)

This module supplies S from a **generic** power curve so the conversion can be made
explicitly rather than assumed, and supplies the indicative AEP that the analysis
engine reports as its second headline metric (design doc §7.12, §11).

**One curve, both uses.** S and the published AEP must come from the same machine.
Reporting energy off a 3 MW curve while computing the speed-to-energy conversion off
a 4.2 MW one would mean the two numbers described different turbines — an easy
mistake to make while the curve was a module-level constant, and the reason it is now
a named registry resolved per call.

The curves are generic on purpose.  S depends on where a site's speed distribution
sits against whichever curve is used, so a project number needs the project's own
turbine; these give the right order and the right behaviour (S falls as a site climbs
towards rated power) without pretending to be a specific machine.  AEP is likewise
**gross and indicative**: no wake, availability or electrical losses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

HOURS_PER_YEAR = 8766.0  # 365.25 days, leap-averaged


@dataclass(frozen=True)
class PowerCurve:
    """One generic turbine power curve, in kW at 1 m/s bins from 0 m/s."""

    name: str
    rated_kw: float
    rotor_diameter_m: float
    cut_in_mps: float
    cut_out_mps: float
    power_kw: np.ndarray = field(repr=False)

    @property
    def speed_mps(self) -> np.ndarray:
        """Return the 1 m/s bin centres the curve is tabulated on."""
        return np.arange(0.0, float(self.power_kw.size), 1.0)

    @property
    def specific_power_w_m2(self) -> float:
        """Return rated power per swept area, the number that characterises curve shape."""
        area = np.pi * (self.rotor_diameter_m / 2.0) ** 2
        return float(self.rated_kw * 1000.0 / area)

    def describe(self) -> dict[str, object]:
        """Return the curve's identity for reporting alongside any number derived from it."""
        return {
            "name": self.name,
            "rated_kw": self.rated_kw,
            "rotor_diameter_m": self.rotor_diameter_m,
            "specific_power_w_m2": round(self.specific_power_w_m2, 1),
            "cut_in_mps": self.cut_in_mps,
            "cut_out_mps": self.cut_out_mps,
            "basis": "generic",
        }


# A generic modern onshore machine: 3.0 MW rated, 130 m rotor, specific power 226 W/m2,
# roughly IEC class IIA.  Implied Cp peaks near 0.41 at 6-8 m/s and sheds towards rated,
# which is the correct behaviour for a machine of this class.  This is the curve the
# analysis engine reports AEP on (design doc §11).
GENERIC_3MW = PowerCurve(
    name="generic-3.0MW-130m-IIA",
    rated_kw=3000.0,
    rotor_diameter_m=130.0,
    cut_in_mps=3.0,
    cut_out_mps=25.0,
    power_kw=np.array(
        [
            0, 0, 0, 40, 175, 400, 720, 1150, 1700, 2300, 2750, 2950, 3000, 3000,
            3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000, 3000,
            0, 0, 0, 0, 0,
        ],
        dtype=float,
    ),
)

# The larger machine this module originally carried: 4.2 MW rated, 150 m rotor,
# specific power 238 W/m2.  Retained so a result computed against it can still be
# reproduced, and as the comparison point for how much S depends on the machine.
GENERIC_4_2MW = PowerCurve(
    name="generic-4.2MW-150m-IIA",
    rated_kw=4200.0,
    rotor_diameter_m=150.0,
    cut_in_mps=3.0,
    cut_out_mps=25.0,
    power_kw=np.array(
        [
            0, 0, 0, 60, 250, 570, 1000, 1600, 2300, 3050, 3700, 4100, 4200, 4200,
            4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200,
            0, 0, 0, 0, 0,
        ],
        dtype=float,
    ),
)

POWER_CURVES: dict[str, PowerCurve] = {
    GENERIC_3MW.name: GENERIC_3MW,
    GENERIC_4_2MW.name: GENERIC_4_2MW,
}

DEFAULT_POWER_CURVE = GENERIC_3MW


def get_power_curve(name: str | None = None) -> PowerCurve:
    """Return a named curve, or the default when no name is given."""
    if name is None:
        return DEFAULT_POWER_CURVE
    try:
        return POWER_CURVES[name]
    except KeyError:
        valid = ", ".join(sorted(POWER_CURVES))
        raise ValueError(f"power curve must be one of {valid}, got '{name}'") from None


def power_curve_names() -> tuple[str, ...]:
    """Return every registered curve name in a stable order."""
    return tuple(POWER_CURVES)


def _resolve(curve: PowerCurve | str | None) -> PowerCurve:
    """Accept a curve, a curve name, or nothing and return a curve."""
    if isinstance(curve, PowerCurve):
        return curve
    return get_power_curve(curve)


# Backwards-compatible aliases. These now describe the **default** curve, which is the
# 3 MW machine rather than the 4.2 MW one the module used to hard-code; moving S onto
# the same curve the engine reports AEP on is a deliberate change (design doc §7.12).
GENERIC_CURVE_NAME = DEFAULT_POWER_CURVE.name
GENERIC_RATED_KW = DEFAULT_POWER_CURVE.rated_kw
GENERIC_ROTOR_DIAMETER_M = DEFAULT_POWER_CURVE.rotor_diameter_m
CUT_IN_MPS = DEFAULT_POWER_CURVE.cut_in_mps
CUT_OUT_MPS = DEFAULT_POWER_CURVE.cut_out_mps


def turbine_power_kw(speed, curve: PowerCurve | str | None = None):
    """Interpolate a power curve linearly in speed, with hard cut-in and cut-out.

    Linear interpolation on the published bins is the IEC 61400-12-1 convention; a spline
    would overshoot near the knee and around rated power.
    """
    selected = _resolve(curve)
    values = np.asarray(speed, dtype=float)
    power = np.interp(values, selected.speed_mps, selected.power_kw, left=0.0, right=0.0)
    outside = (values < selected.cut_in_mps) | (values > selected.cut_out_mps)
    return np.where(outside, 0.0, power)


def indicative_aep_mwh(speed, curve: PowerCurve | str | None = None) -> float:
    """Indicative gross AEP for one generic turbine: mean power over the series x hours/year.

    Indicative, not a project number: it is gross, uses a generic curve, applies no wake,
    availability or electrical losses, and assumes reference density unless the caller has
    already normalised the speed.
    """
    values = np.asarray(speed, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Energy sensitivity requires at least one finite wind-speed value")
    return float(np.mean(turbine_power_kw(values, curve)) / 1000.0 * HOURS_PER_YEAR)


def indicative_capacity_factor(speed, curve: PowerCurve | str | None = None) -> float:
    """Gross capacity factor of the generic turbine on this series."""
    selected = _resolve(curve)
    return indicative_aep_mwh(speed, selected) / (selected.rated_kw / 1000.0 * HOURS_PER_YEAR)


def energy_sensitivity_factor(
    speed,
    epsilon: float = 0.01,
    curve: PowerCurve | str | None = None,
) -> float:
    """Return S = d(ln AEP)/d(ln U), by central difference on the actual series.

    Computed from the site's own speed distribution rather than a rule of thumb, because S
    is not a constant: it approaches 3 where the whole distribution sits in the cubic part
    of the curve and falls towards 0 once most hours are at rated power.

    ``curve`` must be the same curve any reported AEP was computed on, or the published
    energy figure and the speed-to-energy conversion describe different machines.
    """
    if not 0.0 < epsilon < 0.5:
        raise ValueError("epsilon must be a small positive fraction")
    selected = _resolve(curve)
    values = np.asarray(speed, dtype=float)
    upper = indicative_aep_mwh(values * (1.0 + epsilon), selected)
    lower = indicative_aep_mwh(values * (1.0 - epsilon), selected)
    return float((np.log(upper) - np.log(lower)) / (np.log1p(epsilon) - np.log1p(-epsilon)))


def conversion_guidance(
    sensitivity: float,
    speed_uncertainty_pct: float,
    curve: PowerCurve | str | None = None,
) -> dict[str, object]:
    """Explain how to turn the reported wind-speed uncertainty into an energy uncertainty.

    The arithmetic is one multiplication; what matters is that the reader knows it is
    required, knows the factor is site- and turbine-specific, and knows what the result
    does and does not include.
    """
    selected = _resolve(curve)
    energy_pct = sensitivity * speed_uncertainty_pct
    return {
        "steps": [
            f"1. Take the reported wind-speed uncertainty: {speed_uncertainty_pct:.2f}% of mean wind speed.",
            f"2. Multiply by this site's energy sensitivity factor S = {sensitivity:.3f}.",
            f"3. The result, {energy_pct:.2f}%, is the energy uncertainty implied by the "
            "wind-speed uncertainty alone.",
            "4. Apply the normal exceedance factors to that energy figure, not to the "
            f"speed figure: P90_energy = AEP x (1 - 1.282 x {energy_pct:.2f}/100) = "
            f"AEP x {1.0 - 1.282 * energy_pct / 100.0:.4f}.",
        ],
        "worked_example": (
            f"{speed_uncertainty_pct:.2f}% speed x S {sensitivity:.3f} = {energy_pct:.2f}% energy; "
            f"the P50-P90 band is {1.282 * energy_pct / 100.0:.1%} of energy against "
            f"{1.282 * speed_uncertainty_pct / 100.0:.1%} if the speed figure were used directly."
        ),
        "do_not": (
            "Do not apply the wind-speed p_factors to an energy yield. They are speed "
            "exceedances; using them on AEP understates the energy band by a factor of S."
        ),
        "not_included": (
            "This conversion propagates the wind-speed uncertainty only. A bankable energy "
            "uncertainty must also carry power-curve, wake, availability, electrical-loss and "
            "flow-modelling terms, none of which GoKaatru models — so treat the converted "
            "figure as a floor, not an estimate."
        ),
        "factor_is_specific": (
            f"S was measured on this site's own long-term distribution against the generic "
            f"{selected.name} curve. It is turbine-specific: a machine with different "
            "specific power gives a different S, and S falls as a site sits higher on the "
            "power curve. Recompute it with the project turbine before publishing."
        ),
    }


# IEC 61400-12-1 reference air density.  A power curve is measured at this density, so a
# measured speed has to be normalised to it before the curve is read (F-57).
REFERENCE_AIR_DENSITY = 1.225


def normalise_speed_to_reference_density(
    speed,
    air_density,
    regulation: str = "stall",
):
    """Normalise measured wind speed to the power curve's reference density (IEC 61400-12-1).

    For a **stall-regulated** machine the standard treats the density difference as a speed
    correction, ``U_n = U (rho / rho_0)^(1/3)``: the cube root is there because power scales
    with ``rho U^3``, so an equal-power speed at the reference density is what the curve
    should be read at.

    For a **pitch-regulated** machine the standard corrects the power *curve* rather than the
    speed, because below rated the machine tracks the same tip-speed ratio and above rated it
    holds power flat regardless of density.  Applying the speed correction to a pitch machine
    would move the rated knee, so this function refuses rather than quietly doing the wrong
    thing.

    Nothing in the pipeline applied any of this before: ``density_correction_factor`` was
    computed in ``atmosphere.py``, displayed in the Sensor Overview, and applied to nothing.
    It became live the moment an indicative AEP existed.
    """
    if regulation not in {"stall", "pitch"}:
        raise ValueError(f"regulation must be 'stall' or 'pitch', got '{regulation}'")
    if regulation == "pitch":
        raise ValueError(
            "IEC 61400-12-1 corrects the power curve, not the wind speed, for a "
            "pitch-regulated machine. Normalising the speed would move the rated knee. Use "
            "the measured density against a density-corrected power curve instead."
        )
    values = np.asarray(speed, dtype=float)
    density = np.asarray(air_density, dtype=float)
    if np.any(density[np.isfinite(density)] <= 0.0):
        raise ValueError("air_density must be positive")
    return values * np.cbrt(density / REFERENCE_AIR_DENSITY)
