"""pipelines — the campaign's chosen chain: its order, the state of each step, and named copies.

The canvas edits one pipeline per campaign (decisions/0015.1): steps, each an operation with
its parameters. ``order_pipeline`` puts them in the order their reads and writes require
(``server/core/pipeline.py``) and says, for each, whether the result in the session is the
one this step would build:

``current``
    built by this operation with these parameters, and nothing it was built from changed.
``changed``
    built by this operation with other parameters, or by another operation.
``stale``
    built by this step, from something that has changed since (decisions/0015.3).
``not_run``
    nothing this step writes has been built yet.
``upstream``
    current itself, but a step it reads from is not, so it will be rebuilt after it.
``invalid``
    its parameters do not fit the operation.
``ready``
    a read: it builds nothing, and its inputs are current.

Nothing runs here. The pipeline runs one step at a time through the generated routes, in
this order (decisions/0015.4). Named pipelines are saved in the campaign (decisions/0015.5),
with the project, and undone like a saved selection.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from server.core.pipeline import PipelineError, StepDeclaration, order_steps
from server.operations import ACTOR, REGISTRY, Operation, call_parameters, note_undo, operation, parameters_model
from server.schemas.results import pipelines as result_models
from server.state.artifacts import ARTIFACTS
from server.state.session import SessionState, session

#: Results, of which one step may produce each.
RESULTS = frozenset(name for name, artifact in ARTIFACTS.items() if artifact.derived)
#: The keys a step may carry: ``position`` is where the canvas drew it, kept with a saved one.
STEP_KEYS = frozenset({"id", "operation", "parameters", "position"})


def _steppable(declared: Operation) -> str | None:
    """Why an operation cannot be a pipeline step, or None when it can."""
    if not declared.canvas:
        return "it is not offered on the canvas"
    if declared.secret_parameters:
        # A saved pipeline is written to disk with the project; credentials never are.
        return "it takes credentials, which are never saved with a pipeline"
    return None


def _declarations() -> dict[str, StepDeclaration]:
    return {
        declared.name: StepDeclaration(declared.stage_rank, declared.reads, declared.writes)
        for declared in REGISTRY
        if _steppable(declared) is None
    }


def _checked_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise ValueError("A pipeline is a list of steps, each an object with an id, an operation and parameters")
    for step in steps:
        unknown = set(step) - STEP_KEYS
        if unknown:
            raise ValueError(f"Step '{step.get('id', '')}': unknown keys {sorted(unknown)}")
        name = str(step.get("operation", ""))
        if name in REGISTRY.names():
            reason = _steppable(REGISTRY.get(name))
            if reason is not None:
                raise ValueError(f"Step '{step.get('id', '')}': '{name}' cannot be a pipeline step: {reason}")
        if not isinstance(step.get("parameters", {}), dict):
            raise ValueError(f"Step '{step.get('id', '')}': parameters must be an object")
    return steps


def _parameters(declared: Operation, given: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """The step's parameters as a call would log them, or the reasons they do not fit."""
    try:
        body = parameters_model(declared)(**given)
    except ValidationError as exc:
        return None, [f"{'.'.join(map(str, error['loc'])) or 'parameters'}: {error['msg']}" for error in exc.errors()]
    return call_parameters(declared, body.model_dump()), []


def _last_writer(state: SessionState, artifact: str) -> dict[str, Any] | None:
    """The latest successful call, not undone, of an operation that writes ``artifact``."""
    undone = set(state.undo_stack)
    for entry in reversed(state.operation_log):
        name = entry.get("operation")
        if entry.get("status") != "ok" or entry.get("seq") in undone or name not in REGISTRY.names():
            continue
        if artifact in REGISTRY.get(name).writes:
            return entry
    return None


def _status(state: SessionState, declared: Operation, parameters: dict[str, Any]) -> dict[str, Any]:
    results = [name for name in declared.writes if name in RESULTS]
    tracked = results or list(declared.writes)
    if not tracked:
        return {"status": "ready"}
    for artifact in tracked:
        built = state.derived_provenance.get(artifact) if artifact in RESULTS else _last_writer(state, artifact)
        if built is None and artifact in state.derived_versions:
            return {
                "status": "changed",
                "reason": f"{artifact} was built outside an operation, so the parameters it was built with are unknown",
            }
        if built is None:
            return {"status": "not_run", "reason": f"{artifact} has not been built"}
        if built.get("operation") != declared.name:
            return {"status": "changed", "reason": f"{artifact} was built by {built.get('operation')}"}
        if built.get("parameters") != parameters:
            return {"status": "changed", "reason": f"{artifact} was built with other parameters"}
    for artifact in results:
        reason = state.stale_reason(artifact)
        if reason is not None:
            return {"status": "stale", "reason": f"{artifact}: {reason}"}
    return {"status": "current"}


def _order_pipeline(state: SessionState, steps: list[dict[str, Any]]) -> dict[str, Any]:
    steps = _checked_steps(steps)
    try:
        ordered = order_steps(steps, _declarations(), RESULTS)
    except PipelineError as exc:
        raise ValueError(str(exc)) from exc
    by_id = {str(step["id"]): step for step in steps}
    report: dict[str, dict[str, Any]] = {}
    for step_id in ordered.order:
        step = by_id[step_id]
        declared = REGISTRY.get(str(step["operation"]))
        parameters, errors = _parameters(declared, dict(step.get("parameters") or {}))
        entry: dict[str, Any] = {
            "operation": declared.name,
            "inputs": {artifact: list(sources) for artifact, sources in ordered.inputs[step_id].items()},
            "outputs": list(declared.writes),
        }
        if errors:
            entry.update(status="invalid", errors=errors)
        else:
            entry.update(parameters=parameters, **_status(state, declared, parameters or {}))
        waiting = sorted(
            {source for sources in ordered.inputs[step_id].values() for source in sources}
            - {other for other, done in report.items() if done["status"] in ("current", "ready")}
        )
        if waiting and entry["status"] in ("current", "ready"):
            entry.update(status="upstream", waiting_on=waiting)
        report[step_id] = entry
    return {
        "order": list(ordered.order),
        "edges": [{"source": e.source, "target": e.target, "artifact": e.artifact} for e in ordered.edges],
        "steps": report,
        "to_run": [step_id for step_id in ordered.order if report[step_id]["status"] not in ("current", "ready")],
    }


def _summary(name: str, stored: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "steps": copy.deepcopy(stored["steps"]),
        "actor": stored.get("actor"),
        "saved_at": stored.get("saved_at"),
    }


def _save_pipeline(state: SessionState, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("A pipeline needs a name")
    _order_pipeline(state, steps)
    before = copy.deepcopy(state.pipelines.get(name))
    state.pipelines[name] = {
        "steps": copy.deepcopy(steps),
        "actor": ACTOR.get(),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    note_undo({"name": name, "before": before, "after": copy.deepcopy(state.pipelines[name])})
    state.touch()
    return {"status": "ok", "replaced": before is not None, **_summary(name, state.pipelines[name])}


def _delete_pipeline(state: SessionState, name: str) -> dict[str, Any]:
    if name not in state.pipelines:
        raise ValueError(f"No pipeline named '{name}'")
    note_undo({"name": name, "before": copy.deepcopy(state.pipelines[name]), "after": None})
    del state.pipelines[name]
    state.touch()
    return {"status": "ok", "deleted": name}


def _list_pipelines(state: SessionState) -> dict[str, Any]:
    return {"pipelines": [_summary(name, stored) for name, stored in sorted(state.pipelines.items())]}


@operation(effect="read", stage="pipeline", canvas=False, result=result_models.OrderPipelineResult)
def order_pipeline(steps: list[dict]) -> dict:
    """Order a pipeline's steps by what each reads and writes, and say for each whether the
    session holds the result it would build: current, changed, stale, not run, waiting on a
    step upstream, or invalid. Refuses two steps building one result, and a cycle."""
    return _order_pipeline(session, steps)


@operation(
    effect="change", stage="pipeline", canvas=False, result=result_models.SavePipelineResult,
    reads=("pipelines",), writes=("pipelines",),
)
def save_pipeline(name: str, steps: list[dict]) -> dict:
    """Save or replace a named pipeline in the campaign; refused when its steps cannot be ordered."""
    return _save_pipeline(session, name, steps)


@operation(
    effect="change", stage="pipeline", canvas=False, result=result_models.DeletePipelineResult,
    reads=("pipelines",), writes=("pipelines",),
)
def delete_pipeline(name: str) -> dict:
    """Delete a named pipeline."""
    return _delete_pipeline(session, name)


@operation(
    effect="read", stage="pipeline", canvas=False, result=result_models.ListPipelinesResult,
    reads=("pipelines",),
)
def list_pipelines() -> dict:
    """List the campaign's named pipelines with their steps, who saved each and when."""
    return _list_pipelines(session)
