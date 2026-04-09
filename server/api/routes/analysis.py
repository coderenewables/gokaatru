"""analysis — Workflow analysis routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Callable

import pandas as pd
from fastapi import APIRouter, Depends

from server.api.deps import get_session_state, to_bad_gateway, to_bad_request
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
    SaveScenarioRequest,
    SensorStatisticsResponse,
    UndoCleaningRuleRequest,
)
from server.state.session import SessionState
from server.tools.cleaning import _apply_cleaning_rule, _get_cleaning_log, _undo_cleaning_rule
from server.tools.clipping import _run_clipping_analysis
from server.tools.ensemble import _run_ensemble
from server.tools.era5 import (
    Era5UpstreamError,
    _compute_era5_wind_speed,
    _extract_era5_data,
    _find_era5_nodes,
    _interpolate_era5_to_site,
)
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
from server.tools.statistics import _sensor_statistics
from server.tools.uncertainty import _calculate_uncertainty

router = APIRouter(prefix="/sessions/{session_id}", tags=["analysis"])

LTC_ALGORITHMS: dict[str, Callable[..., dict]] = {
    "linear_least_squares": _run_ltc_linear_least_squares,
    "total_least_squares": _run_ltc_total_least_squares,
    "speedsort": _run_ltc_speedsort,
    "variance_ratio": _run_ltc_variance_ratio,
    "xgboost": _run_ltc_xgboost,
}


def _scenario_frame_mean(frame_like: object, column: str) -> float:
    """Return the mean value for one numeric column from a stored dataframe-like payload."""
    frame = pd.DataFrame(frame_like)
    if column not in frame.columns:
        raise ValueError(f"Scenario export requires column '{column}' to be available")
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        raise ValueError(f"Scenario export requires non-null values in column '{column}'")
    return float(series.mean())


def _scenario_sensor_list(state: SessionState) -> list[str]:
    """Return mapped wind-speed sensors to snapshot the current measurement configuration."""
    return [
        str(mapping["speed_col"])
        for _height, mapping in sorted(state.sensor_mapping.items(), reverse=True)
        if isinstance(mapping.get("speed_col"), str)
    ]


def _scenario_config(state: SessionState, uncertainty: dict[str, object]) -> dict[str, object]:
    """Build the saved scenario configuration snapshot from session state and latest uncertainty inputs."""
    inputs = uncertainty.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("Latest uncertainty result is missing its inputs payload")
    cutoff_value = state.runconfig.get("cutoff_year", state.runconfig.get("homogeneity_cutoff_year"))
    cutoff_year = int(cutoff_value) if isinstance(cutoff_value, (int, float)) else None
    algorithm = str(inputs.get("algorithm", "speedsort"))
    shear_aggregation = state.runconfig.get("shear_aggregation", "mean")
    return {
        "shear_method": str(inputs.get("shear_method", "simple_power_law")),
        "shear_aggregation": str(shear_aggregation),
        "hub_height_m": float(inputs.get("hub_height_m", state.get_hub_height_m() or 0.0)),
        "sensors_used": _scenario_sensor_list(state),
        "ltc_algorithm": algorithm,
        "ltc_source": str(state.runconfig.get("ltc_source", algorithm)),
        "cutoff_year": cutoff_year,
    }


def _scenario_results(state: SessionState, uncertainty: dict[str, object]) -> dict[str, object]:
    """Build the saved scenario results snapshot from stored LTC and uncertainty outputs."""
    inputs = uncertainty.get("inputs")
    components = uncertainty.get("components")
    p_factors = uncertainty.get("p_factors")
    if not isinstance(inputs, dict) or not isinstance(components, dict) or not isinstance(p_factors, dict):
        raise ValueError("Latest uncertainty result is incomplete and cannot be saved as a scenario")
    algorithm = str(inputs.get("algorithm", "speedsort"))
    payload = state.ltc_results.get(algorithm)
    if payload is None:
        raise ValueError(f"LTC result '{algorithm}' is not available for scenario capture")
    ensemble_mean = None if state.ensemble_df is None else _scenario_frame_mean(state.ensemble_df, "Ensemble_Speed")
    return {
        "long_term_mean_speed": _scenario_frame_mean(payload.get("df", []), "corrected_wind_speed"),
        "ensemble_mean_speed": ensemble_mean,
        "total_uncertainty_pct": float(uncertainty.get("total_uncertainty_pct", 0.0)),
        "p50": float(p_factors.get("p50", 1.0)),
        "p75": float(p_factors.get("p75", 1.0)),
        "p90": float(p_factors.get("p90", 1.0)),
        "p99": float(p_factors.get("p99", 1.0)),
        "measurement_uncertainty_pct": float(components.get("measurement", 0.0)),
        "vertical_uncertainty_pct": float(components.get("vertical_extrapolation", 0.0)),
        "mcp_uncertainty_pct": float(components.get("mcp", 0.0)),
        "future_uncertainty_pct": float(components.get("future_variability", 0.0)),
    }


def _build_scenario_snapshot(state: SessionState, name: str) -> dict[str, object]:
    """Capture the current configuration and result state as one named scenario snapshot."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Scenario name must not be empty")
    if state.latest_uncertainty is None:
        raise ValueError("Run uncertainty before saving a scenario")
    uncertainty = state.latest_uncertainty
    return {
        "name": cleaned_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": _scenario_config(state, uncertainty),
        "results": _scenario_results(state, uncertainty),
    }


@router.get("/statistics/{sensor_name}", response_model=SensorStatisticsResponse)
def get_sensor_statistics(
    session_id: str,
    sensor_name: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> SensorStatisticsResponse:
    """Return descriptive statistics, Weibull parameters, and seasonal profiles for one sensor."""
    del session_id
    try:
        return SensorStatisticsResponse(**_sensor_statistics(state, sensor_name))
    except ValueError as exc:
        raise to_bad_request(exc) from exc


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
    except Era5UpstreamError as exc:
        raise to_bad_gateway(exc) from exc
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
    except Era5UpstreamError as exc:
        raise to_bad_gateway(exc) from exc
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
        result = _calculate_uncertainty(
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
    state.touch()
    return result


@router.post("/scenarios")
def save_scenario(
    session_id: str,
    body: SaveScenarioRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Capture the current analysis configuration and outputs as a named scenario snapshot."""
    del session_id
    try:
        scenario = _build_scenario_snapshot(state, body.name)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.scenarios.append(scenario)
    state.touch()
    return {"status": "ok", "scenario_index": len(state.scenarios) - 1, "name": scenario["name"]}


@router.get("/scenarios")
def list_scenarios(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return all saved scenarios for the current browser session."""
    del session_id
    return {"scenarios": [scenario.copy() for scenario in state.scenarios]}


@router.delete("/scenarios/{scenario_index}")
def delete_scenario(
    session_id: str,
    scenario_index: int,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Delete one saved scenario by index from the current browser session."""
    del session_id
    if scenario_index < 0 or scenario_index >= len(state.scenarios):
        raise to_bad_request(ValueError(f"Scenario index {scenario_index} is out of range"))
    removed = state.scenarios.pop(scenario_index)
    state.touch()
    return {"status": "ok", "name": removed.get("name", f"scenario-{scenario_index}")}
