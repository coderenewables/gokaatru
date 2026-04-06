"""clipping — Phase 4 MCP tool for long-term clipping and historic-climate uncertainty tradeoff.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from server.main import mcp
from server.state.session import session


def _source_series(speed_col: str, source: str) -> pd.Series:
    """Resolve the long-term corrected source series used for clipping analysis by annual means."""
    if source == "ensemble":
        if session.ensemble_df is None:
            raise ValueError("Ensemble dataframe is not available. Run run_ensemble first")
        frame = pd.DataFrame(session.ensemble_df).copy()
    else:
        payload = session.ltc_results.get(source)
        if payload is None or "df" not in payload:
            raise ValueError(f"LTC result '{source}' is not available")
        frame = pd.DataFrame(payload["df"]).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if speed_col not in frame.columns:
        raise ValueError(f"Speed column '{speed_col}' not found in selected clipping source '{source}'")
    return frame[speed_col].sort_index().dropna()


@mcp.tool()
def run_clipping_analysis(speed_col: str, source: str = "ensemble") -> dict:
    """Minimize combined historic and climate uncertainty using annual means and the clipping methodology."""
    series = _source_series(speed_col, source)
    annual_means = series.resample("YE").mean().dropna()
    if len(annual_means) <= 5:
        raise ValueError(f"Clipping analysis requires more than 5 annual means, got {len(annual_means)}")
    full_iav = float(annual_means.std(ddof=1) / annual_means.mean())
    reference_mean = float(annual_means.iloc[-5:].mean())
    climate_max = 0.04
    f1 = 0.005
    f2 = 0.01
    log_term = float(np.log((climate_max - f1) / f2))
    results: list[dict[str, object]] = []
    start_years = annual_means.index.year.to_numpy(dtype=int)
    for start_year in start_years[:-4]:
        subset = annual_means[annual_means.index.year >= start_year]
        n_years = int(len(subset))
        subset_iav = float(subset.std(ddof=1) / subset.mean())
        lta_ratio = float(subset.mean() / reference_mean)
        historic_uncertainty = float(subset_iav / np.sqrt(n_years))
        scale = float(subset_iav / np.sqrt(5.0))
        deviation = abs(1.0 - 2.0 * float(norm.cdf(lta_ratio, loc=1.0, scale=scale)))
        climate_uncertainty = float(f1 + f2 * np.exp(-1.0 + (1.0 + log_term) * deviation**5))
        combined = float(np.sqrt(historic_uncertainty**2 + climate_uncertainty**2))
        results.append(
            {
                "start_year": int(start_year),
                "n_years": n_years,
                "mean_speed": float(subset.mean()),
                "iav": subset_iav,
                "lta_ratio": lta_ratio,
                "historic_uncertainty": historic_uncertainty,
                "climate_uncertainty": climate_uncertainty,
                "combined_uncertainty": combined,
            }
        )
    best = min(results, key=lambda item: float(item["combined_uncertainty"]))
    return {
        "optimal_start_year": int(best["start_year"]),
        "min_uncertainty": float(best["combined_uncertainty"]),
        "iav": full_iav,
        "analysis_data": results,
    }
