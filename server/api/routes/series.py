"""series — a series window as an Arrow stream (decisions/0005).

The interface draws long series from this route: each channel's per-bucket minimum, maximum
and valid count as Arrow columns, with the window's description in the schema metadata
under ``gokaatru``. It calls the same ``_series_window`` as the ``get_series_window``
operation and resolves a selection with the same ``selection_mask``, blanking only the
requested channels in the requested window rather than copying the whole session as a
selectable operation's wrapper does; ``tests/test_series_window.py`` checks the two agree.
Hand-written because the generated routes return JSON.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

import pyarrow as pa
from fastapi import APIRouter, Depends, HTTPException, Response

from server.api.deps import get_session_state
from server.core.decimation import Window
from server.operations import selection_disclosure
from server.state.session import SessionState
from server.tools.selections import selection_mask
from server.tools.series import DEFAULT_SERIES_BUCKETS, _series_window

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


@router.get("/sessions/{session_id}/series")
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
    try:
        content = series_arrow(state, channels, start, end, buckets, selection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=content, media_type=ARROW_STREAM)
