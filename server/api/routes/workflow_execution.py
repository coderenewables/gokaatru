"""workflow_execution - Phase 3 workflow execution routes.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Callable

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from server.api.deps import get_session_manager, get_session_state, to_bad_request
from server.api.schemas import (
    WorkflowDispatchCapabilitiesResponse,
    WorkflowDispatchCapability,
    WorkflowCompareDiffEntry,
    WorkflowCompareMetric,
    WorkflowComparePlot,
    WorkflowComparePlots,
    WorkflowCompareRequest,
    WorkflowCompareResponse,
    WorkflowExecuteRequest,
    WorkflowExecutionEvent,
    WorkflowExecutionResponse,
    WorkflowExecutionStatusResponse,
    WorkflowForkBranchRequest,
    WorkflowForkBranchResponse,
    WorkflowLoadSnapshotResponse,
    WorkflowSaveSnapshotRequest,
    WorkflowSaveSnapshotResponse,
    WorkflowSnapshotListResponse,
    WorkflowSnapshotSummary,
)
from server.core.executor import WorkflowExecutionEdge, WorkflowExecutionNode, WorkflowExecutor, dispatch_capabilities
from server.state.manager import SessionManager
from server.state.session import SessionState

router = APIRouter(prefix="/sessions/{session_id}/workflow", tags=["workflow-execution"])
SNAPSHOT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SNAPSHOT_DIR_NAME = "workflows"


def _to_executor(state: SessionState, body: WorkflowExecuteRequest) -> WorkflowExecutor:
    """Build a WorkflowExecutor from request schema payloads."""
    nodes = [
        WorkflowExecutionNode(
            id=node.id,
            kind=node.kind,
            label=node.label,
            template_id=node.template_id,
            config=dict(node.config),
            status=node.status,
        )
        for node in body.nodes
    ]
    edges = [WorkflowExecutionEdge(source=edge.source, target=edge.target) for edge in body.edges]
    return WorkflowExecutor(state, nodes, edges)


def _runtime_snapshot(state: SessionState) -> WorkflowExecutionStatusResponse:
    """Serialize the session workflow execution runtime into an API response."""
    runtime = state.workflow_execution
    run_id_raw = runtime.get("run_id")
    run_id = str(run_id_raw) if isinstance(run_id_raw, str) else None

    statuses_raw = runtime.get("node_statuses", {})
    node_statuses = statuses_raw if isinstance(statuses_raw, dict) else {}

    events_raw = runtime.get("events", [])
    events_payload = events_raw if isinstance(events_raw, list) else []
    events: list[WorkflowExecutionEvent] = []
    for item in events_payload:
        if not isinstance(item, dict):
            continue
        timestamp_value = item.get("timestamp")
        timestamp = timestamp_value if isinstance(timestamp_value, datetime) else datetime.now(timezone.utc)
        events.append(
            WorkflowExecutionEvent(
                run_id=str(item.get("run_id", run_id or "")),
                event_type=str(item.get("event_type", "event")),
                node_id=str(item.get("node_id")) if item.get("node_id") is not None else None,
                status=str(item.get("status")) if item.get("status") is not None else None,
                message=str(item.get("message")) if item.get("message") is not None else None,
                timestamp=timestamp,
            )
        )

    return WorkflowExecutionStatusResponse(
        run_id=run_id,
        is_running=bool(runtime.get("is_running", False)),
        cancelled=bool(runtime.get("cancel_requested", False)),
        node_statuses={str(key): str(value) for key, value in node_statuses.items()},
        events=events,
    )


def _event_to_sse(event: dict[str, object]) -> str:
    """Convert an execution event dictionary into one SSE data frame."""
    return f"data: {json.dumps(event, default=str)}\n\n"


def _snapshot_dir(state: SessionState) -> Path:
    """Resolve and create the workflow snapshot directory for the session workspace."""
    workspace_dir = state.workspace_dir
    if workspace_dir is None:
        raise ValueError("Session workspace is not available")
    directory = workspace_dir / SNAPSHOT_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _snapshot_name(raw_name: str) -> str:
    """Validate snapshot names and prevent unsafe path traversal tokens."""
    cleaned = raw_name.strip()
    if not SNAPSHOT_NAME_PATTERN.fullmatch(cleaned):
        raise ValueError("Snapshot name must be 1-64 chars of letters, numbers, underscore, or hyphen")
    return cleaned


def _snapshot_saved_at(path: Path) -> datetime:
    """Return UTC timestamp representing snapshot file last modification time."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _safe_float(value: object) -> float | None:
    """Convert runtime numeric-like values to finite floats for API payloads."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None


def _to_json_value(value: object) -> object:
    """Convert nested Python values into JSON-serializable primitives for diff payloads."""
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_json_value(item) for item in value]
    return str(value)


def _flatten_config(value: object, prefix: str = "", output: dict[str, object] | None = None) -> dict[str, object]:
    """Flatten nested runconfig dictionaries to dotted keys for pairwise diffing."""
    if output is None:
        output = {}

    if isinstance(value, dict):
        for key in sorted(value.keys(), key=lambda item: str(item)):
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            _flatten_config(value[key], next_prefix, output)
        return output

    output[prefix] = _to_json_value(value)
    return output


def _first_numeric_series(frame: pd.DataFrame, preferred_tokens: list[str]) -> pd.Series | None:
    """Return the first non-empty numeric series from preferred then fallback columns."""
    if frame.empty:
        return None

    preferred: list[str] = []
    fallback: list[str] = []
    for column in frame.columns:
        label = str(column).lower()
        if any(token in label for token in preferred_tokens):
            preferred.append(str(column))
            continue
        fallback.append(str(column))

    for column_name in preferred + fallback:
        if column_name not in frame.columns:
            continue
        series = pd.to_numeric(frame[column_name], errors="coerce").dropna()
        if not series.empty:
            return series.reset_index(drop=True)
    return None


def _primary_speed_series(state: SessionState) -> pd.Series | None:
    """Resolve one representative wind-speed series for summary metrics and overlays."""
    if state.ensemble_df is not None:
        ensemble_series = _first_numeric_series(state.ensemble_df, ["ensemble_speed", "speed", "spd", "corrected"])
        if ensemble_series is not None:
            return ensemble_series

    if state.timeseries_df is not None:
        timeseries_series = _first_numeric_series(state.timeseries_df, ["speed", "spd", "ws"])
        if timeseries_series is not None:
            return timeseries_series

    for payload in state.ltc_results.values():
        if not isinstance(payload, dict):
            continue
        frame_payload = payload.get("df")
        if frame_payload is None:
            continue
        frame = pd.DataFrame(frame_payload)
        ltc_series = _first_numeric_series(frame, ["corrected", "speed", "spd"])
        if ltc_series is not None:
            return ltc_series
    return None


def _primary_direction_series(state: SessionState) -> pd.Series | None:
    """Resolve one representative wind-direction series for windrose generation."""
    if state.timeseries_df is None:
        return None
    return _first_numeric_series(state.timeseries_df, ["direction", "dir", "wd"])


def _uncertainty_payload(state: SessionState) -> dict[str, object] | None:
    """Return latest uncertainty payload when available and well-formed."""
    uncertainty = state.latest_uncertainty
    if isinstance(uncertainty, dict):
        return uncertainty
    return None


def _metric_from_uncertainty(state: SessionState, *path: str) -> float | None:
    """Extract one nested numeric uncertainty metric by key path."""
    current: object = _uncertainty_payload(state)
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _safe_float(current)


def _metric_row(
    name: str,
    unit: str,
    states: dict[str, SessionState],
    extractor: Callable[[SessionState], float | None],
) -> WorkflowCompareMetric:
    """Create one comparison metric row across all selected sessions."""
    values: dict[str, float | None] = {}
    for session_id, state in states.items():
        values[session_id] = extractor(state)
    return WorkflowCompareMetric(name=name, unit=unit, values=values)


def _build_metrics(states: dict[str, SessionState]) -> list[WorkflowCompareMetric]:
    """Build side-by-side summary metrics for the comparison dashboard."""
    def _lt_mean_speed(state: SessionState) -> float | None:
        series = _primary_speed_series(state)
        if series is None or series.empty:
            return None
        return _safe_float(float(series.mean()))

    return [
        _metric_row("LT Mean Speed", "m/s", states, _lt_mean_speed),
        _metric_row("P50", "-", states, lambda state: _metric_from_uncertainty(state, "p_factors", "p50")),
        _metric_row("P75", "-", states, lambda state: _metric_from_uncertainty(state, "p_factors", "p75")),
        _metric_row("P90", "-", states, lambda state: _metric_from_uncertainty(state, "p_factors", "p90")),
        _metric_row("P99", "-", states, lambda state: _metric_from_uncertainty(state, "p_factors", "p99")),
        _metric_row(
            "Total Uncertainty",
            "%",
            states,
            lambda state: _metric_from_uncertainty(state, "total_uncertainty_pct"),
        ),
        _metric_row(
            "Measurement Uncertainty",
            "%",
            states,
            lambda state: _metric_from_uncertainty(state, "components", "measurement"),
        ),
        _metric_row(
            "Vertical Uncertainty",
            "%",
            states,
            lambda state: _metric_from_uncertainty(state, "components", "vertical_extrapolation"),
        ),
        _metric_row(
            "MCP Uncertainty",
            "%",
            states,
            lambda state: _metric_from_uncertainty(state, "components", "mcp"),
        ),
        _metric_row(
            "Future Uncertainty",
            "%",
            states,
            lambda state: _metric_from_uncertainty(state, "components", "future_variability"),
        ),
    ]


def _build_config_diff(states: dict[str, SessionState]) -> dict[str, list[WorkflowCompareDiffEntry]]:
    """Build dotted-key runconfig diffs between the first session and each additional session."""
    session_ids = list(states.keys())
    if len(session_ids) < 2:
        return {}

    base_session_id = session_ids[0]
    base_flat = _flatten_config(states[base_session_id].runconfig)
    diffs: dict[str, list[WorkflowCompareDiffEntry]] = {}

    for compare_session_id in session_ids[1:]:
        compare_flat = _flatten_config(states[compare_session_id].runconfig)
        entries: list[WorkflowCompareDiffEntry] = []
        for key in sorted(set(base_flat.keys()) | set(compare_flat.keys())):
            base_value = base_flat.get(key)
            compare_value = compare_flat.get(key)
            if base_value == compare_value:
                continue
            entries.append(
                WorkflowCompareDiffEntry(
                    key=key,
                    a=_to_json_value(base_value),
                    b=_to_json_value(compare_value),
                )
            )
        diffs[f"{base_session_id}<->{compare_session_id}"] = entries[:300]

    return diffs


def _plot_payload(title: str, figure: dict[str, object]) -> WorkflowComparePlot:
    """Serialize one Plotly figure dictionary into the shared API plot payload shape."""
    return WorkflowComparePlot(title=title, plotly_json=json.dumps(figure, default=str))


def _build_weibull_plot(states: dict[str, SessionState]) -> WorkflowComparePlot:
    """Build multi-trace speed distribution overlay across selected sessions."""
    traces: list[dict[str, object]] = []
    for session_id, state in states.items():
        series = _primary_speed_series(state)
        if series is None or series.empty:
            continue

        bounded = series.clip(lower=0, upper=29.999)
        bins = list(range(0, 31))
        bucketed = pd.cut(bounded, bins=bins, right=False, include_lowest=True)
        counts = bucketed.value_counts().sort_index()
        total = int(counts.sum())
        if total <= 0:
            continue

        x_values: list[float] = []
        y_values: list[float] = []
        for interval, count in counts.items():
            if pd.isna(interval):
                continue
            x_values.append(float(interval.left + ((interval.right - interval.left) / 2.0)))
            y_values.append(float((count / total) * 100.0))

        traces.append(
            {
                "type": "scatter",
                "mode": "lines",
                "name": session_id,
                "x": x_values,
                "y": y_values,
            }
        )

    layout: dict[str, object] = {
        "title": "Weibull Overlay",
        "xaxis": {"title": "Wind speed (m/s)"},
        "yaxis": {"title": "Frequency (%)"},
        "legend": {"orientation": "h"},
    }
    if not traces:
        layout["annotations"] = [
            {
                "text": "No wind-speed series available for comparison",
                "showarrow": False,
                "x": 0.5,
                "y": 0.5,
                "xref": "paper",
                "yref": "paper",
            }
        ]
    return _plot_payload("Weibull Overlay", {"data": traces, "layout": layout})


def _build_windrose_plots(states: dict[str, SessionState]) -> list[WorkflowComparePlot]:
    """Build one windrose figure per compared session for side-by-side visualization."""
    plots: list[WorkflowComparePlot] = []
    for session_id, state in states.items():
        speed = _primary_speed_series(state)
        direction = _primary_direction_series(state)
        traces: list[dict[str, object]] = []
        layout: dict[str, object] = {
            "title": f"Windrose {session_id}",
            "polar": {"angularaxis": {"direction": "clockwise", "rotation": 90}},
        }

        if speed is not None and direction is not None:
            frame = pd.DataFrame({"speed": speed, "direction": direction}).dropna()
            if not frame.empty:
                sectors = ((frame["direction"] % 360) // 30).astype(int)
                counts = sectors.value_counts().reindex(range(12), fill_value=0)
                total = int(counts.sum())
                if total > 0:
                    traces.append(
                        {
                            "type": "barpolar",
                            "name": session_id,
                            "theta": [int(index * 30 + 15) for index in counts.index],
                            "r": [float((value / total) * 100.0) for value in counts.values],
                        }
                    )

        if not traces:
            layout["annotations"] = [
                {
                    "text": "No speed + direction data available",
                    "showarrow": False,
                    "x": 0.5,
                    "y": 0.5,
                    "xref": "paper",
                    "yref": "paper",
                }
            ]

        plots.append(_plot_payload(f"Windrose {session_id}", {"data": traces, "layout": layout}))

    return plots


def _build_ltc_scatter_plot(states: dict[str, SessionState]) -> WorkflowComparePlot:
    """Build multi-trace LTC scatter plot overlays from available LTC dataframes."""
    traces: list[dict[str, object]] = []
    for session_id, state in states.items():
        frame: pd.DataFrame | None = None
        for payload in state.ltc_results.values():
            if not isinstance(payload, dict):
                continue
            maybe_frame = pd.DataFrame(payload.get("df", []))
            if maybe_frame.empty:
                continue
            frame = maybe_frame
            break

        if frame is None:
            continue

        x_series = _first_numeric_series(frame, ["long", "reference", "reanalysis", "x"])
        y_series = _first_numeric_series(frame, ["corrected", "short", "speed", "y"])
        if x_series is None or y_series is None:
            continue

        sample_size = min(len(x_series), len(y_series), 400)
        if sample_size <= 0:
            continue

        traces.append(
            {
                "type": "scattergl",
                "mode": "markers",
                "name": session_id,
                "x": [float(value) for value in x_series.iloc[:sample_size].tolist()],
                "y": [float(value) for value in y_series.iloc[:sample_size].tolist()],
                "marker": {"size": 5, "opacity": 0.55},
            }
        )

    layout: dict[str, object] = {
        "title": "LTC Scatter Overlay",
        "xaxis": {"title": "Reference"},
        "yaxis": {"title": "Corrected"},
        "legend": {"orientation": "h"},
    }
    if not traces:
        layout["annotations"] = [
            {
                "text": "No LTC result frames available",
                "showarrow": False,
                "x": 0.5,
                "y": 0.5,
                "xref": "paper",
                "yref": "paper",
            }
        ]
    return _plot_payload("LTC Scatter Overlay", {"data": traces, "layout": layout})


def _build_uncertainty_tornado_plot(states: dict[str, SessionState]) -> WorkflowComparePlot:
    """Build grouped uncertainty-component bars across compared sessions."""
    labels = ["Measurement", "Vertical", "MCP", "Future"]
    keys = ["measurement", "vertical_extrapolation", "mcp", "future_variability"]

    traces: list[dict[str, object]] = []
    for session_id, state in states.items():
        uncertainty = _uncertainty_payload(state)
        components = uncertainty.get("components") if isinstance(uncertainty, dict) else None
        if not isinstance(components, dict):
            continue

        values = [_safe_float(components.get(key)) for key in keys]
        if all(value is None for value in values):
            continue

        traces.append(
            {
                "type": "bar",
                "name": session_id,
                "x": labels,
                "y": [0.0 if value is None else value for value in values],
            }
        )

    layout: dict[str, object] = {
        "title": "Uncertainty Tornado",
        "barmode": "group",
        "yaxis": {"title": "Uncertainty (%)"},
    }
    if not traces:
        layout["annotations"] = [
            {
                "text": "No uncertainty components available",
                "showarrow": False,
                "x": 0.5,
                "y": 0.5,
                "xref": "paper",
                "yref": "paper",
            }
        ]
    return _plot_payload("Uncertainty Tornado", {"data": traces, "layout": layout})


def _build_compare_plots(states: dict[str, SessionState]) -> WorkflowComparePlots:
    """Build all comparison dashboard plot payloads from selected session states."""
    return WorkflowComparePlots(
        weibull=_build_weibull_plot(states),
        windrose=_build_windrose_plots(states),
        ltc_scatter=_build_ltc_scatter_plot(states),
        uncertainty_tornado=_build_uncertainty_tornado_plot(states),
    )


@router.post("/execute", response_model=WorkflowExecutionResponse)
async def execute_workflow(
    session_id: str,
    body: WorkflowExecuteRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowExecutionResponse:
    """Execute all pending workflow nodes and return collected execution events."""
    del session_id
    executor = _to_executor(state, body)
    try:
        events = [event async for event in executor.execute_auto()]
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    snapshot = _runtime_snapshot(state)
    final_status = events[-1].get("status", "ok") if events else "ok"
    run_id = str(events[0].get("run_id", "")) if events else (snapshot.run_id or "")
    return WorkflowExecutionResponse(
        run_id=run_id,
        status=str(final_status),
        node_statuses=snapshot.node_statuses,
        events=[WorkflowExecutionEvent.model_validate(event) for event in events],
    )


@router.post("/execute/step", response_model=WorkflowExecutionResponse)
async def execute_workflow_step(
    session_id: str,
    body: WorkflowExecuteRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowExecutionResponse:
    """Execute only the next pending node and return execution events for that step."""
    del session_id
    executor = _to_executor(state, body)
    try:
        events = await executor.execute_step()
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    snapshot = _runtime_snapshot(state)
    final_status = events[-1].get("status", "ok") if events else "ok"
    run_id = str(events[0].get("run_id", "")) if events else (snapshot.run_id or "")
    return WorkflowExecutionResponse(
        run_id=run_id,
        status=str(final_status),
        node_statuses=snapshot.node_statuses,
        events=[WorkflowExecutionEvent.model_validate(event) for event in events],
    )


@router.post("/execute/stream")
async def execute_workflow_stream(
    session_id: str,
    body: WorkflowExecuteRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> StreamingResponse:
    """Execute all pending workflow nodes and stream lifecycle updates via SSE."""
    del session_id
    executor = _to_executor(state, body)

    async def event_generator() -> object:
        try:
            async for event in executor.execute_auto():
                yield _event_to_sse(event)
        except ValueError as exc:
            event = {
                "run_id": "",
                "event_type": "run_failed",
                "node_id": None,
                "status": "error",
                "message": str(exc),
                "timestamp": datetime.now(timezone.utc),
            }
            yield _event_to_sse(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/status", response_model=WorkflowExecutionStatusResponse)
def get_workflow_execution_status(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowExecutionStatusResponse:
    """Return current workflow execution status for the active browser session."""
    del session_id
    return _runtime_snapshot(state)


@router.post("/stop")
def stop_workflow_execution(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> dict[str, str | bool | None]:
    """Request cancellation of the active workflow execution run."""
    del session_id
    state.workflow_execution["cancel_requested"] = True
    state.touch()
    return {
        "status": "ok",
        "run_id": state.workflow_execution.get("run_id"),
        "is_running": bool(state.workflow_execution.get("is_running", False)),
    }


@router.get("/capabilities", response_model=WorkflowDispatchCapabilitiesResponse)
def get_workflow_dispatch_capabilities(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowDispatchCapabilitiesResponse:
    """Return executor dispatch capability details for frontend parameter hint rendering."""
    del session_id, state
    return WorkflowDispatchCapabilitiesResponse(
        capabilities=[WorkflowDispatchCapability.model_validate(item) for item in dispatch_capabilities()]
    )


@router.get("/snapshots", response_model=WorkflowSnapshotListResponse)
def list_workflow_snapshots(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowSnapshotListResponse:
    """List workflow snapshots saved in the active session workspace."""
    del session_id
    snapshot_dir = _snapshot_dir(state)

    snapshots: list[WorkflowSnapshotSummary] = []
    for candidate in sorted(snapshot_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        snapshots.append(
            WorkflowSnapshotSummary(
                name=candidate.stem,
                saved_at=_snapshot_saved_at(candidate),
            )
        )

    return WorkflowSnapshotListResponse(snapshots=snapshots)


@router.put("/snapshots/{snapshot_name}", response_model=WorkflowSaveSnapshotResponse)
def save_workflow_snapshot(
    session_id: str,
    snapshot_name: str,
    body: WorkflowSaveSnapshotRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowSaveSnapshotResponse:
    """Persist one workflow snapshot payload to session-scoped workspace storage."""
    del session_id
    try:
        normalized_name = _snapshot_name(snapshot_name)
        snapshot_dir = _snapshot_dir(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    snapshot_path = snapshot_dir / f"{normalized_name}.json"
    snapshot_payload = {"snapshot": body.snapshot}
    snapshot_path.write_text(json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    state.touch()

    return WorkflowSaveSnapshotResponse(name=normalized_name, saved_at=_snapshot_saved_at(snapshot_path))


@router.get("/snapshots/{snapshot_name}", response_model=WorkflowLoadSnapshotResponse)
def load_workflow_snapshot(
    session_id: str,
    snapshot_name: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> WorkflowLoadSnapshotResponse:
    """Load one persisted workflow snapshot payload from session workspace storage."""
    del session_id
    try:
        normalized_name = _snapshot_name(snapshot_name)
        snapshot_dir = _snapshot_dir(state)
    except ValueError as exc:
        raise to_bad_request(exc) from exc

    snapshot_path = snapshot_dir / f"{normalized_name}.json"
    if not snapshot_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow snapshot '{normalized_name}' was not found",
        )

    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow snapshot '{normalized_name}' is corrupted",
        ) from exc

    snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow snapshot '{normalized_name}' has no snapshot payload",
        )

    return WorkflowLoadSnapshotResponse(
        name=normalized_name,
        saved_at=_snapshot_saved_at(snapshot_path),
        snapshot=snapshot,
    )


@router.post("/compare", response_model=WorkflowCompareResponse)
def compare_workflow_branches(
    session_id: str,
    body: WorkflowCompareRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
    manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> WorkflowCompareResponse:
    """Compare selected branch sessions against the current parent session."""
    del state

    ordered_session_ids: list[str] = [session_id]
    for candidate in body.branch_session_ids:
        cleaned = candidate.strip()
        if not cleaned or cleaned in ordered_session_ids:
            continue
        ordered_session_ids.append(cleaned)

    if len(ordered_session_ids) > 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comparison supports up to 4 sessions per request",
        )

    states: dict[str, SessionState] = {}
    for candidate_session_id in ordered_session_ids:
        try:
            states[candidate_session_id] = manager.get_session(candidate_session_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return WorkflowCompareResponse(
        session_ids=ordered_session_ids,
        metrics=_build_metrics(states),
        config_diff=_build_config_diff(states),
        plots=_build_compare_plots(states),
    )


@router.post("/branches/fork", response_model=WorkflowForkBranchResponse)
def fork_workflow_branch(
    session_id: str,
    body: WorkflowForkBranchRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
    manager: Annotated[SessionManager, Depends(get_session_manager)],
) -> WorkflowForkBranchResponse:
    """Fork a branch by cloning session state into a new isolated branch session."""
    del state
    branch_state = manager.fork_session(session_id)
    branch_name = body.name.strip() if body.name and body.name.strip() else "Fork"
    return WorkflowForkBranchResponse(
        parent_session_id=session_id,
        branch_session_id=branch_state.session_id or "",
        branch_name=branch_name,
        from_node_id=body.from_node_id,
    )
