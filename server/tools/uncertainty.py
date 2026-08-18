"""uncertainty — Phase 4 MCP tool for total uncertainty and exceedance factors.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from server.core.powercurve import (
    GENERIC_CURVE_NAME,
    REFERENCE_AIR_DENSITY,
    GENERIC_RATED_KW,
    GENERIC_ROTOR_DIAMETER_M,
    conversion_guidance,
    energy_sensitivity_factor,
    indicative_capacity_factor,
    normalise_speed_to_reference_density,
)
from server.main import mcp
from server.state.session import SessionState, session

# Generic inter-annual variability used only when the site's own value is unknown.
# Treated as a sentinel: an explicit caller value other than this is respected, while
# this value means "no preference", so a measured IAV can take its place.
DEFAULT_IAV_PCT = 6.0

# Assumed operating life over which inter-annual variability averages out.  Now the
# default of a parameter rather than an inline sqrt(20): a 15-year life gives 1.55% where
# 20 years gives 1.34%, and which life applies is the project's fact, not the tool's (F-32).
PROJECT_LIFE_YEARS = 20.0

# Concurrent months beyond which the MCP sampling term stops improving (F-31).  The term
# is 3/sqrt(months): uncapped, a five-year campaign would claim 0.39% where one year claims
# 0.87%, and that extra credit is not real, because beyond a year the limit on an MCP is
# the stability of the transfer function rather than the number of pairs.  The cap is the
# defensible part; what was not defensible is that it was invisible and unmovable, so a
# three-year campaign earned exactly nothing over a one-year one with nothing saying why.
DEFAULT_CONCURRENT_MONTHS_CAP = 12.0

# Correlation assumed between the three components that all derive from the same measured
# series - measurement, vertical extrapolation and MCP (F-33).  The default of 0.0 is pure
# quadrature, which is what the model has always done and what most published RSS practice
# assumes; it is almost certainly optimistic, so every response also reports the total at
# CORRELATION_SENSITIVITY_RHO so the size of the assumption is visible.
DEFAULT_COMPONENT_CORRELATION = 0.0
CORRELATION_SENSITIVITY_RHO = 0.5
CORRELATED_COMPONENTS = ("measurement", "vertical_extrapolation", "mcp")


def _long_term_speed_series(state: SessionState) -> tuple["pd.Series | None", str]:
    """Return the best available long-term corrected speed series, and where it came from.

    Preference order matches the pipeline: the ensemble blend, then any single LTC result,
    then the measured hub-height column.  The sensitivity factor should describe the
    distribution the P-values will actually be quoted against.
    """
    if state.ensemble_df is not None:
        frame = pd.DataFrame(state.ensemble_df)
        if "Ensemble_Speed" in frame.columns:
            series = frame["Ensemble_Speed"].dropna()
            if not series.empty:
                return series, "ensemble"
    for algorithm in sorted(state.ltc_results):
        payload = state.ltc_results.get(algorithm)
        if isinstance(payload, dict) and "df" in payload:
            frame = pd.DataFrame(payload["df"])
            if "corrected_wind_speed" in frame.columns:
                series = frame["corrected_wind_speed"].dropna()
                if not series.empty:
                    return series, f"ltc:{algorithm}"
    hub_height = state.get_hub_height_m()
    if state.timeseries_df is not None and hub_height is not None:
        column = f"Spd_{int(hub_height) if float(hub_height).is_integer() else hub_height}m_hub"
        if column in state.timeseries_df.columns:
            series = state.timeseries_df[column].dropna()
            if not series.empty:
                return series, f"measured:{column}"
    return None, "unavailable"


def _density_normalised(
    state: SessionState,
    speed: "np.ndarray",
) -> tuple["np.ndarray", dict[str, object]]:
    """Normalise speed to the power curve's reference density where the site's density is known.

    IEC 61400-12-1 normalises measured speed to a reference density before power-curve work
    (F-57).  Nothing in the pipeline did: ``density_correction_factor`` was computed in
    ``atmosphere.py``, displayed in the Sensor Overview, and applied to nothing.  It became
    live the moment an indicative AEP existed, because reading a curve measured at
    1.225 kg/m3 with speeds from a 1.10 kg/m3 site overstates the energy.

    The session's mean measured density is used when a density series exists; otherwise the
    speeds are read as-is and the response says the normalisation was skipped, rather than
    silently assuming standard conditions.
    """
    density = state.runconfig.get("mean_air_density_kgm3")
    if not isinstance(density, (int, float)) or not density > 0.0:
        return speed, {
            "applied": False,
            "reason": (
                "No site air density is recorded, so the speeds were read against a power "
                "curve measured at 1.225 kg/m3 without normalisation. IEC 61400-12-1 "
                "normalises speed to the reference density first; at a 1.10 kg/m3 site that "
                "is a 3.5% speed correction and the sensitivity factor shifts with it. Run "
                "compute_atmospheric_conditions to record the measured density."
            ),
            "reference_density_kgm3": REFERENCE_AIR_DENSITY,
        }
    normalised = normalise_speed_to_reference_density(
        speed, np.full(speed.shape, float(density)), regulation="stall"
    )
    return normalised, {
        "applied": True,
        "method": "iec_61400_12_1_stall",
        "site_density_kgm3": round(float(density), 4),
        "reference_density_kgm3": REFERENCE_AIR_DENSITY,
        "speed_factor": round(float((density / REFERENCE_AIR_DENSITY) ** (1.0 / 3.0)), 6),
        "note": (
            "Speeds were normalised to the curve's reference density as U*(rho/rho0)^(1/3), "
            "which is the IEC treatment for a stall-regulated machine. A pitch-regulated "
            "machine is handled by correcting the power curve instead, which needs the "
            "project turbine."
        ),
    }


def _energy_sensitivity_block(state: SessionState, u_total: float) -> dict[str, object]:
    """Return the energy sensitivity factor and how to use it, or say why it is unavailable.

    The uncertainty this tool reports is a wind-speed uncertainty, and every component of
    it is a percentage of wind speed.  P50/P75/P90 in wind resource assessment normally
    name *energy* exceedances, so the conversion has to be stated rather than left to the
    reader to guess at.  The factor is measured on the session's own long-term
    distribution against a generic power curve; no energy uncertainty is published here,
    because a defensible one needs loss and power-curve terms this application does not
    model.
    """
    series, source = _long_term_speed_series(state)
    if series is None:
        return {
            "available": False,
            "reason": (
                "No long-term corrected series is available yet, so the energy sensitivity "
                "factor cannot be measured. Run the LTC and ensemble stages first; until "
                "then the reported uncertainty is wind speed only and must not be applied "
                "to an energy yield."
            ),
        }
    values = series.to_numpy(dtype=float)
    values, density_basis = _density_normalised(state, values)
    sensitivity = energy_sensitivity_factor(values)
    return {
        "available": True,
        "factor": round(sensitivity, 4),
        "density_normalisation": density_basis,
        "definition": "S = d(ln AEP) / d(ln U), by central difference at +/-1% on the series below",
        "measured_on": source,
        "records": int(values.size),
        "mean_speed_mps": round(float(values.mean()), 4),
        "power_curve": {
            "name": GENERIC_CURVE_NAME,
            "rated_kw": GENERIC_RATED_KW,
            "rotor_diameter_m": GENERIC_ROTOR_DIAMETER_M,
            "basis": "generic",
            "indicative_capacity_factor": round(float(indicative_capacity_factor(values)), 4),
        },
        "how_to_convert": conversion_guidance(sensitivity, u_total),
    }


def _combine_with_correlation(
    components: dict[str, float],
    correlated: tuple[str, ...],
    rho: float,
) -> float:
    """Combine uncertainty components in quadrature, with *rho* between the correlated set.

    ``sqrt(sum(u_i^2) + 2 rho sum_{i<j in correlated} u_i u_j)``.  At rho = 0 this is exactly
    the pure RSS the model has always used, so the default result is bit-for-bit unchanged.
    """
    total_squared = sum(value**2 for value in components.values())
    if rho:
        present = [components[name] for name in correlated if name in components]
        for index, first in enumerate(present):
            for second in present[index + 1 :]:
                total_squared += 2.0 * rho * first * second
    return float(math.sqrt(max(total_squared, 0.0)))


def _calculate_uncertainty(
    state: SessionState,
    measurement_uncertainty_pct: float,
    measurement_height_m: float,
    hub_height_m: float,
    shear_method: str,
    mcp_r_squared: float,
    concurrent_hours: float,
    algorithm: str = "speedsort",
    iav_pct: float = DEFAULT_IAV_PCT,
    shear_std: float = 0.0,
    is_interpolation: bool = False,
    project_life_years: float = PROJECT_LIFE_YEARS,
    concurrent_months_cap: float = DEFAULT_CONCURRENT_MONTHS_CAP,
    component_correlation: float = DEFAULT_COMPONENT_CORRELATION,
) -> dict:
    """Calculate total uncertainty by root-sum-square combination of measurement, vertical, MCP, and future terms.

    Valid shear_method values: "calculate_shear", "simple_power_law", "log_law",
    "power_law" (alias for simple_power_law).
    """
    # Normalize alias: "power_law" is accepted as synonym for "simple_power_law".
    normalized_shear = "simple_power_law" if shear_method == "power_law" else shear_method
    u_meas = float(measurement_uncertainty_pct)
    if is_interpolation:
        u_vert = 1.0
    elif measurement_height_m <= 0.0 or hub_height_m <= 0.0:
        u_vert = 5.0
    else:
        if normalized_shear == "calculate_shear" and shear_std > 0.0:
            k_shear = float(shear_std)
        elif normalized_shear == "log_law":
            k_shear = 0.05
        else:
            # "simple_power_law" and any validated method get standard k.
            k_shear = 0.03
        u_vert = float(k_shear * abs(math.log(hub_height_m / measurement_height_m)) * 100.0)
    if project_life_years <= 0.0:
        raise ValueError(f"project_life_years must be positive, got {project_life_years}")
    if concurrent_months_cap < 1.0:
        raise ValueError(f"concurrent_months_cap must be at least 1, got {concurrent_months_cap}")
    if not -1.0 <= component_correlation <= 1.0:
        raise ValueError(
            f"component_correlation must lie between -1 and 1, got {component_correlation}"
        )
    concurrent_months = max(1.0, float(concurrent_hours) / 730.0)
    concurrent_months_eff = min(concurrent_months, float(concurrent_months_cap))
    r_squared = min(1.0, max(0.0, float(mcp_r_squared)))
    algorithm_factor = 4.0 if algorithm in {"speedsort", "xgboost", "gam_multivariate"} else 5.0
    fit_term = float((1.0 - r_squared) * algorithm_factor)
    u_mcp = float((3.0 / math.sqrt(concurrent_months_eff)) + fit_term)
    # What the sampling term would have given without the cap, so the credit the cap
    # withholds is a number the reader can see rather than an absence (F-31).
    u_mcp_uncapped = float((3.0 / math.sqrt(concurrent_months)) + fit_term)
    # Prefer the site's own inter-annual variability over the generic default.  The
    # clipping run measures it on the window it selected; without this the term used a
    # hand-typed 6% while the measured value sat on screen in another view.
    measured_iav_pct = state.get_measured_iav_pct()
    iav_source = "default"
    if measured_iav_pct is not None and float(iav_pct) == DEFAULT_IAV_PCT:
        iav_pct = measured_iav_pct
        iav_source = "clipping_selected_window"
    elif float(iav_pct) != DEFAULT_IAV_PCT:
        iav_source = "caller"
    u_future = float(iav_pct / math.sqrt(float(project_life_years)))
    raw_components = {
        "measurement": u_meas,
        "vertical_extrapolation": u_vert,
        "mcp": u_mcp,
        "future_variability": u_future,
    }
    u_total = _combine_with_correlation(
        raw_components, CORRELATED_COMPONENTS, float(component_correlation)
    )
    u_total_correlated = _combine_with_correlation(
        raw_components, CORRELATED_COMPONENTS, CORRELATION_SENSITIVITY_RHO
    )
    result = {
        "total_uncertainty_pct": round(u_total, 2),
        "components": {
            "measurement": round(u_meas, 2),
            "vertical_extrapolation": round(u_vert, 2),
            "mcp": round(u_mcp, 2),
            "future_variability": round(u_future, 2),
        },
        # F-33.  RSS treats all four components as independent, but measurement, vertical
        # extrapolation and MCP all derive from the same measured series - a mast that reads
        # low reads low in every one of them.  Zero correlation is what published RSS
        # practice assumes and what this model has always done, so it stays the default;
        # what changes is that the size of the assumption is now on the page.
        "combination": {
            "method": "root_sum_square",
            "component_correlation": float(component_correlation),
            "correlated_components": list(CORRELATED_COMPONENTS),
            "total_at_rho_0.5_pct": round(u_total_correlated, 2),
            "sensitivity_ratio": round(u_total_correlated / u_total, 4) if u_total > 0 else 1.0,
            "note": (
                "Components are combined in quadrature assuming independence. Measurement, "
                "vertical extrapolation and MCP all derive from the same measured series, so "
                "independence is optimistic: at a correlation of 0.5 among those three the "
                f"total is {u_total_correlated:.2f}% against the reported {u_total:.2f}%, and "
                "the difference flows straight into every P-value. Set component_correlation "
                "to combine them with a correlation instead."
            ),
        },
        # Every component above is a percentage of WIND SPEED, so these exceedance
        # factors are wind-speed exceedances.  In wind resource assessment P50/P75/P90
        # normally name *energy* exceedances, and the two differ by the site's energy
        # sensitivity factor S = d(lnAEP)/d(lnU) — roughly 1.2 at a windy site and above
        # 2 at a marginal one.  The basis is stated here so the numbers cannot be read as
        # energy by default.  GoKaatru computes no AEP, so it cannot supply the energy
        # equivalents itself.
        "basis": "wind_speed",
        "p_factors": {
            "basis": "wind_speed",
            "p50": 1.0,
            "p75": round(1.0 - (0.674 * u_total / 100.0), 4),
            "p90": round(1.0 - (1.282 * u_total / 100.0), 4),
            "p99": round(1.0 - (2.326 * u_total / 100.0), 4),
            "note": (
                "Wind-speed exceedance factors. Multiply a mean wind speed, not an energy "
                "yield. To convert, see `energy_sensitivity` in this response: multiply the "
                "total uncertainty by that factor first, then apply the exceedance "
                "quantiles to the energy figure."
            ),
        },
        "inputs": {
            "measurement_height_m": float(measurement_height_m),
            "hub_height_m": float(hub_height_m),
            "shear_method": shear_method,
            "mcp_r_squared": r_squared,
            # Report the value the arithmetic used, not the uncapped input: u_mcp applies
            # min(months, 12), so disclosing 60 for a five-year campaign made the response
            # impossible to reproduce from its own inputs.
            "concurrent_months": round(concurrent_months, 1),
            "concurrent_months_used": round(concurrent_months_eff, 1),
            "concurrent_months_cap": float(concurrent_months_cap),
            "iav_pct": round(float(iav_pct), 2),
            "iav_source": iav_source,
            "project_life_years": float(project_life_years),
            "algorithm": algorithm,
            "is_interpolation": bool(is_interpolation),
        },
        "mcp_sampling_cap": {
            "cap_months": float(concurrent_months_cap),
            "months_available": round(concurrent_months, 1),
            "cap_applied": bool(concurrent_months > concurrent_months_cap),
            "u_mcp_pct": round(u_mcp, 4),
            "u_mcp_uncapped_pct": round(u_mcp_uncapped, 4),
            "credit_withheld_pct": round(u_mcp - u_mcp_uncapped, 4),
            "note": (
                "The MCP sampling term is 3/sqrt(concurrent months), capped so a campaign "
                "longer than the cap earns no further credit. Beyond about a year the limit "
                "on an MCP is the stability of the transfer function rather than the number "
                "of concurrent pairs, so the extra credit would not be real - but the cap was "
                "previously invisible and unmovable, and a three-year campaign scored exactly "
                "the same as a one-year one with nothing saying why. Raise "
                "concurrent_months_cap to claim more of it."
            ),
        },
    }
    if concurrent_months > concurrent_months_cap:
        result["mcp_sampling_cap"]["warning"] = (
            f"{concurrent_months:.1f} concurrent months were supplied and "
            f"{concurrent_months_cap:g} were used. Uncapped, u_mcp would be "
            f"{u_mcp_uncapped:.2f}% against the reported {u_mcp:.2f}%."
        )
    result["energy_sensitivity"] = _energy_sensitivity_block(state, u_total)
    result.update(state.staleness_report())
    state.latest_uncertainty = result
    state.stamp_derived("uncertainty")
    return result


@mcp.tool()
def calculate_uncertainty(
    measurement_uncertainty_pct: float,
    measurement_height_m: float,
    hub_height_m: float,
    shear_method: str,
    mcp_r_squared: float,
    concurrent_hours: float,
    algorithm: str = "speedsort",
    iav_pct: float = DEFAULT_IAV_PCT,
    shear_std: float = 0.0,
    is_interpolation: bool = False,
    project_life_years: float = PROJECT_LIFE_YEARS,
    concurrent_months_cap: float = DEFAULT_CONCURRENT_MONTHS_CAP,
    component_correlation: float = DEFAULT_COMPONENT_CORRELATION,
) -> dict:
    """Calculate total uncertainty by root-sum-square combination of measurement, vertical, MCP, and future terms.

    ``project_life_years`` sets the horizon over which inter-annual variability averages out
    (``u_future = iav / sqrt(life)``); a 15-year life gives 1.55% where the 20-year default
    gives 1.34%.

    ``concurrent_months_cap`` bounds the MCP sampling term, which is otherwise
    ``3 / sqrt(months)`` without limit. The response reports what the cap withheld.

    ``component_correlation`` is the correlation assumed between measurement, vertical
    extrapolation and MCP, which all derive from the same measured series. The default of 0
    is pure quadrature; the response always reports the total at 0.5 alongside so the size
    of the independence assumption is visible.
    """
    return _calculate_uncertainty(
        session,
        measurement_uncertainty_pct,
        measurement_height_m,
        hub_height_m,
        shear_method,
        mcp_r_squared,
        concurrent_hours,
        algorithm,
        iav_pct,
        shear_std,
        is_interpolation,
        project_life_years,
        concurrent_months_cap,
        component_correlation,
    )


def _compute_energy_sensitivity(state: SessionState, speed_uncertainty_pct: float = 0.0) -> dict:
    """Measure the wind-speed-to-energy sensitivity factor on the session's long-term series."""
    block = _energy_sensitivity_block(state, float(speed_uncertainty_pct))
    if not block.get("available"):
        raise ValueError(str(block.get("reason")))
    stored = state.latest_uncertainty
    if speed_uncertainty_pct <= 0.0 and isinstance(stored, dict):
        total = stored.get("total_uncertainty_pct")
        if isinstance(total, (int, float)) and total > 0:
            block = _energy_sensitivity_block(state, float(total))
            block["speed_uncertainty_source"] = "latest_uncertainty"
    return {"status": "ok", **block, **state.staleness_report()}


@mcp.tool()
def compute_energy_sensitivity(speed_uncertainty_pct: float = 0.0) -> dict:
    """Measure S = d(lnAEP)/d(lnU) on the long-term series and explain the energy conversion.

    GoKaatru reports uncertainty on a wind-speed basis. This returns the factor needed to
    express it as an energy uncertainty, measured on the session's own long-term
    distribution against a generic power curve, together with the arithmetic and the
    caveats. Pass ``speed_uncertainty_pct`` to work the conversion for a specific figure;
    omitted, it uses the session's latest uncertainty result.
    """
    return _compute_energy_sensitivity(session, speed_uncertainty_pct)
