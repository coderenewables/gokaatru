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

# Window length below which a "long-term" estimate is not normally defensible.  The
# objective is free to select shorter windows — that trade-off is the point of the
# method — but a selection this short is reported as a warning rather than passed off
# as an ordinary result.
MIN_DEFENSIBLE_WINDOW_YEARS = 10


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
    complete_years = [int(stamp.year) for stamp in annual_means.index]
    selected_years = [year for year in complete_years if year >= int(best["start_year"])]
    dropped_by_objective = [year for year in complete_years if year < int(best["start_year"])]
    reasons: list[str] = []
    if excluded_years:
        reasons.append(
            f"Calendar year below the {min_year_completeness:.0%} completeness threshold; "
            "a partial year yields a seasonally-biased mean that inflates inter-annual variability."
        )
    if dropped_by_objective:
        # Years the objective declined are not years the data lacked.  Reporting them
        # under the same heading as the completeness exclusions made the two
        # indistinguishable, so a reader assumed every listed year informed the result.
        reasons.append(
            f"{len(dropped_by_objective)} further complete year(s) "
            f"({dropped_by_objective[0]}-{dropped_by_objective[-1]}) lie outside the selected "
            "window: the representativeness objective traded their contribution to the "
            "historic term against the climate term and excluded them."
        )
    payload: dict[str, object] = {
        "optimal_start_year": int(best["start_year"]),
        "min_uncertainty": float(best["combined_uncertainty"]),
        # Percent-denominated mirrors of every fractional field.  The bare fractions are
        # retained for compatibility, but a consumer that appends "%" to them understates
        # the result a hundredfold, so the correctly-scaled value now travels with it.
        "min_uncertainty_pct": float(best["combined_uncertainty"]) * 100.0,
        "iav": full_iav,
        "iav_pct": full_iav * 100.0,
        "selected_iav": float(best["iav"]),
        "selected_iav_pct": float(best["iav"]) * 100.0,
        "selected_years": selected_years,
        "selected_n_years": int(best["n_years"]),
        "selected_mean_speed": float(best["mean_speed"]),
        "analysis_data": results,
        "years_used": complete_years,
        "years_dropped_by_objective": dropped_by_objective,
        "years_excluded": [entry["year"] for entry in excluded_years],
        "excluded_reason": " ".join(reasons),
        "excluded_detail": excluded_years,
        "min_year_completeness": float(min_year_completeness),
        "reference_window_years": int(REFERENCE_WINDOW_YEARS),
        "shortest_candidate_years": int(min(int(row["n_years"]) for row in results)),
    }
    if int(best["n_years"]) < MIN_DEFENSIBLE_WINDOW_YEARS:
        payload["warning"] = (
            f"The selected window is {best['n_years']} years, below the "
            f"{MIN_DEFENSIBLE_WINDOW_YEARS}-year period normally expected of a long-term "
            f"estimate. {len(dropped_by_objective)} complete year(s) were available and not "
            "used. Note also that every candidate window ends at the final year and so "
            f"contains the {REFERENCE_WINDOW_YEARS}-year reference period, which gives short "
            "windows a structural advantage on the climate term."
        )
    # Persist so the measured IAV can reach the uncertainty model instead of being
    # retyped from one tab into another (the u_future term otherwise uses a generic 6%).
    payload.update(state.staleness_report())
    state.clipping_result = payload
    state.stamp_derived("clipping")
    state.touch()
    return payload


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
