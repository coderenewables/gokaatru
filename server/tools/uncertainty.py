"""uncertainty — Phase 4 MCP tool for total uncertainty and exceedance factors.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import math

import pandas as pd

from server.core.powercurve import (
    GENERIC_CURVE_NAME,
    GENERIC_RATED_KW,
    GENERIC_ROTOR_DIAMETER_M,
    conversion_guidance,
    energy_sensitivity_factor,
    indicative_capacity_factor,
)
from server.main import mcp
from server.state.session import SessionState, session

# Generic inter-annual variability used only when the site's own value is unknown.
# Treated as a sentinel: an explicit caller value other than this is respected, while
# this value means "no preference", so a measured IAV can take its place.
DEFAULT_IAV_PCT = 6.0

# Assumed operating life over which inter-annual variability averages out.  Promoted
# from an inline sqrt(20) so it is visible and can become a parameter.
PROJECT_LIFE_YEARS = 20.0


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
    sensitivity = energy_sensitivity_factor(values)
    return {
        "available": True,
        "factor": round(sensitivity, 4),
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
    concurrent_months = max(1.0, float(concurrent_hours) / 730.0)
    concurrent_months_eff = min(concurrent_months, 12.0)
    r_squared = min(1.0, max(0.0, float(mcp_r_squared)))
    algorithm_factor = 4.0 if algorithm in {"speedsort", "xgboost", "gam_multivariate"} else 5.0
    u_mcp = float((3.0 / math.sqrt(concurrent_months_eff)) + ((1.0 - r_squared) * algorithm_factor))
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
    u_future = float(iav_pct / math.sqrt(PROJECT_LIFE_YEARS))
    u_total = float(math.sqrt(u_meas**2 + u_vert**2 + u_mcp**2 + u_future**2))
    result = {
        "total_uncertainty_pct": round(u_total, 2),
        "components": {
            "measurement": round(u_meas, 2),
            "vertical_extrapolation": round(u_vert, 2),
            "mcp": round(u_mcp, 2),
            "future_variability": round(u_future, 2),
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
            "concurrent_months_cap": 12.0,
            "iav_pct": round(float(iav_pct), 2),
            "iav_source": iav_source,
            "project_life_years": PROJECT_LIFE_YEARS,
            "algorithm": algorithm,
            "is_interpolation": bool(is_interpolation),
        },
    }
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
) -> dict:
    """Calculate total uncertainty by root-sum-square combination of measurement, vertical, MCP, and future terms."""
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
