"""analysis — Workflow analysis routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from typing import Annotated, Callable

from fastapi import APIRouter, Depends

from server.api.deps import get_session_state, to_bad_request
from server.api.schemas import (
    ApplyCleaningRuleRequest,
    BuildTableRequest,
    CalculateShearRequest,
    CalculateUncertaintyRequest,
    ClippingRequest,
    EnsembleRequest,
    ExtractEra5Request,
    ExtrapolateHubRequest,
    FindEra5NodesRequest,
    HomogeneityAnalyzeRequest,
    HomogeneityApplyRequest,
    RunLtcRequest,
    UndoCleaningRuleRequest,
)
from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule, _get_cleaning_log, _undo_cleaning_rule
from server.tools.clipping import _run_clipping_analysis
from server.tools.ensemble import _run_ensemble
from server.tools.era5 import _compute_era5_wind_speed, _extract_era5_data, _find_era5_nodes, _interpolate_era5_to_site
from server.tools.extrapolation import _extrapolate_to_hub_height
from server.tools.homogeneity import _analyze_homogeneity, _apply_homogeneity_cutoff
from server.tools.ltc import (
    _run_ltc_linear_least_squares,
    _run_ltc_speedsort,
    _run_ltc_total_least_squares,
    _run_ltc_variance_ratio,
)
from server.tools.ltc_ml import _run_ltc_xgboost
from server.tools.shear import (
    _build_roughness_table,
    _build_shear_table,
    _calculate_roughness_timeseries,
    _calculate_shear_timeseries,
)
from server.tools.uncertainty import _calculate_uncertainty

router = APIRouter(prefix="/sessions/{session_id}", tags=["analysis"])

LTC_ALGORITHMS: dict[str, Callable[..., dict]] = {
    "linear_least_squares": _run_ltc_linear_least_squares,
    "total_least_squares": _run_ltc_total_least_squares,
    "speedsort": _run_ltc_speedsort,
    "variance_ratio": _run_ltc_variance_ratio,
    "xgboost": _run_ltc_xgboost,
}


@router.post("/cleaning/apply")
def apply_cleaning(
    session_id: str,
    body: ApplyCleaningRuleRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Apply one cleaning rule to the session timeseries through the shared cleaning helper."""
    del session_id
    try:
        result = _apply_cleaning_rule(
            state,
            body.rule_type,
            body.sensor,
            json.dumps(body.params),
            body.start_date,
            body.end_date,
        )
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/cleaning/undo")
def undo_cleaning(
    session_id: str,
    body: UndoCleaningRuleRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Undo one cleaning log entry and replay the remaining rules on the session timeseries."""
    del session_id
    try:
        result = _undo_cleaning_rule(state, body.entry_index)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.get("/cleaning/log")
def get_cleaning_log(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return the applied cleaning log for the current session."""
    del session_id
    return _get_cleaning_log(state)


@router.post("/shear/calculate")
def calculate_shear(
    session_id: str,
    body: CalculateShearRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Calculate shear timeseries values using the shared state-aware helper."""
    del session_id
    try:
        result = _calculate_shear_timeseries(state, body.height_sensors)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/shear/table")
def build_shear_table(
    session_id: str,
    body: BuildTableRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Build the month-hour shear lookup table for the current session."""
    del session_id
    try:
        result = _build_shear_table(state, body.aggregation)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/roughness/calculate")
def calculate_roughness(
    session_id: str,
    body: CalculateShearRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Calculate roughness timeseries values using the shared state-aware helper."""
    del session_id
    try:
        result = _calculate_roughness_timeseries(state, body.height_sensors)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/roughness/table")
def build_roughness_table(
    session_id: str,
    body: BuildTableRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Build the month-hour roughness lookup table for the current session."""
    del session_id
    try:
        result = _build_roughness_table(state, body.aggregation)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/extrapolation/hub")
def extrapolate_hub(
    session_id: str,
    body: ExtrapolateHubRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Extrapolate measured wind speed to hub height for the current session."""
    del session_id
    try:
        result = _extrapolate_to_hub_height(state, body.hub_height_m, body.shear_model)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/era5/nodes")
def find_era5_nodes(
    session_id: str,
    body: FindEra5NodesRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Find surrounding ERA5 grid nodes for the session site coordinate."""
    del session_id
    try:
        result = _find_era5_nodes(state, body.latitude, body.longitude)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/era5/extract")
def extract_era5(
    session_id: str,
    body: ExtractEra5Request,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Extract ERA5 node data and compute wind speed components required for interpolation."""
    del session_id
    try:
        result = _extract_era5_data(state, body.latitude, body.longitude, body.start_date, body.end_date)
        wind_result = _compute_era5_wind_speed(state, body.latitude, body.longitude)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return {**result, **wind_result}


@router.post("/era5/interpolate")
def interpolate_era5(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Interpolate loaded ERA5 node datasets to the site location for the current session."""
    del session_id
    try:
        result = _interpolate_era5_to_site(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/ltc/{algorithm}")
def run_ltc(
    session_id: str,
    algorithm: str,
    body: RunLtcRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Run one LTC algorithm through the shared helper registry for the current session."""
    del session_id
    ltc_function = LTC_ALGORITHMS.get(algorithm)
    if ltc_function is None:
        raise to_bad_request(ValueError(f"Unknown LTC algorithm '{algorithm}'"))
    try:
        if algorithm == "xgboost":
            result = ltc_function(state, body.short_col, body.long_col, body.short_dir_col, body.long_dir_col)
        else:
            result = ltc_function(state, body.short_col, body.long_col)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/ensemble")
def run_ensemble(
    session_id: str,
    body: EnsembleRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Blend available LTC algorithms into one ensemble result for the session."""
    del session_id
    try:
        result = _run_ensemble(state, body.measured_col)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/clipping")
def run_clipping(
    session_id: str,
    body: ClippingRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Run clipping analysis for one corrected source series in the current session."""
    del session_id
    try:
        return _run_clipping_analysis(state, body.speed_col, body.source)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.post("/homogeneity/analyze")
def analyze_homogeneity(
    session_id: str,
    body: HomogeneityAnalyzeRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Run Pettitt homogeneity analysis on loaded ERA5 node data for the session."""
    del session_id
    try:
        return _analyze_homogeneity(state, body.method)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.post("/homogeneity/apply")
def apply_homogeneity(
    session_id: str,
    body: HomogeneityApplyRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Trim interpolated ERA5 data to a homogeneous start year for the current session."""
    del session_id
    try:
        result = _apply_homogeneity_cutoff(state, body.cutoff_year)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return result


@router.post("/uncertainty")
def calculate_uncertainty(
    session_id: str,
    body: CalculateUncertaintyRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Calculate total uncertainty using the shared Phase 4 uncertainty helper."""
    del session_id
    try:
        return _calculate_uncertainty(
            state,
            body.measurement_uncertainty_pct,
            body.measurement_height_m,
            body.hub_height_m,
            body.shear_method,
            body.mcp_r_squared,
            body.concurrent_hours,
            body.algorithm,
            body.iav_pct,
            body.shear_std,
            body.is_interpolation,
        )
    except ValueError as exc:
        raise to_bad_request(exc) from exc
