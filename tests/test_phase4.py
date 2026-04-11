"""test_phase4 — Verification tests for GoKaatru Phase 4 features.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import asyncio
import json
import math

import numpy as np
import pandas as pd

from server.main import mcp
from server.state.session import session
from server.tools.clipping import run_clipping_analysis
from server.tools.config import update_run_config
from server.tools.ensemble import run_ensemble
from server.tools.homogeneity import analyze_homogeneity
from server.tools.map import get_mast_marker
from server.tools.uncertainty import calculate_uncertainty
from server.tools.visualization import plot_weibull


def _ltc_result_frame(index: pd.DatetimeIndex, values: np.ndarray) -> pd.DataFrame:
    """Create a standard LTC result dataframe with Timestamp and corrected wind speed columns."""
    return pd.DataFrame({"Timestamp": index, "ERA5_original": values, "corrected_wind_speed": values})


def test_ensemble_weights_sum_to_one(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify inverse-RMSE ensemble weights sum to unity across at least two LTC algorithms."""
    measured = sample_timeseries_df.iloc[:240].copy()
    session.timeseries_df = measured
    index = measured.index
    base = measured["Spd_100m"].to_numpy(dtype=float)
    session.ltc_results = {
        "algo_a": {"df": _ltc_result_frame(index, base * 1.02), "metrics": {}, "file": "a.csv"},
        "algo_b": {"df": _ltc_result_frame(index, base * 0.98), "metrics": {}, "file": "b.csv"},
    }
    result = run_ensemble("Spd_100m")
    assert math.isclose(sum(result["weights"].values()), 1.0, rel_tol=1e-9)
    assert session.ensemble_df is not None


def test_clipping_returns_optimal_year() -> None:
    """Verify clipping analysis prefers the post-shift stable period when early years are biased low."""
    index = pd.date_range("2000-01-01", "2020-12-31", freq="ME")
    values = np.where(index.year < 2010, 6.0, 8.0) + 0.05 * np.sin(np.arange(len(index)))
    session.ensemble_df = pd.DataFrame({"Timestamp": index, "Ensemble_Speed": values})
    result = run_clipping_analysis("Ensemble_Speed")
    assert result["optimal_start_year"] >= 2010


def test_pettitt_detects_shift() -> None:
    """Verify Pettitt homogeneity screening reports a statistically significant shift for a synthetic breakpoint."""
    index = pd.date_range("2000-01-01", "2019-12-31", freq="ME")
    values = np.where(index.year < 2010, 6.0, 8.0) + 0.02 * np.cos(np.arange(len(index)))
    session.era5_data = {"52.25_4.75": pd.DataFrame({"Spd_100m": values}, index=index)}
    result = analyze_homogeneity("monthly")
    assert result["datasets"]
    assert result["datasets"][0]["pettitt_p_value"] < 0.01


def test_uncertainty_components() -> None:
    """Verify total uncertainty follows root-sum-square combination of the reported component model."""
    result = calculate_uncertainty(3.0, 100.0, 150.0, "simple_power_law", 0.9, 8760.0)
    expected_vertical = 0.03 * abs(math.log(150.0 / 100.0)) * 100.0
    expected_mcp = 3.0 / math.sqrt(12.0) + (1.0 - 0.9) * 4.0
    expected_future = 6.0 / math.sqrt(20.0)
    expected_total = math.sqrt(3.0**2 + expected_vertical**2 + expected_mcp**2 + expected_future**2)
    assert math.isclose(result["total_uncertainty_pct"], round(expected_total, 2), abs_tol=0.01)


def test_uncertainty_p_factors_ordering() -> None:
    """Verify exceedance factors decrease monotonically from P50 to P99 as uncertainty increases."""
    result = calculate_uncertainty(3.5, 100.0, 140.0, "calculate_shear", 0.85, 4380.0, shear_std=0.02)
    p_factors = result["p_factors"]
    assert p_factors["p50"] > p_factors["p75"] > p_factors["p90"] > p_factors["p99"]


def test_plot_weibull_returns_plotly_json(sample_timeseries_df: pd.DataFrame) -> None:
    """Verify Weibull plotting returns Plotly JSON that parses as a valid figure payload."""
    session.timeseries_df = sample_timeseries_df.copy()
    result = plot_weibull("Spd_100m")
    parsed = json.loads(result["plotly_json"])
    assert "data" in parsed
    assert result["title"].startswith("Weibull Fit")


def test_geojson_mast_marker() -> None:
    """Verify the site mast marker is returned as a valid GeoJSON point feature."""
    update_run_config("location.latitude", "52.4")
    update_run_config("location.longitude", "4.8")
    marker = get_mast_marker()
    assert marker["type"] == "Feature"
    assert marker["geometry"]["type"] == "Point"
    assert marker["geometry"]["coordinates"] == [4.8, 52.4]


def test_all_tools_registered() -> None:
    """Verify the MCP server registers the full Phase 1-4 tool surface after all imports."""
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 209
