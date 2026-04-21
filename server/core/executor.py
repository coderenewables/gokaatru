"""executor - Phase 3 workflow execution orchestration.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from server.state.session import SessionState

TOOL_MODULE_PATHS = [
    "server.tools.data_io",
    "server.tools.cleaning",
    "server.tools.shear",
    "server.tools.extrapolation",
    "server.tools.era5",
    "server.tools.homogeneity",
    "server.tools.ltc",
    "server.tools.ltc_ml",
    "server.tools.ensemble",
    "server.tools.clipping",
    "server.tools.uncertainty",
    "server.tools.air_density",
    "server.tools.statistics",
    "server.tools.visualization",
    "server.tools.map",
    "server.tools.config",
    "server.tools.brighthub",
    "server.tools.windkit.wind",
    "server.tools.windkit.climate",
    "server.tools.windkit.climate_stats",
    "server.tools.windkit.topography",
    "server.tools.windkit.windfarm",
    "server.tools.windkit.spatial",
    "server.tools.windkit.ltc",
    "server.tools.windkit.other",
    "server.tools.windkit.plotting",
]

PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "file_path": ("path", "timeseries_path", "timeseries_file", "datamodel_path", "datamodel_file"),
    "sensor_name": ("sensor",),
    "entry_index": ("index",),
    "height_sensors": ("sensors", "height_map"),
    "direction_sensor": ("dir_sensor",),
    "sensor_names": ("sensors",),
    "nodes_json": ("nodes",),
    "params": ("rule_params", "parameters"),
    "west_east": ("we",),
    "south_north": ("sn",),
    "height": ("h",),
}

_TOOL_REGISTRY: dict[str, tuple[ModuleType, Callable[..., Any]]] | None = None


def _dispatch_capability_from_function(template_id: str, function: Callable[..., Any]) -> dict[str, object]:
    """Build required and optional parameter lists from one tool callable signature."""
    signature = inspect.signature(function)
    required_params: list[str] = []
    optional_params: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        if parameter.default is inspect._empty:
            required_params.append(parameter.name)
        else:
            optional_params.append(parameter.name)
    return {
        "template_id": template_id,
        "required_params": required_params,
        "optional_params": optional_params,
    }


def dispatch_capabilities() -> list[dict[str, object]]:
    """Return dispatch capability details for all executable node templates."""
    capabilities = [
        {
            "template_id": "select-dataset",
            "required_params": [],
            "optional_params": [],
        }
    ]
    for template_id, (_module, function) in sorted(_tool_registry().items(), key=lambda item: item[0]):
        capabilities.append(_dispatch_capability_from_function(template_id, function))
    return capabilities


@dataclass
class WorkflowExecutionNode:
    """Represent one lightweight executable node payload from the workflow canvas."""

    id: str
    kind: str
    label: str
    template_id: str | None
    config: dict[str, object]
    status: str | None


@dataclass
class WorkflowExecutionEdge:
    """Represent one directed dependency between two workflow nodes."""

    source: str
    target: str


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamps for execution events."""
    return datetime.now(timezone.utc)


def _as_status(value: str | None, fallback: str = "pending") -> str:
    """Normalize node statuses used by the workflow execution runtime."""
    allowed = {"idle", "pending", "running", "done", "error", "skipped"}
    if value in allowed:
        return value
    return fallback


def _as_event(
    run_id: str,
    event_type: str,
    node_id: str | None,
    status: str | None,
    message: str | None,
) -> dict[str, object]:
    """Create one event payload emitted by execute and execute-stream endpoints."""
    return {
        "run_id": run_id,
        "event_type": event_type,
        "node_id": node_id,
        "status": status,
        "message": message,
        "timestamp": _utcnow(),
    }


def _tool_registry() -> dict[str, tuple[ModuleType, Callable[..., Any]]]:
    """Return a cached mapping of tool function name to (module, callable)."""
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is not None:
        return _TOOL_REGISTRY

    registry: dict[str, tuple[ModuleType, Callable[..., Any]]] = {}
    for module_path in TOOL_MODULE_PATHS:
        module = importlib.import_module(module_path)
        for name, value in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_"):
                continue
            if value.__module__ != module.__name__:
                continue
            registry.setdefault(name, (module, value))

    _TOOL_REGISTRY = registry
    return registry


class WorkflowExecutor:
    """Execute workflow operation/dataset nodes in topological order for one session."""

    def __init__(self, state: SessionState, nodes: list[WorkflowExecutionNode], edges: list[WorkflowExecutionEdge]) -> None:
        self.state = state
        self.nodes = [node for node in nodes if node.kind in {"dataset", "operation"}]
        self.edges = edges

    def _ordered_nodes(self) -> list[WorkflowExecutionNode]:
        """Return executable nodes in topological order, with deterministic fallback for cycles."""
        by_id = {node.id: node for node in self.nodes}
        indegree = {node.id: 0 for node in self.nodes}
        adjacency: dict[str, set[str]] = {node.id: set() for node in self.nodes}

        for edge in self.edges:
            if edge.source not in by_id or edge.target not in by_id:
                continue
            if edge.target in adjacency[edge.source]:
                continue
            adjacency[edge.source].add(edge.target)
            indegree[edge.target] += 1

        ready = sorted([node_id for node_id, degree in indegree.items() if degree == 0])
        ordered_ids: list[str] = []

        while ready:
            current = ready.pop(0)
            ordered_ids.append(current)
            for neighbor in sorted(adjacency[current]):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
            ready.sort()

        if len(ordered_ids) == len(by_id):
            return [by_id[node_id] for node_id in ordered_ids]

        # For cycle cases, keep deterministic behavior and continue execution in id order.
        remaining = sorted(node_id for node_id in by_id if node_id not in ordered_ids)
        return [by_id[node_id] for node_id in ordered_ids + remaining]

    def _params(self, config: dict[str, object]) -> dict[str, object]:
        """Parse params_json plus direct config keys into backend dispatch parameters."""
        raw = config.get("params_json")
        parsed: dict[str, object] = {}

        if raw is None:
            parsed = {}
        elif isinstance(raw, dict):
            parsed = dict(raw)
        elif isinstance(raw, str):
            payload = raw.strip()
            if payload != "":
                decoded = json.loads(payload)
                if not isinstance(decoded, dict):
                    raise ValueError("params_json must decode to a JSON object")
                parsed = dict(decoded)
        else:
            raise ValueError("params_json must be a JSON object or string")

        for key, value in config.items():
            if key == "params_json":
                continue
            parsed.setdefault(key, value)
        return parsed

    def _resolve_tool(self, template_id: str) -> tuple[ModuleType, Callable[..., Any]]:
        """Resolve one template id to a registered backend tool callable."""
        registry = _tool_registry()
        tool = registry.get(template_id)
        if tool is not None:
            return tool
        raise ValueError(f"No backend tool is registered for template_id '{template_id}'")

    def _param_value(self, params: dict[str, object], name: str) -> object | None:
        """Resolve one argument value using exact name or supported alias names."""
        if name in params:
            return params[name]
        for alias in PARAM_ALIASES.get(name, ()):
            if alias in params:
                return params[alias]
        return None

    def _coerce_value(self, parameter: inspect.Parameter, value: object) -> object:
        """Coerce one raw params value to the callable parameter annotation where possible."""
        annotation = parameter.annotation
        if annotation is inspect._empty:
            return value

        if annotation is str:
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            if value is None:
                return ""
            return str(value)

        if annotation is int:
            if isinstance(value, bool):
                return int(value)
            return int(value)

        if annotation is float:
            return float(value)

        if annotation is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "y", "on"}:
                    return True
                if normalized in {"false", "0", "no", "n", "off"}:
                    return False
                raise ValueError(f"Cannot coerce '{value}' to bool for parameter '{parameter.name}'")
            return bool(value)

        return value

    def _build_kwargs(self, function: Callable[..., Any], params: dict[str, object]) -> dict[str, object]:
        """Build keyword arguments for a tool callable from node params_json payload."""
        kwargs: dict[str, object] = {}
        signature = inspect.signature(function)
        for parameter in signature.parameters.values():
            if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
                continue
            raw_value = self._param_value(params, parameter.name)
            if raw_value is None:
                if parameter.default is inspect._empty:
                    raise ValueError(
                        f"Missing required parameter '{parameter.name}' for '{function.__name__}'"
                    )
                continue
            kwargs[parameter.name] = self._coerce_value(parameter, raw_value)
        return kwargs

    def _invoke_tool(self, template_id: str, params: dict[str, object]) -> dict[str, object]:
        """Invoke one template-resolved backend tool function with session-scoped context."""
        if template_id == "select-dataset":
            return {"status": "ok", "message": "Dataset selection is a canvas helper and has no backend operation"}

        module, function = self._resolve_tool(template_id)
        kwargs = self._build_kwargs(function, params)

        has_session = hasattr(module, "session")
        previous_session = getattr(module, "session", None)
        if has_session:
            setattr(module, "session", self.state)
        try:
            result = function(**kwargs)
        finally:
            if has_session:
                setattr(module, "session", previous_session)

        if result is None:
            return {"status": "ok"}
        if isinstance(result, dict):
            return result
        return {"status": "ok", "result": result}

    def _summarize_result(self, template_id: str, result: dict[str, object]) -> str:
        """Build a concise execution summary message from a backend tool response payload."""
        message = result.get("message")
        if isinstance(message, str) and message.strip():
            return message

        parts: list[str] = []
        for key in ("rows", "count", "records", "record_count", "algorithm"):
            value = result.get(key)
            if value is not None:
                parts.append(f"{key}={value}")

        coverage = result.get("coverage_pct")
        if isinstance(coverage, (int, float)):
            parts.append(f"coverage={coverage:.2f}%")

        if parts:
            return f"{template_id} completed ({', '.join(parts)})"
        return f"{template_id} completed"

    def _run_operation(self, template_id: str, config: dict[str, object]) -> str:
        """Dispatch one operation template to a registered backend tool callable."""
        params = self._params(config)
        result = self._invoke_tool(template_id, params)
        return self._summarize_result(template_id, result)

    async def _execute_node(self, node: WorkflowExecutionNode) -> str:
        """Execute one workflow node and return a user-facing summary message."""
        await asyncio.sleep(0.04)
        if node.kind == "dataset":
            return f"Dataset node '{node.label or node.id}' is ready"
        if node.kind != "operation":
            return f"Skipped non-executable node kind '{node.kind}'"

        template_id = (node.template_id or "").strip()
        if not template_id:
            return "Operation has no template_id; placeholder execution completed"
        return self._run_operation(template_id, node.config)

    def _seed_runtime(self, ordered_nodes: list[WorkflowExecutionNode]) -> str:
        """Initialize the session execution runtime before a run starts."""
        run_id = uuid4().hex
        node_statuses = {node.id: _as_status(node.status, fallback="pending") for node in ordered_nodes}
        self.state.workflow_execution = {
            "run_id": run_id,
            "is_running": True,
            "cancel_requested": False,
            "node_statuses": node_statuses,
            "events": [],
        }
        self.state.touch()
        return run_id

    def _append_event(self, event: dict[str, object]) -> None:
        """Append one execution event to session runtime history with a bounded buffer."""
        runtime = self.state.workflow_execution
        events = runtime.get("events", [])
        if not isinstance(events, list):
            events = []
        events.append(event)
        runtime["events"] = events[-400:]

    def _set_node_status(self, node_id: str, status: str) -> None:
        """Set one node execution status in the session runtime map."""
        runtime = self.state.workflow_execution
        statuses = runtime.get("node_statuses", {})
        if not isinstance(statuses, dict):
            statuses = {}
        statuses[node_id] = status
        runtime["node_statuses"] = statuses

    def _finish_runtime(self, cancelled: bool) -> None:
        """Mark runtime as no longer running and persist cancellation state."""
        self.state.workflow_execution["is_running"] = False
        self.state.workflow_execution["cancel_requested"] = cancelled
        self.state.touch()

    def _is_cancelled(self) -> bool:
        """Return whether a stop request was issued for the current run."""
        value = self.state.workflow_execution.get("cancel_requested", False)
        return bool(value)

    async def execute_auto(self) -> AsyncIterator[dict[str, object]]:
        """Run all pending executable nodes in topological order and stream events."""
        ordered = self._ordered_nodes()
        if not ordered:
            raise ValueError("Workflow execution requires at least one dataset or operation node")

        run_id = self._seed_runtime(ordered)
        started = _as_event(run_id, "run_started", None, "running", "Workflow execution started")
        self._append_event(started)
        yield started

        encountered_error = False
        for node in ordered:
            current_status = str(self.state.workflow_execution.get("node_statuses", {}).get(node.id, "pending"))
            if current_status in {"done", "skipped"}:
                continue
            if self._is_cancelled():
                break

            self._set_node_status(node.id, "running")
            node_started = _as_event(run_id, "node_started", node.id, "running", f"Running {node.label or node.id}")
            self._append_event(node_started)
            yield node_started

            try:
                message = await self._execute_node(node)
                self._set_node_status(node.id, "done")
                node_finished = _as_event(run_id, "node_finished", node.id, "done", message)
                self._append_event(node_finished)
                yield node_finished
            except Exception as exc:  # pragma: no cover - defensive wrapper
                encountered_error = True
                self._set_node_status(node.id, "error")
                node_failed = _as_event(run_id, "node_failed", node.id, "error", str(exc))
                self._append_event(node_failed)
                yield node_failed
                break

        cancelled = self._is_cancelled()
        final_status = "cancelled" if cancelled else "error" if encountered_error else "ok"
        final_event_type = "run_cancelled" if cancelled else "run_finished"
        final_message = "Execution cancelled" if cancelled else "Execution completed" if not encountered_error else "Execution stopped after error"
        finished = _as_event(run_id, final_event_type, None, final_status, final_message)
        self._append_event(finished)
        self._finish_runtime(cancelled)
        yield finished

    async def execute_step(self) -> list[dict[str, object]]:
        """Execute only the next pending executable node and return collected events."""
        ordered = self._ordered_nodes()
        if not ordered:
            raise ValueError("Workflow step requires at least one dataset or operation node")

        run_id = self._seed_runtime(ordered)
        events: list[dict[str, object]] = []

        started = _as_event(run_id, "run_started", None, "running", "Workflow step started")
        self._append_event(started)
        events.append(started)

        next_node: WorkflowExecutionNode | None = None
        statuses = self.state.workflow_execution.get("node_statuses", {})
        if not isinstance(statuses, dict):
            statuses = {}
        for node in ordered:
            if str(statuses.get(node.id, "pending")) not in {"done", "skipped"}:
                next_node = node
                break

        if next_node is None:
            finished = _as_event(run_id, "run_finished", None, "ok", "No pending nodes remaining")
            self._append_event(finished)
            events.append(finished)
            self._finish_runtime(False)
            return events

        self._set_node_status(next_node.id, "running")
        node_started = _as_event(run_id, "node_started", next_node.id, "running", f"Running {next_node.label or next_node.id}")
        self._append_event(node_started)
        events.append(node_started)

        try:
            message = await self._execute_node(next_node)
            self._set_node_status(next_node.id, "done")
            node_finished = _as_event(run_id, "node_finished", next_node.id, "done", message)
            self._append_event(node_finished)
            events.append(node_finished)
            finished = _as_event(run_id, "run_finished", None, "ok", "Step completed")
            self._append_event(finished)
            events.append(finished)
            self._finish_runtime(False)
            return events
        except Exception as exc:  # pragma: no cover - defensive wrapper
            self._set_node_status(next_node.id, "error")
            node_failed = _as_event(run_id, "node_failed", next_node.id, "error", str(exc))
            self._append_event(node_failed)
            events.append(node_failed)
            finished = _as_event(run_id, "run_finished", None, "error", "Step failed")
            self._append_event(finished)
            events.append(finished)
            self._finish_runtime(False)
            return events
