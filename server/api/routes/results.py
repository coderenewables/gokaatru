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
    _plot_data_coverage,
    _plot_diurnal,
    _plot_ltc_comparison,
    _plot_monthly_means,
    _plot_scatter,
    _plot_shear_table,
    _plot_timeseries,
    _plot_uncertainty_breakdown,
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
    if state.ensemble_df is None:
        return {"available": False}
    frame = pd.DataFrame(state.ensemble_df)
    return {"available": True, "rows": int(len(frame)), "columns": frame.columns.tolist()}


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
        "data_coverage": lambda: _plot_data_coverage(state),
        "shear_table": lambda: _plot_shear_table(state, body.table_type),
        "monthly_means": lambda: _plot_monthly_means(state, body.sensor_names),
        "ltc_comparison": lambda: _plot_ltc_comparison(state),
        "annual_means": lambda: _plot_annual_means(state),
        "uncertainty_breakdown": lambda: _plot_uncertainty_breakdown(
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
