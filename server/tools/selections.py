"""selections — named record selections, defined once and used by every view (decisions/0011).

The definition is what the analyst drew; ``server.core.selection`` resolves it to records
against the working data each time it is used, so a selection follows the data through
cleaning rather than freezing a list of rows.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from server.core.selection import SelectionError, resolve, validate
from server.operations import ACTOR, note_undo, operation
from server.schemas.results import selections as result_models
from server.state.session import SessionState, session

#: A summary lists at most this many contiguous runs of selected records.
SELECTION_RANGE_LIMIT = 50


def _frame(state: SessionState) -> pd.DataFrame:
    if state.timeseries_df is None:
        raise ValueError("Load a timeseries first: a selection is resolved against the loaded records")
    return state.timeseries_df


def _runs(index: pd.Index, mask: np.ndarray) -> list[list[str]]:
    positions = np.flatnonzero(mask)
    if positions.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(positions) > 1)
    starts = np.concatenate(([positions[0]], positions[breaks + 1]))
    ends = np.concatenate((positions[breaks], [positions[-1]]))
    return [[pd.Timestamp(index[s]).isoformat(), pd.Timestamp(index[e]).isoformat()] for s, e in zip(starts, ends)]


def _summary(name: str, definition: dict[str, Any], frame: pd.DataFrame) -> dict[str, Any]:
    try:
        mask = resolve(definition, frame)
    except SelectionError as exc:
        raise ValueError(f"Selection '{name}': {exc}") from exc
    runs = _runs(frame.index, mask)
    return {
        "name": name,
        "definition": definition,
        "records": int(mask.sum()),
        "of_records": int(len(frame)),
        "ranges": runs[:SELECTION_RANGE_LIMIT],
        "ranges_truncated": len(runs) > SELECTION_RANGE_LIMIT,
        "range_limit": SELECTION_RANGE_LIMIT,
    }


def is_inline(selection: str) -> bool:
    """Whether a ``selection`` argument is a definition rather than a saved selection's name.

    A name never starts with ``{`` (``define_selection`` refuses one), so the two cannot be
    confused.
    """
    return selection.lstrip().startswith("{")


def inline_definition(selection: str) -> dict[str, Any]:
    try:
        definition = json.loads(selection)
    except json.JSONDecodeError as exc:
        raise ValueError(f"An inline selection must be a JSON object: {exc.msg} at character {exc.pos}") from exc
    if not isinstance(definition, dict):
        raise ValueError("An inline selection must be a JSON object")
    return definition


def selection_mask(state: SessionState, selection: str) -> np.ndarray:
    """The records a selection holds in the session's working data: a saved selection named,
    or a definition sent inline as JSON (the browser's live brushing, decisions/0014.6)."""
    if is_inline(selection):
        try:
            return resolve(inline_definition(selection), _frame(state))
        except SelectionError as exc:
            raise ValueError(f"Inline selection: {exc}") from exc
    if selection not in state.selections:
        raise ValueError(f"No selection named '{selection}'")
    try:
        return resolve(state.selections[selection]["definition"], _frame(state))
    except SelectionError as exc:
        raise ValueError(f"Selection '{selection}': {exc}") from exc


def _define_selection(state: SessionState, name: str, definition: dict[str, Any]) -> dict[str, Any]:
    if not name.strip():
        raise ValueError("A selection needs a name")
    if is_inline(name):
        raise ValueError("A selection's name cannot start with '{', which marks an inline definition")
    frame = _frame(state)
    try:
        validate(definition, frame.columns)
    except SelectionError as exc:
        raise ValueError(str(exc)) from exc
    replaced = name in state.selections
    before = copy.deepcopy(state.selections.get(name))
    state.selections[name] = {
        "definition": definition,
        "actor": ACTOR.get(),
        "defined_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    note_undo({"name": name, "before": before, "after": copy.deepcopy(state.selections[name])})
    state.touch()
    return {"status": "ok", "replaced": replaced, **_summary(name, definition, frame)}


def _delete_selection(state: SessionState, name: str) -> dict[str, Any]:
    if name not in state.selections:
        raise ValueError(f"No selection named '{name}'")
    note_undo({"name": name, "before": copy.deepcopy(state.selections[name]), "after": None})
    del state.selections[name]
    state.touch()
    return {"status": "ok", "deleted": name}


def _list_selections(state: SessionState) -> dict[str, Any]:
    frame = state.timeseries_df
    listed = []
    for name, stored in sorted(state.selections.items()):
        entry: dict[str, Any] = {"name": name, "definition": stored["definition"], "actor": stored.get("actor")}
        if frame is not None:
            try:
                entry["records"] = int(resolve(stored["definition"], frame).sum())
            except SelectionError as exc:
                entry["unresolvable"] = str(exc)
        listed.append(entry)
    return {"selections": listed}


def _resolve_selection(state: SessionState, name: str) -> dict[str, Any]:
    if name not in state.selections:
        raise ValueError(f"No selection named '{name}'")
    return _summary(name, state.selections[name]["definition"], _frame(state))


def _summarise_channels(state: SessionState, channels: str) -> dict[str, Any]:
    frame = _frame(state)
    names = [name.strip() for name in channels.split(",") if name.strip()]
    if not names:
        raise ValueError("Name at least one channel")
    missing = [name for name in names if name not in frame.columns]
    if missing:
        raise ValueError(f"No channel named {', '.join(missing)}")
    summary: dict[str, dict[str, Any]] = {}
    for name in names:
        values = pd.to_numeric(frame[name], errors="coerce").dropna()
        summary[name] = {
            "valid": int(len(values)),
            "mean": float(values.mean()) if len(values) else None,
            "min": float(values.min()) if len(values) else None,
            "max": float(values.max()) if len(values) else None,
        }
    return {"records": int(len(frame)), "channels": summary}


@operation(
    effect="read", stage="selection", canvas=False, selectable=True,
    result=result_models.SummariseChannelsResult,
    reads=("measured_data",),
)
def summarise_channels(channels: str) -> dict:
    """Valid records, mean, minimum and maximum of measured channels (comma-separated); with a
    selection, of its records only, which is how a selection is compared with every record."""
    return _summarise_channels(session, channels)


@operation(
    effect="change", stage="selection", canvas=False, result=result_models.DefineSelectionResult,
    reads=("measured_data",),
    writes=("selections",),
)
def define_selection(name: str, definition: dict) -> dict:
    """Define or replace a named selection of records: time ranges, direction sectors, value
    bands, polygons over two channels or record sets, combined by union and intersection."""
    return _define_selection(session, name, definition)


@operation(
    effect="change", stage="selection", canvas=False, result=result_models.DeleteSelectionResult,
    reads=("selections",),
    writes=("selections",),
)
def delete_selection(name: str) -> dict:
    """Delete a named selection."""
    return _delete_selection(session, name)


@operation(
    effect="read", stage="selection", canvas=False, result=result_models.ListSelectionsResult,
    reads=("measured_data", "selections"),
)
def list_selections() -> dict:
    """List the session's named selections with how many records each holds now."""
    return _list_selections(session)


@operation(
    effect="read", stage="selection", canvas=False, result=result_models.ResolveSelectionResult,
    reads=("measured_data", "selections"),
)
def resolve_selection(name: str) -> dict:
    """Resolve a named selection against the working data: how many records, and where."""
    return _resolve_selection(session, name)
