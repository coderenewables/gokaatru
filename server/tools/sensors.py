"""sensors — removing sensors from the analysis, and putting them back (P2-6).

Removal takes a sensor out of the inventory, its slot out of the height mapping and its
column out of the working and raw data, and records it in the run configuration's
``excluded_sensors`` so a datamodel-only re-import keeps it out. Loading a new timeseries
clears the exclusion (``server/tools/data_io.py``).

Each removal made through the operation keeps what it took out in
``state.removed_sensors``, keyed by its operation-log sequence, so undo can restore it
exactly; the columns are frames, which the project store saves like any other. Undo refuses
when a later change has moved what it would restore.
"""
from __future__ import annotations

import copy
from typing import Any

import pandas as pd

from server.operations import current_operation, note_undo, operation
from server.schemas.results import sensors as result_models
from server.state.session import SessionState, session
from server.tools.config import _persist_runconfig

#: The sensor_mapping slot that holds each sensor type's column.
SENSOR_TYPE_TO_SLOT: dict[str, str] = {
    "wind_speed": "speed_col",
    "wind_direction": "dir_col",
    "temperature": "temp_col",
    "pressure": "pressure_col",
}
FRAMES: tuple[str, ...] = ("timeseries_df", "raw_timeseries_df")
_ABSENT = "__absent__"


def _remove_sensors(state: SessionState, sensor_names: list[str], stash_key: str | None = None) -> dict[str, Any]:
    """Remove the named sensors; with ``stash_key``, keep what was removed for undo."""
    if not state.sensor_inventory:
        raise ValueError("Sensor inventory is not loaded")
    if not sensor_names:
        raise ValueError("Name at least one sensor to remove")
    before = {
        "inventory_order": list(state.sensor_inventory),
        "mapping": copy.deepcopy(state.sensor_mapping),
        "excluded_sensors": copy.deepcopy(state.runconfig.get("excluded_sensors", _ABSENT)),
        "columns": {name: None if getattr(state, name) is None else list(getattr(state, name).columns)
                    for name in FRAMES},
    }
    removed: list[str] = []
    not_found: list[str] = []
    inventory: dict[str, Any] = {}
    for name in sensor_names:
        if name not in state.sensor_inventory or name in removed:
            not_found.append(name)
            continue
        meta = state.sensor_inventory.pop(name)
        inventory[name] = meta
        removed.append(name)
        height = meta.get("height_m")
        slot = SENSOR_TYPE_TO_SLOT.get(str(meta.get("sensor_type", "")))
        if slot is None or height is None:
            continue
        # sensor_mapping keys are float heights; match loosely.
        for map_height, slots in list(state.sensor_mapping.items()):
            if abs(float(map_height) - float(height)) < 0.01 and slots.get(slot) == name:
                slots[slot] = None
                # A speed sensor's standard deviation goes with it.
                if slot == "speed_col":
                    slots["sd_col"] = None
                if all(value is None for value in slots.values()):
                    del state.sensor_mapping[map_height]
                break
    state.sensor_mapping = dict(sorted(state.sensor_mapping.items(), reverse=True))

    dropped: dict[str, list[str]] = {name: [] for name in FRAMES}
    columns: dict[str, pd.DataFrame | None] = {name: None for name in FRAMES}
    if removed:
        for frame_name in FRAMES:
            frame = getattr(state, frame_name)
            if frame is None:
                continue
            drop = [column for column in frame.columns if column in set(removed)]
            if drop:
                columns[frame_name] = frame[drop].copy()
                setattr(state, frame_name, frame.drop(columns=drop))
                dropped[frame_name] = drop
        existing = state.runconfig.get("excluded_sensors")
        excluded = [str(name) for name in existing] if isinstance(existing, list) else []
        excluded += [name for name in removed if name not in excluded]
        state.runconfig["excluded_sensors"] = excluded
        # The working data changed: anything derived from the removed columns is stale.
        state.bump_data_version()
        if stash_key is not None:
            state.removed_sensors[stash_key] = {
                **before,
                "names": removed,
                "inventory": inventory,
                "frames": columns,
                "mapping_after": copy.deepcopy(state.sensor_mapping),
                "excluded_after": list(excluded),
            }
    state.touch()
    return {
        "status": "ok",
        "removed": removed,
        "not_found": not_found,
        "remaining_count": len(state.sensor_inventory),
        "columns_dropped": dropped,
    }


def _ordered(columns: list[str], restored: list[str], current: list[str]) -> list[str]:
    """The columns as they stood before the removal, with any added since at the end."""
    present = set(current) | set(restored)
    return [column for column in columns if column in present] + [
        column for column in current if column not in set(columns)
    ]


def _restore_sensors(state: SessionState, stash_key: str) -> dict[str, Any]:
    """Undo one removal: every field it changed goes back to what it was."""
    stash = state.removed_sensors.get(stash_key)
    if stash is None:
        raise ValueError(f"Nothing is kept for the sensor removal of log entry {stash_key}, so it cannot be undone")
    names = list(stash["names"])
    moved: list[str] = []
    if any(name in state.sensor_inventory for name in names):
        moved.append("the sensor inventory (a removed sensor is back)")
    if state.sensor_mapping != stash["mapping_after"]:
        moved.append("the sensor mapping")
    if state.runconfig.get("excluded_sensors", _ABSENT) != stash["excluded_after"]:
        moved.append("excluded_sensors")
    for frame_name in FRAMES:
        kept = stash["frames"][frame_name]
        frame = getattr(state, frame_name)
        if kept is None:
            continue
        if frame is None or not frame.index.equals(kept.index) or set(kept.columns) & set(frame.columns):
            moved.append(f"the records of {frame_name}")
    if moved:
        raise ValueError(
            f"Cannot undo the sensor removal of log entry {stash_key}: a later change has moved "
            f"{', '.join(moved)}, so restoring the earlier state would overwrite it."
        )
    for frame_name in FRAMES:
        kept = stash["frames"][frame_name]
        if kept is None:
            continue
        frame = pd.concat([getattr(state, frame_name), kept], axis=1)
        setattr(state, frame_name, frame[_ordered(stash["columns"][frame_name], list(kept.columns),
                                                  list(frame.columns))])
    inventory = {**state.sensor_inventory, **stash["inventory"]}
    order = [name for name in stash["inventory_order"] if name in inventory]
    state.sensor_inventory = {name: inventory[name] for name in order + [n for n in inventory if n not in order]}
    state.sensor_mapping = copy.deepcopy(stash["mapping"])
    if stash["excluded_sensors"] == _ABSENT:
        state.runconfig.pop("excluded_sensors", None)
    else:
        state.runconfig["excluded_sensors"] = copy.deepcopy(stash["excluded_sensors"])
    del state.removed_sensors[stash_key]
    state.bump_data_version()
    state.touch()
    return {"restored": names}


def _list_instruments(state: SessionState) -> dict[str, Any]:
    """The campaign's instruments by height, each with the statistic columns it logs.

    An instrument is a sensor of the inventory. Its statistic columns (standard deviation,
    minimum, maximum) are the ones the data model builder's header inference pairs with it
    (``draft_columns``: same stem, a statistic suffix), plus the mapping's ``sd_col``, so a
    flag can cover the whole instrument (decisions/0014.2) and the data tree can show it.
    """
    from server.core.datamodel_builder import ROLE_STATISTIC, draft_columns

    frame = state.timeseries_df
    columns = [str(column) for column in frame.columns] if frame is not None else []
    drafts = draft_columns(columns)
    statistics: dict[str, list[str]] = {}
    for draft in drafts:
        if draft.role == ROLE_STATISTIC and draft.parent:
            statistics.setdefault(draft.parent, []).append(draft.name)
    roles: dict[str, str] = {}
    for slots in state.sensor_mapping.values():
        for slot, column in slots.items():
            if isinstance(column, str) and slot != "sd_col":
                roles.setdefault(column, slot)
            if slot == "sd_col" and isinstance(column, str) and isinstance(slots.get("speed_col"), str):
                speed = str(slots["speed_col"])
                if column not in statistics.get(speed, []) and column in columns:
                    statistics.setdefault(speed, []).append(column)
    instruments = []
    for name, meta in state.sensor_inventory.items():
        entry: dict[str, Any] = {
            "name": name,
            "height_m": meta.get("height_m"),
            "sensor_type": meta.get("sensor_type"),
            "in_data": name in columns,
            "mapped_as": roles.get(name),
            "statistics": sorted(statistics.get(name, [])),
        }
        if meta.get("boom_orientation_deg") is not None:
            entry["boom_orientation_deg"] = meta["boom_orientation_deg"]
        instruments.append(entry)
    instruments.sort(key=lambda entry: (-(entry["height_m"] or 0.0), str(entry["sensor_type"]), entry["name"]))
    belonging = {entry["name"] for entry in instruments} | {
        column for entry in instruments for column in entry["statistics"]
    }
    other = [
        {"name": draft.name, "role": draft.role, "reason": draft.reason}
        for draft in drafts
        if draft.name not in belonging
    ]
    heights = sorted({entry["height_m"] for entry in instruments if entry["height_m"] is not None}, reverse=True)
    return {"heights": heights, "instruments": instruments, "other_channels": other}


@operation(
    effect="read", stage="ingest", canvas=False, result=result_models.ListInstrumentsResult,
    reads=("data_model", "measured_data", "hub_height_series"),
)
def list_instruments() -> dict:
    """The campaign's instruments by height (highest first), each with its type, boom, mapped
    role and the statistic columns it logs, and every other channel of the data."""
    return _list_instruments(session)


def _preview_remove_sensors(state: SessionState, sensor_names: list[str]) -> dict[str, Any]:
    from server.tools.cleaning import _preview

    def run(replica: SessionState) -> dict[str, Any]:
        replica.removed_sensors = dict(state.removed_sensors)
        return _remove_sensors(replica, sensor_names)

    return _preview(state, run)


def preview_remove_sensors(sensor_names: list[str]) -> dict:
    """Show what remove_sensors would take out, without changing the session."""
    return _preview_remove_sensors(session, sensor_names)


@operation(
    effect="change", stage="ingest", canvas=False, dry_run=preview_remove_sensors,
    result=result_models.RemoveSensorsResult, preview_result=result_models.RemoveSensorsPreview,
    reads=("data_model", "measured_data"),
    writes=("data_model", "measured_data"),
)
def remove_sensors(sensor_names: list[str]) -> dict:
    """Remove sensors from the analysis: inventory, height mapping, working and raw data.

    The removal is recorded in the run configuration's excluded_sensors, so a datamodel
    re-import keeps them out; loading a new timeseries brings every sensor back. Undoable.
    """
    call = current_operation.get()
    stash_key = str(call["seq"]) if call is not None else None
    result = _remove_sensors(session, sensor_names, stash_key)
    if result["removed"]:
        _persist_runconfig(session)
        if stash_key is not None:
            note_undo({"kind": "sensor_removal", "stash_key": stash_key, "names": result["removed"]})
    return result
