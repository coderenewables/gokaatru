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

import json

from server.core.datamodel_builder import (
    ROLE_MEASUREMENT,
    build_datamodel,
    draft_columns,
)
from server.operations import operation
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


def _build_data_model(state: SessionState, spec: dict) -> dict:
    """Build, persist and parse a minimal Task 43 data model from a declared spec."""
    from server.tools.data_io import _confined_file_path, _parse_datamodel

    columns = _require_timeseries(state)
    payload = build_datamodel(spec, available_columns=columns)
    path = _confined_file_path(state, BUILT_DATAMODEL_FILENAME, subdir="uploads")
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    result = _parse_datamodel(state, BUILT_DATAMODEL_FILENAME)
    points = payload["measurement_location"][0]["measurement_point"]
    return {
        **result,
        "file_path": str(path),
        "file_name": BUILT_DATAMODEL_FILENAME,
        "points_declared": len(points),
        "warnings": _mapping_warnings(points),
    }


# The draft proposes a reading of the column headers and writes nothing; the build writes a
# data model into the workspace and replaces the sensor mapping and timezone in one call.
@operation(effect="read", stage="ingest", canvas=False, result=result_models.DraftDataModelResult)
def draft_data_model() -> dict:
    """Draft a Task 43 reading of the loaded timeseries columns for review."""
    return _draft_data_model(session)


@operation(effect="change", stage="ingest", canvas=False, result=result_models.BuildDataModelResult)
def build_data_model(spec: dict) -> dict:
    """Build a minimal IEA Task 43 data model from declared columns and load it."""
    return _build_data_model(session, spec)
