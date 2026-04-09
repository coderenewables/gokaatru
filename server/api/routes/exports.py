"""exports — File-download endpoints for GoKaatru browser sessions.

Part of GoKaatru MCP Server.
"""
from __future__ import annotations

import io
import json
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from server.api.deps import get_session_state, to_bad_request
from server.state.session import SessionState
from server.tools.config import _get_run_config, _save_run_config

router = APIRouter(prefix="/sessions/{session_id}/exports", tags=["exports"])


def _frame_for_csv(frame_like: object) -> pd.DataFrame:
    """Normalize stored dataframe-like payloads into a CSV-ready dataframe."""
    frame = pd.DataFrame(frame_like).copy()
    if "Timestamp" not in frame.columns and isinstance(frame.index, pd.DatetimeIndex):
        index_name = frame.index.name or "index"
        frame = frame.reset_index().rename(columns={index_name: "Timestamp"})
    return frame


def _csv_download(frame_like: object, filename: str) -> StreamingResponse:
    """Return a CSV attachment response for one in-memory dataframe payload."""
    frame = _frame_for_csv(frame_like)
    csv_text = frame.to_csv(index=False)
    return StreamingResponse(
        io.BytesIO(csv_text.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _json_download(payload: object, filename: str) -> StreamingResponse:
    """Return a JSON attachment response for one in-memory payload."""
    json_text = json.dumps(payload, indent=2)
    return StreamingResponse(
        io.BytesIO(json_text.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/timeseries")
def export_timeseries_csv(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> StreamingResponse:
    """Export the current cleaned timeseries dataframe as a CSV attachment."""
    del session_id
    if state.timeseries_df is None:
        raise to_bad_request(ValueError("Timeseries data is not loaded"))
    return _csv_download(state.timeseries_df, "timeseries_cleaned.csv")


@router.get("/ltc/{algorithm}")
def export_ltc_csv(
    session_id: str,
    algorithm: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> StreamingResponse:
    """Export one LTC result dataframe as a CSV attachment."""
    del session_id
    payload = state.ltc_results.get(algorithm)
    if payload is None:
        raise to_bad_request(ValueError(f"LTC result '{algorithm}' is not available"))
    return _csv_download(payload.get("df", []), f"ltc_{algorithm}.csv")


@router.get("/ensemble")
def export_ensemble_csv(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> StreamingResponse:
    """Export the ensemble dataframe as a CSV attachment."""
    del session_id
    if state.ensemble_df is None:
        raise to_bad_request(ValueError("Ensemble result is not available"))
    return _csv_download(state.ensemble_df, "ensemble_results.csv")


@router.get("/runconfig")
def export_runconfig_json(
    session_id: str,
    state: Annotated[SessionState, Depends(get_session_state)],
) -> StreamingResponse:
    """Export the current runconfig as a JSON attachment."""
    del session_id
    _save_run_config(state)
    return _json_download(_get_run_config(state), "runconfig.json")