"""clipping — Phase 4 MCP tool for long-term clipping and historic-climate uncertainty tradeoff.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from server.main import mcp
from server.state.session import SessionState, session

# Minimum fraction of a calendar year that must carry data before that year's
# mean is treated as an annual mean (D5).  The first and last years of a
# long-term series are almost always partial, and a Nov-Dec "year" is a
# winter-biased pseudo-mean that inflates IAV — which drives both the clipping
# choice and the iav_pct term in the uncertainty model.
DEFAULT_MIN_YEAR_COMPLETENESS = 0.9

# Clipping-methodology coefficients.  These follow the industry long-term
# adjustment formulation in which climate uncertainty is bounded above by
# CLIMATE_MAX and decays towards CLIMATE_FLOOR as the candidate period's mean
# approaches the recent-climate reference.  Promoted from inline literals so a
# sensitivity sweep can vary them; changing them changes every reported P-value.
CLIMATE_MAX = 0.04
CLIMATE_FLOOR = 0.005  # f1 — asymptotic minimum climate uncertainty
CLIMATE_SCALE = 0.01  # f2 — scale of the exponential term above the floor

# The recent-climate reference window: the last N annual means define "current
# climate" against which each candidate start year is compared.
REFERENCE_WINDOW_YEARS = 5


def _source_series(state: SessionState, speed_col: str, source: str) -> pd.Series:
    """Resolve the long-term corrected source series used for clipping analysis by annual means."""
    if source == "ensemble":
        if state.ensemble_df is None:
            raise ValueError("Ensemble dataframe is not available. Run run_ensemble first")
        frame = pd.DataFrame(state.ensemble_df).copy()
    else:
        payload = state.ltc_results.get(source)
        if payload is None or "df" not in payload:
            raise ValueError(f"LTC result '{source}' is not available")
        frame = pd.DataFrame(payload["df"]).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if speed_col not in frame.columns:
        raise ValueError(f"Speed column '{speed_col}' not found in selected clipping source '{source}'")
    return frame[speed_col].sort_index().dropna()


def _complete_annual_means(
    series: pd.Series,
    min_year_completeness: float,
) -> tuple[pd.Series, list[dict[str, object]]]:
    """Return annual means for years meeting the completeness gate, plus the exclusions (D5).

    Completeness is measured against the samples a full year would hold at the
    series' own cadence, leap-aware, so a partial first or last calendar year is
    dropped rather than contributing a seasonally-biased pseudo-mean.
    """
    # Cadence is derived here rather than via detect_timestep_minutes: that helper
    # enforces the ingest cadence whitelist (D6), but a clipping source is a
    # derived long-term series which may legitimately be monthly or hourly.
    spacings = series.index.to_series().diff().dropna()
    if spacings.empty:
        raise ValueError("Clipping analysis requires at least two timestamps to infer the series cadence")
    step_minutes = float(spacings.median().total_seconds() / 60.0)
    if step_minutes <= 0:
        raise ValueError("Clipping analysis could not infer a positive cadence from the source series")
    samples_per_day = 24 * 60 / step_minutes
    counts = series.resample("YE").count()
    means = series.resample("YE").mean()
    days_in_year = counts.index.to_series().dt.dayofyear.to_numpy(dtype=float)  # 365 or 366
    expected = pd.Series(days_in_year * samples_per_day, index=counts.index)
    completeness = counts / expected

    keep = completeness >= min_year_completeness
    excluded = [
        {
            "year": int(stamp.year),
            "completeness": float(completeness.loc[stamp]),
            "records": int(counts.loc[stamp]),
            "expected_records": int(expected.loc[stamp]),
        }
        for stamp in counts.index[~keep]
    ]
    return means[keep].dropna(), excluded


def _run_clipping_analysis(
    state: SessionState,
    speed_col: str,
    source: str = "ensemble",
    min_year_completeness: float = DEFAULT_MIN_YEAR_COMPLETENESS,
) -> dict:
    """Minimize combined historic and climate uncertainty using annual means and the clipping methodology."""
    if not 0.0 <= min_year_completeness <= 1.0:
        raise ValueError(f"min_year_completeness must be between 0 and 1, got {min_year_completeness}")
    series = _source_series(state, speed_col, source)
    annual_means, excluded_years = _complete_annual_means(series, min_year_completeness)
    if len(annual_means) <= REFERENCE_WINDOW_YEARS:
        raise ValueError(
            f"Clipping analysis requires more than {REFERENCE_WINDOW_YEARS} complete annual means, "
            f"got {len(annual_means)} at a {min_year_completeness:.0%} completeness threshold "
            f"({len(excluded_years)} year(s) excluded as partial)."
        )
    full_iav = float(annual_means.std(ddof=1) / annual_means.mean())
    reference_mean = float(annual_means.iloc[-REFERENCE_WINDOW_YEARS:].mean())
    log_term = float(np.log((CLIMATE_MAX - CLIMATE_FLOOR) / CLIMATE_SCALE))
    results: list[dict[str, object]] = []
    start_years = annual_means.index.year.to_numpy(dtype=int)
    for start_year in start_years[: -(REFERENCE_WINDOW_YEARS - 1)]:
        subset = annual_means[annual_means.index.year >= start_year]
        n_years = int(len(subset))
        subset_iav = float(subset.std(ddof=1) / subset.mean())
        lta_ratio = float(subset.mean() / reference_mean)
        historic_uncertainty = float(subset_iav / np.sqrt(n_years))
        scale = float(subset_iav / np.sqrt(float(REFERENCE_WINDOW_YEARS)))
        deviation = abs(1.0 - 2.0 * float(norm.cdf(lta_ratio, loc=1.0, scale=scale)))
        climate_uncertainty = float(
            CLIMATE_FLOOR + CLIMATE_SCALE * np.exp(-1.0 + (1.0 + log_term) * deviation**5)
        )
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
        "years_used": [int(stamp.year) for stamp in annual_means.index],
        "years_excluded": [entry["year"] for entry in excluded_years],
        "excluded_reason": (
            f"Calendar year below the {min_year_completeness:.0%} completeness threshold; "
            "a partial year yields a seasonally-biased mean that inflates inter-annual variability."
            if excluded_years
            else ""
        ),
        "excluded_detail": excluded_years,
        "min_year_completeness": float(min_year_completeness),
    }


@mcp.tool()
def run_clipping_analysis(
    speed_col: str,
    source: str = "ensemble",
    min_year_completeness: float = DEFAULT_MIN_YEAR_COMPLETENESS,
) -> dict:
    """Minimize combined historic and climate uncertainty using annual means and the clipping methodology.

    Calendar years holding less than ``min_year_completeness`` of their expected
    samples are excluded and reported, so a partial first or last year cannot
    inflate inter-annual variability.
    """
    return _run_clipping_analysis(session, speed_col, source, min_year_completeness)
