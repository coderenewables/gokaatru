"""ltc — Phase 3 MCP tools for deterministic long-term correction algorithms.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from server.core.regression import robust_huber_fit, total_least_squares_fit
from server.core.validators import (
    TIMESTAMP_LABEL_CHOICES,
    TIMESTAMP_LABEL_CONVENTION,
    detect_timestep_minutes,
    to_utc_index,
)
from server.main import mcp
from server.state.session import SessionState, session

MEASURED_COLUMN = "__measured__"
REFERENCE_COLUMN = "__reference__"

SPEEDSORT_NUM_SECTORS = 12
SPEEDSORT_SECTOR_WIDTH_DEG = 30.0
SPEEDSORT_MIN_SECTOR_RECORDS = 200

# Huber IRLS tuning constant used by `linear_least_squares` (F-37).
HUBER_DELTA = 1.35

# Hard floor for a defensible MCP: six months of valid concurrent hourly pairs
# (D9.1).  Counted as records rather than calendar span, so a gappy nine-month
# overlap is judged on the data it actually contains.
MIN_CONCURRENT_HOURS = 4380

# Measured data is resampled to hourly *means* while the reanalysis reference is
# *instantaneous* (D9.2).  Averaging removes within-hour variance from the
# measured side only, which biases any pure std-ratio method — variance_ratio
# above all — low.  Disclosed in every LTC response rather than corrected: which
# matching convention is right is a methodology decision for the analyst.
RESAMPLING_NOTE = (
    "Measured data is resampled to hourly means while the reanalysis reference is "
    "instantaneous. This removes within-hour variance from the measured series only, "
    "biasing variance-ratio (std-ratio) results low. Slope-based methods are far less "
    "affected."
)


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


def _align_timestamp_label(state: SessionState, frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Shift the measured index onto interval-start, which is what the reference assumes.

    IEA Task 43 permits interval-start, -end and -centre labelling, and GoKaatru never
    declared or checked which one a file used (F-07).  Reanalysis references are
    instantaneous, so a measured series labelled by interval *end* sits a full interval
    later than the flow it describes and every LTC pairs it against the wrong reference
    hour - a systematic offset, not noise.

    The convention is a property of the logger, so it cannot be inferred from the data.  It
    is read from the run configuration, defaults to interval-start, and any shift applied is
    reported with the result.
    """
    label = str(state.runconfig.get("timestamp_label", TIMESTAMP_LABEL_CONVENTION))
    if label not in TIMESTAMP_LABEL_CHOICES:
        raise ValueError(
            f"timestamp_label must be one of {', '.join(TIMESTAMP_LABEL_CHOICES)}, got '{label}'"
        )
    disclosure: dict[str, object] = {"timestamp_label": label}
    if label == TIMESTAMP_LABEL_CONVENTION:
        disclosure["timestamp_shift_minutes"] = 0.0
        return frame, disclosure
    try:
        timestep_minutes = float(detect_timestep_minutes(frame))
    except ValueError:
        disclosure["timestamp_shift_minutes"] = 0.0
        disclosure["timestamp_shift_note"] = "Cadence could not be detected, so no shift was applied."
        return frame, disclosure
    shift = timestep_minutes if label == "interval_end" else timestep_minutes / 2.0
    shifted = frame.copy()
    shifted.index = pd.DatetimeIndex(shifted.index) - pd.Timedelta(minutes=shift)
    disclosure["timestamp_shift_minutes"] = float(shift)
    disclosure["timestamp_shift_note"] = (
        f"The measured index was shifted back {shift:g} minutes to interval-start before "
        "matching, because the run configuration declares it was labelled by "
        f"{label.replace('_', ' ')}."
    )
    return shifted, disclosure


# F-66.  A half-populated hour carries higher variance than a full one, which feeds
# straight into the variance-ratio LTC.  50% is a defensible threshold; what was not
# defensible is that it appeared in no response, no constant and no documentation.
HOURLY_COVERAGE_MINIMUM = 0.5


def _prepare_short_term(short_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Resample sub-hourly measured data to hourly means, dropping under-populated hours.

    An hour is kept when at least ``HOURLY_COVERAGE_MINIMUM`` of its expected sub-hourly
    samples are present, so a 1-of-6 hour is dropped and a 3-of-6 hour is kept and averaged
    as though it were full.  That is a real trade - a partly-populated hour is noisier than
    a full one - and the counts are now reported so it can be judged (F-66).
    """
    try:
        timestep_minutes = detect_timestep_minutes(short_df)
    except ValueError:
        return short_df, {"hourly_resampled": False, "hourly_resample_reason": "cadence_undetectable"}
    if timestep_minutes >= 60:
        return short_df, {"hourly_resampled": False}
    expected_samples = max(1.0, 60.0 / timestep_minutes)
    hourly_mean = short_df.resample("h").mean()
    hourly_count = short_df.resample("h").count()
    coverage = hourly_count.iloc[:, 0] / expected_samples
    kept = coverage >= HOURLY_COVERAGE_MINIMUM
    populated = coverage > 0.0
    partial = kept & (coverage < 1.0)
    return hourly_mean.loc[kept], {
        "hourly_resampled": True,
        "hourly_coverage_minimum": HOURLY_COVERAGE_MINIMUM,
        "hourly_expected_samples": float(expected_samples),
        "hours_kept": int(kept.sum()),
        "hours_dropped_below_minimum": int((populated & ~kept).sum()),
        "hours_kept_partially_populated": int(partial.sum()),
        "hourly_coverage_note": (
            f"Hours with at least {HOURLY_COVERAGE_MINIMUM:.0%} of their expected "
            f"{expected_samples:g} sub-hourly samples were kept and averaged as full hours. "
            "A partly-populated hour is noisier than a full one, which biases variance-ratio "
            "results in particular."
        ),
    }


def _concurrent_frame(
    state: SessionState,
    short_col: str,
    long_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the measured, reference, and concurrent datasets used by LTC algorithms."""
    short_df, long_df = _require_ltc_inputs(state, short_col, long_col)
    # Align the interval label before averaging, so an interval-end series is binned into
    # the hour it describes rather than the following one (F-07).
    short_df, label_disclosure = _align_timestamp_label(state, short_df)
    prepared_short, coverage_disclosure = _prepare_short_term(short_df)
    state.ltc_matching_disclosure = {**label_disclosure, **coverage_disclosure}
    # Ensure both indexes are tz-aware UTC for a safe inner join (D8).
    prepared_short = to_utc_index(prepared_short)
    long_df = to_utc_index(long_df)
    concurrent = prepared_short.join(long_df, how="inner").dropna()
    if len(concurrent) < MIN_CONCURRENT_HOURS:
        raise ValueError(
            f"LTC requires at least {MIN_CONCURRENT_HOURS} valid concurrent records "
            f"(six months at hourly resolution), got {len(concurrent)}. "
            "A shorter concurrent period does not support a defensible long-term "
            "correction, so no result is produced rather than one that invites use."
        )
    return prepared_short, long_df, concurrent


def _resampling_disclosure(state: SessionState) -> dict[str, object]:
    """Report how the measured series was matched to the reference before fitting (D9.2).

    Carries three separate decisions the caller cannot otherwise see: whether the measured
    series was averaged to hourly at all, which interval label it was assumed to carry
    (F-07), and how many hours the coverage gate kept, dropped or accepted partly populated
    (F-66).
    """
    frame = state.timeseries_df
    matching = dict(state.ltc_matching_disclosure)
    if frame is None:
        return matching
    try:
        timestep_minutes = detect_timestep_minutes(frame)
    except ValueError:
        return matching
    if timestep_minutes >= 60:
        return {
            "measured_resampled_to_hourly": False,
            "measured_timestep_minutes": int(timestep_minutes),
            **matching,
        }
    return {
        "measured_resampled_to_hourly": True,
        "measured_timestep_minutes": int(timestep_minutes),
        "resampling_note": RESAMPLING_NOTE,
        **matching,
    }


def _clip_negative_predictions(corrected: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    """Clip negative predicted speeds to zero and report how many were clipped (D9.3).

    A non-trivial count means the transfer function is producing physically
    impossible speeds, so the truncation is reported rather than applied silently.
    """
    values = np.asarray(corrected, dtype=float)
    negative = int(np.count_nonzero(values < 0.0))
    total = int(values.size)
    return np.clip(values, 0.0, None), {
        "negative_predictions_clipped": negative,
        "negative_predictions_clipped_fraction": float(negative / total) if total else 0.0,
    }


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
    """Build the standard LTC result dataframe with timestamp and corrected wind speeds.

    ``corrected`` must already be clipped by :func:`_clip_negative_predictions`
    so the clipped count reaches the metrics instead of vanishing here.
    """
    return pd.DataFrame(
        {
            "Timestamp": reference_df.index,
            "ERA5_original": reference_df[REFERENCE_COLUMN].to_numpy(dtype=float),
            "corrected_wind_speed": np.asarray(corrected, dtype=float),
        }
    )


def _save_ltc_result(state: SessionState, algorithm: str, result_df: pd.DataFrame, metrics: dict[str, object]) -> str:
    """Persist an LTC result to CSV and store it in session state."""
    output_dir = Path(state.get_data_dir()) / "ltc_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output_path = output_dir / f"ltc_{algorithm}_{timestamp}.csv"
    result_df.to_csv(output_path, index=False)
    state.ltc_results[algorithm] = {"df": result_df.copy(), "metrics": metrics.copy(), "file": str(output_path)}
    state.stamp_derived(f"ltc:{algorithm}")
    return str(output_path)


def _variance_attenuation(reference_df: pd.DataFrame, corrected: np.ndarray) -> dict[str, object]:
    """Report how much of the reference's variance the transfer function retained (F-38).

    A slope fit retains exactly R-squared of the target variance, so every regression method
    attenuates variability while variance-ratio scaling preserves it by construction.
    Measured across the four algorithms on one dataset, the spread reached 0.58 points of
    inter-annual variability - a ~10% relative difference in the quantity that drives
    ``u_future`` and the clipping objective.

    The README already discloses the *resampling* variance loss; this is the separate
    *regression* attenuation, which the ensemble then blends into a mixture nothing
    described. Reported rather than corrected: which variance a long-term series should
    carry is a methodology decision, not an implementation detail.
    """
    reference = reference_df[REFERENCE_COLUMN].to_numpy(dtype=float)
    values = np.asarray(corrected, dtype=float)
    valid = np.isfinite(reference) & np.isfinite(values)
    if int(valid.sum()) < 3:
        return {}
    reference_std = float(np.std(reference[valid], ddof=1))
    corrected_std = float(np.std(values[valid], ddof=1))
    if reference_std <= 0.0:
        return {}
    # A slope fit maps the reference linearly, so the ratio of standard deviations is the
    # slope's magnitude; what matters downstream is the spread it leaves in the result.
    ratio = corrected_std / reference_std
    # Names are prefixed: `variance_ratio` already reports its own concurrent-period
    # `measured_std` / `reference_std`, and these are long-term quantities.
    report: dict[str, object] = {
        "long_term_corrected_std": round(corrected_std, 6),
        "long_term_reference_std": round(reference_std, 6),
        "variance_ratio_to_reference": round(ratio, 6),
        "variance_note": (
            "Ratio of the corrected series' standard deviation to the reference's. Slope "
            "methods retain R-squared of the target variance and so attenuate variability; "
            "variance_ratio preserves it by construction. This spread flows into the "
            "inter-annual variability that drives u_future and the clipping objective, and "
            "the ensemble blends variance-preserving with variance-attenuating components."
        ),
    }
    corrected_mean = float(np.mean(values[valid]))
    if corrected_mean > 0.0:
        report["long_term_coefficient_of_variation"] = round(corrected_std / corrected_mean, 6)
    return report


def _ltc_response(
    state: SessionState,
    algorithm: str,
    reference_df: pd.DataFrame,
    corrected: np.ndarray,
    metrics: dict[str, object],
) -> dict:
    """Clip, disclose, save an LTC result and return the standard MCP tool response payload.

    Clipping (D9.3) and the resampling disclosure (D9.2) live here so every
    algorithm reports them identically and none can quietly omit them.
    """
    clipped, clip_stats = _clip_negative_predictions(corrected)
    metrics.update(clip_stats)
    metrics.update(_resampling_disclosure(state))
    metrics.update(_variance_attenuation(reference_df, clipped))
    result_df = _result_frame(reference_df, clipped)
    result_file = _save_ltc_result(state, algorithm, result_df, metrics)
    return {"status": "ok", "algorithm": algorithm, "metrics": metrics, "result_file": result_file}


def _run_ltc_linear_least_squares(state: SessionState, short_col: str, long_col: str) -> dict:
    """Run robust linear MCP using Huber IRLS and apply the fit to the full long-term record."""
    _, long_df, concurrent = _concurrent_frame(state, short_col, long_col)
    measured = concurrent[MEASURED_COLUMN].to_numpy(dtype=float)
    reference = concurrent[REFERENCE_COLUMN].to_numpy(dtype=float)
    slope, intercept, y_hat, r_squared = robust_huber_fit(reference, measured, delta=HUBER_DELTA)
    corrected = long_df[REFERENCE_COLUMN].to_numpy(dtype=float) * slope + intercept
    metrics = _regression_metrics(measured, y_hat)
    metrics.update(
        {
            "algorithm": "linear_least_squares",
            # F-37: the tool is named for least squares and fits Huber IRLS. Huber is the
            # better estimator under contamination - measured +1.83% on slope against OLS
            # with 2% frozen-sensor records - but a response that asserts a method it does
            # not use cannot be reconciled against WAsP, windPRO or Windographer OLS, and
            # reconciliation is exactly what the name invites.
            "estimator": "huber_irls",
            "huber_delta": HUBER_DELTA,
            "estimator_note": (
                "Fitted by Huber IRLS with delta = 1.35, not ordinary least squares, despite "
                "the tool name. Huber down-weights outliers, so the slope will not reconcile "
                "exactly against an OLS fit in WAsP, windPRO or Windographer - measured "
                "differences run from -0.03% on clean data to +1.83% with 2% contamination."
            ),
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": r_squared,
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
        }
    )
    return _ltc_response(state, "linear_least_squares", long_df, corrected, metrics)


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
            # F-43: orthogonal regression is the maximum-likelihood fit only when the two
            # series carry equal error variance. Reanalysis error greatly exceeds mast
            # error, so neither TLS (ratio 1) nor OLS (ratio 0) sits at the right point.
            "error_variance_ratio_assumed": 1.0,
            "error_variance_note": (
                "Total least squares assumes equal error variance in the measured and "
                "reference series. Reanalysis error greatly exceeds mast error, so this "
                "assumption does not hold and TLS overshoots the slope: measured 1.138 "
                "against a true 1.080 with all error in the measured series, a 5.4% "
                "overshoot worth about +0.5% on the long-term mean. OLS sits at the other "
                "extreme (ratio 0); Deming regression needs an error-variance ratio nothing "
                "in this pipeline supplies. Treat TLS and linear_least_squares as bracketing "
                "the answer rather than as peer algorithms."
            ),
            "slope": float(slope),
            "intercept": float(intercept),
            "concurrent_points": int(len(concurrent)),
            "total_corrected_points": int(len(long_df)),
        }
    )
    return _ltc_response(state, "total_least_squares", long_df, corrected, metrics)


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
        era5_dir = to_utc_index(state.era5_interpolated_df[[long_dir_col]].copy())
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

        # Predict concurrent (for metrics).  NaN-filled, not `np.empty_like`: a record
        # whose sector has no model must stay absent rather than inherit whatever was
        # last in that memory.
        predicted = np.full(measured.shape, np.nan, dtype=float)
        for s, model in sector_models.items():
            s_mask = sectors == s
            s_ref = reference[s_mask]
            predicted[s_mask] = np.where(
                s_ref >= model["threshold"],
                s_ref * model["slope"] + model["intercept"],
                s_ref * model["dog_leg_slope"],
            )
        scored = np.isfinite(predicted)
        if not scored.any():
            raise ValueError("SpeedSort produced no predictions for the concurrent period")

        # Correct full long-term record using direction.  A NaN reference direction has
        # no sector, so those records cannot be corrected: they must come out NaN and be
        # counted, not silently inherit uninitialised memory (a plausible-looking 0.0
        # would pass the negative-prediction check and drag the long-term mean down).
        long_direction = era5_dir[long_dir_col].reindex(long_df.index).to_numpy(dtype=float)
        directionless = ~np.isfinite(long_direction)
        long_sectors = _speedsort_sector_index(np.where(directionless, 0.0, long_direction))
        long_sectors[directionless] = -1
        full_reference = long_df[REFERENCE_COLUMN].to_numpy(dtype=float)
        corrected = np.full(full_reference.shape, np.nan, dtype=float)
        for s, model in sector_models.items():
            s_mask = long_sectors == s
            s_ref = full_reference[s_mask]
            corrected[s_mask] = np.where(
                s_ref >= model["threshold"],
                s_ref * model["slope"] + model["intercept"],
                s_ref * model["dog_leg_slope"],
            )
        unmodelled = int(np.count_nonzero(~np.isfinite(corrected)))

        metrics = _regression_metrics(measured[scored], predicted[scored])
        metrics.update(
            {
                "algorithm": "speedsort",
                "threshold": threshold,
                "concurrent_points": int(len(concurrent)),
                "concurrent_points_scored": int(scored.sum()),
                "total_corrected_points": int(len(long_df)),
                "directional": True,
                "num_sectors": SPEEDSORT_NUM_SECTORS,
                "sector_width_deg": SPEEDSORT_SECTOR_WIDTH_DEG,
                "min_sector_records": SPEEDSORT_MIN_SECTOR_RECORDS,
                "independent_sectors": independent_count,
                "reference_direction_missing": int(directionless.sum()),
                "unmodelled_records": unmodelled,
                "unmodelled_fraction": float(unmodelled / len(long_df)) if len(long_df) else 0.0,
                "sector_models": {
                    str(k): {key: float(val) for key, val in v.items()}
                    for k, v in sorted(sector_models.items())
                },
            }
        )
        if unmodelled:
            metrics["warning"] = (
                f"{unmodelled:,} of {len(long_df):,} long-term records "
                f"({unmodelled / len(long_df):.1%}) could not be corrected because the reference "
                "direction is missing or their sector has no model. They are returned as NaN, so "
                "any downstream mean, ensemble or clipping run covers a shorter period than the "
                "reference series."
            )
        return _ltc_response(state, "speedsort", long_df, corrected, metrics)

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
    return _ltc_response(state, "speedsort", long_df, corrected, metrics)


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
    return _ltc_response(state, "variance_ratio", long_df, corrected, metrics)


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
