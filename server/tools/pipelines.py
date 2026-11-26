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
import json
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


def _height_sensors(selection: dict[str, Any]) -> str:
    heights, columns = selection["resolved_heights_m"], selection["resolved_columns"]
    return json.dumps({str(int(height)): column for height, column in zip(heights, columns)})


def _pipeline_from_scenario(state: SessionState, sweep_id: str, config_hash: str) -> dict[str, Any]:
    """The steps that compute one sweep scenario, as the sweep's stages computed it
    (``server/core/scenario_pipeline.py``), each through the operation the stage shares."""
    from server.core.reanalysis import get_reference_source
    from server.core.scenario_result import fixed_prefix_hash
    from server.core.sweep import load_scenario_runconfig
    from server.tools.ltc_runs import DIRECTIONAL_LTC_ALGORITHMS

    config = load_scenario_runconfig(state, sweep_id, config_hash)
    scenario = config.get("scenario")
    if not isinstance(scenario, dict):
        raise ValueError(f"Scenario {config_hash} of sweep {sweep_id} carries no scenario record")
    resolved = scenario["sensor_selection_resolved"]
    fit, reference = resolved["shear_fit"], resolved["extrapolation_reference"]
    shear_model = str(scenario["shear_model"])
    algorithm = str(scenario["ltc_algorithm"])
    source = str(scenario["reference_source"])
    alpha = scenario.get("analyst_shear_alpha")
    hub = scenario.get("hub_height_m", config.get("hub_height_m"))
    log_law = shear_model.startswith("log_law")

    steps: list[dict[str, Any]] = []
    if alpha is not None:
        steps.append({"id": "shear_table", "operation": "build_constant_shear_table", "parameters": {"alpha": alpha}})
    elif log_law:
        steps += [
            {"id": "roughness_series", "operation": "calculate_roughness_timeseries",
             "parameters": {"height_sensors": _height_sensors(fit)}},
            {"id": "roughness_table", "operation": "build_roughness_table",
             "parameters": {"aggregation": shear_model.removeprefix("log_law_")}},
        ]
    else:
        steps.append({"id": "shear_series", "operation": "calculate_shear_timeseries",
                      "parameters": {"height_sensors": _height_sensors(fit)}})
        steps.append(
            {"id": "shear_table", "operation": "build_constant_shear_table", "parameters": {}}
            if shear_model == "power_law_constant"
            else {"id": "shear_table", "operation": "build_shear_table",
                  "parameters": {"aggregation": shear_model.removeprefix("power_law_")}}
        )
    steps.append({
        "id": "hub",
        "operation": "extrapolate_to_hub_height",
        "parameters": {
            "hub_height_m": hub,
            "shear_model": "log_law" if log_law else "power_law",
            "reference_columns": list(reference["resolved_columns"]),
            "extrapolate_reanalysis": False,
        },
    })
    ltc = scenario.get("stages", {}).get("run_ltc", {})
    correction: dict[str, Any] = {
        "short_col": ltc["short_column"], "long_col": ltc["long_column"], "reference_source": source,
    }
    if algorithm in DIRECTIONAL_LTC_ALGORITHMS:
        # As the sweep resolves them: the highest mapped vane, and the source's own direction.
        correction["short_dir_col"] = next(
            (str(slots["dir_col"]) for _, slots in sorted(state.sensor_mapping.items(), reverse=True)
             if isinstance(slots.get("dir_col"), str)),
            "",
        )
        correction["long_dir_col"] = get_reference_source(source).dir_col
    steps.append({"id": "correction", "operation": f"run_ltc_{algorithm}", "parameters": correction})
    steps.append({
        "id": "uncertainty",
        "operation": "calculate_scenario_uncertainty",
        "parameters": {
            "algorithm": algorithm,
            "shear_model": shear_model,
            "reference_heights": list(reference["resolved_heights_m"]),
            "hub_height_m": scenario.get("hub_height_m"),
            "shear_source": "analyst_supplied" if alpha is not None else "fitted",
        },
    })
    prefix = scenario.get("fixed_prefix_hash")
    result: dict[str, Any] = {
        "sweep_id": sweep_id,
        "config_hash": config_hash,
        "scenario": {
            "shear_fit_policy": fit.get("policy"),
            "reference_policy": reference.get("policy"),
            "shear_model": shear_model,
            "reference_source": source,
            "ltc_algorithm": algorithm,
            "hub_height_m": hub,
            "analyst_shear_alpha": alpha,
        },
        "steps": steps,
        "prefix_matches": prefix == fixed_prefix_hash(state),
    }
    if not result["prefix_matches"]:
        result["prefix_note"] = (
            "The campaign's data, cleaning, reanalysis or engine has changed since this sweep ran "
            f"(prefix {prefix}, now {fixed_prefix_hash(state)}): the steps run on today's session and "
            "will not reproduce the scenario's row."
        )
    return result


_SWEEP_DEFAULT_POLICY = "nearest_2"


def _policies_resolving_to(state: SessionState, columns: list[str], hub: float | None) -> list[str]:
    from server.core.sensor_selection import resolve_all

    wanted = sorted(columns)
    return [
        name for name, selection in resolve_all(state, hub).items()
        if selection.available and sorted(selection.columns) == wanted
    ]


def _sweep_spec_from_pipeline(state: SessionState, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """The sweep specification whose levels are this pipeline's choices (decisions/0015.1):
    what "Sweep around this" fills the matrix with. A choice no sweep level expresses is
    listed in ``unmatched`` with why, and its axis takes the sweep's default."""
    from server.tools.ltc_runs import LTC_ALGORITHMS

    _checked_steps(steps)
    by_operation: dict[str, list[dict[str, Any]]] = {}
    for step in steps:
        by_operation.setdefault(str(step.get("operation")), []).append(dict(step.get("parameters") or {}))
    unmatched: list[dict[str, str]] = []

    hub_steps = by_operation.get("extrapolate_to_hub_height", [])
    given = hub_steps[0].get("hub_height_m") if hub_steps else None
    hub = float(given) if given is not None else state.get_hub_height_m()

    shear_models: list[str] = []
    alpha: float | None = None
    for parameters in by_operation.get("build_shear_table", []):
        shear_models.append(f"power_law_{parameters.get('aggregation', 'mean')}")
    for parameters in by_operation.get("build_roughness_table", []):
        shear_models.append(f"log_law_{parameters.get('aggregation', 'mean')}")
    for parameters in by_operation.get("build_constant_shear_table", []):
        if parameters.get("alpha") is None:
            shear_models.append("power_law_constant")
        else:
            alpha = float(parameters["alpha"])
            shear_models.append("power_law_mean")
    if "build_aggr_momm_shear_table" in by_operation:
        unmatched.append({"axis": "shear_model", "why": "the aggregated MoMM table is not a sweep level"})
    if not shear_models:
        unmatched.append({"axis": "shear_model", "why": "the pipeline builds no shear or roughness table"})
        shear_models = ["power_law_mean"]

    def policies(axis: str, columns: list[str] | None, what: str) -> list[str]:
        if columns:
            found = _policies_resolving_to(state, columns, hub)
            if found:
                return found
            unmatched.append({"axis": axis, "why": f"no sensor policy resolves to {', '.join(columns)}"})
        else:
            unmatched.append({"axis": axis, "why": f"the pipeline names no {what}"})
        return [_SWEEP_DEFAULT_POLICY]

    fit_columns: list[str] | None = None
    for name in ("calculate_shear_timeseries", "calculate_roughness_timeseries", "build_aggr_momm_shear_table"):
        for parameters in by_operation.get(name, []):
            if parameters.get("height_sensors"):
                fit_columns = list(json.loads(parameters["height_sensors"]).values())
    reference_columns = hub_steps[0].get("reference_columns") if hub_steps else None

    algorithms, sources = [], []
    for name in LTC_ALGORITHMS:
        for parameters in by_operation.get(f"run_ltc_{name}", []):
            algorithms.append(name)
            sources.append(str(parameters.get("reference_source") or state.active_reference_source))
    if not algorithms:
        unmatched.append({"axis": "ltc_algorithm", "why": "the pipeline runs no long-term correction"})
        algorithms, sources = ["variance_ratio"], [state.active_reference_source]

    spec = {
        "shear_fit_policies": policies("shear_fit_policy", fit_columns, "shear-fit sensors")
        if alpha is None else [_SWEEP_DEFAULT_POLICY],
        "reference_policies": policies("reference_policy", reference_columns, "reference sensors"),
        "shear_models": sorted(set(shear_models)),
        "reference_sources": sorted(set(sources)),
        "ltc_algorithms": sorted(set(algorithms)),
        "hub_height_m": hub,
        "analyst_shear_alpha": alpha,
    }
    return {"spec": spec, "unmatched": unmatched}


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


# Reads of the session's own sweeps directory, through the path-confined sweep loader, as
# the sweep-reading operations are (server/tools/sweep_analysis.py).
@operation(
    effect="read", stage="pipeline", canvas=False, disclosure=("prefix_matches",),
    result=result_models.PipelineFromScenarioResult,
    reads=("data_model", "measured_data", "site", "reanalysis_nodes", "reference_series", "settings"),
)
def pipeline_from_scenario(sweep_id: str, config_hash: str) -> dict:
    """The pipeline that computes one sweep scenario: its shear steps, the extrapolation from
    its reference sensors, its correction against its reference source and its own
    uncertainty, each the operation the sweep's stage shares. Says when the campaign has
    changed since the sweep, as the steps then will not reproduce the row."""
    return _pipeline_from_scenario(session, sweep_id, config_hash)


@operation(
    effect="read", stage="pipeline", canvas=False, disclosure=("unmatched",),
    result=result_models.SweepSpecFromPipelineResult,
    reads=("data_model", "measured_data", "site", "reference_choice"),
)
def sweep_spec_from_pipeline(steps: list[dict]) -> dict:
    """The sweep specification whose levels are a pipeline's own choices (its sensor policies,
    shear model, reference sources, corrections and hub height): the matrix "Sweep around this"
    starts from. A choice no sweep level expresses is listed in unmatched, with why."""
    return _sweep_spec_from_pipeline(session, steps)
