"""series — a series window as an Arrow stream (decisions/0005).

The interface draws long series from this route: each channel's per-bucket minimum, maximum
and valid count as Arrow columns, with the window's description in the schema metadata
under ``gokaatru``. It calls the same ``_series_window`` as the ``get_series_window``
operation and resolves a selection with the same ``selection_mask``, blanking only the
requested channels in the requested window rather than copying the whole session as a
selectable operation's wrapper does; ``tests/test_series_window.py`` checks the two agree.
Hand-written because the generated routes return JSON. The selection is a saved name or an
inline definition; POST takes the same query as a body, for a lasso too long for a URL.

``/sessions/{id}/pairs`` serves a scatter's points the same way: every record where both
channels are valid, with a highlight selection marked rather than applied, from the same
``_scatter_pairs`` as the ``get_scatter_pairs`` operation.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

import pyarrow as pa
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from server.api.deps import get_session_state
from server.core.decimation import Window
from server.operations import selection_disclosure
from server.schemas.results._base import ErrorDetail
from server.state.session import SessionState
from server.tools.selections import selection_mask
from server.tools.series import DEFAULT_SERIES_BUCKETS, Pairs, _scatter_pairs, _series_window

ARROW_STREAM = "application/vnd.apache.arrow.stream"

router = APIRouter(tags=["series"])


def window_table(window: Window, selection: dict[str, Any] | None = None) -> pa.Table:
    """The window as columns: ``time`` (bucket start, UTC) and ``<channel>.min|max|count``."""
    columns: dict[str, pa.Array] = {"time": pa.array(window.time_ms, type=pa.timestamp("ms", tz="UTC"))}
    for column, name in enumerate(window.channels):
        columns[f"{name}.min"] = pa.array(window.minimum[:, column], type=pa.float64(), from_pandas=True)
        columns[f"{name}.max"] = pa.array(window.maximum[:, column], type=pa.float64(), from_pandas=True)
        columns[f"{name}.count"] = pa.array(window.count[:, column], type=pa.int32())
    description = {
        "channels": list(window.channels),
        "start_ms": int(window.start_ms),
        "end_ms": int(window.end_ms),
        "records": window.records,
        "decimated": window.decimated,
        "bucket_ms": window.bucket_ms,
        "selection": selection,
    }
    return pa.table(columns).replace_schema_metadata({"gokaatru": json.dumps(description)})


def arrow_stream(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def series_arrow(
    state: SessionState,
    channels: str,
    start: str = "",
    end: str = "",
    buckets: int = DEFAULT_SERIES_BUCKETS,
    selection: str = "",
) -> bytes:
    """The window as an Arrow stream, on a selection's records when one is named."""
    keep = selection_mask(state, selection) if selection else None
    disclosure = selection_disclosure(selection, keep) if keep is not None else None
    return arrow_stream(window_table(_series_window(state, channels, start, end, buckets, keep), disclosure))


class SeriesWindowRequest(BaseModel):
    """The GET route's query as a body, for a selection too long for a URL (a lasso)."""

    model_config = ConfigDict(extra="forbid")

    channels: str
    start: str = ""
    end: str = ""
    buckets: int = DEFAULT_SERIES_BUCKETS
    selection: str = ""


_ARROW_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"content": {ARROW_STREAM: {}}, "description": "The window as an Arrow IPC stream"},
    400: {"model": ErrorDetail},
}


def _respond(state: SessionState, request: SeriesWindowRequest) -> Response:
    try:
        content = series_arrow(state, request.channels, request.start, request.end, request.buckets, request.selection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=content, media_type=ARROW_STREAM)


@router.get("/sessions/{session_id}/series", response_class=Response, responses=_ARROW_RESPONSE)
def get_series(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
    channels: str,
    start: str = "",
    end: str = "",
    buckets: int = DEFAULT_SERIES_BUCKETS,
    selection: str = "",
) -> Response:
    """Per-bucket minimum, maximum and valid count of channels over [start, end), as Arrow."""
    del session_id
    return _respond(state, SeriesWindowRequest(channels=channels, start=start, end=end, buckets=buckets,
                                               selection=selection))


@router.post("/sessions/{session_id}/series", response_class=Response, responses=_ARROW_RESPONSE)
def post_series(
    session_id: str,
    request: SeriesWindowRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> Response:
    """The same window as the GET route, its query sent as a JSON body."""
    del session_id
    return _respond(state, request)


def pairs_table(pairs: Pairs) -> pa.Table:
    """The pairs as columns ``time`` (UTC), ``x``, ``y`` and, with a highlight, ``highlighted``."""
    columns: dict[str, pa.Array] = {
        "time": pa.array(pairs.time_ms, type=pa.timestamp("ms", tz="UTC")),
        "x": pa.array(pairs.x, type=pa.float64()),
        "y": pa.array(pairs.y, type=pa.float64()),
    }
    if pairs.highlighted is not None:
        columns["highlighted"] = pa.array(pairs.highlighted, type=pa.bool_())
    description = {
        "x_channel": pairs.x_channel,
        "y_channel": pairs.y_channel,
        "start_ms": pairs.start_ms,
        "end_ms": pairs.end_ms,
        "window_records": pairs.window_records,
        "records": int(len(pairs.time_ms)),
        "highlight": pairs.highlight,
    }
    return pa.table(columns).replace_schema_metadata({"gokaatru": json.dumps(description)})


class ScatterPairsRequest(BaseModel):
    """The pairs route's query as a body, for a highlight too long for a URL."""

    model_config = ConfigDict(extra="forbid")

    x_channel: str
    y_channel: str
    start: str = ""
    end: str = ""
    highlight: str = ""


def _respond_pairs(state: SessionState, request: ScatterPairsRequest) -> Response:
    try:
        pairs = _scatter_pairs(state, request.x_channel, request.y_channel, request.start, request.end,
                               request.highlight)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=arrow_stream(pairs_table(pairs)), media_type=ARROW_STREAM)


@router.get("/sessions/{session_id}/pairs", response_class=Response, responses=_ARROW_RESPONSE)
def get_pairs(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
    x_channel: str,
    y_channel: str,
    start: str = "",
    end: str = "",
    highlight: str = "",
) -> Response:
    """Every record of [start, end) where both channels are valid, as Arrow, for a scatter."""
    del session_id
    return _respond_pairs(state, ScatterPairsRequest(x_channel=x_channel, y_channel=y_channel, start=start,
                                                     end=end, highlight=highlight))


@router.post("/sessions/{session_id}/pairs", response_class=Response, responses=_ARROW_RESPONSE)
def post_pairs(
    session_id: str,
    request: ScatterPairsRequest,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> Response:
    """The same pairs as the GET route, the query sent as a JSON body."""
    del session_id
    return _respond_pairs(state, request)
