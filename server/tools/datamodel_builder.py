"""datamodel_builder — MCP surface for building a data model from CSV headers alone.

Part of GoKaatru MCP Server.

A campaign delivered without an IEA Task 43 JSON cannot be analysed at all: nothing
populates ``sensor_mapping`` or ``state.timezone``, so the ``datamodel`` milestone never
completes. These two tools draft a reading of the loaded timeseries columns and turn a
declared spec into a real Task 43 document, which is then parsed by the *existing*
``_parse_datamodel`` — one code path into session state, and a downloadable artifact
recording who declared what.

Paired one-for-one with ``GET/POST /sessions/{id}/datamodel/draft|build`` in
``server/api/routes/uploads.py``; both interfaces call the helpers here.
"""
from __future__ import annotations

import copy
import json
from zoneinfo import ZoneInfo

from server.core.datamodel_builder import (
    ROLE_MEASUREMENT,
    build_datamodel,
    draft_columns,
)
from server.operations import note_undo, operation
from server.schemas.results import datamodel_builder as result_models
from server.state.session import SessionState, session

# data_io is imported inside the functions, not here: declaring an operation imports
# ``server.main``, which runs its own tool-registration imports, so a tool module that
# reaches for a sibling at import time lands in a partially initialised one.

# The file the builder writes into the session uploads directory. Fixed rather than
# timestamped so rebuilding replaces the previous declaration instead of leaving the
# session with several data models and no way to tell which one is live.
BUILT_DATAMODEL_FILENAME = "built_data_model.json"


def _require_timeseries(state: SessionState) -> list[str]:
    """Return the loaded timeseries columns, refusing when there is nothing to describe."""
    if state.timeseries_df is None:
        raise ValueError(
            "Load a timeseries first — the builder describes the columns it actually has, "
            "so it has nothing to draft until the CSV is parsed."
        )
    return [str(column) for column in state.timeseries_df.columns]


def _mapping_warnings(points: list[dict[str, object]]) -> list[str]:
    """Flag declarations that will silently lose data when the mapping is built.

    ``_build_sensor_mapping`` only keeps a height that has a wind speed, so a direction or
    temperature declared at a height with no anemometer is dropped without comment. That
    is long-standing behaviour; what was missing is anyone saying so at declaration time.
    """
    speed_heights = {
        point.get("height_m")
        for point in points
        if point.get("measurement_type_id") == "wind_speed"
    }
    orphaned = sorted(
        {
            f"{point.get('name')} ({point.get('height_m')} m)"
            for point in points
            if point.get("measurement_type_id") != "wind_speed"
            and point.get("height_m") not in speed_heights
        }
    )
    if not orphaned:
        return []
    return [
        "These columns sit at heights with no wind speed sensor, so they will not appear "
        "in the sensor mapping: " + ", ".join(orphaned) + "."
    ]


def _draft_data_model(state: SessionState) -> dict:
    """Propose a reading of every loaded timeseries column for the analyst to correct."""
    columns = _require_timeseries(state)
    drafts = draft_columns(columns)
    heights = sorted(
        {
            draft.height_m
            for draft in drafts
            if draft.role == ROLE_MEASUREMENT and draft.height_m is not None
        }
    )
    undeclared = [
        draft.name
        for draft in drafts
        if draft.role == ROLE_MEASUREMENT and draft.height_m is None
    ]
    return {
        "columns": [draft.as_dict() for draft in drafts],
        "detected_heights_m": heights,
        "columns_needing_a_height": undeclared,
        "basis": "header_inference",
        "note": (
            "Every reading below is drafted from the column name only. Confirm or correct "
            "each one — a height read wrongly is not detectable downstream."
        ),
    }


def _refuse_an_uploaded_model(state: SessionState) -> None:
    origin = state.datamodel_origin
    if origin is not None and not origin.get("built"):
        raise ValueError(
            f"The campaign's own data model, {origin.get('file')}, is in use. It is shown and never changed "
            "(decisions/0014.8); load the timeseries in a new campaign to build one from its headers instead."
        )


def _build_data_model(state: SessionState, spec: dict) -> dict:
    """Build, persist and parse a minimal Task 43 data model from a declared spec.

    Rebuilding replaces the mapping every height-indexed result was computed from, so the
    data version moves and those results read as stale.
    """
    from server.tools.data_io import _confined_file_path, _parse_datamodel

    columns = _require_timeseries(state)
    _refuse_an_uploaded_model(state)
    payload = build_datamodel(spec, available_columns=columns)
    path = _confined_file_path(state, BUILT_DATAMODEL_FILENAME, subdir="uploads")
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        result = _parse_datamodel(state, BUILT_DATAMODEL_FILENAME)
    except Exception:
        # A refused build leaves the declaration on disk as it was, matching the session.
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(previous, encoding="utf-8")
        raise
    state.datamodel_origin = {**(state.datamodel_origin or {}), "spec": copy.deepcopy(spec)}
    state.bump_data_version()
    points = payload["measurement_location"][0]["measurement_point"]
    return {
        **result,
        "file_path": str(path),
        "file_name": BUILT_DATAMODEL_FILENAME,
        "points_declared": len(points),
        "warnings": _mapping_warnings(points),
    }


def timezone_spec(tz: object) -> dict[str, object] | None:
    """A timezone as JSON, for an undo note; ``timezone_from`` reads it back."""
    if tz is None:
        return None
    if isinstance(tz, ZoneInfo):
        return {"zone": tz.key}
    offset = tz.utcoffset(None)  # type: ignore[attr-defined]
    return {"offset_minutes": int(offset.total_seconds() // 60) if offset is not None else 0}


def timezone_from(spec: dict[str, object] | None) -> object:
    from datetime import timedelta, timezone

    if spec is None:
        return None
    if "zone" in spec:
        return ZoneInfo(str(spec["zone"]))
    return timezone(timedelta(minutes=int(spec["offset_minutes"])))  # type: ignore[arg-type]


def datamodel_state(state: SessionState) -> dict[str, object]:
    """Everything a build changes, as JSON, so its undo can check and restore it."""
    from server.tools.config import config_snapshot
    from server.tools.data_io import _confined_file_path

    path = _confined_file_path(state, BUILT_DATAMODEL_FILENAME, subdir="uploads") if state.workspace_dir else None
    return json.loads(json.dumps({
        "config": config_snapshot(state),
        "mapping": {str(height): slots for height, slots in state.sensor_mapping.items()},
        "inventory": state.sensor_inventory,
        "timezone": timezone_spec(state.timezone),
        "origin": state.datamodel_origin,
        "document": path.read_text(encoding="utf-8") if path is not None and path.exists() else None,
    }, default=str))


def same_declaration(left: str | None, right: str | None) -> bool:
    """Whether two built documents declare the same thing: equal but for when each was
    written, so a redo's fresh ``date`` does not read as a later change."""
    if left is None or right is None:
        return left is right
    first, second = json.loads(left), json.loads(right)
    first.pop("date", None)
    second.pop("date", None)
    return first == second


def _records_in_local_time(state: SessionState) -> bool:
    """Whether a build would put the records into UTC, which no undo can take back."""
    import pandas as pd

    return any(
        frame is not None and isinstance(frame.index, pd.DatetimeIndex) and frame.index.tz is None
        for frame in (state.timeseries_df, state.raw_timeseries_df)
    )


# The draft proposes a reading of the column headers and writes nothing; the build writes a
# data model into the workspace and replaces the sensor mapping and timezone in one call.
@operation(effect="read", stage="ingest", canvas=False, result=result_models.DraftDataModelResult)
def draft_data_model() -> dict:
    """Draft a Task 43 reading of the loaded timeseries columns for review, with the data
    model in use: its file, whether it was built here (only then can it be edited) and the
    spec it was built from."""
    return {**_draft_data_model(session), "in_use": copy.deepcopy(session.datamodel_origin)}


@operation(effect="change", stage="ingest", canvas=False, result=result_models.BuildDataModelResult)
def build_data_model(spec: dict) -> dict:
    """Build a minimal IEA Task 43 data model from declared columns and load it.

    Refused while the campaign's own uploaded data model is in use. Undoable, except the
    build that first puts the records into UTC.
    """
    before = datamodel_state(session)
    converted = _records_in_local_time(session)
    result = _build_data_model(session, spec)
    note_undo({"kind": "data_model", "converts_records": converted, "before": before,
               "after": datamodel_state(session)})
    return result
