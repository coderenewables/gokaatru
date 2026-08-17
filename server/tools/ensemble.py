"""ensemble — Phase 4 MCP tool for multi-algorithm long-term correction blending.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from server.core.validators import to_utc_index
from server.main import mcp
from server.state.session import SessionState, session

# Inverse-RMSE weighting needs a floor so a vanishing RMSE cannot take the entire
# blend on the strength of round-off.  The floor is relative to the worst component,
# so it scales with the data rather than assuming a unit; the absolute minimum only
# guards the case where every component is effectively exact.
RMSE_FLOOR_FRACTION = 1e-6
MIN_RMSE_FLOOR = 1e-12


def _measured_series(state: SessionState, measured_col: str) -> pd.Series:
    """Return the measured wind-speed series for ensemble scoring using overlap-period bias and RMSE."""
    if state.timeseries_df is None:
        raise ValueError("Measured timeseries is not loaded")
    if measured_col not in state.timeseries_df.columns:
        raise ValueError(f"Measured column '{measured_col}' not found in session.timeseries_df")
    return to_utc_index(state.timeseries_df[measured_col].copy())


def _ltc_result_series(state: SessionState, algorithm: str) -> pd.Series:
    """Return a corrected LTC series indexed by timestamp using the Phase 3 result-file schema."""
    payload = state.ltc_results.get(algorithm)
    if payload is None or "df" not in payload:
        raise ValueError(f"LTC result for algorithm '{algorithm}' is not available")
    frame = pd.DataFrame(payload["df"]).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if "corrected_wind_speed" not in frame.columns:
        raise ValueError(f"LTC result for '{algorithm}' does not contain 'corrected_wind_speed'")
    # LTC results are tz-aware UTC; the measured series may be naive (D8 is only
    # enforced on the file-ingest path), so normalize before any inner join.
    return to_utc_index(frame["corrected_wind_speed"].sort_index())


def _overlap_metrics(observed: pd.Series, predicted: pd.Series) -> dict[str, float]:
    """Compute overlap-period bias, RMSE, and $R^2$ for inverse-RMSE ensemble weighting."""
    overlap = pd.concat([observed, predicted], axis=1, join="inner").dropna()
    if overlap.empty:
        raise ValueError("Ensemble requires overlapping measured and corrected timestamps")
    measured = overlap.iloc[:, 0].to_numpy(dtype=float)
    corrected = overlap.iloc[:, 1].to_numpy(dtype=float)
    residuals = corrected - measured
    rmse = float(np.sqrt(np.mean(residuals**2)))
    ss_res = float(np.sum((measured - corrected) ** 2))
    ss_tot = float(np.sum((measured - measured.mean()) ** 2))
    r_squared = 0.0 if ss_tot == 0.0 else float(1.0 - ss_res / ss_tot)
    return {
        "bias": float(np.mean(residuals)),
        "rmse": rmse,
        "r2": r_squared,
        "count": int(len(overlap)),
    }


def _coverage_summary(
    covered_weight: np.ndarray,
    component_series: dict[str, pd.Series],
    index: pd.DatetimeIndex,
) -> dict[str, object]:
    """Report how much of the blend weight each timestamp actually carried.

    A blend built from partially overlapping components is legitimate but its basis
    varies along the series, so the split has to travel with the result rather than
    being inferred from the component CSV columns.
    """
    total = int(covered_weight.size)
    full = int(np.count_nonzero(covered_weight >= 1.0 - 1e-9))
    empty = int(np.count_nonzero(covered_weight <= 0.0))
    partial = total - full - empty
    return {
        "total_records": total,
        "fully_covered_records": full,
        "partially_covered_records": partial,
        "partially_covered_fraction": float(partial / total) if total else 0.0,
        "uncovered_records": empty,
        "component_records": {
            algorithm: int(series.reindex(index).notna().sum())
            for algorithm, series in component_series.items()
        },
    }


def _ensemble_output_path(state: SessionState) -> Path:
    """Return the standard Phase 4 ensemble CSV output path under data/ltc_results."""
    output_dir = Path(state.get_data_dir()) / "ltc_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return output_dir / f"ensemble_{timestamp}.csv"


def _run_ensemble(state: SessionState, measured_col: str) -> dict:
    """Blend LTC algorithms using inverse-RMSE weights and overlap-period bias correction per MCP ensemble practice."""
    algorithms = sorted(state.ltc_results.keys())
    if len(algorithms) < 2:
        raise ValueError(f"Ensemble requires at least 2 LTC results, got {len(algorithms)}")
    measured = _measured_series(state, measured_col)
    component_series = {algorithm: _ltc_result_series(state, algorithm) for algorithm in algorithms}
    overlap_stats = {algorithm: _overlap_metrics(measured, series) for algorithm, series in component_series.items()}
    # Prefer out-of-sample RMSE where available (e.g. XGBoost validation slice),
    # falling back to overlap RMSE for algorithms that do not provide it (D10).
    effective_rmse: dict[str, float] = {}
    for algorithm, stats in overlap_stats.items():
        payload = state.ltc_results.get(algorithm, {})
        stored_metrics: dict[str, object] = payload.get("metrics", {}) if isinstance(payload, dict) else {}
        oos_rmse = stored_metrics.get("out_of_sample_rmse")
        if isinstance(oos_rmse, (int, float)) and oos_rmse > 0.0:
            effective_rmse[algorithm] = float(oos_rmse)
        else:
            effective_rmse[algorithm] = stats["rmse"]
    # A zero RMSE means a component reproduced the measured series exactly: the best
    # possible fit, not the worst.  Guarding the reciprocal with `0.0 if rmse <= 0`
    # inverted that — it handed a perfect component weight 0 and excluded it, while a
    # component with RMSE 1e-9 took the whole blend.  Floor the RMSE instead, so the
    # weighting stays monotone and continuous through zero.
    finite_rmse = {
        algorithm: rmse
        for algorithm, rmse in effective_rmse.items()
        if np.isfinite(rmse) and rmse >= 0.0
    }
    if not finite_rmse:
        raise ValueError("Ensemble weights are undefined because no component reported a usable RMSE")
    rmse_floor = max(RMSE_FLOOR_FRACTION * max(finite_rmse.values()), MIN_RMSE_FLOOR)
    inverse_rmse = {
        algorithm: 1.0 / max(rmse, rmse_floor) for algorithm, rmse in finite_rmse.items()
    }
    total_inverse_rmse = float(sum(inverse_rmse.values()))
    if total_inverse_rmse <= 0.0:
        raise ValueError("Ensemble weights are undefined because all component RMSE values are zero or invalid")
    weights = {algorithm: float(value / total_inverse_rmse) for algorithm, value in inverse_rmse.items()}
    all_index = pd.DatetimeIndex([])
    for series in component_series.values():
        all_index = all_index.union(series.index)
    aligned = pd.DataFrame(index=all_index.sort_values())
    weighted_sum = np.zeros(len(aligned), dtype=float)
    covered_weight = np.zeros(len(aligned), dtype=float)
    for algorithm, series in component_series.items():
        corrected = series.reindex(aligned.index) - overlap_stats[algorithm]["bias"]
        aligned[algorithm] = corrected
        values = corrected.to_numpy(dtype=float)
        present = np.isfinite(values)
        weighted_sum[present] += values[present] * weights[algorithm]
        covered_weight[present] += weights[algorithm]
    # Renormalise by the weight actually present at each timestamp.  The index is the
    # union of the component indexes, so components rarely cover it identically:
    # XGBoost's feature join drops rows, SpeedSort can leave records unmodelled, and
    # two algorithms run against different reanalysis vintages disagree outright.
    # Treating an absent component as a zero contribution while still applying only
    # the remaining fractional weights scales the blend down by the missing weight —
    # a two-component ensemble reports *half* the wind speed wherever one component
    # is absent, and the result is finite, so nothing reveals it.  Dividing by the
    # covered weight leaves a fully-covered timestamp untouched and makes a partly
    # covered one the weighted mean of the components that actually exist.
    ensemble = np.divide(
        weighted_sum,
        covered_weight,
        out=np.full(len(aligned), np.nan, dtype=float),
        where=covered_weight > 0.0,
    )
    aligned["Ensemble_Speed"] = ensemble
    coverage = _coverage_summary(covered_weight, component_series, aligned.index)
    overlap = pd.concat([measured.rename("measured"), aligned["Ensemble_Speed"]], axis=1, join="inner").dropna()
    metrics = _overlap_metrics(overlap["measured"], overlap["Ensemble_Speed"])
    output = aligned.reset_index(names="Timestamp")
    output_path = _ensemble_output_path(state)
    output.to_csv(output_path, index=False)
    state.ensemble_df = output.copy()
    response: dict[str, object] = {
        "status": "ok",
        "weights": weights,
        "metrics": {"rmse": metrics["rmse"], "r2": metrics["r2"], "bias": metrics["bias"]},
        "component_coverage": coverage,
        "result_file": str(output_path),
    }
    if int(coverage["partially_covered_records"]) > 0:
        response["warning"] = (
            f"{coverage['partially_covered_records']:,} of {coverage['total_records']:,} timestamps "
            f"({coverage['partially_covered_fraction']:.1%}) are covered by only some components. "
            "Those records are the weighted mean of the components present, so the blend basis "
            "varies across the series — check why the component series differ in extent before "
            "using the ensemble for clipping or uncertainty."
        )
    return response


@mcp.tool()
def run_ensemble(measured_col: str) -> dict:
    """Blend LTC algorithms using inverse-RMSE weights and overlap-period bias correction per MCP ensemble practice."""
    return _run_ensemble(session, measured_col)
