"""history — undo and redo the last cleaning rule, configuration change, sensor removal, data
model build or saved selection (P1-13, P2-6, P2-7, P3-1, decisions/0010).

Undo inverts one logged call. A cleaning rule is removed by the replay-from-raw undo that
already exists: rules are order-dependent, so only a replay gives back the series as it was.
A configuration change is inverted by restoring exactly the run-configuration paths and
synced fields it changed. A sensor removal is inverted from what it kept aside
(``server/tools/sensors.py``), a data model build from the state it recorded before and
after; the build that first puts the records into UTC cannot be undone. A saved selection is
put back as the call found it. Each inverse first
checks that the session is still as that call left it, and refuses rather than guesses when
a later change has moved what it would restore. Redo calls the undone operation again with
its logged parameters. Any other change starts a new branch of the history, so what was
undone can no longer be redone.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from server.operations import operation
from server.schemas.common import Coordinate
from server.schemas.results import history as result_models
from server.state.session import SessionState, session
from server.tools.cleaning import _apply_cleaning_rule, _undo_cleaning_rule
from server.tools.config import SYNCED_FIELDS, _persist_runconfig, _update_run_config, config_snapshot
from server.tools.selections import restore_selection
from server.tools.sensors import _remove_sensors, _restore_sensors

UNDOABLE_OPERATIONS: tuple[str, ...] = (
    "apply_cleaning_rule", "update_run_config", "remove_sensors", "build_data_model",
    "define_selection", "delete_selection",
)
_ABSENT = object()


Path = tuple[str, ...]


def _paths(config: Any, prefix: Path = ()) -> dict[Path, Any]:
    # Tuples, not dotted strings: sensor_mapping's keys are heights such as "100.0".
    if not isinstance(config, dict) or not config:
        return {prefix: config} if prefix else {}
    found: dict[Path, Any] = {}
    for key, value in config.items():
        found.update(_paths(value, (*prefix, str(key))))
    return found


def _get(config: dict[str, Any], path: Path) -> Any:
    node: Any = config
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return _ABSENT
        node = node[part]
    return node


def _set(config: dict[str, Any], path: Path, value: Any) -> None:
    node = config
    for part in path[:-1]:
        node = node.setdefault(part, {})
    if value is _ABSENT:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = copy.deepcopy(value)


def _prune_empty(config: dict[str, Any]) -> None:
    for key in list(config):
        if isinstance(config[key], dict):
            _prune_empty(config[key])
            if not config[key]:
                del config[key]


def _applied(state: SessionState) -> list[dict[str, Any]]:
    undone = set(state.undo_stack)
    return [
        entry
        for entry in state.operation_log
        if entry.get("operation") in UNDOABLE_OPERATIONS
        and entry.get("status") == "ok"
        and entry.get("seq") not in undone
        and isinstance(entry.get("undo"), dict)
    ]


def _undo_cleaning(state: SessionState, entry: dict[str, Any]) -> dict[str, Any]:
    note = entry["undo"]
    last = state.cleaning_log[-1] if state.cleaning_log else None
    if (
        len(state.cleaning_log) != note["cleaning_sequence"]
        or last is None
        or (last.get("rule_type"), last.get("sensor")) != (note["rule_type"], note["sensor"])
    ):
        raise ValueError(
            f"Cannot undo '{note['rule_type']}' on '{note['sensor']}' (log entry {entry['seq']}): it is no "
            "longer the last cleaning rule, so removing it would not give back the series it was applied to. "
            "Use undo_cleaning_rule with its index instead."
        )
    return _undo_cleaning_rule(state, len(state.cleaning_log) - 1)


def _undo_config(state: SessionState, entry: dict[str, Any]) -> dict[str, Any]:
    before, after = entry["undo"]["before"], entry["undo"]["after"]
    old_paths, new_paths = _paths(before["runconfig"]), _paths(after["runconfig"])
    changed = sorted(
        path
        for path in old_paths.keys() | new_paths.keys()
        if old_paths.get(path, _ABSENT) != new_paths.get(path, _ABSENT)
    )
    moved = [".".join(path) for path in changed if _get(state.runconfig, path) != new_paths.get(path, _ABSENT)]
    current_fields = config_snapshot(state)["fields"]
    moved += [
        name
        for name in SYNCED_FIELDS
        if before["fields"][name] != after["fields"][name] and current_fields[name] != after["fields"][name]
    ]
    if moved:
        raise ValueError(
            f"Cannot undo the configuration change of log entry {entry['seq']}: a later change has moved "
            f"{', '.join(moved)}, so restoring the earlier values would overwrite it."
        )
    for path in changed:
        _set(state.runconfig, path, old_paths.get(path, _ABSENT))
    _prune_empty(state.runconfig)
    for name in SYNCED_FIELDS:
        if before["fields"][name] != after["fields"][name]:
            value = before["fields"][name]
            setattr(state, name, Coordinate(**value) if name == "coordinate" and value is not None else value)
    state.touch()
    return {"restored_paths": [".".join(path) for path in changed]}


def _undo_removal(state: SessionState, entry: dict[str, Any]) -> dict[str, Any]:
    detail = _restore_sensors(state, entry["undo"]["stash_key"])
    _persist_runconfig(state)
    return detail


def _redo_removal(state: SessionState, entry: dict[str, Any]) -> dict[str, Any]:
    # Kept under the original entry's sequence, so undoing it again finds it.
    detail = _remove_sensors(state, entry["parameters"]["sensor_names"], str(entry["seq"]))
    _persist_runconfig(state)
    return detail


_DATA_MODEL_PARTS = (
    ("mapping", "the sensor mapping"),
    ("inventory", "the sensor inventory"),
    ("timezone", "the timezone"),
    ("origin", "the data model in use"),
    ("document", "the built document"),
)


def _undo_data_model(state: SessionState, entry: dict[str, Any]) -> dict[str, Any]:
    from server.tools.data_io import _confined_file_path
    from server.tools.datamodel_builder import (
        BUILT_DATAMODEL_FILENAME,
        datamodel_state,
        same_declaration,
        timezone_from,
    )

    note = entry["undo"]
    if note["converts_records"]:
        raise ValueError(
            f"Cannot undo the data model build of log entry {entry['seq']}: it put the records into UTC, and "
            "undoing it would move every timestamp. Build again with the earlier declaration instead."
        )
    before, after = note["before"], note["after"]
    current = datamodel_state(state)
    moved = [
        label
        for key, label in _DATA_MODEL_PARTS
        if not (same_declaration(current[key], after[key]) if key == "document" else current[key] == after[key])
    ]
    if moved:
        raise ValueError(
            f"Cannot undo the data model build of log entry {entry['seq']}: a later change has moved "
            f"{', '.join(moved)}, so restoring the earlier data model would overwrite it."
        )
    # Restores the run-configuration paths and synced fields, refusing first if a later change
    # moved one of them.
    detail = _undo_config(state, {"seq": entry["seq"], "undo": {"before": before["config"], "after": after["config"]}})
    state.sensor_mapping = {float(height): dict(slots) for height, slots in before["mapping"].items()}
    state.sensor_inventory = copy.deepcopy(before["inventory"])
    state.timezone = timezone_from(before["timezone"])
    state.datamodel_origin = copy.deepcopy(before["origin"])
    path = _confined_file_path(state, BUILT_DATAMODEL_FILENAME, subdir="uploads")
    if before["document"] is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(before["document"], encoding="utf-8")
    state.bump_data_version()
    return {**detail, "data_model": "restored"}


def _redo_data_model(state: SessionState, entry: dict[str, Any]) -> dict[str, Any]:
    from server.tools.datamodel_builder import _build_data_model

    return _build_data_model(state, entry["parameters"]["spec"])


_UNDO = {
    "apply_cleaning_rule": _undo_cleaning,
    "update_run_config": _undo_config,
    "remove_sensors": _undo_removal,
    "build_data_model": _undo_data_model,
    "define_selection": lambda state, entry: restore_selection(state, entry["undo"], undo=True),
    "delete_selection": lambda state, entry: restore_selection(state, entry["undo"], undo=True),
}
_REDO = {
    "build_data_model": _redo_data_model,
    "apply_cleaning_rule": lambda state, entry: _apply_cleaning_rule(state, **entry["parameters"]),
    "update_run_config": lambda state, entry: _update_run_config(
        state, entry["parameters"]["key"], entry["parameters"]["value"]
    ),
    "remove_sensors": _redo_removal,
    "define_selection": lambda state, entry: restore_selection(state, entry["undo"], undo=False),
    "delete_selection": lambda state, entry: restore_selection(state, entry["undo"], undo=False),
}


def _summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {"seq": entry["seq"], "operation": entry["operation"], "parameters": entry["parameters"]}


def _undo_last_change(state: SessionState) -> dict[str, Any]:
    applied = _applied(state)
    if not applied:
        raise ValueError(
            "Nothing to undo: no cleaning rule, configuration change, sensor removal, data model build "
            "or saved selection is in the history"
        )
    entry = applied[-1]
    detail = _UNDO[entry["operation"]](state, entry)
    state.undo_stack.append(int(entry["seq"]))
    return {
        "status": "ok",
        "undone": _summary(entry),
        "detail": detail,
        "can_undo": bool(_applied(state)),
        "can_redo": True,
        **state.staleness_report(),
    }


def _redo_last_change(state: SessionState) -> dict[str, Any]:
    if not state.undo_stack:
        raise ValueError("Nothing to redo: no undone change is waiting, or a later change replaced it")
    seq = state.undo_stack[-1]
    entry = next(item for item in state.operation_log if item.get("seq") == seq)
    detail = _REDO[entry["operation"]](state, entry)
    state.undo_stack.pop()
    return {
        "status": "ok",
        "redone": _summary(entry),
        "detail": json.loads(json.dumps(detail, default=str)),
        "can_undo": True,
        "can_redo": bool(state.undo_stack),
        **state.staleness_report(),
    }


def _get_operation_log(state: SessionState, limit: int) -> dict[str, Any]:
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    entries = [{key: value for key, value in entry.items() if key != "undo"} for entry in state.operation_log[-limit:]]
    return {
        "total": len(state.operation_log),
        "entries": entries,
        "undo_stack": list(state.undo_stack),
        "can_undo": bool(_applied(state)),
        "can_redo": bool(state.undo_stack),
        # The workbench's status bar reads the history and what is stale in one call.
        **state.staleness_report(),
    }


@operation(effect="change", stage="config", canvas=False, result=result_models.UndoLastChangeResult)
def undo_last_change() -> dict:
    """Undo the last cleaning rule, configuration change, sensor removal, data model build or saved
    selection still in the history."""
    return _undo_last_change(session)


@operation(effect="change", stage="config", canvas=False, result=result_models.RedoLastChangeResult)
def redo_last_change() -> dict:
    """Redo the change most recently undone, with the parameters it was first called with."""
    return _redo_last_change(session)


@operation(effect="read", stage="config", canvas=False, result=result_models.GetOperationLogResult)
def get_operation_log(limit: int = 50) -> dict:
    """Return the most recent operation calls: who, what, with which parameters, the undo state,
    and which derived results are stale."""
    return _get_operation_log(session, limit)
