"""results — Results, plots, and export routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from typing import Annotated, Callable

import pandas as pd
from fastapi import APIRouter, Depends

from server.api.deps import get_session_state, to_bad_request
from server.api.schemas import PlotRequest
from server.schemas.common import PlotResult
from server.state.session import SessionState
from server.tools.config import _get_run_config, _save_run_config
from server.tools.map import _get_site_overview_map
from server.tools.visualization import (
    _plot_annual_means,
    _plot_cleaning_overlay,
    _plot_coverage_timeline,
    _plot_data_coverage,
    _plot_diurnal,
    _plot_era5_comparison,
    _plot_era5_measured_overlay,
    _plot_ltc_comparison,
    _plot_ltc_annual_convergence,
    _plot_ltc_monthly_comparison,
    _plot_ltc_residuals,
    _plot_ltc_scatter,
    _plot_monthly_means,
    _plot_scatter,
    _plot_scenario_comparison,
    _plot_shear_profile,
    _plot_shear_table,
    _plot_timeseries_preview,
    _plot_timeseries,
    _plot_turbulence_intensity,
    _plot_uncertainty_breakdown,
    _plot_uncertainty_tornado,
    _plot_weibull,
    _plot_windrose,
)

router = APIRouter(prefix="/sessions/{session_id}", tags=["results"])


def _frame_rows(frame_like: object) -> int:
    """Return the row count for a stored dataframe-like session payload."""
    return int(len(pd.DataFrame(frame_like)))


@router.get("/results/ltc")
def get_ltc_results(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return compact summaries of all LTC results currently stored in the session."""
    del session_id
    results: list[dict[str, object]] = []
    for algorithm, payload in sorted(state.ltc_results.items()):
        results.append(
            {
                "algorithm": algorithm,
                "metrics": payload.get("metrics", {}),
                "result_file": payload.get("file"),
                "rows": _frame_rows(payload.get("df", [])),
            }
        )
    return {"results": results}


@router.get("/results/ensemble")
def get_ensemble_results(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return a compact summary of the stored ensemble result, if one exists."""
    del session_id
    reference_columns = [] if state.era5_interpolated_df is None else pd.DataFrame(state.era5_interpolated_df).columns.tolist()
    if state.ensemble_df is None:
        return {"available": False, "reference_columns": reference_columns}
    frame = pd.DataFrame(state.ensemble_df)
    return {
        "available": True,
        "rows": int(len(frame)),
        "columns": frame.columns.tolist(),
        "reference_columns": reference_columns,
    }


@router.post("/plots/{plot_name}", response_model=PlotResult)
def get_plot(
    session_id: str,
    plot_name: str,
    body: PlotRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> PlotResult:
    """Dispatch one supported Plotly result endpoint to the shared visualization helpers."""
    del session_id
    plot_dispatch: dict[str, Callable[[], dict]] = {
        "windrose": lambda: _plot_windrose(
            state,
            body.speed_sensor or body.sensor_name,
            body.direction_sensor,
        ),
        "weibull": lambda: _plot_weibull(state, body.sensor_name),
        "diurnal": lambda: _plot_diurnal(state, body.sensor_names),
        "scatter": lambda: _plot_scatter(state, body.sensor_a, body.sensor_b),
        "timeseries": lambda: _plot_timeseries(state, body.sensor_names),
        "timeseries_preview": lambda: _plot_timeseries_preview(state),
        "cleaning_overlay": lambda: _plot_cleaning_overlay(state, body.sensor_name),
        "coverage_timeline": lambda: _plot_coverage_timeline(state),
        "data_coverage": lambda: _plot_data_coverage(state),
        "scenario_comparison": lambda: _plot_scenario_comparison(state),
        "era5_comparison": lambda: _plot_era5_comparison(state),
        "era5_measured_overlay": lambda: _plot_era5_measured_overlay(state),
        "shear_table": lambda: _plot_shear_table(state, body.table_type),
        "shear_profile": lambda: _plot_shear_profile(state),
        "monthly_means": lambda: _plot_monthly_means(state, body.sensor_names),
        "turbulence_intensity": lambda: _plot_turbulence_intensity(
            state,
            body.speed_sensor or body.sensor_name,
            body.sensor_b,
        ),
        "ltc_comparison": lambda: _plot_ltc_comparison(state),
        "ltc_scatter": lambda: _plot_ltc_scatter(state, body.algorithm or "linear_least_squares"),
        "ltc_residuals": lambda: _plot_ltc_residuals(state, body.algorithm or "linear_least_squares"),
        "ltc_monthly": lambda: _plot_ltc_monthly_comparison(state),
        "ltc_convergence": lambda: _plot_ltc_annual_convergence(state),
        "annual_means": lambda: _plot_annual_means(state),
        "uncertainty_breakdown": lambda: _plot_uncertainty_breakdown(
            state,
            body.total_pct,
            body.measurement_pct,
            body.vertical_pct,
            body.mcp_pct,
            body.future_pct,
        ),
        "uncertainty_tornado": lambda: _plot_uncertainty_tornado(
            state,
            body.total_pct,
            body.measurement_pct,
            body.vertical_pct,
            body.mcp_pct,
            body.future_pct,
        ),
    }
    plot_builder = plot_dispatch.get(plot_name)
    if plot_builder is None:
        raise to_bad_request(ValueError(f"Unknown plot_name '{plot_name}'"))
    try:
        return PlotResult(**plot_builder())
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/map/site")
def get_site_map(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return the site overview GeoJSON map for the current session."""
    del session_id
    try:
        return _get_site_overview_map(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/runconfig/export")
def export_runconfig(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Persist and return the current session runconfig for browser export flows."""
    del session_id
    saved = _save_run_config(state)
    return {"status": "ok", "file_path": saved["file_path"], "runconfig": _get_run_config(state)}
