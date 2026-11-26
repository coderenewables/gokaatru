"""analysis — Workflow analysis routes for the GoKaatru web API.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends

from server.api.deps import get_session_state, to_bad_request
from server.api.schemas import (
    ImportRunconfigRequest,
    RunScenarioRequest,
    SaveScenarioRequest,
    SensorStatisticsResponse,
)
from server.core.uncertainty_inputs import derive_uncertainty_inputs
from server.state.session import SessionState
from server.tools.config import _persist_runconfig, _sync_state_from_runconfig
from server.tools.ensemble import _run_ensemble
from server.tools.ltc_runs import (
    DIRECTIONAL_LTC_ALGORITHMS,  # noqa: F401 — re-exported for callers of this module
    LTC_ALGORITHMS,
    run_ltc_algorithm,
)
from server.tools.ltc_runs import resolve_ltc_columns as _resolve_ltc_columns
from server.tools.overview_summary import _compute_overview_summary
from server.tools.statistics import _sensor_statistics
from server.tools.uncertainty import _calculate_uncertainty

router = APIRouter(prefix="/sessions/{session_id}", tags=["analysis"])

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


def _import_runconfig(state: SessionState, runconfig: dict[str, object]) -> dict[str, object]:
    """Import a runconfig payload into the session, merging over the current runconfig.

    The session runconfig.json is the single source of truth, so the merge is
    written through to disk.
    """
    state.runconfig.update(runconfig)
    _sync_state_from_runconfig(state)
    _persist_runconfig(state)
    return dict(state.runconfig)


def _run_scenario_pipeline(
    state: SessionState,
    name: str,
    runconfig_overrides: dict[str, object],
    ltc_algorithms: list[str],
    uncertainty_params: dict[str, object] | None,
) -> dict[str, object]:
    """Import config overrides, execute LTC \u2192 ensemble \u2192 uncertainty, and save as a scenario."""
    # --- 1. Import config ---
    if runconfig_overrides:
        _import_runconfig(state, runconfig_overrides)

    # --- 2. Preparedness checks ---
    if state.timeseries_df is None:
        raise ValueError("Timeseries data must be loaded before running a scenario")
    if state.era5_interpolated_df is None:
        raise ValueError("ERA5 interpolation must be completed before running a scenario")

    short_col, long_col, short_dir_col, long_dir_col = _resolve_ltc_columns(state)

    # --- 3. Run requested LTC algorithms ---
    steps_completed: list[str] = []
    for algorithm_name in ltc_algorithms:
        ltc_fn = LTC_ALGORITHMS.get(algorithm_name)
        if ltc_fn is None:
            raise ValueError(f"Unknown LTC algorithm '{algorithm_name}'")
        run_ltc_algorithm(
            state, algorithm_name, ltc_fn, short_col, long_col, short_dir_col, long_dir_col
        )
        steps_completed.append(f"ltc:{algorithm_name}")

    # --- 4. Ensemble (when multiple algorithms) ---
    if len(ltc_algorithms) > 1:
        _run_ensemble(state, short_col)
        steps_completed.append("ensemble")

    # --- 5. Uncertainty ---
    if uncertainty_params is None:
        # Derived from this scenario's own results, not from constants. The block that
        # used to sit here hardcoded mcp_r_squared 0.85, concurrent_hours 8760 and
        # shear_std 0.0, which across a sweep would have made every scenario report
        # near-identical uncertainty however well its own fit performed (design doc S7.5).
        uncertainty_params = derive_uncertainty_inputs(state, ltc_algorithms[0])
    else:
        # Ensure algorithm is in the executed set
        algo_in_params = str(uncertainty_params.get("algorithm", ltc_algorithms[0]))
        if algo_in_params not in ltc_algorithms:
            algo_in_params = ltc_algorithms[0]
        uncertainty_params["algorithm"] = algo_in_params

    _calculate_uncertainty(
        state,
        float(uncertainty_params["measurement_uncertainty_pct"]),
        float(uncertainty_params["measurement_height_m"]),
        float(uncertainty_params["hub_height_m"]),
        str(uncertainty_params["shear_method"]),
        float(uncertainty_params["mcp_r_squared"]),
        float(uncertainty_params["concurrent_hours"]),
        str(uncertainty_params.get("algorithm", ltc_algorithms[0])),
        float(uncertainty_params.get("iav_pct", 6.0)),
        float(uncertainty_params.get("shear_std", 0.0)),
        bool(uncertainty_params.get("is_interpolation", False)),
    )
    steps_completed.append("uncertainty")

    # --- 6. Save scenario snapshot ---
    scenario = _build_scenario_snapshot(state, name)
    state.scenarios.append(scenario)
    steps_completed.append("scenario_saved")
    state.touch()

    return {
        "status": "ok",
        "scenario_index": len(state.scenarios) - 1,
        "name": scenario["name"],
        "steps_completed": steps_completed,
        "scenario": scenario,
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


@router.get("/overview-summary")
def get_overview_summary(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
    speed_sensor: str = "",
    direction_sensor: str = "",
) -> dict:
    """Return a concise bankable summary table assembled from available overview analyses."""
    del session_id
    try:
        return _compute_overview_summary(state, speed_sensor, direction_sensor)
    except ValueError as exc:
        raise to_bad_request(exc) from exc


@router.get("/clipping/columns")
def get_clipping_columns(
    session_id: str,
    source: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Return the list of numeric columns available for a given clipping source."""
    del session_id
    if source == "ensemble":
        if state.ensemble_df is None:
            return {"columns": []}
        import pandas as pd
        frame = pd.DataFrame(state.ensemble_df)
        cols = [c for c in frame.columns if c not in ("Timestamp",) and frame[c].dtype.kind in ("f", "i")]
        return {"columns": cols}
    payload = state.ltc_results.get(source)
    if payload is None or "df" not in payload:
        return {"columns": []}
    import pandas as pd
    frame = pd.DataFrame(payload["df"])
    cols = [c for c in frame.columns if c not in ("Timestamp",) and frame[c].dtype.kind in ("f", "i")]
    return {"columns": cols}


@router.post("/config/import")
def import_runconfig(
    session_id: str,
    body: ImportRunconfigRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Import a complete runconfig JSON payload into the current session, merging over existing keys."""
    del session_id
    try:
        merged = _import_runconfig(state, body.runconfig)
    except ValueError as exc:
        raise to_bad_request(exc) from exc
    state.touch()
    return {"status": "ok", "runconfig": merged}


@router.post("/scenarios/run")
def run_scenario(
    session_id: str,
    body: RunScenarioRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict:
    """Import runconfig overrides, execute LTC \u2192 ensemble \u2192 uncertainty, and save as a named scenario."""
    del session_id
    uncertainty_dict: dict[str, object] | None = None
    if body.uncertainty is not None:
        uncertainty_dict = body.uncertainty.model_dump()
    try:
        result = _run_scenario_pipeline(
            state,
            body.name,
            dict(body.runconfig),
            body.ltc_algorithms,
            uncertainty_dict,
        )
    except ValueError as exc:
        raise to_bad_request(exc) from exc
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
