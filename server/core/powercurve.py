"""powercurve — generic turbine power curve and wind-speed-to-energy sensitivity.

GoKaatru reports uncertainty on a **wind-speed** basis, because that is what the
pipeline measures: every component of the uncertainty model is a percentage of wind
speed.  In wind resource assessment, however, P50/P75/P90 normally name *energy*
exceedances, and the two differ by the site's energy sensitivity factor

    S = d(ln AEP) / d(ln U)

This module supplies S from a **generic** power curve so the conversion can be made
explicitly rather than assumed.  It deliberately stops there: no AEP is published as a
project number and no energy-specific uncertainty terms (power curve, wake, availability,
electrical losses) are modelled, because those need a real turbine selection and a loss
model that this application does not have.
"""
from __future__ import annotations

import numpy as np

# A generic modern onshore machine used only to characterise the *shape* of the
# speed-to-energy relationship: 4.2 MW rated, 150 m rotor, specific power 238 W/m2,
# roughly IEC class IIA.  Power in kW at 1 m/s bins from 0 m/s.
#
# The curve is generic on purpose.  S depends on where a site's speed distribution sits
# against whichever curve is used, so a project number needs the project's own turbine —
# this one gives the right order and the right behaviour (S falls as a site climbs towards
# rated power) without pretending to be a specific machine.
GENERIC_CURVE_NAME = "generic-4.2MW-150m-IIA"
GENERIC_RATED_KW = 4200.0
GENERIC_ROTOR_DIAMETER_M = 150.0
CUT_IN_MPS = 3.0
CUT_OUT_MPS = 25.0
HOURS_PER_YEAR = 8766.0  # 365.25 days, leap-averaged

_CURVE_SPEED = np.arange(0.0, 31.0, 1.0)
_CURVE_POWER_KW = np.array(
    [
        0, 0, 0, 60, 250, 570, 1000, 1600, 2300, 3050, 3700, 4100, 4200, 4200,
        4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200, 4200,
        0, 0, 0, 0, 0,
    ],
    dtype=float,
)


def turbine_power_kw(speed):
    """Interpolate the generic power curve linearly in speed, with hard cut-in and cut-out.

    Linear interpolation on the published bins is the IEC 61400-12-1 convention; a spline
    would overshoot near the knee and around rated power.
    """
    values = np.asarray(speed, dtype=float)
    power = np.interp(values, _CURVE_SPEED, _CURVE_POWER_KW, left=0.0, right=0.0)
    outside = (values < CUT_IN_MPS) | (values > CUT_OUT_MPS)
    return np.where(outside, 0.0, power)


def indicative_aep_mwh(speed) -> float:
    """Indicative gross AEP for one generic turbine: mean power over the series x hours/year.

    Indicative, not a project number: it is gross, uses a generic curve, applies no wake,
    availability or electrical losses, and assumes standard density.
    """
    values = np.asarray(speed, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Energy sensitivity requires at least one finite wind-speed value")
    return float(np.mean(turbine_power_kw(values)) / 1000.0 * HOURS_PER_YEAR)


def indicative_capacity_factor(speed) -> float:
    """Gross capacity factor of the generic turbine on this series."""
    return indicative_aep_mwh(speed) / (GENERIC_RATED_KW / 1000.0 * HOURS_PER_YEAR)


def energy_sensitivity_factor(speed, epsilon: float = 0.01) -> float:
    """Return S = d(ln AEP)/d(ln U), by central difference on the actual series.

    Computed from the site's own speed distribution rather than a rule of thumb, because S
    is not a constant: it approaches 3 where the whole distribution sits in the cubic part
    of the curve and falls towards 0 once most hours are at rated power.  Measured on the
    generic curve it runs from about 2.1 at a 5.5 m/s site to about 0.6 at 10.5 m/s.
    """
    if not 0.0 < epsilon < 0.5:
        raise ValueError("epsilon must be a small positive fraction")
    values = np.asarray(speed, dtype=float)
    upper = indicative_aep_mwh(values * (1.0 + epsilon))
    lower = indicative_aep_mwh(values * (1.0 - epsilon))
    return float((np.log(upper) - np.log(lower)) / (np.log1p(epsilon) - np.log1p(-epsilon)))


def conversion_guidance(sensitivity: float, speed_uncertainty_pct: float) -> dict[str, object]:
    """Explain how to turn the reported wind-speed uncertainty into an energy uncertainty.

    The arithmetic is one multiplication; what matters is that the reader knows it is
    required, knows the factor is site- and turbine-specific, and knows what the result
    does and does not include.
    """
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
            f"{GENERIC_CURVE_NAME} curve. It is turbine-specific: a machine with different "
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
