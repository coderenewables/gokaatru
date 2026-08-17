"""uncertainty — Phase 4 MCP tool for total uncertainty and exceedance factors.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import math

from server.main import mcp
from server.state.session import SessionState, session

# Generic inter-annual variability used only when the site's own value is unknown.
# Treated as a sentinel: an explicit caller value other than this is respected, while
# this value means "no preference", so a measured IAV can take its place.
DEFAULT_IAV_PCT = 6.0

# Assumed operating life over which inter-annual variability averages out.  Promoted
# from an inline sqrt(20) so it is visible and can become a parameter.
PROJECT_LIFE_YEARS = 20.0


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
                "yield: converting to energy requires this site's energy sensitivity factor "
                "applied to the total uncertainty first."
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
    state.latest_uncertainty = result
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
