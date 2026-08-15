"""ltc — Phase 3 MCP tools for deterministic long-term correction algorithms.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from server.core.regression import robust_huber_fit, total_least_squares_fit
from server.core.validators import detect_timestep_minutes
from server.main import mcp
from server.state.session import SessionState, session

MEASURED_COLUMN = "__measured__"
REFERENCE_COLUMN = "__reference__"

SPEEDSORT_NUM_SECTORS = 12
SPEEDSORT_SECTOR_WIDTH_DEG = 30.0
SPEEDSORT_MIN_SECTOR_RECORDS = 200


def _require_ltc_inputs(state: SessionState, short_col: str, long_col: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate measured and reference datasets required for LTC algorithms."""
    if state.timeseries_df is None:
        raise ValueError("Measured timeseries is not loaded")
    if state.era5_interpolated_df is None:
        raise ValueError("Interpolated ERA5 dataframe is not available")
    if short_col not in state.timeseries_df.columns:
        raise ValueError(f"Measured column '{short_col}' not found in session.timeseries_df")
    if long_col not in state.era5_interpolated_df.columns:
        raise ValueError(f"Reference column '{long_col}' not found in session.era5_interpolated_df")
    return (
        state.timeseries_df[[short_col]].copy().rename(columns={short_col: MEASURED_COLUMN}),
        state.era5_interpolated_df[[long_col]].copy().rename(columns={long_col: REFERENCE_COLUMN}),
    )


def _prepare_short_term(short_df: pd.DataFrame) -> pd.DataFrame:
    """Resample sub-hourly measured data to hourly means with a 50% minimum coverage threshold."""
    try:
        timestep_minutes = detect_timestep_minutes(short_df)
    except ValueError:
        return short_df
    if timestep_minutes >= 60:
        return short_df
    expected_samples = max(1.0, 60.0 / timestep_minutes)
    hourly_mean = short_df.resample("h").mean()
    hourly_count = short_df.resample("h").count()
    coverage = hourly_count.iloc[:, 0] / expected_samples
    return hourly_mean.loc[coverage >= 0.5]


def _concurrent_frame(
    state: SessionState,
    short_col: str,
    long_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the measured, reference, and concurrent datasets used by LTC algorithms."""
    short_df, long_df = _require_ltc_inputs(state, short_col, long_col)
    prepared_short = _prepare_short_term(short_df)
    # Ensure both indexes are tz-aware for a safe inner join (D8).
    if prepared_short.index.tz is None:
        prepared_short = prepared_short.copy()
        prepared_short.index = prepared_short.index.tz_localize("UTC")
    if long_df.index.tz is None:
        long_df = long_df.copy()
        long_df.index = long_df.index.tz_localize("UTC")
    concurrent = prepared_short.join(long_df, how="inner").dropna()
    if len(concurrent) < 10:
        raise ValueError(f"LTC requires at least 10 concurrent points, got {len(concurrent)}")
    return prepared_short, long_df, concurrent


def _regression_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Calculate common regression diagnostics for LTC concurrent-period predictions."""
    residuals = observed - predicted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((observed - observed.mean()) ** 2))
    r_squared = 0.0 if ss_tot == 0.0 else float(1.0 - ss_res / ss_tot)
    return {
        "r_squared": r_squared,
        "rmse": float(np.sqrt(np.mean(residuals**2))),
        "mae": float(np.mean(np.abs(residuals))),
        "mbe": float(np.mean(predicted - observed)),
        "std_residuals": float(np.std(residuals)),
    }


def _speedsort_sector_index(directions: np.ndarray) -> np.ndarray:
    """Compute sector index [0..11] for 12 sectors of 30° with boundaries shifted by half-width."""
    half = SPEEDSORT_SECTOR_WIDTH_DEG / 2.0
    return ((np.mod(directions, 360.0) + half) % 360.0 // SPEEDSORT_SECTOR_WIDTH_DEG).astype(int)


def _pearson_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Pearson correlation without NumPy covariance helpers."""
    centered_x = x - float(np.mean(x))
    centered_y = y - float(np.mean(y))
    denominator = float(np.sqrt(np.sum(centered_x**2) * np.sum(centered_y**2)))
    if denominator <= 0.0:
        return 0.0
    return float(np.sum(centered_x * centered_y) / denominator)


def _result_frame(reference_df: pd.DataFrame, corrected: np.ndarray) -> pd.DataFrame:
    """Build the standard LTC result dataframe with timestamp and corrected wind speeds."""
    frame = pd.DataFrame(
        {
            "Timestamp": reference_df.index,
            "ERA5_original": reference_df[REFERENCE_COLUMN].to_numpy(dtype=float),
            "corrected_wind_speed": np.clip(corrected, 0.0, None),
        }
    )
    return frame


def _save_ltc_result(state: SessionState, algorithm: str, result_df: pd.DataFrame, metrics: dict[str, object]) -> str:
    """Persist an LTC result to CSV and store it in session state."""
    output_dir = Path(state.get_data_dir()) / "ltc_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output_path = output_dir / f"ltc_{algorithm}_{timestamp}.csv"
    result_df.to_csv(output_path, index=False)
    state.ltc_results[algorithm] = {"df": result_df.copy(), "metrics": metrics.copy(), "file": str(output_path)}
    return str(output_path)


def _ltc_response(state: SessionState, algorithm: str, result_df: pd.DataFrame, metrics: dict[str, object]) -> dict:
    """Save an LTC result and return the standard MCP tool response payload."""
    result_file = _save_ltc_result(state, algorithm, result_df, metrics)
    return {"status": "ok", "algorithm": algorithm, "metrics": metrics, "result_file": result_file}


def _run_ltc_linear_least_squares(state: SessionState, short_col: str, long_col: str) -> dict:
    """Run robust linear MCP using Huber IRLS and apply the fit to the full long-term record."""
    _, long_df, concurrent = _concurrent_frame(state, short_col, long_col)
    measured = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    reference = concurrent[REFERENCE_COLUMN].to_numpy(dtype=float)
    slope, intercept, y_hat, r_squared = robust_huber_fit(reference, measured)
    corrected = long_df[REFERENCE_COLUMN].to_numpy(dtype=float) * slope + intercept
    metrics = _regression_metrics(measured, y_hat)
    metrics.update(
        {
            "algorithm": "linear_least_squares",
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": r_squared,
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
        }
    )
    return _ltc_response(state, "linear_least_squares", _result_frame(long_df, corrected), metrics)


def _run_ltc_total_least_squares(state: SessionState, short_col: str, long_col: str) -> dict:
    """Run orthogonal total least squares MCP and apply the fit to the full long-term record."""
    _, long_df, concurrent = _concurrent_frame(state, short_col, long_col)
    measured = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    reference = concurrent[REFERENCE_COLUMN].to_numpy(dtype=float)
    slope, intercept = total_least_squares_fit(reference, measured)
    predicted = slope * reference + intercept
    corrected = long_df[REFERENCE_COLUMN].to_numpy(dtype=float) * slope + intercept
    metrics = _regression_metrics(measured, predicted)
    metrics.update(
        {
            "algorithm": "total_least_squares",
            "slope": float(slope),
            "intercept": float(intercept),
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
        }
    )
    return _ltc_response(state, "total_least_squares", _result_frame(long_df, corrected), metrics)


def _run_ltc_speedsort(
    state: SessionState,
    short_col: str,
    long_col: str,
    short_dir_col: str = "",
    long_dir_col: str = "",
) -> dict:
    """Run SpeedSort LTC with a dog-leg low-speed segment and TLS on the high-speed tail.

    When *long_dir_col* is provided and present in the ERA5 data the algorithm
    performs directional binning: per-sector transfer functions are fitted for
    sectors containing at least ``SPEEDSORT_MIN_SECTOR_RECORDS`` concurrent
    records; sparse sectors fall back to the all-sector (direction-agnostic) fit.
    Otherwise the original non-directional behaviour is preserved.
    """
    _, long_df, concurrent = _concurrent_frame(state, short_col, long_col)
    measured = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    reference = concurrent[REFERENCE_COLUMN].to_numpy(dtype=float)

    # --- Directional path ---
    if long_dir_col and long_dir_col in state.era5_interpolated_df.columns:
        era5_dir = state.era5_interpolated_df[[long_dir_col]].copy()
        if era5_dir.index.tz is None:
            era5_dir.index = era5_dir.index.tz_localize("UTC")
        concurrent = concurrent.join(era5_dir, how="inner").dropna(subset=[long_dir_col])
        if len(concurrent) < 10:
            raise ValueError(
                f"SpeedSort requires at least 10 concurrent points with direction, got {len(concurrent)}"
            )
        measured = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
        reference = concurrent[REFERENCE_COLUMN].to_numpy(dtype=float)
        ref_dir = concurrent[long_dir_col].to_numpy(dtype=float)
        sectors = _speedsort_sector_index(ref_dir)

        # All-sector fallback model (for sparse sectors)
        threshold = float(min(4.0, 0.5 * float(np.mean(reference))))
        fallback_model: dict[str, float] | None = None
        mask_all = reference >= threshold
        if np.any(mask_all):
            slope_all, intercept_all = total_least_squares_fit(reference[mask_all], measured[mask_all])
            dog_leg_all = (
                float((slope_all * threshold + intercept_all) / threshold) if threshold > 0 else float(slope_all)
            )
            fallback_model = {
                "slope": slope_all,
                "intercept": intercept_all,
                "threshold": threshold,
                "dog_leg_slope": dog_leg_all,
            }

        # Per-sector fits
        sector_models: dict[int, dict[str, float]] = {}
        independent_count = 0
        for s in range(SPEEDSORT_NUM_SECTORS):
            s_mask = sectors == s
            n_records = int(s_mask.sum())
            if n_records < SPEEDSORT_MIN_SECTOR_RECORDS:
                if fallback_model is not None:
                    sector_models[s] = dict(fallback_model)
                continue
            s_ref = reference[s_mask]
            s_meas = measured[s_mask]
            s_thresh = float(min(4.0, 0.5 * float(np.mean(s_ref))))
            above = s_ref >= s_thresh
            if not np.any(above):
                if fallback_model is not None:
                    sector_models[s] = dict(fallback_model)
                continue
            slope, intercept = total_least_squares_fit(s_ref[above], s_meas[above])
            dog_leg = float((slope * s_thresh + intercept) / s_thresh) if s_thresh > 0 else float(slope)
            sector_models[s] = {
                "slope": slope,
                "intercept": intercept,
                "threshold": s_thresh,
                "dog_leg_slope": dog_leg,
                "count": float(n_records),
            }
            independent_count += 1

        if not sector_models:
            raise ValueError("SpeedSort could not build any sector model")

        # Predict concurrent (for metrics)
        predicted = np.empty_like(measured)
        for s, model in sector_models.items():
            s_mask = sectors == s
            s_ref = reference[s_mask]
            predicted[s_mask] = np.where(
                s_ref >= model["threshold"],
                s_ref * model["slope"] + model["intercept"],
                s_ref * model["dog_leg_slope"],
            )

        # Correct full long-term record using direction
        long_direction = era5_dir[long_dir_col].reindex(long_df.index).to_numpy(dtype=float)
        long_sectors = _speedsort_sector_index(long_direction)
        full_reference = long_df[REFERENCE_COLUMN].to_numpy(dtype=float)
        corrected = np.empty_like(full_reference)
        for s, model in sector_models.items():
            s_mask = long_sectors == s
            s_ref = full_reference[s_mask]
            corrected[s_mask] = np.where(
                s_ref >= model["threshold"],
                s_ref * model["slope"] + model["intercept"],
                s_ref * model["dog_leg_slope"],
            )

        metrics = _regression_metrics(measured, predicted)
        metrics.update(
            {
                "algorithm": "speedsort",
                "threshold": threshold,
                "concurrent_points": int(len(concurrent)),
                "total_corrected_points": int(len(long_df)),
                "directional": True,
                "num_sectors": SPEEDSORT_NUM_SECTORS,
                "sector_width_deg": SPEEDSORT_SECTOR_WIDTH_DEG,
                "min_sector_records": SPEEDSORT_MIN_SECTOR_RECORDS,
                "independent_sectors": independent_count,
                "sector_models": {
                    str(k): {key: float(val) for key, val in v.items()}
                    for k, v in sorted(sector_models.items())
                },
            }
        )
        return _ltc_response(state, "speedsort", _result_frame(long_df, corrected), metrics)

    # --- Original non-directional SpeedSort ---
    threshold = float(min(4.0, 0.5 * long_df[REFERENCE_COLUMN].mean()))
    mask = reference >= threshold
    if not np.any(mask):
        raise ValueError("SpeedSort found no concurrent points above the threshold")
    slope, intercept = total_least_squares_fit(reference[mask], measured[mask])
    dog_leg_slope = float((slope * threshold + intercept) / threshold) if threshold > 0 else float(slope)
    predicted = np.where(reference >= threshold, reference * slope + intercept, reference * dog_leg_slope)
    full_reference = long_df[REFERENCE_COLUMN].to_numpy(dtype=float)
    corrected = np.where(
        full_reference >= threshold,
        full_reference * slope + intercept,
        full_reference * dog_leg_slope,
    )
    metrics = _regression_metrics(measured, predicted)
    metrics.update(
        {
            "algorithm": "speedsort",
            "slope": float(slope),
            "intercept": float(intercept),
            "threshold": threshold,
            "dog_leg_slope": dog_leg_slope,
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
            "directional": False,
        }
    )
    return _ltc_response(state, "speedsort", _result_frame(long_df, corrected), metrics)


def _run_ltc_variance_ratio(state: SessionState, short_col: str, long_col: str) -> dict:
    """Run variance-ratio MCP using mean and standard-deviation scaling of the reference series."""
    _, long_df, concurrent = _concurrent_frame(state, short_col, long_col)
    measured = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    reference = concurrent[REFERENCE_COLUMN].to_numpy(dtype=float)
    measured_mean = float(np.mean(measured))
    reference_mean = float(np.mean(reference))
    measured_std = float(np.std(measured, ddof=1))
    reference_std = float(np.std(reference, ddof=1))
    if reference_std == 0.0:
        raise ValueError("Variance ratio is undefined when the reference standard deviation is zero")
    variance_ratio = measured_std / reference_std
    predicted = measured_mean + variance_ratio * (reference - reference_mean)
    corrected = measured_mean + variance_ratio * (long_df[REFERENCE_COLUMN].to_numpy(dtype=float) - reference_mean)
    metrics = _regression_metrics(measured, predicted)
    metrics.update(
        {
            "algorithm": "variance_ratio",
            "measured_mean": measured_mean,
            "reference_mean": reference_mean,
            "measured_std": measured_std,
            "reference_std": reference_std,
            "variance_ratio": variance_ratio,
            "correlation": _pearson_correlation(measured, reference),
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
        }
    )
    return _ltc_response(state, "variance_ratio", _result_frame(long_df, corrected), metrics)


@mcp.tool()
def run_ltc_linear_least_squares(short_col: str, long_col: str) -> dict:
    """Run robust linear MCP using Huber IRLS and apply the fit to the full long-term record."""
    return _run_ltc_linear_least_squares(session, short_col, long_col)


@mcp.tool()
def run_ltc_total_least_squares(short_col: str, long_col: str) -> dict:
    """Run orthogonal total least squares MCP and apply the fit to the full long-term record."""
    return _run_ltc_total_least_squares(session, short_col, long_col)


@mcp.tool()
def run_ltc_speedsort(
    short_col: str,
    long_col: str,
    short_dir_col: str = "",
    long_dir_col: str = "",
) -> dict:
    """Run directional SpeedSort LTC with per-sector transfer functions and dog-leg low-speed segment.

    When *long_dir_col* is supplied and present in ERA5, the algorithm bins by
    12 direction sectors (30° each) and fits an independent transfer function
    per sector.  Sectors with fewer than 200 concurrent records fall back to
    the all-sector fit.  Without *long_dir_col* the original non-directional
    behaviour is preserved.
    """
    return _run_ltc_speedsort(session, short_col, long_col, short_dir_col, long_dir_col)


@mcp.tool()
def run_ltc_variance_ratio(short_col: str, long_col: str) -> dict:
    """Run variance-ratio MCP using mean and standard-deviation scaling of the reference series."""
    return _run_ltc_variance_ratio(session, short_col, long_col)
