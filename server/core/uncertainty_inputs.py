"""uncertainty_inputs — derive a scenario's uncertainty inputs from its own results.

``_run_scenario_pipeline`` used to build its uncertainty call from constants::

    "mcp_r_squared": 0.85,
    "concurrent_hours": 8760.0,
    "shear_std": 0.0,

Across a single run that is merely approximate. Across a *sweep* it is fatal: every
scenario would report near-identical uncertainty regardless of how well its own fit
actually performed, so the uncertainty column would carry no information and the
spread built on it would be decorative (design doc §7.5).

Every input here is measured from the scenario's own artefacts — its LTC metrics, its
actual concurrent overlap, its own shear series — and every one carries provenance
saying whether it was derived or fell back. A fallback is legitimate; a *silent*
fallback is what turns a missing measurement into a confident-looking number.

One property worth knowing: ``metrics["r_squared"]`` is already the right quantity for
both closed-form estimators and XGBoost. The closed-form algorithms store the
concurrent-period fit; XGBoost's metrics dict opens with ``**val_metrics``, which is
the *out-of-fold* score, keeping its separate in-sample figure under
``in_sample_r_squared``. So a uniform read is out-of-sample wherever out-of-sample
exists, and neither this module nor the admissibility gate needs to special-case it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: Used only when a scenario's own R^2 cannot be read. Matches the constant the old
#: hardcoded block used, so falling back reproduces previous behaviour exactly.
FALLBACK_MCP_R_SQUARED = 0.85

#: One year of hourly records, the previous hardcoded value.
FALLBACK_CONCURRENT_HOURS = 8760.0

#: Measurement uncertainty is an instrument property, not something the sweep varies.
DEFAULT_MEASUREMENT_UNCERTAINTY_PCT = 2.0


@dataclass(frozen=True)
class DerivedInput:
    """One uncertainty input, with the evidence for where its value came from."""

    value: float
    derived: bool
    source: str

    def as_record(self) -> dict[str, object]:
        """Return the provenance record written into the scenario runconfig."""
        return {"value": self.value, "derived": self.derived, "source": self.source}


def _ltc_metrics(state: Any, algorithm: str) -> dict[str, object]:
    """Return one algorithm's stored metrics, or an empty dict when it has not run."""
    payload = state.ltc_results.get(algorithm)
    if not isinstance(payload, dict):
        return {}
    metrics = payload.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def derive_mcp_r_squared(state: Any, algorithm: str) -> DerivedInput:
    """Read the scenario's own goodness of fit rather than assuming one.

    Out-of-sample where the estimator provides it (see the module docstring).
    """
    value = _ltc_metrics(state, algorithm).get("r_squared")
    if isinstance(value, (int, float)) and np.isfinite(value):
        # A negative R^2 means the fit is worse than the series mean. That is real
        # information and the admissibility gate should see it, but feeding it to the
        # MCP uncertainty formula is meaningless, so it floors at zero here and the
        # provenance says the floor fired.
        clamped = float(max(0.0, min(1.0, float(value))))
        source = f"ltc_metrics:{algorithm}"
        if clamped != float(value):
            source = f"ltc_metrics:{algorithm} (clamped from {float(value):.4f} to [0, 1])"
        return DerivedInput(clamped, True, source)
    return DerivedInput(
        FALLBACK_MCP_R_SQUARED,
        False,
        f"fallback: '{algorithm}' stored no finite r_squared",
    )


def derive_concurrent_hours(state: Any, algorithm: str) -> DerivedInput:
    """Measure the overlap the correction was actually fitted on.

    The concurrent frame is an hourly inner join — the measured series is resampled to
    hourly and joined to an hourly reference — so one concurrent point is one hour.
    """
    points = _ltc_metrics(state, algorithm).get("concurrent_points")
    if isinstance(points, (int, float)) and points > 0:
        return DerivedInput(float(points), True, f"ltc_metrics:{algorithm}.concurrent_points")
    return DerivedInput(
        FALLBACK_CONCURRENT_HOURS,
        False,
        f"fallback: '{algorithm}' stored no concurrent_points",
    )


def derive_shear_std(state: Any) -> DerivedInput:
    """Measure the dispersion of the scenario's own shear series.

    ``_calculate_uncertainty`` only consults ``shear_std`` when ``shear_method`` is
    ``calculate_shear``; passing 0.0 with a fitted profile silently discarded the very
    variability the fitted branch exists to represent.
    """
    frame = getattr(state, "shear_timeseries_df", None)
    if frame is not None and "shear_coefficient" in frame.columns:
        valid = frame["shear_coefficient"].dropna()
        if len(valid) > 1:
            std = float(valid.std(ddof=1))
            if np.isfinite(std) and std >= 0.0:
                return DerivedInput(std, True, f"shear_timeseries_df over {len(valid):,} records")
    return DerivedInput(0.0, False, "fallback: no usable shear timeseries")


def measurement_heights(state: Any) -> list[float]:
    """Return the mapped measurement heights present in the loaded data, ascending."""
    if state.timeseries_df is None:
        return []
    return sorted(
        float(height)
        for height, slots in state.sensor_mapping.items()
        if slots.get("speed_col") in state.timeseries_df.columns
    )


def derive_measurement_height(state: Any, reference_heights: list[float] | None = None) -> DerivedInput:
    """Return the height the hub series was actually carried from.

    Defaults to the top mapped sensor, but a scenario whose extrapolation-reference
    policy (axis A2) selected a lower set is levered from *that* set's top height, and
    the vertical uncertainty must be computed against the height actually used.
    """
    heights = reference_heights if reference_heights else measurement_heights(state)
    if heights:
        top = float(max(heights))
        origin = "axis A2 selection" if reference_heights else "top mapped sensor"
        return DerivedInput(top, True, f"{origin}: {top:g} m")
    return DerivedInput(80.0, False, "fallback: no mapped measurement height")


def is_hub_interpolated(state: Any, hub_height_m: float | None = None) -> bool:
    """Whether hub height sits *inside* the measured profile rather than above it.

    An interpolated hub carries far less vertical uncertainty than an extrapolated one,
    and ``_calculate_uncertainty`` already models that — but only if it is told. A
    bracketing lidar that reported itself as extrapolating would overstate `u_vert`
    on every scenario.
    """
    hub = state.get_hub_height_m() if hub_height_m is None else float(hub_height_m)
    heights = measurement_heights(state)
    if hub is None or len(heights) < 2:
        return False
    return heights[0] < float(hub) < heights[-1]


def derive_uncertainty_inputs(
    state: Any,
    algorithm: str,
    *,
    hub_height_m: float | None = None,
    reference_heights: list[float] | None = None,
    shear_source: str = "fitted",
    measurement_uncertainty_pct: float = DEFAULT_MEASUREMENT_UNCERTAINTY_PCT,
    iav_pct: float | None = None,
) -> dict[str, object]:
    """Build one scenario's complete uncertainty-input set, with provenance.

    ``shear_source`` distinguishes a fitted profile from an analyst-supplied exponent
    (design doc §3.A.1). A supplied exponent has no measured dispersion, so it must take
    the *assumed*-shear branch and carry its larger `u_vert`; left implicit it would
    inherit a fitted-shear uncertainty from a sibling scenario and under-report.
    """
    if shear_source not in {"fitted", "analyst_supplied"}:
        raise ValueError(
            f"shear_source must be 'fitted' or 'analyst_supplied', got '{shear_source}'"
        )
    hub = state.get_hub_height_m() if hub_height_m is None else float(hub_height_m)
    r_squared = derive_mcp_r_squared(state, algorithm)
    concurrent = derive_concurrent_hours(state, algorithm)
    shear_std = derive_shear_std(state)
    height = derive_measurement_height(state, reference_heights)
    interpolated = is_hub_interpolated(state, hub)

    if shear_source == "analyst_supplied":
        shear_method = "simple_power_law"
        shear_std = DerivedInput(
            0.0, False, "analyst-supplied exponent has no measured dispersion"
        )
    elif shear_std.derived:
        shear_method = "calculate_shear"
    else:
        # No measured dispersion available, so claiming a fitted profile would let the
        # fitted branch run on a zero spread and understate the vertical term.
        shear_method = "simple_power_law"

    inputs: dict[str, object] = {
        "measurement_uncertainty_pct": float(measurement_uncertainty_pct),
        "measurement_height_m": height.value,
        "hub_height_m": float(hub) if hub is not None else height.value,
        "shear_method": shear_method,
        "mcp_r_squared": r_squared.value,
        "concurrent_hours": concurrent.value,
        "algorithm": algorithm,
        "shear_std": shear_std.value,
        "is_interpolation": interpolated,
    }
    if iav_pct is not None:
        inputs["iav_pct"] = float(iav_pct)

    inputs["provenance"] = {
        "mcp_r_squared": r_squared.as_record(),
        "concurrent_hours": concurrent.as_record(),
        "shear_std": shear_std.as_record(),
        "measurement_height_m": height.as_record(),
        "shear_source": shear_source,
        "shear_method_basis": (
            "analyst-supplied exponent, so the assumed-shear branch applies"
            if shear_source == "analyst_supplied"
            else "fitted profile with measured dispersion"
            if shear_method == "calculate_shear"
            else "fitted profile requested but no dispersion measured, so assumed-shear applies"
        ),
        "is_interpolation": {
            "value": interpolated,
            "derived": True,
            "source": (
                f"hub {hub:g} m within measured profile"
                if interpolated and hub is not None
                else "hub outside measured profile or too few heights"
            ),
        },
    }
    return inputs


def uncertainty_call_args(inputs: dict[str, object]) -> dict[str, object]:
    """Strip provenance, leaving the keyword arguments ``_calculate_uncertainty`` takes."""
    return {key: value for key, value in inputs.items() if key != "provenance"}
