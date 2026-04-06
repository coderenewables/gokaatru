"""ensemble — Phase 4 MCP tool for multi-algorithm long-term correction blending.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from server.main import mcp
from server.state.session import session


def _measured_series(measured_col: str) -> pd.Series:
    """Return the measured wind-speed series for ensemble scoring using overlap-period bias and RMSE."""
    if session.timeseries_df is None:
        raise ValueError("Measured timeseries is not loaded")
    if measured_col not in session.timeseries_df.columns:
        raise ValueError(f"Measured column '{measured_col}' not found in session.timeseries_df")
    return session.timeseries_df[measured_col].copy()


def _ltc_result_series(algorithm: str) -> pd.Series:
    """Return a corrected LTC series indexed by timestamp using the Phase 3 result-file schema."""
    payload = session.ltc_results.get(algorithm)
    if payload is None or "df" not in payload:
        raise ValueError(f"LTC result for algorithm '{algorithm}' is not available")
    frame = pd.DataFrame(payload["df"]).copy()
    if "Timestamp" in frame.columns:
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        frame = frame.dropna(subset=["Timestamp"]).set_index("Timestamp")
    if "corrected_wind_speed" not in frame.columns:
        raise ValueError(f"LTC result for '{algorithm}' does not contain 'corrected_wind_speed'")
    return frame["corrected_wind_speed"].sort_index()


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


def _ensemble_output_path() -> Path:
    """Return the standard Phase 4 ensemble CSV output path under data/ltc_results."""
    output_dir = Path(session.get_data_dir()) / "ltc_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return output_dir / f"ensemble_{timestamp}.csv"


@mcp.tool()
def run_ensemble(measured_col: str) -> dict:
    """Blend LTC algorithms using inverse-RMSE weights and overlap-period bias correction per MCP ensemble practice."""
    algorithms = sorted(session.ltc_results.keys())
    if len(algorithms) < 2:
        raise ValueError(f"Ensemble requires at least 2 LTC results, got {len(algorithms)}")
    measured = _measured_series(measured_col)
    component_series = {algorithm: _ltc_result_series(algorithm) for algorithm in algorithms}
    overlap_stats = {algorithm: _overlap_metrics(measured, series) for algorithm, series in component_series.items()}
    inverse_rmse = {
        algorithm: 0.0 if stats["rmse"] <= 0.0 else 1.0 / stats["rmse"] for algorithm, stats in overlap_stats.items()
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
    for algorithm, series in component_series.items():
        corrected = series.reindex(aligned.index) - overlap_stats[algorithm]["bias"]
        aligned[algorithm] = corrected
        weighted_sum += corrected.fillna(0.0).to_numpy(dtype=float) * weights[algorithm]
    aligned["Ensemble_Speed"] = weighted_sum
    overlap = pd.concat([measured.rename("measured"), aligned["Ensemble_Speed"]], axis=1, join="inner").dropna()
    metrics = _overlap_metrics(overlap["measured"], overlap["Ensemble_Speed"])
    output = aligned.reset_index(names="Timestamp")
    output_path = _ensemble_output_path()
    output.to_csv(output_path, index=False)
    session.ensemble_df = output.copy()
    return {
        "status": "ok",
        "weights": weights,
        "metrics": {"rmse": metrics["rmse"], "r2": metrics["r2"], "bias": metrics["bias"]},
        "result_file": str(output_path),
    }
