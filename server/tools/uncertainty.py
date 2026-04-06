"""uncertainty — Phase 4 MCP tool for total uncertainty and exceedance factors.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import math

from server.main import mcp


@mcp.tool()
def calculate_uncertainty(
    measurement_uncertainty_pct: float,
    measurement_height_m: float,
    hub_height_m: float,
    shear_method: str,
    mcp_r_squared: float,
    concurrent_hours: float,
    algorithm: str = "speedsort",
    iav_pct: float = 6.0,
    shear_std: float = 0.0,
    is_interpolation: bool = False,
) -> dict:
    """Calculate total uncertainty by root-sum-square combination of measurement, vertical, MCP, and future terms."""
    u_meas = float(measurement_uncertainty_pct)
    if is_interpolation:
        u_vert = 1.0
    elif measurement_height_m <= 0.0 or hub_height_m <= 0.0:
        u_vert = 5.0
    else:
        if shear_method == "calculate_shear" and shear_std > 0.0:
            k_shear = float(shear_std)
        else:
            k_shear = 0.03 if shear_method == "simple_power_law" else 0.01
        u_vert = float(k_shear * abs(math.log(hub_height_m / measurement_height_m)) * 100.0)
    concurrent_months = max(1.0, float(concurrent_hours) / 730.0)
    concurrent_months_eff = min(concurrent_months, 12.0)
    r_squared = min(1.0, max(0.0, float(mcp_r_squared)))
    algorithm_factor = 4.0 if algorithm in {"speedsort", "xgboost", "gam_multivariate"} else 5.0
    u_mcp = float((3.0 / math.sqrt(concurrent_months_eff)) + ((1.0 - r_squared) * algorithm_factor))
    u_future = float(iav_pct / math.sqrt(20.0))
    u_total = float(math.sqrt(u_meas**2 + u_vert**2 + u_mcp**2 + u_future**2))
    return {
        "total_uncertainty_pct": round(u_total, 2),
        "components": {
            "measurement": round(u_meas, 2),
            "vertical_extrapolation": round(u_vert, 2),
            "mcp": round(u_mcp, 2),
            "future_variability": round(u_future, 2),
        },
        "p_factors": {
            "p50": 1.0,
            "p75": round(1.0 - (0.674 * u_total / 100.0), 4),
            "p90": round(1.0 - (1.282 * u_total / 100.0), 4),
            "p99": round(1.0 - (2.326 * u_total / 100.0), 4),
        },
        "inputs": {
            "measurement_height_m": float(measurement_height_m),
            "hub_height_m": float(hub_height_m),
            "shear_method": shear_method,
            "mcp_r_squared": r_squared,
            "concurrent_months": round(concurrent_months, 1),
            "iav_pct": round(float(iav_pct), 2),
            "algorithm": algorithm,
            "is_interpolation": bool(is_interpolation),
        },
    }
